"""supervisor-admin-activity — GET /admin/activity (PII-redacted)"""
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
    agent = get_query_param(event, "agent")
    try:
        limit = min(int(get_query_param(event, "limit") or 50), 200)
    except (TypeError, ValueError):
        return error_response(400, "limit must be an integer")

    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            agent_calls = storage.get_agent_calls(
                agent_name=agent,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
            )
            activities = [PIIRedactor.create_admin_activity_summary(c) for c in agent_calls]
            return success_response({
                "activities": activities,
                "total": len(activities),
                "_privacy": {"pii_redacted": True, "content_hidden": True, "safe_for_admin_viewing": True},
            })
        except Exception as e:
            return error_response(500, f"Error retrieving activity: {e}")
