"""supervisor-actions-pending — GET /actions/pending (DEPRECATED stub).

Kept for backwards compatibility. Pending actions now flow through the chat
WebSocket path (Phase 4) instead of being polled via REST.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(_HERE, "shared")
for p in (_SHARED, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.lambda_helpers import success_response, options_response


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()
    return success_response({
        "pending_actions": [],
        "count": 0,
        "deprecated": True,
        "message": "Pending actions are now handled via chat conversation."
    })
