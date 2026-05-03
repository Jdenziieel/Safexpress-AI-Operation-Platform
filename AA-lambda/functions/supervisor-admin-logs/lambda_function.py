"""supervisor-admin-logs — GET /admin/logs (PII-redacted)"""
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

    level = get_query_param(event, "level")
    component = get_query_param(event, "component")
    start_time = get_query_param(event, "start_time")
    end_time = get_query_param(event, "end_time")
    try:
        limit = min(int(get_query_param(event, "limit") or 100), 500)
        offset = int(get_query_param(event, "offset") or 0)
    except (TypeError, ValueError):
        return error_response(400, "limit and offset must be integers")

    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            logs, total = storage.get_logs(
                level=level.upper() if level else None,
                component=component,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
                offset=offset,
            )
            redacted = [PIIRedactor.redact_log_entry(log, level="admin") for log in logs]
            return success_response({
                "logs": redacted,
                "total": total,
                "limit": limit,
                "offset": offset,
                "_privacy": {
                    "pii_redacted": True,
                    "redaction_level": "admin",
                    "safe_for_admin_viewing": True,
                },
            })
        except Exception as e:
            return error_response(500, f"Error retrieving admin logs: {e}")
