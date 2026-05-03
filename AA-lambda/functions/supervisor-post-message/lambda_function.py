"""supervisor-post-message — POST /threads/{thread_id}/messages

DEPRECATED: returns 410 Gone. Chat traffic now flows over the existing
WebSocket API via the `sendAgentMessage` action. This shim exists for any
older client that still hits the REST endpoint so they receive a clear
machine-readable signal to switch transport rather than a silent failure.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(_HERE, "shared")
for p in (_SHARED, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.lambda_helpers import options_response, CORS_HEADERS
import json


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()
    return {
        "statusCode": 410,
        "headers": {"Content-Type": "application/json", **CORS_HEADERS},
        "body": json.dumps({
            "error": "use_websocket",
            "ws_route": "sendAgentMessage",
            "detail": "POST /threads/{id}/messages is deprecated. Send chat traffic over the existing WebSocket using action='sendAgentMessage'.",
        }),
    }
