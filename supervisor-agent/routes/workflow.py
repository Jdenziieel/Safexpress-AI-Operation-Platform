# Transfer this file out of routes to keep file organization clean - main workflow logic should be separate from HTTP concerns.

"""
Workflow execution route.

Handles POST /workflow - the main endpoint to accept user input
and execute the supervisor → orchestrator workflow.

Architecture:
  run_workflow(user_input)  ← pure function, no HTTP deps, used by threads.py directly
  execute_workflow(request) ← thin HTTP wrapper for POST /workflow
"""

from fastapi import APIRouter, HTTPException
from datetime import datetime
import json
import traceback

from supervisor_agent import workflow, react_workflow
from models.models import UserRequest, WorkflowResponse, SharedState
from llm_error_handler import handle_llm_error, LLMServiceException, is_llm_error
from execution_logger import trace
from logging_config import (
    supervisor_logger as logger,
    set_request_context,
    clear_request_context,
    generate_request_id,
)

router = APIRouter(tags=["workflow"])


def run_workflow(user_input: str, context_overrides: dict = None, execution_mode: str = "standard") -> WorkflowResponse:
    """
    Execute the supervisor → orchestrator workflow.

    Pure function — no HTTP, no request context.
    Can be called directly by threads.py or via the /workflow HTTP endpoint.

    Args:
        user_input: The user's natural language request
        context_overrides: Optional dict merged into the initial context
            (e.g. {"uploaded_file": {...}} so the orchestrator can access it)
        execution_mode: "standard" (plan-all) or "react" (iterative step-by-step)

    Returns:
        WorkflowResponse with status, final_context, plan, and message

    Raises:
        LLMServiceException: If an LLM error occurs (rate limit, quota, etc.)
        Exception: For unexpected errors (not wrapped)
    """
    today = datetime.now().strftime("%Y-%m-%d")

    context = {"today_date": today}
    if context_overrides:
        context.update(context_overrides)

    initial_state: SharedState = {
        "input": user_input,
        "plan": {},
        "context": context,
        "final_context": {},
        "execution_mode": execution_mode,
        # Orchestrator output fields (populated during execution)
        "results": [],
        "error": "",
        "stopped_at_step": 0,
        # ReAct fields (only meaningful when execution_mode == "react")
        "react_history": [],
        "react_iteration": 0,
        "react_done": False,
    }

    selected_workflow = react_workflow if execution_mode == "react" else workflow

    print(f"📅 Date context: today={today}")
    print(f"🚀 Starting workflow execution (mode={execution_mode})...")
    trace.step("workflow_invoke", f"LangGraph workflow.invoke() starting (mode={execution_mode})")

    result_state = selected_workflow.invoke(initial_state)

    print("\n✅ Workflow completed successfully")
    plan = result_state.get('plan', {})
    steps = plan.get('steps', []) if isinstance(plan, dict) else []
    trace.workflow_end("success", steps_completed=len(steps), total_steps=len(steps))

    print(
        f"\n📋 Generated Plan:\n{json.dumps(result_state.get('plan', {}), indent=2)}"
    )
    print(
        f"\n📊 Final Context: {json.dumps(result_state.get('final_context', {}), indent=2)}"
    )

    # Determine real status from result state
    final_context = result_state.get("final_context", {})
    has_error = result_state.get("error") or final_context.get("error")
    status = "error" if has_error else "success"
    message = result_state.get("error") or "Workflow executed successfully"

    return WorkflowResponse(
        status=status,
        final_context=final_context,
        plan=result_state.get("plan", {}),
        message=message,
    )

# Can be deleted if not needed, but keeps HTTP concerns separate from core workflow logic
@router.post("/workflow", response_model=WorkflowResponse)
async def execute_workflow(request: UserRequest):
    """
    HTTP endpoint wrapper for run_workflow().
    Adds request context, logging, and HTTP error handling.
    """
    try:
        request_id = set_request_context(
            request_id=generate_request_id(),
            conversation_id=None,
            thread_id=None,
        )
        trace.set_context(request_id=request_id)
        trace.request_start("POST /workflow", {"input_preview": request.input[:80]})
        print(f"\n📥 Received request: {request.input}")

        result = run_workflow(request.input)

        logger.request_summary()
        trace.request_end("200 OK")
        clear_request_context()
        return result

    except LLMServiceException as llm_ex:
        trace.error("LLM error in workflow", llm_ex)
        trace.request_end(f"{llm_ex.status_code} LLM Error")
        clear_request_context()
        raise

    except Exception as e:
        if is_llm_error(e):
            llm_error = handle_llm_error(e, context="Workflow Execution")
            trace.error("LLM error in workflow", e, {"user_message": llm_error.user_message})
            trace.request_end(f"{llm_error.status_code} LLM Error")
            clear_request_context()
            raise LLMServiceException(llm_error)

        trace.error("workflow execution failed", e)
        traceback.print_exc()
        trace.request_end("500 Internal Error")
        clear_request_context()
        raise HTTPException(
            status_code=500, detail=f"Workflow execution failed: {str(e)}"
        )
