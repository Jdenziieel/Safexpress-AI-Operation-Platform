"""supervisor-admin-metrics — GET /admin/metrics"""
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


_PERIODS = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    start_time = get_query_param(event, "start_time")
    end_time = get_query_param(event, "end_time")
    period = get_query_param(event, "period") or "24h"

    if not start_time and not end_time:
        delta = _PERIODS.get(period, _PERIODS["24h"])
        start_time = (datetime.utcnow() - delta).isoformat() + "Z"

    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            agent_calls = storage.get_agent_calls(start_time=start_time, end_time=end_time, limit=10000)
        except Exception as e:
            return error_response(500, f"Error retrieving metrics: {e}")

        agent_stats: dict = {}
        for call in agent_calls:
            agent = call.get("agent_name", "unknown")
            stats = agent_stats.setdefault(agent, {"total_calls": 0, "successful_calls": 0, "total_duration_ms": 0})
            stats["total_calls"] += 1
            if call.get("success"):
                stats["successful_calls"] += 1
            stats["total_duration_ms"] += call.get("duration_ms", 0)

        agents_out = {}
        for agent, stats in agent_stats.items():
            total = stats["total_calls"]
            successful = stats["successful_calls"]
            success_rate = (successful / total * 100) if total > 0 else 0
            avg_duration = stats["total_duration_ms"] / total if total > 0 else 0
            agents_out[agent] = {
                "success_rate": round(success_rate, 1),
                "avg_response_time_ms": round(avg_duration, 0),
                "total_actions": total,
                "failed_actions": total - successful,
            }

        try:
            system_stats = storage.get_avg_response_time(start_time=start_time, end_time=end_time)
        except Exception:
            system_stats = {"avg_response_time_ms": 0, "total_requests": 0}

        return success_response({
            "system": system_stats,
            "agents": agents_out,
            "period": period,
            "time_range": {"start": start_time, "end": end_time},
            "_privacy": {
                "pii_redacted": True,
                "aggregated_metrics_only": True,
                "safe_for_admin_viewing": True,
            },
        })
