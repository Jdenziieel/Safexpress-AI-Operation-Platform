"""supervisor-action-get — GET /action/{action_id}"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(_HERE, "shared")
for p in (_SHARED, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from datetime import timedelta

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

    action_id = get_path_param(event, "action_id")
    if not action_id:
        return error_response(400, "action_id is required")

    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            row = storage.get_pending_action(action_id)
        except Exception as e:
            return error_response(500, f"failed to load action: {e}")

    if not row:
        return error_response(404, "Action not found")

    # Reshape the flat persistence row into the nested step_info shape that
    # the source FastAPI endpoint returns. Matches
    # ``supervisor_agent.get_pending_action`` (lines 936-944).
    step_info = {
        "step_number": row.get("step_number"),
        "agent": row.get("agent_name"),
        "tool": row.get("tool_name"),
        "description": row.get("description"),
        "inputs": row.get("inputs"),
        "output_variables": row.get("output_variables"),
        "risk_level": row.get("risk_level"),
    }
    tool = step_info["tool"]
    inputs = step_info.get("inputs") or {}
    try:
        from shared.utils import generate_action_summary  # type: ignore
        summary = generate_action_summary(tool, inputs)
    except Exception:
        summary = {"action": tool, "description": f"Execute {tool}", "details": inputs}

    created_at = row.get("created_at")
    expires_at = None
    if created_at:
        try:
            from datetime import datetime
            ts = datetime.fromisoformat(created_at) if isinstance(created_at, str) else created_at
            # Source uses 5min — preserved verbatim.
            expires_at = (ts + timedelta(minutes=5)).isoformat()
        except Exception:
            expires_at = None

    return success_response({
        "action_id": action_id,
        "step_info": step_info,
        "summary": summary,
        "status": row.get("status", "unknown"),
        "created_at": created_at,
        "expires_at": expires_at,
    })
