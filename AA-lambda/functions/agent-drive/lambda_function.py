"""
agent-drive Lambda handler.

Dispatches via `DRIVE_TOOLS` from `api.py`. Drive tool funcs take
`(inputs: dict, credentials_dict: dict)` directly (NOT keyword-unpacked).

Lambda specifics:
- `tempfile.mkdtemp` automatically uses `/tmp` because Lambda sets
  `TMPDIR=/tmp` by default. The `download_file_tool` path is therefore safe.
- This Lambda is built as an OCI/Docker image (heavy deps: pdfplumber, pymupdf, pandas).
"""

from __future__ import annotations

import json
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Belt-and-braces — Lambda already sets TMPDIR=/tmp but be explicit so any
# library that reads os.environ directly (instead of going through tempfile)
# picks the same value.
os.environ.setdefault("TMPDIR", "/tmp")

from api import DRIVE_TOOLS, CredentialsDict


def lambda_handler(event, context):
    body = json.loads(event["body"]) if isinstance(event.get("body"), str) else event
    tool = body.get("tool")
    inputs = body.get("inputs") or {}
    creds = dict(body.get("credentials_dict") or {})

    creds.pop("_user_id", None)
    creds.pop("_jwt", None)
    creds.pop("_request_id", None)

    if not tool:
        return _err(400, "tool is required")
    if not creds:
        return _err(401, "credentials_dict is required for Drive operations")
    tool_func = DRIVE_TOOLS.get(tool)
    if not tool_func:
        return _err(400, f"Unknown tool: {tool}. Available: {list(DRIVE_TOOLS.keys())}")

    # Wrap raw dict in the Pydantic ``CredentialsDict`` (same pattern as
    # agent-sheets). Drive tool funcs use attribute access:
    # ``credentials_dict.access_token``, ``.client_id``, etc.
    try:
        creds_obj = CredentialsDict(**creds)
    except Exception as e:
        return _err(401, f"credentials_dict validation failed: {e}")

    try:
        result = tool_func(inputs, creds_obj)
        if not isinstance(result, dict):
            result = {"output": result, "success": True}
        if "success" not in result:
            result["success"] = not bool(result.get("error"))
        return {"statusCode": 200, "body": json.dumps({"output": result, **result}, default=str)}
    except Exception as e:
        traceback.print_exc()
        return _err(500, str(e))


def _err(code, msg, **extra):
    payload = {"success": False, "error": msg}
    payload.update(extra)
    return {"statusCode": code, "body": json.dumps(payload, default=str)}
