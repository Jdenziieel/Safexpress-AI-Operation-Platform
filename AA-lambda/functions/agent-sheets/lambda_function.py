"""
agent-sheets Lambda handler.

Dispatches via `TOOL_REGISTRY` from `sheets_agent_api.py` (where every entry
is `{"func": callable, "description": str}` and the func expects
`credentials_dict` injected into inputs — same shape as the FastAPI route).
"""

from __future__ import annotations

import json
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from sheets_agent_api import TOOL_REGISTRY, CredentialsDict


def lambda_handler(event, context):
    body = json.loads(event["body"]) if isinstance(event.get("body"), str) else event
    tool = body.get("tool")
    inputs = dict(body.get("inputs") or {})
    creds = dict(body.get("credentials_dict") or {})

    creds.pop("_user_id", None)
    creds.pop("_jwt", None)
    creds.pop("_request_id", None)

    if not tool:
        return _err(400, "tool is required")

    tool_info = TOOL_REGISTRY.get(tool)
    if not tool_info:
        return _err(400, f"Unknown tool: {tool}. Available: {list(TOOL_REGISTRY.keys())}")

    # Wrap raw dict in the Pydantic ``CredentialsDict`` so downstream tools
    # that do ``credentials_dict.access_token`` (attribute access) work
    # identically to the FastAPI path \u2014 Pydantic v2 auto-validates the
    # raw dict against the model schema.
    if creds:
        try:
            inputs["credentials_dict"] = CredentialsDict(**creds)
        except Exception as e:
            return _err(401, f"credentials_dict validation failed: {e}")
    else:
        inputs["credentials_dict"] = None

    try:
        result = tool_info["func"](**inputs)
        if not isinstance(result, dict):
            result = {"output": result, "success": True}
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "success": result.get("success", False),
                    "result": result if result.get("success") else None,
                    "error": result.get("error") if not result.get("success") else None,
                    "error_type": result.get("error_type") if not result.get("success") else None,
                    "output": result,
                },
                default=str,
            ),
        }
    except Exception as e:
        traceback.print_exc()
        return _err(500, str(e))


def _err(code, msg, **extra):
    payload = {"success": False, "error": msg}
    payload.update(extra)
    return {"statusCode": code, "body": json.dumps(payload, default=str)}
