"""supervisor-logs-clear — DELETE /logs"""
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

    confirm = (get_query_param(event, "confirm") or "").lower() in ("true", "1", "yes")
    before_time = get_query_param(event, "before_time")

    if not confirm:
        return error_response(400, "Set confirm=true to actually delete logs")

    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            deleted = storage.clear_logs(before_time)
            return success_response({"deleted_count": deleted, "before_time": before_time or "all"})
        except Exception as e:
            return error_response(500, f"Error clearing logs: {e}")
