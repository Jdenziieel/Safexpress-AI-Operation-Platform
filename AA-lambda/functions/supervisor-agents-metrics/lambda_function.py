"""supervisor-agents-metrics — GET /agents/metrics"""
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
    get_query_param,
    set_request_context_lambda,
)
from shared.persistence_factory import get_log_storage


def _score(stats):
    total = stats["total_calls"]
    successful = stats["successful_calls"]
    accuracy = (successful / total * 100) if total > 0 else 0
    reliability = accuracy
    avg_duration = stats["total_duration_ms"] / total if total > 0 else 0
    if avg_duration < 3000:
        speed = 100
    elif avg_duration < 10000:
        speed = 75
    else:
        speed = 50
    efficiency = 70
    user_feedback = 70
    overall = accuracy * 0.35 + speed * 0.25 + reliability * 0.15 + efficiency * 0.10 + user_feedback * 0.15
    if overall >= 85:
        tier = "Excellent"
    elif overall >= 70:
        tier = "Good"
    elif overall >= 50:
        tier = "Fair"
    else:
        tier = "Poor"
    return {
        "accuracy": round(accuracy, 1),
        "speed": round(speed, 1),
        "reliability": round(reliability, 1),
        "efficiency": round(efficiency, 1),
        "user_feedback": round(user_feedback, 1),
        "overall_score": round(overall, 1),
        "tier": tier,
        "total_calls": total,
        "successful_calls": successful,
        "success_rate": round(accuracy, 1),
        "avg_latency_ms": round(avg_duration, 0),
    }


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    start_time = get_query_param(event, "start_time")
    end_time = get_query_param(event, "end_time")

    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            agent_calls = storage.get_agent_calls(start_time=start_time, end_time=end_time, limit=10000)
        except Exception as e:
            return error_response(500, f"Error retrieving agent metrics: {e}")

    stats_per_agent = {}
    for call in agent_calls:
        agent = call.get("agent_name") or "unknown"
        s = stats_per_agent.setdefault(agent, {
            "total_calls": 0, "successful_calls": 0, "total_duration_ms": 0, "durations": []
        })
        s["total_calls"] += 1
        if call.get("success"):
            s["successful_calls"] += 1
        d = call.get("duration_ms", 0) or 0
        s["total_duration_ms"] += d
        s["durations"].append(d)

    metrics = {agent: _score(stats) for agent, stats in stats_per_agent.items()}
    return success_response({
        "metrics": metrics,
        "time_range": {"start": start_time, "end": end_time},
        "agent_count": len(metrics),
    })
