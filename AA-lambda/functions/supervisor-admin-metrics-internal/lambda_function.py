"""supervisor-admin-metrics-internal — GET /admin/metrics/internal

Aggregates LLM-call metrics by tier, grouping into 'conversational' and
'supervisor' logical components.
"""
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


_CONVERSATIONAL_TIERS = ("0.5", "1", "formatter", "memory")
_SUPERVISOR_TIERS = ("supervisor", "classifier", "orchestrator")
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
            stats = storage.get_token_usage_stats(
                start_time=start_time, end_time=end_time, group_by="tier"
            )
        except Exception as e:
            return error_response(500, f"Error retrieving internal metrics: {e}")

    by_tier_list = stats.get("by_tier") or []
    by_tier_map = {row.get("tier"): row for row in by_tier_list if row.get("tier")}

    def _aggregate(tiers):
        matching = [by_tier_map[t] for t in tiers if t in by_tier_map]
        total = sum(int(r.get("calls", 0) or 0) for r in matching)
        successful = sum(int(r.get("successful_calls", 0) or 0) for r in matching)
        tokens = sum(int(r.get("tokens", 0) or 0) for r in matching)
        cost = sum(float(r.get("cost_usd", 0) or 0) for r in matching)
        avg_ms = (
            sum(float(r.get("avg_duration_ms", 0) or 0) * int(r.get("calls", 0) or 0) for r in matching) / total
            if total else 0
        )
        return {
            "total_calls": total,
            "successful_calls": successful,
            "failed_calls": total - successful,
            "success_rate": round((successful / total * 100) if total > 0 else 0, 1),
            "avg_duration_ms": round(avg_ms, 0),
            "total_tokens": tokens,
            "total_cost_usd": round(cost, 6),
        }

    return success_response({
        "conversational": _aggregate(_CONVERSATIONAL_TIERS),
        "supervisor": _aggregate(_SUPERVISOR_TIERS),
        "period": period,
        "time_range": {"start": start_time, "end": end_time},
    })
