"""supervisor-logs-by-request — GET /logs/requests/{request_id}"""
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


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    request_id = get_path_param(event, "request_id")
    if not request_id:
        return error_response(400, "request_id is required")

    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            logs, total = storage.get_logs(request_id=request_id, limit=1000)
        except Exception as e:
            return error_response(500, f"Error retrieving request logs: {e}")

    token_total = 0
    cost_total = 0.0
    llm_calls = []
    agent_calls = []

    for log in logs:
        data = log.get("data", {}) or {}
        if log.get("component") == "llm" and "input_tokens" in data:
            token_total += data.get("total_tokens", 0)
            cost_total += data.get("estimated_cost_usd", 0)
            llm_calls.append({
                "operation": log.get("operation"),
                "model": data.get("model"),
                "tokens": data.get("total_tokens"),
                "cost_usd": data.get("estimated_cost_usd"),
                "duration_ms": data.get("duration_ms"),
            })
        elif log.get("component") == "orchestrator" and "agent" in data:
            agent_calls.append({
                "agent": data.get("agent"),
                "tool": data.get("tool"),
                "success": data.get("success"),
                "duration_ms": data.get("duration_ms"),
            })

    return success_response({
        "request_id": request_id,
        "logs": logs,
        "total_logs": total,
        "summary": {
            "total_tokens": token_total,
            "total_cost_usd": round(cost_total, 6),
            "llm_calls": len(llm_calls),
            "agent_calls": len(agent_calls),
            "llm_details": llm_calls,
            "agent_details": agent_calls,
        },
    })
