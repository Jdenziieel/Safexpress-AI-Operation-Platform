"""
Workflow execution route.

Handles POST /workflow - the main endpoint to accept user input
and execute the supervisor → orchestrator workflow.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
import json
import traceback

from supervisor_agent import workflow, UserRequest, WorkflowResponse, SharedState
from llm_error_handler import handle_llm_error, LLMServiceException, is_llm_error
from execution_logger import trace

router = APIRouter(tags=["workflow"])


@router.post("/workflow", response_model=WorkflowResponse)
async def execute_workflow(request: UserRequest):
    """
    Main endpoint to accept user input and execute the workflow.

    Args:
        request: UserRequest containing:
            - input: The user's natural language request
            - memory: Optional context from previous interactions
            - policies: Optional access control policies

    Returns:
        WorkflowResponse with status, final context, plan, and message
    """
    try:
        print(f"\n📥 Received request: {request.input}")

        # Get current date for date-aware queries (Gmail-compatible format)
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        # Prepare initial state with date context
        initial_state: SharedState = {
            "input": request.input,
            "plan": {},
            "context": {
                "today_date": today,
                "yesterday_date": yesterday,
                "current_year": datetime.now().year,
                "current_month": datetime.now().month,
                "current_day": datetime.now().day,
            },
            "memory": request.memory,
            "policy": request.policies,
            "final_context": {},
        }

        print(f"📅 Date context: today={today}, yesterday={yesterday}")

        # Execute workflow
        print("🚀 Starting workflow execution...")
        trace.step("workflow_invoke", "LangGraph workflow.invoke() starting")
        result_state = workflow.invoke(initial_state)

        print("\n✅ Workflow completed successfully")
        plan = result_state.get('plan', {})
        steps = plan.get('steps', []) if isinstance(plan, dict) else []
        trace.workflow_end("success", steps_completed=len(steps), total_steps=len(steps))

        # Also print to console for immediate viewing
        print(
            f"\n📋 Generated Plan:\n{json.dumps(result_state.get('plan', {}), indent=2)}"
        )
        print(
            f"\n📊 Final Context: {json.dumps(result_state.get('final_context', {}), indent=2)}"
        )

        return WorkflowResponse(
            status="success",
            final_context=result_state.get("final_context", {}),
            plan=result_state.get("plan", {}),
            message="Workflow executed successfully",
        )

    # except ApprovalRequiredException as approval_ex:
    #     # Handle approval requirement gracefully
    #     print(
    #         f"\n⏸️ Workflow paused - approval required for action: {approval_ex.action_id}"
    #     )

        # Return structured response for approval
        raise HTTPException(
            status_code=202,  # 202 Accepted - request received but not completed
            detail={
                "status": "approval_required",
                "action_id": approval_ex.action_id,
                "step_info": approval_ex.step_info,
                "message": str(approval_ex),
                "approval_endpoint": f"/action/approve/{approval_ex.action_id}",
                "next_steps": [
                    f"Review the action details at GET /action/{approval_ex.action_id}",
                    f"Approve with POST /action/approve/{approval_ex.action_id}",
                    "Include decision: 'approve', 'reject', or 'skip'",
                ],
            },
        )
    
    except LLMServiceException as llm_ex:
        # Handle LLM-specific errors with structured response
        print(f"\n🔴 LLM Error in workflow: {llm_ex}")
        return JSONResponse(
            status_code=llm_ex.status_code,
            content=llm_ex.to_dict()
        )

    except Exception as e:
        # Check if this is an LLM error that wasn't wrapped
        if is_llm_error(e):
            llm_error = handle_llm_error(e, context="Workflow Execution")
            print(f"\n🔴 LLM Error in workflow: {llm_error.user_message}")
            return JSONResponse(
                status_code=llm_error.status_code,
                content=llm_error.to_dict()
            )
        
        print(f"\n❌ Error executing workflow: {str(e)}")
        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Workflow execution failed: {str(e)}"
        )
