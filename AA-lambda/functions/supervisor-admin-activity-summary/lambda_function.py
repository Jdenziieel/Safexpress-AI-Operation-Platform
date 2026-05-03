"""supervisor-admin-activity-summary — GET /admin/activity/summary"""
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

    try:
        from pii_redactor import PIIRedactor  # type: ignore
    except ImportError as e:
        return error_response(500, f"PIIRedactor not available: {e}")

    start_time = get_query_param(event, "start_time")
    end_time = get_query_param(event, "end_time")
    period = get_query_param(event, "period") or "24h"

    if not start_time and not end_time:
        delta = _PERIODS.get(period, _PERIODS["24h"])
        start_time = (datetime.utcnow() - delta).isoformat() + "Z"

    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            calls = storage.get_agent_calls(start_time=start_time, end_time=end_time, limit=10000)
            summary = PIIRedactor.create_activity_aggregation(calls)
            summary["period"] = period
            summary["time_range"] = {"start": start_time, "end": end_time}
            summary["_privacy"] = {
                "pii_redacted": True,
                "aggregated_data_only": True,
                "safe_for_admin_viewing": True,
            }
            return success_response(summary)
        except Exception as e:
            return error_response(500, f"Error retrieving summary: {e}")
