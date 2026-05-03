"""supervisor-logs-search — GET /logs/search"""
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

    q = get_query_param(event, "q")
    if not q:
        return error_response(400, "q (query string) is required")

    level = get_query_param(event, "level")
    start_time = get_query_param(event, "start_time")
    end_time = get_query_param(event, "end_time")
    try:
        limit = min(int(get_query_param(event, "limit") or 100), 1000)
        offset = int(get_query_param(event, "offset") or 0)
    except (TypeError, ValueError):
        return error_response(400, "limit and offset must be integers")

    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            logs, total = storage.search_logs(
                query=q,
                level=level.upper() if level else None,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
                offset=offset,
            )
            return success_response({"logs": logs, "total": total, "query": q, "limit": limit, "offset": offset})
        except Exception as e:
            return error_response(500, f"Error searching logs: {e}")
