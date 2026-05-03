"""supervisor-create-thread-upload — POST /threads/create-with-upload (Docker)

Two transport variants are supported on the same Lambda:

  1. ``Content-Type: multipart/form-data`` — the original FastAPI shape. The
     Lambda parses the body itself (API Gateway passes through the binary
     body; the function's ``BinaryMediaTypes`` config lists multipart). The
     uploaded file is then stored via ``s3_temp_storage.store_temp_file``.

  2. ``Content-Type: application/json`` with ``s3_key`` and ``filename`` —
     the FE has already issued a presigned PUT to S3 and just needs the
     supervisor to pick the object up. This is the recommended shape for
     large files because API Gateway caps multipart uploads at 10 MB.

After file storage, the Tier 0/0.5/1 enrichment runs identically to
``supervisor-create-thread`` so the FE can decide whether to ask for
clarification or hand off to the WebSocket for execution.
"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback
import base64
import json
import io

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(_HERE, "shared")
for p in (_SHARED, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

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


def _decode_body(event):
    body = event.get("body")
    if body is None:
        return b""
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    if isinstance(body, str):
        if event.get("isBase64Encoded"):
            try:
                return base64.b64decode(body)
            except Exception:
                return body.encode("utf-8", errors="replace")
        return body.encode("utf-8", errors="replace")
    return b""


def _parse_multipart(content_type: str, body_bytes: bytes):
    """Returns (fields_dict, files_list). files_list = [{filename, content_type, content}]."""
    import cgi
    fp = io.BytesIO(body_bytes)
    env = {"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type, "CONTENT_LENGTH": str(len(body_bytes))}
    fs = cgi.FieldStorage(fp=fp, environ=env, keep_blank_values=True)
    fields = {}
    files = []
    if fs.list is None:
        return fields, files
    for item in fs.list:
        if item.filename:
            files.append({
                "filename": item.filename,
                "content_type": item.type or "application/octet-stream",
                "content": item.file.read() if hasattr(item.file, "read") else item.value,
            })
        else:
            fields[item.name] = item.value
    return fields, files


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    content_type = headers.get("content-type") or ""

    user_id = None
    initial_message = None
    uploaded_file = None
    cleanup_path = None

    try:
        if "multipart/form-data" in content_type:
            body_bytes = _decode_body(event)
            fields, files = _parse_multipart(content_type, body_bytes)
            user_id = fields.get("user_id")
            initial_message = fields.get("message")
            if not files:
                return error_response(400, "file is required")
            file_obj = files[0]
            try:
                from s3_temp_storage import store_temp_file  # type: ignore
            except Exception as e:
                return error_response(500, f"s3_temp_storage import failed: {e}")
            try:
                uploaded_file = store_temp_file(
                    io.BytesIO(file_obj["content"]),
                    file_obj["filename"],
                    file_obj["content_type"],
                )
                cleanup_path = uploaded_file
            except Exception as e:
                traceback.print_exc()
                return error_response(500, f"store_temp_file failed: {e}")
        else:
            body = parse_body(event)
            user_id = body.get("user_id")
            initial_message = body.get("message")
            s3_key = body.get("s3_key")
            filename = body.get("filename")
            if not s3_key or not filename:
                return error_response(
                    400,
                    "JSON path requires s3_key and filename. For raw uploads, send Content-Type: multipart/form-data.",
                )
            uploaded_file = {
                "s3_key": s3_key,
                "filename": filename,
                "size": int(body.get("size") or 0),
                "content_type": body.get("content_type") or "application/octet-stream",
                "storage": "s3",
            }

        if not user_id:
            return error_response(400, "user_id is required")
        if not initial_message:
            return error_response(400, "message is required")

        with set_request_context_lambda(event, user_id=user_id) as ctx:
            ok, info = quota_check(
                user_id=ctx["user_id"], jwt=ctx["jwt"],
                estimated_tokens=2500, operation="thread_create_upload",
            )
            if not ok:
                msg = (info or {}).get("message") or "Token quota exceeded"
                return error_response(429, msg, **{k: v for k, v in (info or {}).items() if k != "allowed"})

            tm = get_thread_manager()
            try:
                metadata = tm.create_thread(user_id=user_id)
                thread_id = metadata.thread_id
            except Exception as e:
                traceback.print_exc()
                return error_response(500, f"Error creating thread: {e}")

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
                print(f"[create-thread-upload] auto_generate_title failed (non-fatal): {e}")

            conversation_state = ConversationState()
            try:
                save_conversation_state(thread_id, conversation_state)
            except Exception as e:
                print(f"[create-thread-upload] save_conversation_state pre-flight failed (non-fatal): {e}")

            try:
                bot_response, conversation_state = conversational_agent.process_message(
                    user_message=initial_message,
                    conversation_state=conversation_state,
                    state_id=thread_id,
                    auto_save=True,
                    uploaded_file=uploaded_file,
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

            # === Mirror source create_thread_with_upload (lines 1419-1437):
            # if ready, run workflow inline so a "create + upload + send"
            # REST call returns the FINAL friendly summary (not the Tier-1
            # stub). Pass cleanup_file so _execute_workflow_guarded deletes
            # the uploaded temp file in its `finally` block. ===
            execution_completed = False
            cleanup_handled_by_workflow = False
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
                            _execute_workflow_guarded(
                                conversation_state, thread_id,
                                cleanup_file=uploaded_file,
                            )
                        )
                        execution_completed = True
                        cleanup_handled_by_workflow = True
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
                    conversation_state.ready_for_execution = False
                    conversation_state.intent = None
                    bot_response = "Is there anything else I can help with?"
                    try:
                        conversational_agent.thread_service.save_thread_to_db(
                            thread_id, conversation_state
                        )
                    except Exception:
                        pass

                try:
                    _persist_final_response(thread_id, conversation_state, bot_response)
                except Exception as e:
                    print(f"[create-thread-upload] _persist_final_response failed (non-fatal): {e}")

            # If we did NOT run the workflow (no task, clarification path,
            # ready=False), the upload is still on disk/S3. Source leaves
            # it in place because process_message persisted the file ref
            # into conversation_state for the next turn.
            if cleanup_handled_by_workflow:
                cleanup_path = None  # _execute_workflow_guarded already deleted it.

            try:
                save_conversation_state(thread_id, conversation_state)
            except Exception as e:
                print(f"[create-thread-upload] save_conversation_state post-flight failed (non-fatal): {e}")

            try:
                fresh = tm.get_thread(thread_id)
                metadata_dict = (fresh or metadata).model_dump()
            except Exception:
                metadata_dict = metadata.model_dump()

            response = {
                "thread_id": thread_id,
                "user_id": user_id,
                "metadata": metadata_dict,
                "uploaded_file": {
                    "filename": uploaded_file.get("filename"),
                    "size": uploaded_file.get("size"),
                    "s3_key": uploaded_file.get("s3_key"),
                },
                "bot_response": bot_response,
                "ready_for_execution": bool(getattr(conversation_state, "ready_for_execution", False)),
                "message": "Thread created successfully",
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
    except Exception as e:
        traceback.print_exc()
        if cleanup_path:
            try:
                from s3_temp_storage import delete_temp_file  # type: ignore
                delete_temp_file(cleanup_path)
            except Exception:
                pass
        return error_response(500, f"Failed to create thread with file: {e}")
