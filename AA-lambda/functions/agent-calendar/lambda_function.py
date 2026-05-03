"""
agent-calendar Lambda handler.

Dispatches via `CALENDAR_TOOLS` from `api.py`. The calendar tools take
`(inputs: dict, credentials_dict: dict)` shape (NOT keyword-unpacking).
"""

from __future__ import annotations

import json
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from api import (
    list_events,
    create_event,
    update_event,
    delete_event,
    confirm_delete_event,
    list_calendars,
    create_calendar,
    rename_calendar,
    resolve_conflict,
    sanitize_inputs,
)

CALENDAR_TOOLS = {
    "list_events": list_events,
    "create_event": create_event,
    "update_event": update_event,
    "delete_event": delete_event,
    "confirm_delete_event": confirm_delete_event,
    "list_calendars": list_calendars,
    "create_calendar": create_calendar,
    "rename_calendar": rename_calendar,
    "resolve_conflict": resolve_conflict,
}


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
    tool_func = CALENDAR_TOOLS.get(tool)
    if not tool_func:
        return _err(400, f"Unknown tool: {tool}. Available: {list(CALENDAR_TOOLS.keys())}")

    try:
        sanitized = sanitize_inputs(inputs)
        result = tool_func(sanitized, credentials_dict=creds or None)
        # Mirror api.py:execute_task return shape
        if isinstance(result, dict) and "success" not in result:
            result["success"] = not bool(result.get("error"))
        return {"statusCode": 200, "body": json.dumps({"output": result, **(result if isinstance(result, dict) else {"success": True})}, default=str)}
    except Exception as e:
        traceback.print_exc()
        return _err(500, str(e))


def _err(code, msg, **extra):
    payload = {"success": False, "error": msg}
    payload.update(extra)
    return {"statusCode": code, "body": json.dumps(payload, default=str)}
