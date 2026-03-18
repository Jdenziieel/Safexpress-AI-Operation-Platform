"""
Action approval routes.

Handles all /actions/* and /action/* endpoints for the
pending action approval workflow (approve, reject, skip, cleanup).
"""

from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
import json
import os

from models.models import ActionApprovalRequest
from log_storage import LogStorage
from config import AGENT_ENDPOINTS
from utils import call_agent_with_retry, generate_action_summary
from supervisor_agent import (
    PENDING_ACTIONS_CACHE,
    PendingAction,
    get_pending_action,
    remove_pending_action,
)

router = APIRouter(tags=["actions"])


def execute_single_action(step_info: dict) -> dict:
    """Execute a single approved action"""
    agent_name = step_info["agent"]
    tool_name = step_info["tool"]
    inputs = step_info["inputs"]

    agent_url = AGENT_ENDPOINTS.get(agent_name)
    if not agent_url:
        raise ValueError(f"No endpoint for agent: {agent_name}")

    request_payload = {
        "tool": tool_name,
        "inputs": inputs,
        "credentials_dict": {
            "access_token": os.getenv("GOOGLE_ACCESS_TOKEN"),
            "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN"),
        },
    }

    # Use retry logic
    result = call_agent_with_retry(
        agent_url=agent_url, request_payload=request_payload, max_retries=3
    )

    if not result:
        raise ValueError("Agent call failed after retries")

    return result


@router.get("/actions/pending")
async def list_pending_actions(thread_id: str = None):
    """List all actions waiting for approval (with automatic cleanup from SQLite)"""
    storage = LogStorage()
    
    # First cleanup expired actions
    cleaned_count = storage.cleanup_expired_pending_actions(expire_minutes=5)
    if cleaned_count > 0:
        print(f"🧹 Cleaned up {cleaned_count} expired actions from SQLite")
    
    # Get pending actions from SQLite
    pending_records = storage.get_pending_actions(status="pending", thread_id=thread_id)
    
    # Also sync with in-memory cache (PENDING_ACTIONS_CACHE used for execution callbacks)
    for record in pending_records:
        if record["action_id"] not in PENDING_ACTIONS_CACHE:
            # Reload into cache if missing (note: execution_callback will be None after restart)
            action = PendingAction(
                action_id=record["action_id"],
                step_info={
                    "agent": record["agent_name"],
                    "tool": record["tool_name"],
                    "description": record["description"],
                    "inputs": record["inputs"] if record["inputs"] else {},
                    "output_variables": record["output_variables"] if record["output_variables"] else [],
                    "risk_level": record["risk_level"]
                },
                thread_id=record.get("thread_id"),
                conversation_id=record.get("conversation_id"),
                request_id=record.get("request_id")
            )
            PENDING_ACTIONS_CACHE[record["action_id"]] = action
    
    return {"pending_actions": pending_records, "count": len(pending_records)}


@router.get("/action/{action_id}")
async def get_action_details(action_id: str):
    """Get detailed information about a pending action"""
    action = get_pending_action(action_id)

    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    # Add helpful context
    step_info = action.step_info
    tool = step_info.get("tool")
    inputs = step_info.get("inputs", {})

    # Generate human-readable summary
    summary = generate_action_summary(tool, inputs)

    return {
        "action_id": action_id,
        "step_info": step_info,
        "summary": summary,
        "status": action.status,
        "created_at": action.created_at.isoformat(),
        "expires_at": (action.created_at + timedelta(minutes=5)).isoformat(),
    }


@router.post("/action/approve/{action_id}")
async def approve_action(action_id: str, approval: ActionApprovalRequest):
    """
    Approve or reject a specific action.
    After approval, the workflow continues from where it paused.
    Also updates status in SQLite database.
    """
    storage = LogStorage()
    
    action = get_pending_action(action_id)

    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    if action.status != "pending":
        raise HTTPException(status_code=400, detail=f"Action already {action.status}")

    # Check timeout
    if datetime.now() - action.created_at > timedelta(minutes=360):
        action.status = "expired"
        storage.update_pending_action_status(action_id, "expired", decided_by="system_timeout")
        raise HTTPException(status_code=400, detail="Action approval expired")

    # Handle rejection
    if approval.decision == "reject":
        action.status = "rejected"
        storage.update_pending_action_status(
            action_id, "rejected", 
            decided_by="user",
            error=approval.rejection_reason
        )
        print(f"❌ Action {action_id} rejected: {approval.rejection_reason}")
        return {
            "status": "rejected",
            "action_id": action_id,
            "message": f"Action rejected: {approval.rejection_reason}",
        }

    # Handle skip
    if approval.decision == "skip":
        action.status = "skipped"
        storage.update_pending_action_status(action_id, "skipped", decided_by="user")
        print(f"⏭️ Action {action_id} skipped")
        return {
            "status": "skipped",
            "action_id": action_id,
            "message": "Action skipped, workflow will continue to next step",
        }

    # Handle approval (with optional modifications)
    action.status = "approved"
    storage.update_pending_action_status(action_id, "approved", decided_by="user")

    # Apply modified inputs if provided
    if approval.modified_inputs:
        print(f"📝 Inputs modified by user")
        action.step_info["inputs"] = approval.modified_inputs

    print(f"✅ Action {action_id} approved, executing now...")

    # Execute the approved action
    try:
        result = execute_single_action(action.step_info)
        action.result = result
        action.status = "completed"

        # Update status in SQLite with execution result
        storage.update_pending_action_status(
            action_id, "completed", 
            decided_by="user",
            execution_result=result
        )

        # Clean up from cache
        remove_pending_action(action_id)

        return {
            "status": "completed",
            "action_id": action_id,
            "result": result,
            "message": "Action executed successfully",
        }

    except Exception as e:
        action.status = "failed"
        action.result = {"error": str(e)}
        
        # Update status in SQLite with error
        storage.update_pending_action_status(
            action_id, "failed", 
            decided_by="user",
            error=str(e)
        )

        return {
            "status": "failed",
            "action_id": action_id,
            "error": str(e),
            "message": f"Action execution failed: {str(e)}",
        }


@router.post("/actions/cleanup")
async def cleanup_expired_actions(expire_minutes: int = 5):
    """Clean up expired or completed pending actions from both cache and SQLite"""
    storage = LogStorage()
    
    # Clean up from SQLite
    cleaned_from_db = storage.cleanup_expired_pending_actions(expire_minutes=expire_minutes)
    
    # Also clean up from in-memory cache (PENDING_ACTIONS_CACHE)
    cleaned_from_cache = []
    now = datetime.now()
    
    # Create a list of actions to remove (can't modify dict during iteration)
    actions_to_remove = []
    
    for action_id, action in PENDING_ACTIONS_CACHE.items():
        # Remove if expired (older than specified minutes)
        if now - action.created_at > timedelta(minutes=expire_minutes):
            actions_to_remove.append(action_id)
            cleaned_from_cache.append({
                "action_id": action_id,
                "reason": "expired",
                "age_seconds": (now - action.created_at).total_seconds()
            })
        # Remove if already processed (not pending)
        elif action.status != "pending":
            actions_to_remove.append(action_id)
            cleaned_from_cache.append({
                "action_id": action_id,
                "reason": f"already_{action.status}",
                "status": action.status
            })
    
    # Remove from cache
    for action_id in actions_to_remove:
        PENDING_ACTIONS_CACHE.pop(action_id, None)
    
    # Get remaining pending count from SQLite
    remaining = storage.get_pending_actions(status="pending")
    
    return {
        "cleaned_from_db": cleaned_from_db,
        "cleaned_from_cache": len(cleaned_from_cache),
        "cleaned_cache_details": cleaned_from_cache,
        "remaining_pending": len(remaining)
    }
