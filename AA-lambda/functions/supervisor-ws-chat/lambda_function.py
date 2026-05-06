"""supervisor-ws-chat — sendAgentMessage WebSocket route (Docker, 5min, 2GB).

This is the heavy path. The browser opens a WebSocket to API Gateway
(``wss://rjhzxw8sqj.execute-api.ap-southeast-1.amazonaws.com/prod``)
and sends ``{"action":"sendAgentMessage","thread_id":"...","message":"..."}``.

Design (post-Pass-6 fix):
  Instead of re-implementing the chat-flow inline, this Lambda *delegates*
  to the same helpers used by the source FastAPI route
  ``send_message_to_thread`` in ``routes/threads.py``:

    - ``conversational_agent.process_message`` (Tier 0/0.5/1 + state save)
    - ``_handle_pending_action_decision``      (chat "approve" / "reject")
    - ``_handle_disambiguation_selection``     (chat "1" / "first")
    - ``_execute_workflow_guarded``            (executing flag + cleanup)
    - ``_persist_final_response``              (rewrite stub assistant row)

  This guarantees zero behavioral drift between the deployed WS path and
  the locally-tested REST chat path. The Lambda only owns:

    1. Pulling user_id / jwt off the connection record at $connect time.
    2. Pre-flight quota check (request-level).
    3. Monkey-patching ``progress_manager.broadcast_to_thread`` so the
       brain's existing ``broadcast_progress_sync`` calls fan out over
       this exact WebSocket connection via ``apigw_pusher``.
    4. Translating the (response_text, conversation_state) tuple returned
       by the source helpers into ``complete`` / ``paused`` / ``error``
       WebSocket events.
    5. Stashing ``connection_id`` on the Sup_PendingActions row for any
       paused workflow so ``supervisor-action-approve`` can deliver the
       resume result back to the same client.
    6. ``flush_pending_quota_reports`` + ``clear_request_context`` in finally.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from typing import Any, Dict, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(_HERE, "shared")
for p in (_SHARED, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.lambda_helpers import (  # noqa: E402
    install_persistence_backend,
    quota_check,
    decode_jwt_payload_unsafe,
)
from shared.apigw_pusher import (  # noqa: E402
    ApiGwPusher,
    post_to_connection,
)

install_persistence_backend()


# ----------------------------------------------------------------------
# Singletons (re-used across warm invocations)
# ----------------------------------------------------------------------

_CONN_TABLE_NAME = os.environ.get("WS_CONNECTIONS_TABLE", "KB_WebSocketConnections")
_PENDING_TABLE_NAME = os.environ.get("PENDING_ACTIONS_TABLE", "Sup_PendingActions")
_AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")

_dynamodb_resource = None
_conn_table = None
_pending_table = None


def _get_conn_table():
    global _dynamodb_resource, _conn_table
    if _conn_table is None:
        import boto3  # type: ignore

        if _dynamodb_resource is None:
            _dynamodb_resource = boto3.resource("dynamodb", region_name=_AWS_REGION)
        _conn_table = _dynamodb_resource.Table(_CONN_TABLE_NAME)
    return _conn_table


def _get_pending_table():
    global _dynamodb_resource, _pending_table
    if _pending_table is None:
        import boto3  # type: ignore

        if _dynamodb_resource is None:
            _dynamodb_resource = boto3.resource("dynamodb", region_name=_AWS_REGION)
        _pending_table = _dynamodb_resource.Table(_PENDING_TABLE_NAME)
    return _pending_table


# ----------------------------------------------------------------------
# Brain progress shim — patches `progress_manager.broadcast_to_thread`
# ----------------------------------------------------------------------

_pusher_var: Optional[ApiGwPusher] = None  # set per-invocation, cleared in finally


def _install_progress_shim() -> None:
    """Monkey-patch the brain's ``progress_manager.broadcast_to_thread``
    so that the brain's ``broadcast_progress`` / ``broadcast_progress_sync``
    calls push events over the WebSocket connection captured in
    ``_pusher_var``. Idempotent across warm invocations.
    """
    try:
        import supervisor_agent  # type: ignore
    except Exception as e:
        print(f"[ws-chat] progress shim: brain import failed: {e}")
        return

    pm = getattr(supervisor_agent, "progress_manager", None)
    if pm is None:
        return
    if getattr(pm, "_aa_lambda_shimmed", False):
        return

    from datetime import datetime, timezone

    async def _broadcast_to_thread(_self, thread_id, message_type, data):
        pusher = _pusher_var
        if pusher is None or pusher.gone:
            return
        payload = {
            "type": message_type,
            "data": data,
            "thread_id": thread_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        pusher.push(payload)

    pm.broadcast_to_thread = _broadcast_to_thread.__get__(pm, type(pm))
    pm._aa_lambda_shimmed = True


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _push(pusher: ApiGwPusher, type_: str, **fields) -> None:
    payload = {"type": type_}
    payload.update(fields)
    try:
        pusher.push(payload)
    except Exception as e:
        print(f"[ws-chat] push '{type_}' failed: {e}")


def _load_connection(connection_id: str) -> Dict[str, Any]:
    table = _get_conn_table()
    try:
        resp = table.get_item(Key={"connection_id": connection_id})
        return resp.get("Item") or {}
    except Exception as e:
        print(f"[ws-chat] connections.get_item({connection_id}) failed: {e}")
        return {}


def _stash_connection_on_pending(action_id: str, connection_id: str) -> None:
    """Tag a paused pending-action row with this WS connection so the
    ``supervisor-action-approve`` Lambda can push the resume result back."""
    if not action_id:
        return
    try:
        _get_pending_table().update_item(
            Key={"action_id": action_id},
            UpdateExpression="SET connection_id = :c",
            ExpressionAttributeValues={":c": connection_id},
        )
    except Exception as e:
        print(f"[ws-chat] stash connection_id on pending action failed: {e}")


def _ok():
    return {"statusCode": 200, "body": ""}


# ----------------------------------------------------------------------
# Main async chat flow — mirrors source ``send_message_to_thread``
# ----------------------------------------------------------------------


async def _run_chat_flow(
    *,
    pusher: ApiGwPusher,
    connection_id: str,
    thread_id: str,
    user_message: str,
    uploaded_file: Optional[Dict[str, Any]],
):
    """Runs the source chat flow end-to-end and emits WS events.

    Returns nothing — all signalling is via ``pusher`` events.
    """
    # Imports deferred so any failure surfaces as a WS error rather than a
    # Lambda init crash.
    from routes.threads import (  # type: ignore
        _handle_pending_action_decision,
        _handle_disambiguation_selection,
        _execute_workflow_guarded,
        _has_actionable_task,
        _persist_final_response,
    )
    from supervisor_agent import (  # type: ignore
        conversational_agent,
        broadcast_progress,
        save_conversation_state,
    )
    from execution_logger import trace  # type: ignore
    from models.models import ConversationState  # type: ignore

    started = time.time()

    conversation_state = conversational_agent.thread_service.load_thread_from_db(
        thread_id
    )
    if conversation_state is None:
        # supervisor-create-thread's fast path (no initial_message) writes the
        # Sup_Threads metadata row but skips Sup_ThreadStates to avoid the
        # brain cold-start cost. If the metadata exists, treat this as a
        # freshly-created empty thread and initialize an empty state in
        # memory; process_message's auto_save will populate Sup_ThreadStates
        # on the first turn. Only emit THREAD_NOT_FOUND when the metadata
        # row is genuinely absent (deleted thread, typo'd thread_id, etc.).
        thread_meta = conversational_agent.thread_service.get_thread_metadata(
            thread_id
        )
        if thread_meta:
            print(
                f"[ws-chat] thread {thread_id} metadata present but "
                f"thread_state empty — initializing empty ConversationState"
            )
            conversation_state = ConversationState()
        else:
            _push(pusher, "error", reason="THREAD_NOT_FOUND",
                  message=f"Thread {thread_id} not found")
            return

    if getattr(conversation_state, "executing", False):
        _push(pusher, "error", reason="THREAD_BUSY",
              message="Thread is currently executing. Please wait.")
        return

    # === PROGRESS: Analyzing === (matches source line 1674)
    await broadcast_progress(
        thread_id, 0, 0, "Analyzing your message...", status="analyzing"
    )

    # === Auto-generate thread title on the FIRST real message ===
    # supervisor-create-thread's "no initial_message" fast path (lines
    # 89-117 in that file) creates the thread row with the default
    # "New Conversation" title and skips title generation. The next
    # path the user hits is here (sendAgentMessage WS), so this is the
    # canonical place to backfill the title from the first message —
    # otherwise every thread in the sidebar reads "New Conversation"
    # forever (reported by user 2026-05-03 with two screenshots).
    # Wrapped in try/except: a title-set failure must NEVER block chat.
    #
    # `generated_title` is captured at OUTER scope so we can ship it
    # back on the final `complete` / `paused` push — without that,
    # AIChatNew's sidebar would still show "New Conversation" until the
    # next page-refresh fetches threads from DDB. Mirrors SFXBot's
    # kb-lambda contract (`generated_title` field on the complete
    # event), which is why SFXBot's sidebar live-updates and the AI
    # Assistant's didn't (reported by user 2026-05-03 with screenshot).
    generated_title: Optional[str] = None
    try:
        tm = conversational_agent.thread_service.thread_manager
        meta = tm.get_thread(thread_id)
        current_title = (getattr(meta, "title", "") or "").strip() if meta else ""
        looks_default = current_title in ("", "New Conversation", "New Thread")
        if looks_default and user_message and user_message.strip():
            new_title = tm.auto_generate_title(user_message)
            if new_title and new_title != current_title:
                tm.update_thread(thread_id, title=new_title)
                generated_title = new_title
                print(f"[ws-chat] auto-titled thread {thread_id}: {new_title!r}")
    except Exception as e:
        print(f"[ws-chat] auto_generate_title failed (non-fatal): {e}")

    # process_message is sync; run in thread so the event loop stays free
    # to deliver WebSocket progress (matches source line 1677).
    response_text, conversation_state = await asyncio.to_thread(
        conversational_agent.process_message,
        user_message=user_message,
        conversation_state=conversation_state,
        state_id=thread_id,
        auto_save=True,
        uploaded_file=uploaded_file,
    )

    trace.bot_response(response_text, conversation_state.ready_for_execution)

    # === HANDLE PENDING ACTION APPROVAL/REJECTION (chat-based) ===
    response_text, conversation_state, handled = await _handle_pending_action_decision(
        conversation_state, thread_id, response_text
    )

    # === HANDLE DISAMBIGUATION SELECTION ===
    if not handled:
        response_text, conversation_state, handled = await _handle_disambiguation_selection(
            conversation_state, thread_id, response_text
        )

    # === RUN WORKFLOW IF READY ===
    if not handled and conversation_state.ready_for_execution:
        if _has_actionable_task(conversation_state):
            print(f"Thread {thread_id} ready - executing workflow...")
            trace.decision("ready_for_execution", "YES — executing workflow")
            response_text, conversation_state = await _execute_workflow_guarded(
                conversation_state, thread_id, cleanup_file=uploaded_file
            )
        else:
            trace.warning(
                "ready_for_execution=True but no task context — resetting"
            )
            conversation_state.ready_for_execution = False
            conversation_state.intent = None
            response_text = "Is there anything else I can help with?"
            conversational_agent.thread_service.save_thread_to_db(
                thread_id, conversation_state
            )

    # === Chokepoint: persist final response (closes the disappearing-
    # long-response gap; see _persist_final_response docstring) ===
    _persist_final_response(thread_id, conversation_state, response_text)

    # === Emit final WS event ===
    paused = bool(getattr(conversation_state, "workflow_paused", False))
    pending_action_id = None
    if paused:
        pending_actions = (
            getattr(conversation_state, "pending_actions", None) or []
        )
        if pending_actions:
            first = pending_actions[0]
            if isinstance(first, dict):
                pending_action_id = first.get("action_id")
            else:
                pending_action_id = getattr(first, "action_id", None)

    elapsed_ms = int((time.time() - started) * 1000)

    # Flush quota reports BEFORE we tell the browser the workflow is done.
    # Each LLM call inside the workflow submitted a fire-and-forget
    # `_report_quota_usage()` future to a thread pool — the HTTP POST to
    # /quota/report (which writes to UserQuotas) is in flight when we
    # arrive here. If we push `complete` first and let the finally
    # block flush, the browser's QuotaWidget refresh races and reads
    # the OLD UserQuotas value. Bumping flush in front of the push
    # gives the user a real-time-feeling sidebar (reported by user
    # 2026-05-03: "Why is token quota widget not updating real time?").
    # Cost: up to 3s of added latency on the WS round-trip — acceptable
    # because the browser already shows the response text via the
    # earlier broadcast_progress() / inline assistant message render;
    # this only delays the "isStreaming = false" transition. The
    # finally block still calls flush again as a safety net for any
    # report submitted after this point (none today, but cheap insurance).
    try:
        from logging_config import flush_pending_quota_reports as _flush  # type: ignore

        _flush(timeout=3.0)
    except Exception as e:
        print(f"[ws-chat] pre-push flush failed (non-fatal): {e}")

    # Spread `generated_title` only when set so the WS payload stays
    # tidy on follow-up turns (where the title was already user-set or
    # already auto-generated). The frontend treats absence and `null`
    # identically — "no title update for this push".
    title_field: Dict[str, Any] = (
        {"generated_title": generated_title} if generated_title else {}
    )

    if paused and pending_action_id:
        _stash_connection_on_pending(pending_action_id, connection_id)
        _push(
            pusher, "paused",
            thread_id=thread_id,
            action_id=pending_action_id,
            response=response_text,
            ready_for_execution=getattr(
                conversation_state, "ready_for_execution", False
            ),
            elapsed_ms=elapsed_ms,
            **title_field,
        )
        return

    _push(
        pusher, "complete",
        thread_id=thread_id,
        response=response_text,
        ready_for_execution=getattr(
            conversation_state, "ready_for_execution", False
        ),
        status="success",
        elapsed_ms=elapsed_ms,
        **title_field,
    )


# ----------------------------------------------------------------------
# Lambda entrypoint
# ----------------------------------------------------------------------


def lambda_handler(event, context):
    try:
        body_raw = event.get("body")
        if isinstance(body_raw, str):
            body = json.loads(body_raw or "{}")
        else:
            body = body_raw or {}
    except Exception:
        body = {}

    rc = event.get("requestContext") or {}
    connection_id = rc.get("connectionId")
    if not connection_id:
        print("[ws-chat] missing connectionId in requestContext")
        return _ok()

    pusher = ApiGwPusher(connection_id, event)

    action = body.get("action")
    if action == "ping":
        _push(pusher, "pong")
        return _ok()
    if action != "sendAgentMessage":
        _push(pusher, "error",
              reason="UNKNOWN_ACTION",
              message=f"Unknown action: {action}")
        return _ok()

    thread_id = body.get("thread_id")
    user_message = body.get("message")
    uploaded_file = body.get("file") or body.get("uploaded_file")
    if not thread_id or not user_message:
        _push(pusher, "error",
              reason="BAD_REQUEST",
              message="thread_id and message are required")
        return _ok()

    conn = _load_connection(connection_id)
    user_id = conn.get("user_id") or body.get("user_id")
    jwt = conn.get("jwt")
    # Per-user Google creds live in DynamoDB ``SocialTokens`` keyed by gmail.
    # The kb-stack ``$connect`` lambda may or may not have written ``gmail``
    # onto the connection row, but the JWT it stored definitely carries
    # the ``gmail`` claim (auth-google-login emits it). Read whichever is
    # available so the orchestrator can resolve the right SocialTokens row.
    user_email = (
        conn.get("gmail")
        or conn.get("email")
        or conn.get("user_email")
    )
    if not user_email and jwt:
        claims = decode_jwt_payload_unsafe(jwt)
        user_email = (
            claims.get("gmail")
            or claims.get("email")
            or claims.get("user_email")
        )
    if not user_id:
        _push(pusher, "error",
              reason="UNAUTHORIZED",
              message="No user_id on connection")
        return _ok()

    # Pre-flight quota check (matches REST path's _check_quota_or_raise).
    ok_quota, qdata = quota_check(
        user_id=user_id, jwt=jwt,
        estimated_tokens=2000, operation="ws_chat",
    )
    if not ok_quota:
        _push(
            pusher, "error",
            reason="QUOTA_EXCEEDED",
            message=(qdata or {}).get("message")
                    or f"Token quota exceeded. {((qdata or {}).get('remaining_tokens', 0))} left.",
            remaining_tokens=(qdata or {}).get("remaining_tokens"),
            monthly_limit=(qdata or {}).get("monthly_limit"),
            resets_at=(qdata or {}).get("resets_at"),
        )
        return _ok()
    if (qdata or {}).get("warning"):
        _push(pusher, "status",
              status="warning",
              message=(qdata or {}).get("warning_message")
                      or "Approaching quota limit")

    _push(pusher, "status", status="received",
          message="Analyzing your message...")

    # Brain logging context — unified import path.
    # ``supervisor_logger`` is the singleton StructuredLogger used by every
    # brain LLM call (TokenTracker → logger.llm_call) AND by the per-request
    # finalizer ``logger.request_summary()`` which is the ONLY thing that
    # writes a row to Sup_RequestSummaries. Without that row the admin
    # dashboard's Conversations / Requests / Avg-Response-Time tiles stay
    # at 0 / N/A even when the chat works end-to-end. The REST handler in
    # routes/threads.py:1719 already calls request_summary(); we mirror it
    # here so the WS path has the same observability.
    try:
        from logging_config import (  # type: ignore
            set_request_context,
            clear_request_context,
            generate_request_id,
            flush_pending_quota_reports,
            supervisor_logger as logger,
        )
    except Exception as e:
        traceback.print_exc()
        _push(pusher, "error",
              reason="BRAIN_IMPORT_FAILED",
              message=f"logging_config import failed: {e}")
        return _ok()

    global _pusher_var
    _pusher_var = pusher
    _install_progress_shim()

    set_request_context(
        request_id=generate_request_id(),
        conversation_id=thread_id,
        thread_id=thread_id,
        user_id=user_id,
        jwt=jwt,
        user_email=user_email,
    )

    try:
        try:
            asyncio.run(
                _run_chat_flow(
                    pusher=pusher,
                    connection_id=connection_id,
                    thread_id=thread_id,
                    user_message=user_message,
                    uploaded_file=uploaded_file,
                )
            )
        except Exception as e:
            traceback.print_exc()
            # Translate brain-level exceptions into WS error events. Source
            # raises HTTPException(404/409/500); we surface the detail.
            msg = getattr(e, "detail", None) or str(e)
            reason = "WORKFLOW_FAILED"
            extra: Dict[str, Any] = {}
            try:
                from llm_error_handler import LLMServiceException  # type: ignore

                if isinstance(e, LLMServiceException):
                    reason = "LLM_ERROR"
                    # Surface the structured payload (is_llm_error, error_type,
                    # user_message, etc.) so the FE's LLMErrorModal can render
                    # meaningfully. Mirrors source ``main.py`` behavior of
                    # returning ``exc.to_dict()`` as the response body.
                    try:
                        extra = e.to_dict() or {}
                    except Exception:
                        extra = {}
            except Exception:
                pass
            _push(pusher, "error", reason=reason, message=str(msg), **extra)
        return _ok()
    finally:
        # Persist the per-request summary row to Sup_RequestSummaries BEFORE
        # clear_request_context() wipes the contextvars that request_summary()
        # reads (request_id, conversation_id, thread_id, user_id,
        # token_summary, start_time). Wrapped in try/except because a
        # logging-only failure must never mask a real error from the chat
        # flow. Note: even Tier-0-only turns (e.g. "Hello" → canned greeting,
        # zero tokens) write a row here — that's intentional, the dashboard's
        # conversation/request counts include them.
        try:
            logger.request_summary()
        except Exception as e:
            print(f"[ws-chat] request_summary() failed: {e}")
        try:
            flush_pending_quota_reports(timeout=3.0)
        except Exception as e:
            print(f"[ws-chat] flush_pending_quota_reports failed: {e}")
        try:
            clear_request_context()
        except Exception:
            pass
        _pusher_var = None
