"""supervisor-logs-stats — GET /logs/stats"""
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


_PERIOD_HOURS = {"1h": 1, "6h": 6, "24h": 24, "7d": 168, "30d": 720}


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    period = get_query_param(event, "period")
    start_time = get_query_param(event, "start_time")
    end_time = get_query_param(event, "end_time")
    # Optional per-thread scope. The AI Assistant chat's "Token
    # consumption" modal hits /logs/stats?thread_id=<thread> to get
    # this thread's LLM call history (matches the SFXBot history
    # pattern). Either query param works — `thread_id` is preferred
    # by the new chat modal; `conversation_id` is the legacy alias.
    thread_id = get_query_param(event, "thread_id") or get_query_param(event, "conversation_id")

    if not start_time and period and period in _PERIOD_HOURS:
        start_time = (datetime.utcnow() - timedelta(hours=_PERIOD_HOURS[period])).isoformat() + "Z"

    # When the chat modal asks for include_calls=true (typically in
    # combination with thread_id), also return the raw LLM call rows so
    # the "Show details" toggle has data to render. Capped at 200 rows
    # to keep the payload sane — single-thread requests should never
    # approach this even on heavy workflows.
    include_calls = (get_query_param(event, "include_calls") or "").lower() in ("1", "true", "yes")

    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            token_summary = storage.get_token_summary(
                start_time, end_time, thread_id=thread_id
            )
            request_analytics = storage.get_request_analytics(
                start_time, end_time, thread_id=thread_id
            )
            payload = {
                "token_summary": token_summary,
                "request_analytics": request_analytics,
                "time_range": {"start": start_time, "end": end_time, "period": period},
                "thread_id": thread_id,
            }
            if include_calls:
                payload["llm_calls"] = storage.get_llm_calls(
                    conversation_id=thread_id,
                    since=start_time,
                    until=end_time,
                    limit=200,
                )
            return success_response(payload)
        except Exception as e:
            return error_response(500, f"Error retrieving stats: {e}")
