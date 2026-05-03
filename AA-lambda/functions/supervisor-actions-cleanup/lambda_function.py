"""supervisor-actions-cleanup — POST /actions/cleanup"""
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
    parse_body,
    get_query_param,
    set_request_context_lambda,
)
from shared.persistence_factory import get_log_storage


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    body = parse_body(event)
    expire_minutes = int(body.get("expire_minutes") or get_query_param(event, "expire_minutes", "5") or 5)

    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            cleaned = storage.cleanup_expired_pending_actions(expire_minutes=expire_minutes)
            remaining = storage.get_pending_actions(status="pending")
            return success_response({
                "cleaned_from_db": cleaned,
                "remaining_pending": len(remaining),
            })
        except Exception as e:
            return error_response(500, f"cleanup failed: {e}")
