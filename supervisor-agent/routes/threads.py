"""
Thread management routes.

Handles all /threads/* endpoints for conversation thread CRUD,
messaging, file uploads, and workflow execution triggering.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from datetime import datetime, timedelta, timezone
import asyncio
import json
import hashlib
import os
import tempfile
import shutil
import traceback

# Import logging utilities
from logging_config import (
    supervisor_logger as logger,
    set_request_context,
    clear_request_context,
    generate_request_id,
    check_user_quota,
)

# Import shared objects from supervisor_agent
# (no circular dependency — supervisor_agent does NOT import from routes/)
from supervisor_agent import (
    conversational_agent,
    save_conversation_state,
)
from models.models import CreateThreadRequest
from routes.workflow import run_workflow
from execution_logger import trace
from llm_error_handler import LLMServiceException
from s3_temp_storage import store_temp_file, delete_temp_file

router = APIRouter()


async def _run_workflow_and_update_state(conversation_state):
    """
    Shared helper: execute workflow, update execution history, generate summary.
    Returns (response_text, updated_conversation_state).
    """
    # Preserve the task-specific summary before workflow overwrites it
    original_execution_summary = conversation_state.execution_summary

    supervisor_input = conversational_agent.build_supervisor_input(conversation_state)
    now_iso = datetime.now(timezone.utc).isoformat()

    trace.workflow_start(supervisor_input)

    # Build context overrides — inject uploaded_file so orchestrator can access it
    context_overrides = {}
    uploaded_file = conversation_state.extracted_info.get("uploaded_file")
    if uploaded_file:
        context_overrides["uploaded_file"] = uploaded_file

    # Determine execution mode from conversation state
    execution_mode = getattr(conversation_state, 'execution_mode', 'standard')

    status = "unknown"
    message_text = ""
    final_context = {}
    plan_dict = {}

    try:
        workflow_result = await asyncio.to_thread(
            run_workflow, supervisor_input,
            context_overrides=context_overrides or None,
            execution_mode=execution_mode,
        )
        status = workflow_result.status
        message_text = workflow_result.message
        final_context = workflow_result.final_context or {}
        plan_dict = workflow_result.plan or {}
    except LLMServiceException:
        # Re-raise LLM errors so callers see the structured error
        raise
    except HTTPException as he:
        status = "approval_required" if he.status_code == 202 else "error"
        message_text = str(he.detail) if hasattr(he, "detail") else str(he)
        trace.warning(f"Workflow HTTPException: {status}")
    except Exception as e:
        status = "error"
        message_text = str(e)
        trace.error("Workflow execution failed", exception=e)

    # Compute plan hash
    try:
        plan_json = json.dumps(plan_dict, sort_keys=True)
    except Exception:
        plan_json = json.dumps({"input": supervisor_input}, sort_keys=True)
    plan_hash = hashlib.sha256(plan_json.encode("utf-8")).hexdigest()

    # Build compact history entry — store only a summary of final_context, not the full blob
    context_summary = {
        k: (str(v)[:200] if isinstance(v, (str, list, dict)) else v)
        for k, v in list(final_context.items())[:10]
    }
    history_item = {
        "executed_at": now_iso,
        "plan_hash": plan_hash,
        "status": status,
        "message": message_text,
        "final_context_snapshot": context_summary,
    }

    # Update execution history
    conversation_state.execution_history.append(history_item)
    if len(conversation_state.execution_history) > 50:
        conversation_state.execution_history = conversation_state.execution_history[-50:]

    conversation_state.executed_count += 1
    conversation_state.last_plan_hash = plan_hash
    conversation_state.last_executed_at = now_iso
    # Keep the task-specific summary (e.g. "Send email to john@example.com"),
    # don't overwrite with the generic "Workflow executed successfully"
    conversation_state.execution_summary = original_execution_summary or message_text
    conversation_state.ready_for_execution = False

    # Generate user-friendly summary
    friendly_summary = conversational_agent.summarization_service.summarize_execution(
        conversation_state=conversation_state,
        final_context=final_context,
        execution_status=status,
        execution_message=message_text,
    )

    return friendly_summary, conversation_state


# ============================================================
# THREAD MANAGEMENT ENDPOINTS
# ============================================================


@router.post("/threads")
async def create_thread(request: CreateThreadRequest):
    """
    Create a new conversation thread.

    Returns:
        Thread metadata with thread_id
    """

    user_id = request.user_id
    initial_message = request.message

    trace.set_context(thread_id="new")
    trace.step("create_thread", f"user={user_id}, has_message={initial_message is not None}")

    # === QUOTA CHECK: Verify user has quota before processing ===
    quota_result = check_user_quota(user_id, estimated_tokens=2000)
    if not quota_result.allowed:
        trace.decision("quota_check", f"DENIED: {quota_result.error}")
        error_message = quota_result.error or "Quota check failed"
        if quota_result.user_deactivated:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "account_deactivated",
                    "message": error_message,
                    "user_message": "Your account has been deactivated. Please contact an administrator."
                }
            )
        else:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "quota_exceeded",
                    "message": error_message,
                    "user_message": error_message
                }
            )

    # === REQUEST CONTEXT: Initialize logging context. This is just for logging ===
    request_id = set_request_context(
        request_id=generate_request_id(),
        conversation_id=None,
        thread_id=None,
        user_id=user_id
    )
    trace.set_context(request_id=request_id)

    logger.info(
        f"Create thread request",
        component="api",
        operation="create_thread",
        extra={
            "user_id": user_id,
            "has_initial_message": initial_message is not None
        }
    )

    try:
        # 1. Create thread using conversational agent in thread_service.py
        thread_id, conversation_state, bot_response = conversational_agent.thread_service.create_new_thread(
            user_id=user_id,
            initial_message=initial_message
        )

        # Update logging context with real thread_id
        set_request_context(
            request_id=request_id,
            conversation_id=thread_id,
            thread_id=thread_id,
            user_id=user_id
        )
        trace.set_context(request_id=request_id, thread_id=thread_id)

        # Track whether workflow execution happened
        execution_completed = False

        # If ready for execution after initial message, execute immediately
        if initial_message and conversation_state.ready_for_execution:
            print(f"🚀 Thread {thread_id} ready - executing workflow...")
            trace.decision("ready_for_execution", "YES — executing immediately")

            # Mark as executing to prevent conflicts
            conversation_state.executing = True
            conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)

            try:
                bot_response, conversation_state = await _run_workflow_and_update_state(
                    conversation_state
                )
                execution_completed = True
            finally:
                # Clear executing flag and save
                conversation_state.executing = False
                conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)

        # Get thread metadata
        thread_metadata = conversational_agent.thread_service.get_thread_metadata(thread_id)

        response = {
            "thread_id": thread_id,
            "user_id": user_id,
            "metadata": thread_metadata,
            "message": "Thread created successfully"
        }

        # If there was an initial message, include the bot's response
        if initial_message and bot_response:
            response["bot_response"] = bot_response
            response["ready_for_execution"] = conversation_state.ready_for_execution

            if execution_completed:
                response["needs_clarification"] = False
            elif not conversation_state.ready_for_execution:
                response["needs_clarification"] = True
                response["clarification_question"] = conversation_state.clarification_question
            else:
                response["needs_clarification"] = False

        # Log request summary before returning
        logger.request_summary()
        clear_request_context()

        return response

    except HTTPException:
        logger.request_summary()
        clear_request_context()
        raise
    except Exception as e:
        print(f"❌ Error creating thread: {str(e)}")
        logger.request_summary()
        clear_request_context()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/threads/create-with-upload")
async def create_thread_with_upload(
    message: str = Form(...),
    user_id: str = Form(...),
    file: UploadFile = File(...),
):
    """
    Create a new thread with initial message AND file upload in one request.
    This prevents the "📎 Uploading file..." secondary message issue.
    """

    # === QUOTA CHECK: Verify user has quota before processing ===
    quota_result = check_user_quota(user_id, estimated_tokens=2000)
    if not quota_result.allowed:
        error_message = quota_result.error or "Quota check failed"
        if quota_result.user_deactivated:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "account_deactivated",
                    "message": error_message,
                    "user_message": "Your account has been deactivated. Please contact an administrator."
                }
            )
        else:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "quota_exceeded",
                    "message": error_message,
                    "user_message": error_message
                }
            )

    # === REQUEST CONTEXT: Initialize logging context ===
    request_id = set_request_context(
        request_id=generate_request_id(),
        conversation_id=None,
        thread_id=None,
        user_id=user_id
    )
    trace.set_context(request_id=request_id)

    logger.info(
        f"Create thread with upload request",
        component="api",
        operation="create_thread_upload",
        extra={
            "user_id": user_id,
            "filename": file.filename,
            "message_preview": message[:50] + "..." if len(message) > 50 else message
        }
    )

    try:
        # Store file via temp storage (local or S3 depending on TEMP_STORAGE_BACKEND)
        uploaded_file = store_temp_file(file.file, file.filename, file.content_type or "application/octet-stream")

        print(f"  → Stored: {uploaded_file.get('temp_path') or uploaded_file.get('s3_key')}")
        print(f"  → Size: {uploaded_file['size']} bytes")

        # Create thread with initial message AND file
        thread_id, conversation_state, bot_response = conversational_agent.thread_service.create_new_thread(
            user_id=user_id,
            initial_message=message
        )

        # Update logging context with real thread_id
        set_request_context(
            request_id=request_id,
            conversation_id=thread_id,
            thread_id=thread_id,
            user_id=user_id
        )

        # Store in both cache and SQLite for persistence
        save_conversation_state(thread_id, conversation_state)

        # Process message with file
        response_text, updated_state = conversational_agent.process_message(
            user_message=message,
            conversation_state=conversation_state,
            state_id=thread_id,
            auto_save=True,
            uploaded_file=uploaded_file
        )

        print(f"🤖 Bot response: {response_text}")
        print(f"✅ Ready to execute: {updated_state.ready_for_execution}")

        # If ready for execution, execute immediately
        if updated_state.ready_for_execution:
            print(f"🚀 Thread {thread_id} ready - executing workflow...")

            updated_state.executing = True
            conversational_agent.thread_service.save_thread_to_db(thread_id, updated_state)

            try:
                response_text, updated_state = await _run_workflow_and_update_state(
                    updated_state
                )
            finally:
                updated_state.executing = False
                conversational_agent.thread_service.save_thread_to_db(thread_id, updated_state)

                # Clean up temp file after workflow completes
                delete_temp_file(uploaded_file)
                print(f"🗑️ Cleaned up uploaded file")
        # else: Do NOT delete — file persists (local or S3) until workflow
        # eventually executes.  S3 lifecycle rule handles orphan cleanup.

        # Get thread metadata
        metadata = conversational_agent.thread_service.get_thread_metadata(thread_id)

        # Log request summary before returning
        logger.request_summary()
        clear_request_context()

        return {
            "thread_id": thread_id,
            "bot_response": response_text,
            "ready_for_execution": updated_state.ready_for_execution,
            "metadata": metadata
        }

    except Exception as e:
        print(f"\n❌ Error creating thread with upload: {str(e)}")
        traceback.print_exc()

        # Clean up temp file on error
        if 'uploaded_file' in locals():
            delete_temp_file(uploaded_file)
            print(f"🗑️ Cleaned up uploaded file on error")

        clear_request_context()
        raise HTTPException(status_code=500, detail=f"Failed to create thread with file: {str(e)}")


# NOTE: /threads/search MUST be defined BEFORE /threads/{thread_id}
# otherwise FastAPI matches "search" as a thread_id path parameter.
@router.get("/threads/search")
async def search_threads(user_id: str, q: str, limit: int = 20):
    """
    Search user's threads by title.

    Args:
        user_id: User identifier (required)
        q: Search query (required)
        limit: Maximum results - default: 20

    Returns:
        List of matching threads
    """

    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")
        if not q:
            raise HTTPException(status_code=400, detail="search query (q) is required")

        threads = conversational_agent.thread_service.search_threads(
            user_id=user_id,
            query=q,
            limit=limit
        )

        return {
            "user_id": user_id,
            "query": q,
            "threads": threads,
            "count": len(threads)
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error searching threads: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/threads")
async def list_threads(user_id: str, status: str = "active", limit: int = 50, offset: int = 0):
    """
    List all threads for a user.

    Args:
        user_id: User identifier (required)
        status: Filter by status (active, archived, all) - default: active
        limit: Maximum results - default: 50
        offset: Pagination offset - default: 0

    Returns:
        List of thread metadata
    """

    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")

        threads = conversational_agent.thread_service.list_user_threads(
            user_id=user_id,
            status=status,
            limit=limit,
            offset=offset
        )

        return {
            "user_id": user_id,
            "threads": threads,
            "count": len(threads),
            "limit": limit,
            "offset": offset
        }

    except Exception as e:
        print(f"❌ Error listing threads: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: str):
    """
    Get metadata for a specific thread.

    Args:
        thread_id: Thread identifier

    Returns:
        Thread metadata
    """

    try:
        metadata = conversational_agent.thread_service.get_thread_metadata(thread_id)

        if not metadata:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

        return {
            "thread_id": thread_id,
            "metadata": metadata
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error getting thread: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/threads/{thread_id}/messages")
async def get_thread_messages(thread_id: str, limit: int = 50, offset: int = 0):
    """
    Get full conversation history for a thread from messages table.

    Args:
        thread_id: Thread identifier
        limit: Maximum messages to return (default: 50)
        offset: Pagination offset (default: 0)

    Returns:
        List of messages with role, content, and created_at
    """

    try:
        messages = conversational_agent.thread_service.get_thread_messages(
            thread_id=thread_id,
            limit=limit,
            offset=offset
        )

        if messages is None:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

        return {
            "thread_id": thread_id,
            "messages": messages,
            "count": len(messages),
            "limit": limit,
            "offset": offset
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error getting thread messages: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/threads/{thread_id}/messages")
async def send_message_to_thread(thread_id: str, request: dict):
    """
    Continue a thread by sending a new message.

    Args:
        thread_id: Thread identifier
        request: {"message": str (required)}

    Returns:
        Bot response and updated thread metadata
    """

    # === QUOTA CHECK: Extract user_id from thread_id and verify quota ===
    user_id = thread_id.split('_')[0] if '_' in thread_id else None
    if user_id:
        quota_result = check_user_quota(user_id, estimated_tokens=2000)
        if not quota_result.allowed:
            error_message = quota_result.error or "Quota check failed"
            if quota_result.user_deactivated:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "account_deactivated",
                        "message": error_message,
                        "user_message": "Your account has been deactivated. Please contact an administrator."
                    }
                )
            else:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "quota_exceeded",
                        "message": error_message,
                        "user_message": error_message
                    }
                )

    # === REQUEST CONTEXT: Initialize logging context for this thread ===
    conversation_id = thread_id.split('_')[-1] if '_' in thread_id else thread_id
    request_id = set_request_context(
        request_id=generate_request_id(),
        conversation_id=conversation_id,
        thread_id=thread_id,
        user_id=user_id
    )
    trace.set_context(request_id=request_id, thread_id=thread_id)

    logger.info(
        f"Thread message received",
        component="api",
        operation="thread_message",
        extra={
            "thread_id": thread_id,
            "message_preview": request.get("message", "")[:50] + "..." if len(request.get("message", "")) > 50 else request.get("message", "")
        }
    )

    try:
        message = request.get("message")
        if not message:
            raise HTTPException(status_code=400, detail="message is required")

        trace.set_context(request_id=request_id, thread_id=thread_id)
        trace.user_message(message, thread_id)

        # Load current conversation state
        conversation_state = conversational_agent.thread_service.load_thread_from_db(thread_id)

        if conversation_state is None:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

        # Check if conversation is currently executing - reject to avoid conflicts
        if conversation_state.executing:
            print(f"⏳ Thread {thread_id} is executing — rejecting new input")
            raise HTTPException(
                status_code=409,
                detail="Thread is currently executing. Please wait until the operation completes.",
            )

        # Continue the thread
        response_text, conversation_state = conversational_agent.thread_service.continue_thread(
            thread_id=thread_id,
            new_message=message
        )

        trace.bot_response(response_text, conversation_state.ready_for_execution)

        # If ready for execution, execute immediately
        if conversation_state.ready_for_execution:
            print(f"🚀 Thread {thread_id} ready - executing workflow...")
            trace.decision("ready_for_execution", "YES — executing workflow")

            # Mark as executing to prevent conflicts
            conversation_state.executing = True
            conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)

            try:
                response_text, conversation_state = await _run_workflow_and_update_state(
                    conversation_state
                )
            finally:
                # Clear executing flag and save
                conversation_state.executing = False
                conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)

        # Get updated metadata
        metadata = conversational_agent.thread_service.get_thread_metadata(thread_id)

        # Log request summary before returning
        logger.request_summary()
        clear_request_context()

        return {
            "thread_id": thread_id,
            "bot_response": response_text,
            "ready_for_execution": conversation_state.ready_for_execution,
            "metadata": metadata
        }

    except HTTPException:
        clear_request_context()
        raise
    except ValueError as e:
        clear_request_context()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"❌ Error sending message to thread: {str(e)}")
        clear_request_context()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/threads/{thread_id}/messages/upload")
async def send_message_to_thread_with_upload(
    thread_id: str,
    message: str = Form(...),
    file: UploadFile = File(...)
):
    """
    Continue a thread by sending a new message with file upload.

    Args:
        thread_id: Thread identifier
        message: User's message (required)
        file: File upload (required)

    Returns:
        Bot response and updated thread metadata
    """

    # === REQUEST CONTEXT: Initialize logging context for this thread ===
    conversation_id = thread_id.split('_')[-1] if '_' in thread_id else thread_id
    user_id = thread_id.split('_')[0] if '_' in thread_id else None
    request_id = set_request_context(
        request_id=generate_request_id(),
        conversation_id=conversation_id,
        thread_id=thread_id,
        user_id=user_id
    )
    trace.set_context(request_id=request_id, thread_id=thread_id)

    logger.info(
        f"Thread message with upload received",
        component="api",
        operation="thread_message_upload",
        extra={
            "thread_id": thread_id,
            "filename": file.filename,
            "message_preview": message[:50] + "..." if len(message) > 50 else message
        }
    )

    try:
        print(f"\n📎 File upload to thread {thread_id}: {file.filename}")

        # Store file via temp storage (local or S3 depending on TEMP_STORAGE_BACKEND)
        uploaded_file = store_temp_file(file.file, file.filename, file.content_type or "application/octet-stream")

        print(f"  → Stored: {uploaded_file.get('temp_path') or uploaded_file.get('s3_key')}")
        print(f"  → Size: {uploaded_file['size']} bytes")

        # Load current conversation state
        conversation_state = conversational_agent.thread_service.load_thread_from_db(thread_id)

        if conversation_state is None:
            delete_temp_file(uploaded_file)
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

        # Check if conversation is currently executing
        if conversation_state.executing:
            print(f"⏳ Thread {thread_id} is executing — rejecting new input")
            delete_temp_file(uploaded_file)
            raise HTTPException(
                status_code=409,
                detail="Thread is currently executing. Please wait until the operation completes.",
            )

        # Process message with file
        response_text, updated_state = conversational_agent.process_message(
            user_message=message,
            conversation_state=conversation_state,
            state_id=thread_id,
            auto_save=True,
            uploaded_file=uploaded_file
        )

        print(f"🤖 Bot response: {response_text}")
        print(f"✅ Ready to execute: {updated_state.ready_for_execution}")

        # If ready for execution, execute immediately
        if updated_state.ready_for_execution:
            print(f"🚀 Thread {thread_id} ready - executing workflow...")

            # Mark as executing to prevent conflicts
            updated_state.executing = True
            conversational_agent.thread_service.save_thread_to_db(thread_id, updated_state)

            try:
                response_text, updated_state = await _run_workflow_and_update_state(
                    updated_state
                )
            finally:
                # Clear executing flag and save
                updated_state.executing = False
                conversational_agent.thread_service.save_thread_to_db(thread_id, updated_state)

                # Clean up temp file after workflow completes
                delete_temp_file(uploaded_file)
                print(f"🗑️ Cleaned up uploaded file")
        # else: Do NOT delete — file persists until workflow eventually executes.
        # S3 lifecycle rule handles orphan cleanup.

        # Get updated metadata
        metadata = conversational_agent.thread_service.get_thread_metadata(thread_id)

        # Log request summary before returning
        logger.request_summary()
        clear_request_context()

        return {
            "thread_id": thread_id,
            "bot_response": response_text,
            "ready_for_execution": updated_state.ready_for_execution,
            "metadata": metadata
        }

    except HTTPException:
        clear_request_context()
        raise
    except Exception as e:
        print(f"\n❌ Error sending message with upload to thread: {str(e)}")
        traceback.print_exc()

        # Clean up temp file on error
        if 'uploaded_file' in locals():
            delete_temp_file(uploaded_file)
            print(f"🗑️ Cleaned up uploaded file on error")

        clear_request_context()
        raise HTTPException(status_code=500, detail=f"Upload processing failed: {str(e)}")


@router.put("/threads/{thread_id}")
async def update_thread(thread_id: str, request: dict):
    """
    Update thread metadata.

    Args:
        thread_id: Thread identifier
        request: {
            "title": str (optional),
            "tags": List[str] (optional),
            "status": str (optional)
        }

    Returns:
        Updated thread metadata
    """

    try:
        title = request.get("title")
        tags = request.get("tags")
        status = request.get("status")

        success = conversational_agent.thread_service.update_thread_metadata(
            thread_id=thread_id,
            title=title,
            tags=tags,
            status=status
        )

        if not success:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

        # Get updated metadata
        metadata = conversational_agent.thread_service.get_thread_metadata(thread_id)

        return {
            "thread_id": thread_id,
            "metadata": metadata,
            "message": "Thread updated successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error updating thread: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/threads/{thread_id}")
async def delete_thread(thread_id: str, hard_delete: bool = False):
    """
    Delete a thread (archive by default, hard delete if specified).

    Args:
        thread_id: Thread identifier
        hard_delete: If true, permanently delete. Otherwise, archive.

    Returns:
        Success message
    """

    try:
        success = conversational_agent.thread_service.delete_thread(
            thread_id=thread_id,
            hard_delete=hard_delete
        )

        if not success:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

        action = "deleted permanently" if hard_delete else "archived"

        return {
            "thread_id": thread_id,
            "message": f"Thread {action} successfully",
            "hard_delete": hard_delete
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error deleting thread: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
