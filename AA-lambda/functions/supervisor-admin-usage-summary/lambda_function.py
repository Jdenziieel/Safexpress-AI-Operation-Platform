"""supervisor-admin-usage-summary — GET /admin/usage/summary"""
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
    set_request_context_lambda,
)
from shared.persistence_factory import get_log_storage


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            return success_response(storage.get_usage_summary())
        except Exception as e:
            return error_response(500, f"Error retrieving usage summary: {e}")
