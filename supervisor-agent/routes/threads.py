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
    broadcast_progress,
)
from models.models import CreateThreadRequest
from routes.workflow import run_workflow
from routes.actions import execute_single_action
from checks.tier0_checks import _build_rich_approval_message, _build_disambiguation_message
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
        return response_prefix + "\nIs there anything else I can help with?", conversation_state
    
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
                steps_summary = "\n".join(f"  Step {r['step']}: {r.get('description', r.get('tool', ''))}" for r in completed)
                response_prefix += f"\n{steps_summary}\n"
            
            return response_prefix + "\n\n" + approval_msg, conversation_state

        # Check if the resumed execution paused for disambiguation
        if final_context.get("paused_for_disambiguation"):
            options = final_context.get("disambiguation_options", [])
            variable = final_context.get("disambiguation_variable", "")
            new_remaining = final_context.get("remaining_steps", [])
            source_tool = final_context.get("disambiguation_source_tool", "")

            conversation_state.disambiguation_options = options
            conversation_state.disambiguation_variable = variable
            conversation_state.remaining_steps = new_remaining
            ctx = {k: v for k, v in final_context.items()
                   if k not in ("paused_for_disambiguation", "disambiguation_options",
                                "disambiguation_variable", "disambiguation_source_tool",
                                "remaining_steps", "results")}
            # Bug 5 resume metadata is preserved in ctx (it lives alongside
            # workflow_context) so the resume handler in
            # _handle_pending_action_decision can re-run extract_nested_value
            # against the patched agent_result on the user's selection.
            conversation_state.workflow_context = ctx

            disambig_msg = _build_disambiguation_message(options, source_tool)

            completed = [r for r in results if r.get("status") == "success"]
            if completed:
                steps_summary = "\n".join(f"  Step {r['step']}: {r.get('description', r.get('tool', ''))}" for r in completed)
                response_prefix += f"\n{steps_summary}\n"

            return response_prefix + "\n\n" + disambig_msg, conversation_state

        # All remaining steps completed
        conversation_state.remaining_steps = []
        conversation_state.workflow_context = None

        # Build rich summary from results with actual data.
        # Per-step rendering goes through the response_templates registry
        # so each step gets its full detail block (per-PDF samples,
        # duplicates, sent-email recipient/subject, doc URL, etc.) rather
        # than just the planner's bare description string. Falls back to
        # "{description} — done" for tools without a registered template.
        completed = [r for r in results if r.get("status") == "success"]
        errors = [r for r in results if r.get("status") == "error"]

        try:
            from services.response_templates import format_step
        except Exception as _imp_exc:
            format_step = None  # type: ignore
            print(f"response_templates import failed in resume: {_imp_exc}")

        if completed:
            response_prefix += "\n"
            for r in completed:
                desc = r.get("description", r.get("tool", ""))
                agent_name = r.get("agent", "")
                tool_name = r.get("tool", "")
                output = r.get("output", {}) if isinstance(r.get("output"), dict) else {}
                rich_text = ""
                if format_step is not None:
                    try:
                        rendered = format_step(agent_name, tool_name, output)
                        if rendered and rendered.strip():
                            rich_text = rendered.strip()
                    except Exception as _fmt_exc:
                        print(f"format_step failed for {agent_name}.{tool_name}: {_fmt_exc}")
                if rich_text:
                    response_prefix += f"\n**{desc}**\n{rich_text}\n"
                else:
                    response_prefix += f"\n  {desc} — done"

        if errors:
            try:
                from services.summarization_service import SummarizationService
                _summarizer = SummarizationService
            except Exception:
                _summarizer = None  # type: ignore
            for r in errors:
                desc = r.get("description", r.get("tool", ""))
                # Sub-agents craft user-facing error strings with concrete
                # next steps (e.g. "ask the sheet owner to change your
                # permission from Viewer to Editor"). Surface those
                # verbatim. For raw `<HttpError NNN ...>` text the
                # humanizer translates the HTTP status into a clean
                # sentence — keeps error fidelity while losing the URL
                # and reason-phrase noise.
                err = r.get("error", "Unknown error")
                if _summarizer is not None:
                    try:
                        if not _summarizer._is_verbatim_error_useful(err):
                            humanized = _summarizer._humanize_api_error(err)
                            if humanized != err:
                                err = humanized
                    except Exception:
                        pass
                response_prefix += f"\n\n**{desc} — failed**\n{err}"

        response_prefix += "\n\nAll steps completed! Is there anything else I can help with?"

        return response_prefix, conversation_state

    except Exception as e:
        # Catch-all for orchestrator-level failures during resume — keep the
        # workflow_context cleared so the user can start fresh. Don't dump
        # the raw Python exception (KeyError, UndefinedError, etc.) into
        # chat; route it through the humanizer-then-categorize-then-suggest
        # pipeline that the approval-failure branch uses, so the user
        # sees a sentence they can act on instead of a stack trace.
        err_str = str(e)
        print(f"Error resuming remaining steps: {err_str}")
        conversation_state.remaining_steps = []
        conversation_state.workflow_context = None

        response_prefix += "\n\n**Could not continue the workflow.**"
        try:
            from services.summarization_service import SummarizationService
            if SummarizationService._is_verbatim_error_useful(err_str):
                response_prefix += f"\n\n**Issue:** {err_str}"
            else:
                humanized = SummarizationService._humanize_api_error(err_str)
                if humanized != err_str:
                    response_prefix += f"\n\n**Issue:** {humanized}"
        except Exception:
            pass

        return response_prefix, conversation_state


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
# print(f" Error resuming ReAct workflow: {str(e)}")
#         conversation_state.remaining_steps = []
#         conversation_state.workflow_context = None
# return response_prefix + f"\n\n Error continuing workflow: {str(e)}", conversation_state
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
            steps_summary = "\n".join(f"  Step {r['step']}: {r.get('description', r.get('tool', ''))}" for r in completed)
            approval_message = f"**Completed so far:**\n{steps_summary}\n\n{approval_message}"
        
        return approval_message, conversation_state

    # === CHECK: Did workflow pause for disambiguation? ===
    if status == "paused_for_disambiguation" and final_context.get("paused_for_disambiguation"):
        trace.step("workflow_paused", "Workflow paused — disambiguation needed")

        options = final_context.get("disambiguation_options", [])
        variable = final_context.get("disambiguation_variable", "")
        remaining_steps = final_context.get("remaining_steps", [])
        source_tool = final_context.get("disambiguation_source_tool", "")

        conversation_state.disambiguation_options = options
        conversation_state.disambiguation_variable = variable
        conversation_state.remaining_steps = remaining_steps
        workflow_ctx = {k: v for k, v in final_context.items()
                       if k not in ("paused_for_disambiguation", "disambiguation_options",
                                    "disambiguation_variable", "disambiguation_source_tool",
                                    "remaining_steps", "results")}
        # Bug 5 resume metadata (disambiguation_output_variables,
        # disambiguation_results_field, disambiguation_agent_result) is
        # preserved here by design — the resume handler consumes and scrubs
        # these keys after the user's selection is applied.
        workflow_ctx["_execution_mode"] = execution_mode
        conversation_state.workflow_context = workflow_ctx
        conversation_state.ready_for_execution = False

        disambig_message = _build_disambiguation_message(options, source_tool)

        results = final_context.get("results", [])
        completed = [r for r in results if r.get("status") == "success"]
        if completed:
            steps_summary = "\n".join(f"  Step {r['step']}: {r.get('description', r.get('tool', ''))}" for r in completed)
            disambig_message = f"**Completed so far:**\n{steps_summary}\n\n{disambig_message}"

        return disambig_message, conversation_state

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

    # Clean up temp file if execution was deferred from a prior upload request
    deferred_file = conversation_state.extracted_info.get("uploaded_file")
    if deferred_file and isinstance(deferred_file, dict):
        delete_temp_file(deferred_file)

    _clear_workflow_state(conversation_state)

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

    # === PROGRESS: Composing response ===
    await broadcast_progress(thread_id, 0, 0, "Preparing your response...", status="composing")

    # Generate user-friendly summary
    friendly_summary = conversational_agent.summarization_service.summarize_execution(
        conversation_state=conversation_state,
        final_context=final_context,
        execution_status=status,
        execution_message=message_text,
    )

    # NOTE on persistence:
    # We deliberately do NOT call thread_manager.add_message here. The single
    # chokepoint `_persist_final_response` (called once at the end of the API
    # handler) rewrites the stub assistant row from process_message with the
    # final post-handler response_text — which is exactly this friendly_summary
    # in the standard execution path. Adding it here would create a duplicate
    # DB row and a duplicate memory entry that would survive thread-switches.

    return friendly_summary, conversation_state

# ============================================================
# SHARED HELPERS
# ============================================================

def _persist_final_response(thread_id: str, conversation_state, final_response_text: str) -> None:
    """
    Chokepoint that persists the FINAL post-handler response_text to DB and memory.

    Background — the disappearing-long-response bug:
        `process_message` saves a stub assistant message (e.g. "Ready to execute…"
        or a clarification question) to BOTH the messages table and the memory
        manager BEFORE downstream handlers run. The handlers
        (_handle_pending_action_decision, _handle_disambiguation_selection,
        _execute_workflow_guarded → _run_workflow_and_update_state, plus
        _resume_remaining_steps) ENRICH the response_text with rich Markdown
        (multi-line samples, per-PDF blocks, duplicate counts, etc.). That rich
        text is returned over the API and rendered live by the frontend, but
        nothing was rewriting the persisted row. On thread-switch / re-login
        the FE re-reads from the DB and only finds the original stub — the
        long response visibly "disappears".

    This helper is the single place that closes that gap. It rewrites the
    last assistant row in `messages` and the matching entry in working_context
    + raw_history, then re-saves the memory state to conversation_state.

    Idempotent: if the response is unchanged from the stub (e.g. the path was
    a pure clarification question and no handler enriched it), the rewrite is
    still cheap (just an UPDATE with the same content) and harmless.

    Args:
        thread_id: Thread identifier
        conversation_state: Current conversation state (its memory_state will be refreshed)
        final_response_text: The final, fully-rendered response text returned to the FE
    """
    if not thread_id or not final_response_text:
        return

    try:
        replaced = conversational_agent.thread_manager.replace_last_assistant_message(
            thread_id, final_response_text
        )
        if not replaced:
            conversational_agent.thread_manager.add_message(
                thread_id, "assistant", final_response_text
            )

        memory_mgr = conversational_agent._get_memory_manager(
            thread_id, conversation_state.memory_state
        )
        mem_replaced = memory_mgr.replace_last_assistant_message(final_response_text)
        if not mem_replaced:
            memory_mgr.add_message("assistant", final_response_text)

        conversational_agent._save_memory_to_state(conversation_state, thread_id)
        conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)
    except Exception as exc:
        print(f"[persist_final_response] non-fatal: {exc}")
        traceback.print_exc()


def _check_quota_or_raise(user_id: str, estimated_tokens: int = 2000):
    """Raise 403 (deactivated) or 429 (exceeded) if user fails quota check."""
    quota_result = check_user_quota(user_id, estimated_tokens=estimated_tokens)
    if not quota_result.allowed:
        error_message = quota_result.error or "Quota check failed"
        if quota_result.user_deactivated:
            raise HTTPException(status_code=403, detail={
                "error": "account_deactivated",
                "message": error_message,
                "user_message": "Your account has been deactivated. Please contact an administrator."
            })
        else:
            raise HTTPException(status_code=429, detail={
                "error": "quota_exceeded",
                "message": error_message,
                "user_message": error_message
            })


def _clear_workflow_state(state):
    """Reset all workflow-related fields after execution completes, fails, or is rejected."""
    state.remaining_steps = []
    state.workflow_context = None
    state.intent = None
    state.ready_for_execution = False
    state.execution_summary = None
    state.extracted_info = {}
    state.missing_fields = []
    state.clarification_question = None
    state.disambiguation_options = []
    state.disambiguation_variable = None


def _has_actionable_task(state) -> bool:
    """Return True if conversation state contains a real task to execute."""
    return bool(
        state.execution_summary
        or any(k for k in state.extracted_info if not k.startswith("_"))
    )


async def _execute_workflow_guarded(conversation_state, thread_id: str, cleanup_file: dict = None):
    """Mark state as executing, run the workflow, and guarantee cleanup in finally.

    Args:
        cleanup_file: Optional uploaded-file dict to delete after workflow finishes.

    Returns:
        (response_text, updated_conversation_state)
    """
    conversation_state.executing = True
    conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)
    try:
        response_text, conversation_state = await _run_workflow_and_update_state(
            conversation_state, thread_id=thread_id
        )
        return response_text, conversation_state
    finally:
        conversation_state.executing = False
        conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)
        if cleanup_file:
            delete_temp_file(cleanup_file)
            print(f"Cleaned up uploaded file")


async def _handle_pending_action_decision(conversation_state, thread_id: str, response_text: str):
    """Shared handler for chat-based approve/reject of pending actions.

    Returns:
        (response_text, conversation_state, handled) where handled=True if
        a pending-action decision was processed.
    """
    pending_decision = conversation_state.extracted_info.get("decision")
    pending_action_id = conversation_state.extracted_info.get("action_id")

    if pending_decision == "approve" and pending_action_id and conversation_state.workflow_paused:
        print(f"Chat-based approval for action {pending_action_id}")
        trace.step("chat_approval", f"Executing approved action: {pending_action_id}")

        pending = conversation_state.pending_actions[0] if conversation_state.pending_actions else {}

        try:
            conversation_state.executing = True
            conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)

            step_info = {
                "agent": pending.get("agent"),
                "tool": pending.get("tool"),
                "inputs": pending.get("inputs", {}),
            }
            result = await asyncio.to_thread(execute_single_action, step_info)

            print(f"Action executed: {result.get('success', False)}")

            conversation_state.pending_actions = []
            conversation_state.workflow_paused = False

            from supervisor_agent import remove_pending_action
            try:
                remove_pending_action(pending_action_id)
            except Exception:
                pass

            conversation_state.extracted_info.pop("action_id", None)
            conversation_state.extracted_info.pop("decision", None)

            # Common metadata used by both the success and failure
            # branches below. `clean_description` strips the planner's
            # editorial "(DANGEROUS — requires approval)" suffix because
            # the line is no longer accurate at this point — the user
            # has decided, so showing the approval-required tag in the
            # status header is just noise.
            description = pending.get("description", "Action")
            tool_name = pending.get("tool", "unknown")
            agent_name = pending.get("agent", "")
            inputs = pending.get("inputs", {})

            clean_description = description
            for _suffix in (
                " (DANGEROUS — requires approval)",
                " (CRITICAL — requires approval)",
                " (DANGEROUS - requires approval)",
                " (CRITICAL - requires approval)",
            ):
                if clean_description.endswith(_suffix):
                    clean_description = clean_description[: -len(_suffix)]
                    break

            if result.get("success"):
                response_text = f"**Done — {clean_description}**\n\n"

                # Prefer the rich response_templates registry for the
                # success body. This pulls in per-PDF blocks, duplicate
                # breakdowns, tab summaries, etc. for delivery-order
                # writes; created-doc URL + title; created-event summary
                # with start/end/attendees; sent-email subject/recipient;
                # and so on — all the detail the user needs to verify what
                # actually happened, instead of just echoing the
                # planner's step description.
                #
                # Sub-agent responses come in two shapes (see
                # supervisor_agent.py:1447 for the same dual-handling):
                #   1. Direct  — {"success": true, "rows_written": N, ...}
                #   2. Wrapped — {"success": true, "result": {"rows_written": N, ...}}
                # `format_step` only knows about the inner output dict, so
                # we unwrap the wrapped form here and fall back to the top
                # level for the direct form.
                _nested = result.get("result")
                if isinstance(_nested, dict) and _nested:
                    action_result = _nested
                else:
                    action_result = result if isinstance(result, dict) else {}
                rich_text = ""
                try:
                    from services.response_templates import format_step
                    rendered = format_step(agent_name, tool_name, action_result)
                    if rendered and rendered.strip():
                        rich_text = rendered.strip()
                except Exception as _fmt_exc:
                    # Never let a template bug silence the success
                    # message — fall through to the legacy detail switch.
                    print(f"format_step failed for {agent_name}.{tool_name}: {_fmt_exc}")

                if rich_text:
                    response_text += rich_text + "\n"
                else:
                    # Legacy per-tool detail fallback for tools without a
                    # registered response template, or when rendering
                    # raised. Kept identical to the pre-template behaviour
                    # so anything the registry doesn't cover still emits
                    # the same minimal bullet list it always did.
                    detail_parts = []
                    if tool_name in ("send_draft_email", "send_email_with_attachment"):
                        if inputs.get("to"):
                            detail_parts.append(f"Sent to **{inputs['to']}**")
                        if inputs.get("subject"):
                            detail_parts.append(f"Subject: **{inputs['subject']}**")
                    elif tool_name == "reply_to_email":
                        detail_parts.append("Reply sent")
                    elif tool_name == "create_draft_email":
                        if inputs.get("to"):
                            detail_parts.append(f"Draft created for **{inputs['to']}**")
                    elif tool_name in ("create_doc", "add_text"):
                        title = inputs.get("title") or action_result.get("title", "")
                        if title:
                            detail_parts.append(f"Document: **{title}**")
                    elif tool_name == "create_event":
                        summary = inputs.get("summary") or inputs.get("title", "")
                        if summary:
                            detail_parts.append(f"Event: **{summary}**")
                    elif tool_name in ("delete_email", "delete_file", "delete_event"):
                        detail_parts.append("Deleted successfully")
                    elif tool_name == "upload_file":
                        fname = inputs.get("filename") or inputs.get("file_name", "")
                        if fname:
                            detail_parts.append(f"Uploaded **{fname}**")

                    if detail_parts:
                        response_text += "\n".join(f"- {p}" for p in detail_parts) + "\n"

                remaining = conversation_state.remaining_steps

                if remaining:
                    response_text += f"\nContinuing with {len(remaining)} remaining step(s)...\n"
                    response_text, conversation_state = await _resume_remaining_steps(
                        conversation_state, result, response_text, thread_id,
                        approved_step_info=pending,
                    )
                else:
                    response_text += "\nIs there anything else I can help with?"

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
                    _clear_workflow_state(conversation_state)
            else:
                # Sub-agents (sheets, drive, gmail) return user-facing
                # error messages with concrete remediation hints — e.g.
                # "Access to this spreadsheet was denied. You may only
                #  have view/read-only access. To write data you need
                #  Editor access — ask the sheet owner to change your
                #  permission from Viewer to Editor."
                # Surface that verbatim. Add a categorized Suggestion
                # line on top so the user gets both the specific guidance
                # AND a generic next step.
                error_msg = result.get("error", "Unknown error")
                suggestion = ""
                try:
                    from services.summarization_service import SummarizationService
                    # Categorize against the RAW message so the suggestion
                    # template selection still keys on HTTP status codes
                    # (403, 404, …) embedded in the original HttpError repr.
                    category = SummarizationService(conversational_agent.llm)._categorize_error(error_msg)
                    suggestion_map = {
                        "auth": "Your access may have expired. Try reconnecting your account.",
                        "not_found": "Verify the resource ID or name and try again.",
                        "timeout": "The service may be busy. Please try again in a moment.",
                        "connection": "Check that all services are running and try again.",
                        "permission": "If you cannot adjust the access yourself, contact the resource owner or your administrator.",
                        "rate_limit": "Wait a moment before retrying.",
                    }
                    suggestion = suggestion_map.get(category, "")

                    # Humanize raw `<HttpError NNN ...>` text into a clean
                    # sentence — but ONLY when the sub-agent did not already
                    # provide prose-quality guidance (sheets_agent's curated
                    # permission errors pass through untouched).
                    if not SummarizationService._is_verbatim_error_useful(error_msg):
                        humanized = SummarizationService._humanize_api_error(error_msg)
                        if humanized != error_msg:
                            error_msg = humanized
                except Exception as _cat_exc:
                    print(f"error categorization failed in approval handler: {_cat_exc}")

                response_text = f"**Action Failed — {clean_description}**\n\n**Issue:** {error_msg}\n"
                if suggestion:
                    response_text += f"\n**Suggestion:** {suggestion}\n"
                response_text += "\nWould you like to try again, or is there something else I can help with?"
                _clear_workflow_state(conversation_state)

        except Exception as e:
            err_str = str(e)
            print(f"Error executing approved action: {err_str}")
            response_text = f"**Execution Error**\n\n"
            try:
                from services.summarization_service import SummarizationService
                if SummarizationService._is_verbatim_error_useful(err_str):
                    response_text += f"**Issue:** {err_str}\n"
                else:
                    humanized = SummarizationService._humanize_api_error(err_str)
                    if humanized != err_str:
                        response_text += f"**Issue:** {humanized}\n"
            except Exception:
                response_text += "Something went wrong while running this action.\n"
            response_text += "\nWould you like to try again, or is there something else I can help with?"
            conversation_state.pending_actions = []
            conversation_state.workflow_paused = False
            _clear_workflow_state(conversation_state)
        finally:
            conversation_state.executing = False
            conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)

        return response_text, conversation_state, True

    elif pending_decision == "reject" and pending_action_id and conversation_state.workflow_paused:
        print(f"Chat-based rejection for action {pending_action_id}")

        conversation_state.pending_actions = []
        conversation_state.workflow_paused = False
        _clear_workflow_state(conversation_state)

        from supervisor_agent import remove_pending_action
        try:
            remove_pending_action(pending_action_id)
        except Exception:
            pass

        conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)
        return response_text, conversation_state, True

    return response_text, conversation_state, False


async def _handle_disambiguation_selection(conversation_state, thread_id: str, response_text: str):
    """Handle user's disambiguation selection — inject chosen item into context and resume.

    Returns:
        (response_text, conversation_state, handled)
    """
    decision = conversation_state.extracted_info.get("decision")

    if decision == "cancel" and conversation_state.disambiguation_options:
        trace.step("disambiguation_cancel", "User cancelled disambiguation")
        _clear_workflow_state(conversation_state)
        conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)
        return response_text, conversation_state, True

    if decision == "select" and conversation_state.disambiguation_options:
        selected_item = conversation_state.extracted_info.get("selected_item", {})
        variable_name = conversation_state.disambiguation_variable
        remaining = conversation_state.remaining_steps

        trace.step("disambiguation_select", f"User selected: {selected_item.get('name', selected_item.get('id', ''))}")

        # Rebuild context with the selected item injected.
        variable_context = conversation_state.workflow_context or {}

        # Bug 5 resume: when the orchestrator paused because the planner's
        # output_variables used an indexed pattern like `results[0].id`, we
        # can't just stuff the raw selected_item into `sheet_id` — the
        # variable is supposed to be a scalar ID, not a dict or list. We
        # replay the original extraction path against a patched
        # agent_result whose results array now contains only the user's
        # pick. That same replay also handles the legacy whole-array
        # pattern cleanly (source_field == "results" resolves the entire
        # list back to `[selected_item]` with zero behavior change).
        output_vars_map = (
            conversation_state.workflow_context or {}
        ).get("disambiguation_output_variables") or {}
        results_field_name = (
            conversation_state.workflow_context or {}
        ).get("disambiguation_results_field")
        agent_result_snapshot = (
            conversation_state.workflow_context or {}
        ).get("disambiguation_agent_result") or {}

        if output_vars_map and results_field_name:
            try:
                from supervisor_agent import extract_nested_value
            except ImportError:
                extract_nested_value = None  # type: ignore

            patched = dict(agent_result_snapshot)
            patched[results_field_name] = [selected_item]

            for out_var, source_field in output_vars_map.items():
                value = None
                if extract_nested_value is not None and isinstance(source_field, str):
                    try:
                        value = extract_nested_value(patched, source_field)
                    except Exception:
                        value = None
                if value is None and isinstance(source_field, str):
                    value = patched.get(source_field)
                if value is None:
                    value = [selected_item]
                variable_context[out_var] = value
        elif variable_name:
            variable_context[variable_name] = [selected_item]

        selected_name = selected_item.get("name") or selected_item.get("title") or "selected item"
        response_text = f"Selected **{selected_name}** — continuing workflow...\n"

        # Clear disambiguation state before resuming
        conversation_state.disambiguation_options = []
        conversation_state.disambiguation_variable = None
        conversation_state.extracted_info.pop("decision", None)
        conversation_state.extracted_info.pop("selected_item", None)
        conversation_state.extracted_info.pop("selected_index", None)
        # Scrub the resume-metadata blobs so they don't leak into a later
        # workflow. These are tied to THIS pause/resume cycle only.
        if isinstance(conversation_state.workflow_context, dict):
            for k in (
                "disambiguation_output_variables",
                "disambiguation_results_field",
                "disambiguation_agent_result",
            ):
                conversation_state.workflow_context.pop(k, None)
            variable_context.pop("disambiguation_output_variables", None)
            variable_context.pop("disambiguation_results_field", None)
            variable_context.pop("disambiguation_agent_result", None)

        if not remaining:
            _clear_workflow_state(conversation_state)
            response_text += "\nNo remaining steps. Is there anything else I can help with?"
            conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)
            return response_text, conversation_state, True

        # Resume remaining steps
        conversation_state.workflow_context = variable_context
        try:
            conversation_state.executing = True
            conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)

            response_text, conversation_state = await _resume_remaining_steps(
                conversation_state, None, response_text, thread_id,
                approved_step_info=None,
            )

            if not conversation_state.workflow_paused and not conversation_state.disambiguation_options:
                _clear_workflow_state(conversation_state)
        except Exception as e:
            # Don't dump the raw Python exception text into the chat. Wrap it
            # the same way the approval-failure branch does: an Issue header
            # (verbatim only when the message looks user-friendly) plus a
            # categorized Suggestion. Anything more technical leaks the
            # internals (Jinja undefined names, KeyError tracebacks) to a
            # non-technical user with no actionable next step.
            err_str = str(e)
            print(f"Error resuming after disambiguation: {err_str}")

            response_text += "\n\n**Could not continue the workflow after your selection.**"

            try:
                from services.summarization_service import SummarizationService
                # Same humanization-vs-verbatim rule as the approval-failure
                # branch: if the agent already produced prose, keep it; if
                # the message is a raw HttpError repr, translate via
                # _humanize_api_error; otherwise omit the Issue line entirely
                # so we don't dump KeyError tracebacks into chat.
                category = SummarizationService(
                    conversational_agent.llm
                )._categorize_error(err_str)
                if SummarizationService._is_verbatim_error_useful(err_str):
                    response_text += f"\n\n**Issue:** {err_str}"
                else:
                    humanized = SummarizationService._humanize_api_error(err_str)
                    if humanized != err_str:
                        response_text += f"\n\n**Issue:** {humanized}"
                suggestion_map = {
                    "auth": "Your access may have expired. Try reconnecting your account.",
                    "not_found": "The selected item may have been moved or deleted. Try the search again.",
                    "timeout": "The service may be busy. Please try again in a moment.",
                    "connection": "Check that all services are running and try again.",
                    "permission": "If you cannot adjust the access yourself, contact the resource owner or your administrator.",
                    "rate_limit": "Wait a moment before retrying.",
                    "dependency": "Try running the search again so the workflow has fresh context.",
                }
                suggestion = suggestion_map.get(category, "")
                if suggestion:
                    response_text += f"\n\n**Suggestion:** {suggestion}"
            except Exception as _cat_exc:
                print(f"error categorization failed in disambiguation handler: {_cat_exc}")

            response_text += "\n\nWould you like to try again, or is there something else I can help with?"
            _clear_workflow_state(conversation_state)
        finally:
            conversation_state.executing = False
            conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)

        return response_text, conversation_state, True

    return response_text, conversation_state, False


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

    _check_quota_or_raise(user_id)

    # === REQUEST CONTEXT: Initialize logging context ===
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
        thread_id, conversation_state, _ = conversational_agent.thread_service.create_new_thread(
            user_id=user_id,
            initial_message=None
        )

        set_request_context(
            request_id=request_id,
            conversation_id=thread_id,
            thread_id=thread_id,
            user_id=user_id
        )

        save_conversation_state(thread_id, conversation_state)

        bot_response = None
        execution_completed = False

        if initial_message:
            auto_title = conversational_agent.thread_service.thread_manager.auto_generate_title(initial_message)
            conversational_agent.thread_service.thread_manager.update_thread(thread_id, title=auto_title)

            await broadcast_progress(thread_id, 0, 0, "Analyzing your message...", status="analyzing")
            bot_response, conversation_state = await asyncio.to_thread(
                conversational_agent.process_message,
                user_message=initial_message,
                conversation_state=conversation_state,
                state_id=thread_id,
                auto_save=True,
            )

            if conversation_state.ready_for_execution:
                if _has_actionable_task(conversation_state):
                    print(f"Thread {thread_id} ready - executing workflow...")
                    trace.decision("ready_for_execution", "YES — executing immediately")
                    bot_response, conversation_state = await _execute_workflow_guarded(
                        conversation_state, thread_id
                    )
                    execution_completed = True
                else:
                    trace.warning("ready_for_execution=True but no task context — resetting")
                    conversation_state.ready_for_execution = False
                    conversation_state.intent = None
                    bot_response = "Is there anything else I can help with?"
                    conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)

            # Chokepoint: persist the FINAL post-workflow response so a thread
            # switch / re-login keeps the long response intact. Without this,
            # an initial-message workflow run on a brand-new thread (e.g.
            # "create thread + parse delivery PDFs in one go") writes only the
            # short stub from process_message into messages.db; the rich
            # friendly_summary comes back over the wire but disappears on the
            # very next FE reload of this thread.
            _persist_final_response(thread_id, conversation_state, bot_response)

        thread_metadata = conversational_agent.thread_service.get_thread_metadata(thread_id)

        response = {
            "thread_id": thread_id,
            "user_id": user_id,
            "metadata": thread_metadata,
            "message": "Thread created successfully"
        }

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

        logger.request_summary()
        clear_request_context()

        return response

    except HTTPException:
        logger.request_summary()
        clear_request_context()
        raise
    except LLMServiceException:
        logger.request_summary()
        clear_request_context()
        raise
    except Exception as e:
        print(f"Error creating thread: {str(e)}")
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
    This prevents the "Uploading file..." secondary message issue.
    """

    _check_quota_or_raise(user_id)

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

        # Create thread WITHOUT running analysis -- we call process_message
        # ourselves below so the uploaded_file is visible to Tier 0.5/1.
        thread_id, conversation_state, bot_response = conversational_agent.thread_service.create_new_thread(
            user_id=user_id,
            initial_message=None
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

        # Auto-generate title from the user's message (create_new_thread
        # skips this when initial_message is None).
        auto_title = conversational_agent.thread_service.thread_manager.auto_generate_title(message)
        conversational_agent.thread_service.thread_manager.update_thread(thread_id, title=auto_title)

        # === PROGRESS: Analyzing ===
        await broadcast_progress(thread_id, 0, 0, "Analyzing your message...", status="analyzing")

        # Run in thread so the event loop stays free to deliver WebSocket progress
        response_text, updated_state = await asyncio.to_thread(
            conversational_agent.process_message,
            user_message=message,
            conversation_state=conversation_state,
            state_id=thread_id,
            auto_save=True,
            uploaded_file=uploaded_file,
        )

        print(f"Bot response: {response_text}")
        print(f"Ready to execute: {updated_state.ready_for_execution}")

        if updated_state.ready_for_execution:
            if _has_actionable_task(updated_state):
                print(f"Thread {thread_id} ready - executing workflow...")
                response_text, updated_state = await _execute_workflow_guarded(
                    updated_state, thread_id, cleanup_file=uploaded_file
                )
            else:
                trace.warning("ready_for_execution=True but no task context — resetting")
                updated_state.ready_for_execution = False
                updated_state.intent = None
                response_text = "Is there anything else I can help with?"
                conversational_agent.thread_service.save_thread_to_db(thread_id, updated_state)

        # Chokepoint: persist the FINAL post-workflow response so a thread
        # switch / re-login keeps the long response intact. Mirrors the
        # send_message_to_thread_with_upload chokepoint — the create-with-upload
        # path also runs process_message + execute_workflow_guarded and would
        # otherwise leave the rich friendly_summary unpersisted.
        _persist_final_response(thread_id, updated_state, response_text)

        metadata = conversational_agent.thread_service.get_thread_metadata(thread_id)

        logger.request_summary()
        clear_request_context()

        return {
            "thread_id": thread_id,
            "bot_response": response_text,
            "ready_for_execution": updated_state.ready_for_execution,
            "metadata": metadata
        }

    except LLMServiceException:
        clear_request_context()
        raise
    except Exception as e:
        print(f"\nError creating thread with upload: {str(e)}")
        traceback.print_exc()

        if 'uploaded_file' in locals():
            delete_temp_file(uploaded_file)

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
        print(f"Error searching threads: {str(e)}")
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
        print(f"Error listing threads: {str(e)}")
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
        print(f"Error getting thread: {str(e)}")
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
        print(f"Error getting thread messages: {str(e)}")
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

    user_id = thread_id.split('_')[0] if '_' in thread_id else None
    if user_id:
        _check_quota_or_raise(user_id)

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

        # === PROGRESS: Analyzing ===
        await broadcast_progress(thread_id, 0, 0, "Analyzing your message...", status="analyzing")

        # Run in thread so the event loop stays free to deliver WebSocket progress
        response_text, conversation_state = await asyncio.to_thread(
            conversational_agent.process_message,
            user_message=message,
            conversation_state=conversation_state,
            state_id=thread_id,
            auto_save=True,
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

        if not handled and conversation_state.ready_for_execution:
            if _has_actionable_task(conversation_state):
                print(f"Thread {thread_id} ready - executing workflow...")
                trace.decision("ready_for_execution", "YES — executing workflow")
                response_text, conversation_state = await _execute_workflow_guarded(
                    conversation_state, thread_id
                )
            else:
                trace.warning("ready_for_execution=True but no task context — resetting")
                conversation_state.ready_for_execution = False
                conversation_state.intent = None
                response_text = "Is there anything else I can help with?"
                conversational_agent.thread_service.save_thread_to_db(thread_id, conversation_state)

        # Chokepoint: persist the final, post-handler response to DB and memory
        # so thread-switch / re-login keeps the long response intact.
        _persist_final_response(thread_id, conversation_state, response_text)

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
    except LLMServiceException:
        clear_request_context()
        raise
    except ValueError as e:
        clear_request_context()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"Error sending message to thread: {str(e)}")
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

    user_id = thread_id.split('_')[0] if '_' in thread_id else None
    if user_id:
        _check_quota_or_raise(user_id)

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
        print(f"\nFile upload to thread {thread_id}: {file.filename}")

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

        # === PROGRESS: Analyzing ===
        await broadcast_progress(thread_id, 0, 0, "Analyzing your message...", status="analyzing")

        # Run in thread so the event loop stays free to deliver WebSocket progress
        response_text, updated_state = await asyncio.to_thread(
            conversational_agent.process_message,
            user_message=message,
            conversation_state=conversation_state,
            state_id=thread_id,
            auto_save=True,
            uploaded_file=uploaded_file,
        )

        print(f"Bot response: {response_text}")
        print(f"Ready to execute: {updated_state.ready_for_execution}")

        response_text, updated_state, handled = await _handle_pending_action_decision(
            updated_state, thread_id, response_text
        )

        if not handled:
            response_text, updated_state, handled = await _handle_disambiguation_selection(
                updated_state, thread_id, response_text
            )

        if not handled and updated_state.ready_for_execution:
            if _has_actionable_task(updated_state):
                print(f"Thread {thread_id} ready - executing workflow...")
                response_text, updated_state = await _execute_workflow_guarded(
                    updated_state, thread_id, cleanup_file=uploaded_file
                )
            else:
                trace.warning("ready_for_execution=True but no task context — resetting")
                updated_state.ready_for_execution = False
                updated_state.intent = None
                response_text = "Is there anything else I can help with?"
                conversational_agent.thread_service.save_thread_to_db(thread_id, updated_state)

        _persist_final_response(thread_id, updated_state, response_text)

        metadata = conversational_agent.thread_service.get_thread_metadata(thread_id)

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
    except LLMServiceException:
        clear_request_context()
        raise
    except Exception as e:
        print(f"\nError sending message with upload to thread: {str(e)}")
        traceback.print_exc()

        if 'uploaded_file' in locals():
            delete_temp_file(uploaded_file)

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
        print(f"Error updating thread: {str(e)}")
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
        print(f"Error deleting thread: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
