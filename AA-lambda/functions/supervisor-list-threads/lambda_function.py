"""supervisor-list-threads — GET /threads"""
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
from shared.persistence_factory import get_thread_manager


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    user_id = get_query_param(event, "user_id")
    if not user_id:
        return error_response(400, "user_id is required")
    status = get_query_param(event, "status") or "active"
    try:
        limit = int(get_query_param(event, "limit") or 50)
        offset = int(get_query_param(event, "offset") or 0)
    except (TypeError, ValueError):
        return error_response(400, "limit and offset must be integers")

    tm = get_thread_manager()
    with set_request_context_lambda(event):
        try:
            threads = tm.list_threads(user_id=user_id, status=status, limit=limit, offset=offset)
            data = [t.model_dump() for t in threads]
            return success_response({
                "user_id": user_id,
                "threads": data,
                "count": len(data),
                "limit": limit,
                "offset": offset,
            })
        except Exception as e:
            return error_response(500, f"Error listing threads: {e}")
