"""supervisor-admin-health — GET /admin/health"""
import os
import sys
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(_HERE, "shared")
for p in (_SHARED, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.lambda_helpers import (
    success_response,
    error_response,
    options_response,
    get_query_param,
    set_request_context_lambda,
)
from shared.persistence_factory import get_log_storage


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    start_time = get_query_param(event, "start_time")
    end_time = get_query_param(event, "end_time")
    if not start_time:
        start_time = (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"

    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            agent_calls = storage.get_agent_calls(start_time=start_time, end_time=end_time, limit=10000)
            log_counts = storage.get_log_counts(start_time=start_time, end_time=end_time)
        except Exception as e:
            return error_response(500, f"Error retrieving health: {e}")

    total_calls = len(agent_calls)
    successful_calls = sum(1 for c in agent_calls if c.get("success"))
    failed_calls = total_calls - successful_calls
    success_rate = (successful_calls / total_calls * 100) if total_calls > 0 else 100
    avg_duration = (sum(c.get("duration_ms", 0) for c in agent_calls) / total_calls) if total_calls > 0 else 0
    error_count = (log_counts.get("ERROR", 0) or 0) + (log_counts.get("CRITICAL", 0) or 0)
    warning_count = log_counts.get("WARNING", 0) or 0

    if success_rate >= 95 and avg_duration < 5000 and error_count == 0:
        status, score = "healthy", 100
    elif success_rate >= 90 and avg_duration < 10000 and error_count <= 5:
        status, score = "degraded", 75
    else:
        status, score = "unhealthy", max(0, int(success_rate * 0.5))

    agents_status = {}
    for call in agent_calls:
        agent = call.get("agent_name", "unknown")
        s = agents_status.setdefault(agent, {"total": 0, "success": 0})
        s["total"] += 1
        if call.get("success"):
            s["success"] += 1
    agents_healthy = sum(1 for a in agents_status.values() if a["total"] > 0 and (a["success"] / a["total"]) >= 0.9)
    agents_degraded = len(agents_status) - agents_healthy

    return success_response({
        "status": status,
        "score": score,
        "indicators": {
            "success_rate": round(success_rate, 1),
            "avg_response_time_ms": round(avg_duration, 0),
            "error_count_1h": error_count,
            "warning_count_1h": warning_count,
            "total_actions_1h": total_calls,
            "agents_healthy": agents_healthy,
            "agents_degraded": agents_degraded,
        },
        "time_range": {"start": start_time, "end": end_time or datetime.utcnow().isoformat() + "Z"},
        "last_updated": datetime.utcnow().isoformat() + "Z",
    })
