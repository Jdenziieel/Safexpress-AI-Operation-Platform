"""
agent-mapping Lambda handler.

Dispatches via `TOOL_REGISTRY` from `mapping_agent_api.py`. The smart_column_mapping
tool calls OpenAI internally — quota check + report happens inside
`smart_mapping_engine._openai_mapping` via the per-call context set
here on entry.

Built as an OCI/Docker image (heavy deps: pdfplumber, pymupdf, pandas, numpy).
"""

from __future__ import annotations

import json
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

os.environ.setdefault("TMPDIR", "/tmp")

from mapping_agent_api import TOOL_REGISTRY
from smart_mapping_engine import (
    set_quota_context,
    clear_quota_context,
    flush_quota_reports,
)


_TEMPLATE_TOOLS = {
    "save_mapping_template",
    "load_mapping_template",
    "list_mapping_templates",
}


def lambda_handler(event, context):
    body = json.loads(event["body"]) if isinstance(event.get("body"), str) else event
    tool = body.get("tool")
    inputs = dict(body.get("inputs") or {})
    creds = dict(body.get("credentials_dict") or {})

    user_id = creds.pop("_user_id", None)
    jwt = creds.pop("_jwt", None)
    request_id = creds.pop("_request_id", None)

    if not tool:
        return _err(400, "tool is required")
    tool_info = TOOL_REGISTRY.get(tool)
    if not tool_info:
        return _err(400, f"Unknown tool: {tool}. Available: {list(TOOL_REGISTRY.keys())}")

    # Forward user_id only into the 3 template tools — the others (parse_file,
    # smart_column_mapping, etc.) are stateless and don't need it. Forwarding
    # everywhere would force every tool signature to accept **kwargs which we
    # explicitly avoid (see Bug E in system-architecture.mdc — silent kwarg
    # drops are a documented failure mode).
    if tool in _TEMPLATE_TOOLS and user_id and "user_id" not in inputs:
        inputs["user_id"] = user_id

    set_quota_context(user_id=user_id, jwt=jwt, request_id=request_id)
    try:
        result = tool_info["func"](**inputs)
        if not isinstance(result, dict):
            result = {"output": result, "success": True}
        is_no_results = bool(result.get("no_results"))
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "success": result.get("success", False),
                    "result": result if (result.get("success") or is_no_results) else None,
                    "error": result.get("error") if not result.get("success") else None,
                    "no_results": is_no_results or None,
                    "output": result,
                },
                default=str,
            ),
        }
    except Exception as e:
        traceback.print_exc()
        return _err(500, str(e))
    finally:
        try:
            flush_quota_reports()
        finally:
            clear_quota_context()


def _err(code, msg, **extra):
    payload = {"success": False, "error": msg}
    payload.update(extra)
    return {"statusCode": code, "body": json.dumps(payload, default=str)}
