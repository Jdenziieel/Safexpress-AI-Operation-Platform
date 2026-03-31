"""
Thread management routes.

Handles all /threads/* endpoints for conversation thread CRUD,
messaging, file uploads, and workflow execution triggering.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from datetime import datetime, timedelta, timezone
import asyncio
import json
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
from routes.actions import execute_single_action
from checks.tier0_checks import _build_rich_approval_message
from execution_logger import trace
from llm_error_handler import LLMServiceException
from s3_temp_storage import store_temp_file, delete_temp_file

router = APIRouter()


async def _resume_remaining_steps(conversation_state, previous_result, response_prefix, thread_id,
                                   approved_step_info: dict = None):
    """
    Resume execution of remaining steps after an approved action.
    
    Rebuilds the variable context from the previous result and the saved workflow_context,
    then re-invokes the orchestrator for remaining steps.
    
    Args:
        approved_step_info: The pending action dict (has step_number, agent, output_variables, etc.)
    
    Returns (response_text, updated_conversation_state).
    """
    remaining = conversation_state.remaining_steps
    if not remaining:
        return response_prefix + "\nIs there anything else you'd like to do?", conversation_state
    
    # Rebuild context — merge saved workflow_context with the result from the approved action
    variable_context = conversation_state.workflow_context or {}
    
    # Add the result from the just-executed action under its step namespace
    if previous_result and isinstance(previous_result, dict):
        agent_result = previous_result.get("result", previous_result)
        fields_to_add = {k: v for k, v in agent_result.items() if k not in ("success", "error")}

        step_num = (approved_step_info or {}).get("step_number", 0)
        agent_name = (approved_step_info or {}).get("agent", "unknown")
        namespace_key = f"step_{step_num}_{agent_name}"
        variable_context[namespace_key] = fields_to_add

        # Process output_variables declared in the plan for this step
        from supervisor_agent import extract_nested_value
        output_vars = (approved_step_info or {}).get("output_variables", {})
        for new_var_name, source_field_name in output_vars.items():
            value = extract_nested_value(agent_result, source_field_name)
            if value is not None:
                variable_context[new_var_name] = value
            elif source_field_name in agent_result:
                variable_context[new_var_name] = agent_result[source_field_name]
    
    # Build a mini plan from remaining steps and run workflow orchestrator directly
    from supervisor_agent import orchestrator_node
    from datetime import datetime as dt
    
    mini_plan = {"steps": remaining}
    mini_state = {
        "input": "",
        "plan": mini_plan,
        "context": variable_context,
        "final_context": {},
        "execution_mode": "standard",
        "results": [],
        "error": "",
        "stopped_at_step": 0,
        "react_history": [],
        "react_iteration": 0,
        "react_done": False,
    }
    
    try:
        result_state = await asyncio.to_thread(orchestrator_node, mini_state)
        
        final_context = result_state.get("final_context", {})
        results = final_context.get("results", [])
        
        # Check if the resumed execution also paused for approval
        if final_context.get("paused_for_approval"):
            pending_action = final_context.get("pending_action", {})
            pending_action_id = final_context.get("pending_action_id", "")
            new_remaining = final_context.get("remaining_steps", [])
            
            conversation_state.workflow_paused = True
            conversation_state.pending_actions = [{
                "action_id": pending_action_id,
                **pending_action,
            }]
            conversation_state.remaining_steps = new_remaining
            # Update workflow context for next resumption
            ctx = {k: v for k, v in final_context.items()
                   if k not in ("paused_for_approval", "pending_action", "pending_action_id", "remaining_steps", "results")}
            conversation_state.workflow_context = ctx
            
            # Build approval message for the next step
            approval_msg = _build_rich_approval_message(conversation_state.pending_actions[0])
            
            # Add completed steps from this resumption
            completed = [r for r in results if r.get("status") == "success"]
            if completed:
                steps_summary = "\n".join(f"  ✅ Step {r['step']}: {r.get('description', r.get('tool', ''))}" for r in completed)
                response_prefix += f"\n{steps_summary}\n"
            
            return response_prefix + "\n\n" + approval_msg, conversation_state
        
        # All remaining steps completed
        conversation_state.remaining_steps = []
        conversation_state.workflow_context = None
        
        # Build rich summary from results with actual data
        completed = [r for r in results if r.get("status") == "success"]
        errors = [r for r in results if r.get("status") == "error"]
        
        if completed:
            for r in completed:
                desc = r.get("description", r.get("tool", ""))
                response_prefix += f"\n  ✅ {desc}"
        
        if errors:
            for r in errors:
                desc = r.get("description", r.get("tool", ""))
                err = r.get("error", "Unknown error")
                response_prefix += f"\n  ❌ {desc}: {err}"
        
        response_prefix += "\n\nAll steps completed! Is there anything else you'd like to do?"
        
        return response_prefix, conversation_state
        
    except Exception as e:
        print(f"❌ Error resuming remaining steps: {str(e)}")
        conversation_state.remaining_steps = []
        conversation_state.workflow_context = None
        return response_prefix + f"\n\n❌ Error continuing workflow: {str(e)}", conversation_state


# --- REACT FLOW DISABLED — uncomment to re-enable ---
# async def _resume_react_workflow(conversation_state, previous_result, response_prefix, thread_id):
#     """
#     Resume a ReAct workflow after an approved action.
#     
#     Re-invokes the react_workflow with accumulated history so the planner can
#     observe the approved action's result and decide the next step.
#     
#     Returns (response_text, updated_conversation_state).
#     """
#     saved_ctx = conversation_state.workflow_context or {}
#     react_history = list(saved_ctx.get("_react_history", []))
#     react_iteration = saved_ctx.get("_react_iteration", 0)
#     supervisor_input = saved_ctx.get("_supervisor_input", "")
#     
#     # Build observation for the just-approved action
#     pending = conversation_state.pending_actions[0] if conversation_state.pending_actions else {}
#     approved_obs = {
#         "agent": pending.get("agent", "unknown"),
#         "tool": pending.get("tool", "unknown"),
#         "description": pending.get("description", ""),
#         "status": "success" if previous_result.get("success") else "error",
#         "output_summary": str(previous_result)[:300],
#         "error": previous_result.get("error"),
#     }
#     react_history.append(approved_obs)
#     
#     # Rebuild context (strip internal keys)
#     variable_context = {k: v for k, v in saved_ctx.items() if not k.startswith("_")}
#     
#     # Add result from the approved action to context
#     if previous_result and isinstance(previous_result, dict):
#         agent_result = previous_result.get("result", previous_result)
#         fields_to_add = {k: v for k, v in agent_result.items() if k not in ("success", "error")}
#         variable_context.update(fields_to_add)
#     
#     # Clear pending state before re-invoking
#     conversation_state.pending_actions = []
#     conversation_state.workflow_paused = False
#     
#     from supervisor_agent import react_workflow as react_wf
#     from datetime import datetime as dt
#     from models.models import SharedState
#     
#     initial_state = {
#         "input": supervisor_input,
#         "plan": {"steps": []},  # Empty — planner will generate next step
#         "context": variable_context,
#         "final_context": {},
#         "execution_mode": "react",
#         "results": [],  # Results from prev iteration already in react_history
#         "error": "",
#         "stopped_at_step": 0,
#         "react_history": react_history,
#         "react_iteration": react_iteration,
#         "react_done": False,
#     }
#     
#     try:
#         result_state = await asyncio.to_thread(react_wf.invoke, initial_state)
#         
#         final_context = result_state.get("final_context", {})
#         
#         # Check if the resumed react workflow also paused for approval
#         if final_context.get("paused_for_approval"):
#             new_pending = final_context.get("pending_action", {})
#             new_pending_id = final_context.get("pending_action_id", "")
#             
#             conversation_state.workflow_paused = True
#             conversation_state.pending_actions = [{"action_id": new_pending_id, **new_pending}]
#             conversation_state.remaining_steps = []
#             
#             # Save updated react state for next resumption
#             ctx = {k: v for k, v in final_context.items()
#                    if k not in ("paused_for_approval", "pending_action", "pending_action_id", "results")}
#             ctx["_execution_mode"] = "react"
#             ctx["_react_history"] = result_state.get("react_history", react_history)
#             ctx["_react_iteration"] = result_state.get("react_iteration", react_iteration + 1)
#             ctx["_supervisor_input"] = supervisor_input
#             conversation_state.workflow_context = ctx
#             
#             approval_msg = _build_rich_approval_message(conversation_state.pending_actions[0])
#             return response_prefix + "\n\n" + approval_msg, conversation_state
#         
#         # React workflow completed
#         conversation_state.remaining_steps = []
#         conversation_state.workflow_context = None
#         
#         react_summary = final_context.get("react_summary", "Task completed.")
#         response_prefix += f"\n\n{react_summary}"
#         response_prefix += "\n\nIs there anything else you'd like to do?"
#         
#         return response_prefix, conversation_state
#         
#     except Exception as e:
#         print(f"❌ Error resuming ReAct workflow: {str(e)}")
#         conversation_state.remaining_steps = []
#         conversation_state.workflow_context = None
#         return response_prefix + f"\n\n❌ Error continuing workflow: {str(e)}", conversation_state
# --- END REACT FLOW DISABLED ---


def _summarize_params(inputs: dict, max_len: int = 100) -> str:
    """Extract the most important 2-3 params from step inputs, truncated."""
    priority_keys = ["to", "query", "title", "subject", "document_id", "file_path", "event_id", "message_id"]
    parts = []
    for key in priority_keys:
        if key in inputs and inputs[key]:
            val = str(inputs[key])[:40]
            parts.append(f"{key}: {val}")
            if len(", ".join(parts)) > max_len:
                break
    if not parts:
        for key, val in list(inputs.items())[:2]:
            parts.append(f"{key}: {str(val)[:40]}")
    result = ", ".join(parts)
    return result[:max_len]


def _summarize_result(output: dict, max_len: int = 100) -> str:
    """Extract key result fields (IDs, URLs, counts), truncated."""
    if not output or not isinstance(output, dict):
        return "no output"
    priority_keys = ["draft_id", "document_id", "document_url", "message_id", "event_id",
                     "url", "file_id", "thread_id", "count", "row_count", "title", "subject"]
    parts = []
    for key in priority_keys:
        if key in output and output[key]:
            val = str(output[key])[:40]
            parts.append(f"{key}: {val}")
            if len(", ".join(parts)) > max_len:
                break
    if not parts:
        for key, val in list(output.items())[:2]:
            if key not in ("success", "error"):
                parts.append(f"{key}: {str(val)[:40]}")
    result = ", ".join(parts)
    return result[:max_len] if result else "ok"


async def _run_workflow_and_update_state(conversation_state, thread_id: str = None):
    """
    Shared helper: execute workflow, update execution history, generate summary.
    
    Handles two outcomes:
    1. Workflow completes fully → generate summary, update history, store in memory
    2. Workflow pauses for approval → save pending state, return approval message
    
    Returns (response_text, updated_conversation_state).
    """
    # Preserve the task-specific summary before workflow overwrites it
    original_execution_summary = conversation_state.execution_summary

    supervisor_input = conversational_agent.build_supervisor_input(conversation_state)
    now_iso = datetime.now(timezone.utc).isoformat()

    trace.workflow_start(supervisor_input)

    # Build context overrides — inject uploaded_file and cached tool filter
    context_overrides = {}
    uploaded_file = conversation_state.extracted_info.get("uploaded_file")
    if uploaded_file:
        context_overrides["uploaded_file"] = uploaded_file

    # Pass cached tool filter from Tier 1 so supervisor skips the redundant LLM call
    cached_tool_filter = conversation_state.extracted_info.get("_cached_tool_filter")
    if cached_tool_filter:
        context_overrides["_cached_tool_filter"] = cached_tool_filter

    # Inject enrichment context variables (e.g., extracted_file_text) for orchestrator Jinja2 resolution
    enrichment_ctx = conversation_state.extracted_info.get("_enrichment_context", {})
    if enrichment_ctx:
        context_overrides.update(enrichment_ctx)

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

    # === CHECK: Did workflow pause for approval? ===
    if status == "paused_for_approval" and final_context.get("paused_for_approval"):
        trace.step("workflow_paused", "Workflow paused — action requires chat approval")
        
        pending_action = final_context.get("pending_action", {})
        pending_action_id = final_context.get("pending_action_id", "")
        remaining_steps = final_context.get("remaining_steps", [])
        
        # Save pending state on ConversationState
        conversation_state.workflow_paused = True
        conversation_state.pending_actions = [{
            "action_id": pending_action_id,
            **pending_action,
        }]
        conversation_state.remaining_steps = remaining_steps
        # Save variable_context for resumption (strip large blobs)
        workflow_ctx = {k: v for k, v in final_context.items() 
                       if k not in ("paused_for_approval", "pending_action", "pending_action_id", "remaining_steps", "results")}
        workflow_ctx["_execution_mode"] = execution_mode
        # ReAct state preservation disabled — uncomment to re-enable
        # if execution_mode == "react":
        #     workflow_ctx["_react_history"] = final_context.get("react_history", [])
        #     workflow_ctx["_react_iteration"] = final_context.get("react_iteration", 0)
        #     workflow_ctx["_supervisor_input"] = supervisor_input
        conversation_state.workflow_context = workflow_ctx
        conversation_state.ready_for_execution = False
        
        # Build rich approval message
        approval_message = _build_rich_approval_message(conversation_state.pending_actions[0])
        
        # Add completed steps summary if any
        results = final_context.get("results", [])
        completed = [r for r in results if r.get("status") == "success"]
        if completed:
            steps_summary = "\n".join(f"  ✅ Step {r['step']}: {r.get('description', r.get('tool', ''))}" for r in completed)
            approval_message = f"**Completed so far:**\n{steps_summary}\n\n{approval_message}"
        
        return approval_message, conversation_state

    # === Normal completion path ===

    # Append lean history entry (for future DB observability)
    conversation_state.execution_history.append({
        "executed_at": now_iso,
        "status": status,
        "message": message_text,
    })
    if len(conversation_state.execution_history) > 50:
        conversation_state.execution_history = conversation_state.execution_history[-50:]

    conversation_state.has_executed = True
    conversation_state.last_executed_at = now_iso
    conversation_state.last_execution_status = status
    conversation_state.last_execution_message = message_text
    conversation_state.ready_for_execution = False
    conversation_state.intent = None
    conversation_state.execution_summary = None
    conversation_state.extracted_info = {}
    conversation_state.missing_fields = []
    conversation_state.clarification_question = None

    # Populate completed_tasks from orchestrator step results
    for step_result in final_context.get("results", []):
        step_status = step_result.get("status", "unknown")
        if step_status not in ("success", "no_results"):
            continue
        task_entry = {
            "task_type": step_result.get("agent", "unknown") + "." + step_result.get("tool", "unknown"),
            "params_summary": _summarize_params(step_result.get("inputs", {})),
            "status": step_status,
            "result_summary": _summarize_result(step_result.get("output", {})),
            "timestamp": now_iso,
        }
        conversation_state.completed_tasks.append(task_entry)
    # Cap completed_tasks at 10 entries (FIFO)
    if len(conversation_state.completed_tasks) > 10:
        conversation_state.completed_tasks = conversation_state.completed_tasks[-10:]

    # Generate user-friendly summary
    friendly_summary = conversational_agent.summarization_service.summarize_execution(
        conversation_state=conversation_state,
        final_context=final_context,
        execution_status=status,
        execution_message=message_text,
    )

    # Fix memory gap: store the execution result in conversation memory
    # so it appears in working_context for subsequent turns
    if thread_id:
        memory_mgr = conversational_agent._get_memory_manager(thread_id, conversation_state.memory_state)
        memory_mgr.add_message("assistant", friendly_summary)
        conversational_agent._save_memory_to_state(conversation_state, thread_id)
        conversational_agent.thread_manager.add_message(thread_id, "assistant", friendly_summary)

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
        # trace.set_context(request_id=request_id, thread_id=thread_id)

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
                    conversation_state, thread_id=thread_id
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
                    updated_state, thread_id=thread_id
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

        # Process the message using the already-loaded state (avoids a redundant DB load)
        response_text, conversation_state = conversational_agent.process_message(
            user_message=message,
            conversation_state=conversation_state,
            state_id=thread_id,
            auto_save=True
        )

        trace.bot_response(response_text, conversation_state.ready_for_execution)

        # === HANDLE PENDING ACTION APPROVAL/REJECTION (chat-based) ===
        # Check by looking at the conversation analysis result in extracted_info
        pending_decision = conversation_state.extracted_info.get("decision")
        pending_action_id = conversation_state.extracted_info.get("action_id")
        
        if pending_decision == "approve" and pending_action_id and conversation_state.workflow_paused:
            # User approved the pending action — execute it
            print(f"✅ Chat-based approval for action {pending_action_id}")
            trace.step("chat_approval", f"Executing approved action: {pending_action_id}")
            
            pending = conversation_state.pending_actions[0] if conversation_state.pending_actions else {}
            
            try:
                # Mark as executing
                conversation_state.executing = True
                conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)
                
                # Execute the approved action
                step_info = {
                    "agent": pending.get("agent"),
                    "tool": pending.get("tool"),
                    "inputs": pending.get("inputs", {}),
                }
                result = await asyncio.to_thread(execute_single_action, step_info)
                
                print(f"✅ Action executed: {result.get('success', False)}")
                
                # Clear pending state
                conversation_state.pending_actions = []
                conversation_state.workflow_paused = False
                
                # Remove from cache/DB so it doesn't linger after successful execution
                from supervisor_agent import remove_pending_action
                try:
                    remove_pending_action(pending_action_id)
                except Exception:
                    pass
                
                # Clean up extracted_info decision fields
                conversation_state.extracted_info.pop("action_id", None)
                conversation_state.extracted_info.pop("decision", None)
                
                if result.get("success"):
                    description = pending.get("description", "Action")
                    tool_name = pending.get("tool", "unknown")
                    inputs = pending.get("inputs", {})
                    response_text = f"✅ **Done — {description}**\n\n"

                    # Build a concise summary from actual inputs/results
                    detail_parts = []
                    action_result = result.get("result", {}) if isinstance(result.get("result"), dict) else {}
                    if tool_name in ("send_draft_email", "send_email_with_attachment"):
                        if inputs.get("to"):
                            detail_parts.append(f"📧 Sent to **{inputs['to']}**")
                        if inputs.get("subject"):
                            detail_parts.append(f"Subject: **{inputs['subject']}**")
                    elif tool_name == "reply_to_email":
                        detail_parts.append("↩️ Reply sent")
                    elif tool_name == "create_draft_email":
                        if inputs.get("to"):
                            detail_parts.append(f"📝 Draft created for **{inputs['to']}**")
                    elif tool_name in ("create_doc", "add_text"):
                        title = inputs.get("title") or action_result.get("title", "")
                        if title:
                            detail_parts.append(f"📄 Document: **{title}**")
                    elif tool_name == "create_event":
                        summary = inputs.get("summary") or inputs.get("title", "")
                        if summary:
                            detail_parts.append(f"📅 Event: **{summary}**")
                    elif tool_name == "share_file":
                        if inputs.get("email"):
                            detail_parts.append(f"🔗 Shared with **{inputs['email']}**")
                    elif tool_name in ("delete_email", "delete_file", "delete_event"):
                        detail_parts.append("🗑️ Deleted successfully")
                    elif tool_name == "upload_file":
                        fname = inputs.get("filename") or inputs.get("file_name", "")
                        if fname:
                            detail_parts.append(f"📤 Uploaded **{fname}**")

                    if detail_parts:
                        response_text += "\n".join(f"- {p}" for p in detail_parts) + "\n"
                    
                    # Check remaining steps
                    # NOTE: ReAct continuation disabled — uncomment to re-enable
                    # saved_ctx = conversation_state.workflow_context or {}
                    # is_react = saved_ctx.get("_execution_mode") == "react"
                    # if is_react:
                    #     response_text += f"\n⏳ Continuing ReAct workflow...\n"
                    #     response_text, conversation_state = await _resume_react_workflow(
                    #         conversation_state, result, response_text, thread_id
                    #     )
                    # elif remaining:
                    remaining = conversation_state.remaining_steps
                    
                    if remaining:
                        response_text += f"\n⏳ Continuing with {len(remaining)} remaining step(s)...\n"
                        response_text, conversation_state = await _resume_remaining_steps(
                            conversation_state, result, response_text, thread_id,
                            approved_step_info=pending,
                        )
                    else:
                        response_text += "\nIs there anything else you'd like to do?"
                    
                    if not conversation_state.workflow_paused:
                        now_iso = datetime.now(timezone.utc).isoformat()
                        conversation_state.execution_history.append({
                            "executed_at": now_iso,
                            "status": "success",
                            "message": f"Approved and executed: {description}",
                        })
                        conversation_state.has_executed = True
                        conversation_state.last_executed_at = now_iso
                        conversation_state.last_execution_status = "success"
                        conversation_state.last_execution_message = f"Approved and executed: {description}"
                        conversation_state.workflow_context = None
                        conversation_state.intent = None
                        conversation_state.ready_for_execution = False
                        conversation_state.execution_summary = None
                        conversation_state.extracted_info = {}
                        conversation_state.missing_fields = []
                        conversation_state.clarification_question = None
                else:
                    error_msg = result.get("error", "Unknown error")
                    response_text = f"❌ **Action Failed**\n\n{error_msg}\n\nWould you like to try again?"
                    conversation_state.remaining_steps = []
                    conversation_state.workflow_context = None
                    conversation_state.intent = None
                    conversation_state.ready_for_execution = False
                    conversation_state.execution_summary = None
                    conversation_state.extracted_info = {}
                    conversation_state.missing_fields = []
                    conversation_state.clarification_question = None
                
            except Exception as e:
                print(f"❌ Error executing approved action: {str(e)}")
                response_text = f"❌ **Execution Error**\n\n{str(e)}\n\nWould you like to try again?"
                conversation_state.pending_actions = []
                conversation_state.workflow_paused = False
                conversation_state.remaining_steps = []
                conversation_state.workflow_context = None
                conversation_state.intent = None
                conversation_state.ready_for_execution = False
                conversation_state.execution_summary = None
                conversation_state.extracted_info = {}
                conversation_state.missing_fields = []
                conversation_state.clarification_question = None
            finally:
                conversation_state.executing = False
                conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)
        
        elif pending_decision == "reject" and pending_action_id and conversation_state.workflow_paused:
            # User rejected — response_text already set by Tier 0 check
            print(f"🚫 Chat-based rejection for action {pending_action_id}")
            
            # Clear all pending state
            conversation_state.pending_actions = []
            conversation_state.workflow_paused = False
            conversation_state.remaining_steps = []
            conversation_state.workflow_context = None
            conversation_state.intent = None
            conversation_state.ready_for_execution = False
            conversation_state.execution_summary = None
            conversation_state.extracted_info = {}
            conversation_state.missing_fields = []
            conversation_state.clarification_question = None
            
            # Remove from pending actions cache
            from supervisor_agent import remove_pending_action
            try:
                remove_pending_action(pending_action_id)
            except Exception:
                pass
            
            conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)

        # If ready for execution, execute immediately
        elif conversation_state.ready_for_execution:
            print(f"🚀 Thread {thread_id} ready - executing workflow...")
            trace.decision("ready_for_execution", "YES — executing workflow")

            # Mark as executing to prevent conflicts
            conversation_state.executing = True
            conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)

            try:
                response_text, conversation_state = await _run_workflow_and_update_state(
                    conversation_state, thread_id=thread_id
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

    # === QUOTA CHECK: Verify user has quota before processing ===
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
                    updated_state, thread_id=thread_id
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
async def delete_thread(thread_id: str):
    """
    Soft-delete (archive) a thread.

    Args:
        thread_id: Thread identifier

    Returns:
        Success message
    """
    try:
        success = conversational_agent.thread_service.delete_thread(
            thread_id=thread_id,
            hard_delete=False
        )

        if not success:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

        return {
            "thread_id": thread_id,
            "message": "Thread archived successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error deleting thread: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
