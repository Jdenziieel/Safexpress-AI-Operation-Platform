"""supervisor-post-message-upload — POST /threads/{thread_id}/messages/upload

DEPRECATED: returns 410 Gone. The frontend should upload the file directly
to S3 via a presigned PUT (issued by the create-with-upload pre-flight) and
then send the chat message over the WebSocket using the `sendAgentMessage`
action with the s3_key in the payload.
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
            "detail": "POST /threads/{id}/messages/upload is deprecated. Upload the file via presigned URL, then send the message over the WebSocket using action='sendAgentMessage' with the s3_key field set.",
        }),
    }
