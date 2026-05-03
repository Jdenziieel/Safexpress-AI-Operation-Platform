"""supervisor-get-messages — GET /threads/{thread_id}/messages"""
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
    get_path_param,
    get_query_param,
    set_request_context_lambda,
)
from shared.persistence_factory import get_thread_manager


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    thread_id = get_path_param(event, "thread_id")
    if not thread_id:
        return error_response(400, "thread_id is required")

    try:
        limit = int(get_query_param(event, "limit") or 50)
        offset = int(get_query_param(event, "offset") or 0)
    except (TypeError, ValueError):
        return error_response(400, "limit and offset must be integers")

    tm = get_thread_manager()
    with set_request_context_lambda(event):
        try:
            messages = tm.get_messages(thread_id, limit=limit, offset=offset)
            if messages is None:
                return error_response(404, f"Thread {thread_id} not found")
            return success_response({
                "thread_id": thread_id,
                "messages": messages,
                "count": len(messages),
                "limit": limit,
                "offset": offset,
            })
        except Exception as e:
            return error_response(500, f"Error getting messages: {e}")
