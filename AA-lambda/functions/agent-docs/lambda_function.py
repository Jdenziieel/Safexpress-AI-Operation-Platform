"""
agent-docs Lambda handler.

Reuses the existing FastAPI `execute_task` function from `api.py` by
constructing an `AgentTaskRequest` and invoking it via `asyncio.run`.

Two dispatch paths in `api.py`:
- `request.tool` set → direct TOOL_MAP dispatch, no LLM (the supervisor's
  only path; this is what `agent_capabilities_v3.py` declares for every docs
  tool).
- `request.task` set → LangChain ReAct agent (LLM-backed). Currently dead
  code from the supervisor's POV but preserved here for symmetry.

Quota integration: if a future supervisor flow ever sends `task`, the
caller is expected to provide `_user_id` / `_jwt` / `_request_id` inside
`credentials_dict`. We strip those before forwarding to keep the existing
agent contract unchanged. The actual quota check + report would happen
inside the LangChain branch via `shared/logging_config.py`. For the current
TOOL_MAP path, all docs tools are deterministic Google API calls — zero
LLM cost — so no per-tool quota wrapping is needed here.

This Lambda is built as an OCI/Docker image (heavy deps: langchain,
langchain-openai, langgraph for the dead LangChain path; google-api-python-
client for the live tools).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

os.environ.setdefault("TMPDIR", "/tmp")

from api import AgentTaskRequest, execute_task


def lambda_handler(event, context):
    body = json.loads(event["body"]) if isinstance(event.get("body"), str) else event
    creds = dict(body.get("credentials_dict") or {})

    user_id = creds.pop("_user_id", None)
    jwt = creds.pop("_jwt", None)
    request_id = creds.pop("_request_id", None)

    payload = {
        "task": body.get("task"),
        "tool": body.get("tool"),
        "instruction": body.get("instruction"),
        "inputs": body.get("inputs") or {},
        "expected_output": body.get("expected_output"),
        "credentials_dict": creds,
    }
    payload = {k: v for k, v in payload.items() if v is not None or k in ("inputs", "credentials_dict")}

    try:
        request_obj = AgentTaskRequest(**payload)
    except Exception as e:
        traceback.print_exc()
        return _err(400, f"invalid request: {e}")

    try:
        # Optional: stash request-scoped quota context for the (currently dead)
        # LangChain branch. Imported lazily so a missing shared/logging_config
        # never breaks the live tool-dispatch path.
        if request_obj.task and (user_id or jwt):
            try:
                from shared.logging_config import set_request_context  # type: ignore

                with set_request_context(
                    user_id=user_id,
                    request_id=request_id,
                    jwt=jwt,
                ):
                    response = asyncio.run(execute_task(request_obj))
            except Exception:
                response = asyncio.run(execute_task(request_obj))
        else:
            response = asyncio.run(execute_task(request_obj))

        if hasattr(response, "model_dump"):
            response_dict = response.model_dump()
        elif hasattr(response, "dict"):
            response_dict = response.dict()
        else:
            response_dict = dict(response) if isinstance(response, dict) else {"raw": response}

        result_payload = response_dict.get("result") or {}
        merged = {
            "success": response_dict.get("success", False),
            "result": result_payload,
            "raw_response": response_dict.get("raw_response"),
            "error": response_dict.get("error"),
            "output": result_payload,
        }
        return {"statusCode": 200, "body": json.dumps(merged, default=str)}
    except Exception as e:
        traceback.print_exc()
        return _err(500, str(e))


def _err(code, msg, **extra):
    payload = {"success": False, "error": msg}
    payload.update(extra)
    return {"statusCode": code, "body": json.dumps(payload, default=str)}
