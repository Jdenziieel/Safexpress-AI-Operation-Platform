"""supervisor-get-progress — GET /threads/{thread_id}/progress

Polling fallback for the WebSocket progress stream. Reads the most recent
log entries for the thread to reconstruct an at-a-glance progress snapshot.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(_HERE, "shared")
for p in (_SHARED, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.lambda_helpers import (
    success_response,
    error_response,
    options_response,
    get_path_param,
    set_request_context_lambda,
)
from shared.persistence_factory import get_log_storage


_IDLE = {
    "status": "idle",
    "current_step": 0,
    "total_steps": 0,
    "step_name": None,
    "agent": None,
    "message": None,
    "request_id": None,
    "token_usage": None,
}


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    thread_id = get_path_param(event, "thread_id")
    if not thread_id:
        return error_response(400, "thread_id is required")

    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            logs, _ = storage.get_logs(thread_id=thread_id, limit=50, offset=0)
        except Exception as e:
            return error_response(500, f"Error retrieving progress: {e}")

    if not logs:
        return success_response(_IDLE)

    latest_progress = None
    latest_llm = None
    latest_agent = None
    latest_request_id = None
    current_status = "idle"

    for log in logs:
        level = log.get("level", "")
        component = log.get("component", "")
        operation = log.get("operation", "")
        data = log.get("data", {}) or {}

        if log.get("request_id") and not latest_request_id:
            latest_request_id = log.get("request_id")

        if level == "PROGRESS" and not latest_progress:
            latest_progress = {
                "current_step": data.get("current_step", 0),
                "total_steps": data.get("total_steps", 0),
                "step_name": data.get("step_name", ""),
                "message": log.get("message", ""),
            }
            current_status = "executing"

        if component == "llm" and not latest_llm:
            latest_llm = {
                "operation": operation,
                "model": data.get("model", ""),
                "tokens": data.get("total_tokens", 0),
                "tier": data.get("tier", ""),
            }
            if current_status == "idle":
                current_status = "processing"

        if component == "orchestrator" and operation == "agent_call" and not latest_agent:
            latest_agent = {
                "agent": data.get("agent", ""),
                "tool": data.get("tool", ""),
                "step": data.get("step", 0),
                "total_steps": data.get("total_steps", 0),
                "success": data.get("success", True),
            }
            current_status = "executing"

        if operation == "request_complete":
            current_status = "completed"
            break

    response = {
        "status": current_status,
        "current_step": 0,
        "total_steps": 0,
        "step_name": None,
        "agent": None,
        "message": None,
        "request_id": latest_request_id,
        "token_usage": None,
    }

    if latest_progress:
        response["current_step"] = latest_progress["current_step"]
        response["total_steps"] = latest_progress["total_steps"]
        response["step_name"] = latest_progress["step_name"]
        response["message"] = latest_progress["message"]

    if latest_agent:
        response["agent"] = latest_agent["agent"]
        response["tool"] = latest_agent["tool"]
        if not latest_progress:
            response["current_step"] = latest_agent["step"]
            response["total_steps"] = latest_agent["total_steps"]
            response["step_name"] = f"{latest_agent['agent']}.{latest_agent['tool']}"

    if latest_llm and current_status == "processing":
        response["step_name"] = latest_llm["operation"]
        response["message"] = f"Processing with {latest_llm['model']}..."

    if latest_request_id:
        try:
            request_logs, _ = storage.get_logs(request_id=latest_request_id, component="llm", limit=100)
        except Exception:
            request_logs = []
        total_tokens = 0
        total_cost = 0.0
        llm_calls = 0
        for log in request_logs:
            data = log.get("data", {}) or {}
            if "total_tokens" in data:
                total_tokens += int(data.get("total_tokens") or 0)
                total_cost += float(data.get("estimated_cost_usd") or 0)
                llm_calls += 1
        if llm_calls > 0:
            response["token_usage"] = {
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost, 6),
                "llm_calls": llm_calls,
            }

    return success_response(response)
