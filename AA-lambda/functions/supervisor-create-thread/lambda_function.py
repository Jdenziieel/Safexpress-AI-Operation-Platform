"""supervisor-create-thread — POST /threads (Docker Lambda)

Two paths:
  1. ``initial_message`` absent — fast path: just creates an empty thread via
     the persistence factory and returns metadata. No brain import. This is
     why ``supervisor-create-thread`` can be invoked very early in a session
     without paying the langchain cold-start tax.
  2. ``initial_message`` present — runs Tier 0/0.5/1 enrichment via
     ``conversational_agent.process_message``, then \u2014 mirroring source
     ``routes/threads.py:create_thread`` lines 1262\u20131297 \u2014 invokes
     ``_execute_workflow_guarded`` when the conversation reaches
     ``ready_for_execution=True`` AND a real task is buffered, finally calling
     ``_persist_final_response`` to write the full friendly summary to the
     messages table (closes the disappearing-long-response gap).

     This keeps source behavior verbatim: a "create + send" REST call returns
     the FINAL workflow response, not just the Tier-1 stub. Workflows that
     exceed API Gateway's 29s window finish in the background \u2014 the row
     is persisted, and any open WebSocket on this thread receives the live
     progress events through ``supervisor-agent``'s existing
     ``progress_manager`` (no shim wired here because the create-thread
     REST call doesn't carry a connection_id).
"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(_HERE, "shared")
for p in (_SHARED, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

# Swap thread_manager / log_storage to DDB BEFORE the brain imports them.
from shared.lambda_helpers import (  # noqa: E402
    install_persistence_backend,
    success_response,
    error_response,
    llm_error_response,
    options_response,
    parse_body,
    set_request_context_lambda,
    quota_check,
)
from shared.persistence_factory import get_thread_manager  # noqa: E402

install_persistence_backend()


def _quota_block_or_none(user_id, jwt):
    if not user_id:
        return None
    ok, info = quota_check(user_id=user_id, jwt=jwt, estimated_tokens=1500, operation="thread_create")
    if ok:
        return None
    msg = (info or {}).get("message") or "Token quota exceeded"
    return error_response(429, msg, **{k: v for k, v in (info or {}).items() if k != "allowed"})


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    body = parse_body(event)
    user_id = body.get("user_id")
    initial_message = body.get("message")

    if not user_id:
        return error_response(400, "user_id is required")

    with set_request_context_lambda(event, user_id=user_id) as ctx:
        denial = _quota_block_or_none(ctx["user_id"], ctx["jwt"])
        if denial is not None:
            return denial

        tm = get_thread_manager()

        try:
            metadata = tm.create_thread(user_id=user_id)
            thread_id = metadata.thread_id
        except Exception as e:
            traceback.print_exc()
            return error_response(500, f"Error creating thread: {e}")

        if not initial_message:
            # Mirror ThreadService.create_new_thread's no-initial-message
            # branch: also persist an empty ConversationState to
            # Sup_ThreadStates so a later sendAgentMessage / continue-thread
            # call can load it via load_thread_from_db. Without this, the
            # WS handler's load returns None and the user sees
            # "Thread <id> not found". Pydantic-only import — no langchain
            # cold-start tax.
            try:
                from models.models import ConversationState  # type: ignore

                tm.save_thread_state(thread_id, ConversationState())
            except Exception as e:
                print(
                    f"[create-thread] initial save_thread_state failed "
                    f"(non-fatal, ws-chat will defensively re-init): {e}"
                )

            try:
                fresh = tm.get_thread(thread_id)
                return success_response({
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "metadata": (fresh or metadata).model_dump(),
                    "message": "Thread created successfully",
                })
            except Exception as e:
                traceback.print_exc()
                return error_response(500, f"Error fetching thread metadata: {e}")

        try:
            from models.models import ConversationState  # type: ignore
            from supervisor_agent import (  # type: ignore
                conversational_agent,
                save_conversation_state,
            )
        except Exception as e:
            traceback.print_exc()
            return error_response(500, f"Brain import failed: {e}")

        try:
            auto_title = conversational_agent.thread_manager.auto_generate_title(initial_message)
            conversational_agent.thread_manager.update_thread(thread_id, title=auto_title)
        except Exception as e:
            print(f"[create-thread] auto_generate_title failed (non-fatal): {e}")

        conversation_state = ConversationState()
        try:
            save_conversation_state(thread_id, conversation_state)
        except Exception as e:
            print(f"[create-thread] save_conversation_state pre-flight failed (non-fatal): {e}")

        try:
            bot_response, conversation_state = conversational_agent.process_message(
                user_message=initial_message,
                conversation_state=conversation_state,
                state_id=thread_id,
                auto_save=True,
            )
        except Exception as e:
            try:
                from llm_error_handler import LLMServiceException  # type: ignore

                if isinstance(e, LLMServiceException):
                    return llm_error_response(e)
            except Exception:
                pass
            traceback.print_exc()
            return error_response(500, f"process_message failed: {e}")

        # === Mirror source create_thread (lines 1275-1297): if ready, run
        # the workflow inline so a "create + send" REST call returns the
        # final friendly summary, not the Tier-1 stub. ===
        execution_completed = False
        if getattr(conversation_state, "ready_for_execution", False):
            try:
                from routes.threads import (  # type: ignore
                    _execute_workflow_guarded,
                    _has_actionable_task,
                    _persist_final_response,
                )
            except Exception as e:
                traceback.print_exc()
                return error_response(500, f"routes.threads import failed: {e}")

            if _has_actionable_task(conversation_state):
                try:
                    bot_response, conversation_state = asyncio.run(
                        _execute_workflow_guarded(conversation_state, thread_id)
                    )
                    execution_completed = True
                except Exception as e:
                    try:
                        from llm_error_handler import LLMServiceException  # type: ignore

                        if isinstance(e, LLMServiceException):
                            return llm_error_response(e)
                    except Exception:
                        pass
                    traceback.print_exc()
                    return error_response(500, f"workflow execution failed: {e}")
            else:
                # Source resets when ready_for_execution=True but no task
                # context was buffered (lines 1283-1288).
                conversation_state.ready_for_execution = False
                conversation_state.intent = None
                bot_response = "Is there anything else I can help with?"
                try:
                    conversational_agent.thread_service.save_thread_to_db(
                        thread_id, conversation_state
                    )
                except Exception:
                    pass

            # Chokepoint: persist FINAL post-handler response so the long
            # rendered text survives a thread switch / re-login.
            try:
                _persist_final_response(thread_id, conversation_state, bot_response)
            except Exception as e:
                print(f"[create-thread] _persist_final_response failed (non-fatal): {e}")

        try:
            save_conversation_state(thread_id, conversation_state)
        except Exception as e:
            print(f"[create-thread] save_conversation_state post-flight failed (non-fatal): {e}")

        try:
            fresh = tm.get_thread(thread_id)
            metadata_dict = (fresh or metadata).model_dump()
        except Exception:
            metadata_dict = metadata.model_dump()

        response = {
            "thread_id": thread_id,
            "user_id": user_id,
            "metadata": metadata_dict,
            "message": "Thread created successfully",
            "bot_response": bot_response,
            "ready_for_execution": bool(getattr(conversation_state, "ready_for_execution", False)),
        }
        if execution_completed:
            response["needs_clarification"] = False
        elif not response["ready_for_execution"]:
            response["needs_clarification"] = True
            response["clarification_question"] = getattr(
                conversation_state, "clarification_question", None
            )
        else:
            response["needs_clarification"] = False
        return success_response(response)
