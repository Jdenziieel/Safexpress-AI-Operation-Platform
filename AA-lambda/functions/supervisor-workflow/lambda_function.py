"""supervisor-workflow — POST /workflow (Docker)

Direct workflow invocation. The user posts ``{"input": "...", "execution_mode":
"standard"}`` and the supervisor → orchestrator runs to completion (or pauses).

This is the diagnostic / programmatic entrypoint — the chat UI flows through
``supervisor-ws-chat`` instead so progress can be streamed. Kept here for
parity with the original FastAPI route.
"""
from __future__ import annotations

import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(_HERE, "shared")
for p in (_SHARED, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.lambda_helpers import (  # noqa: E402
    install_persistence_backend,
    success_response,
    error_response,
    llm_error_response,
    options_response,
    parse_body,
    set_request_context_lambda,
    quota_check,
)

install_persistence_backend()


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    body = parse_body(event)
    user_input = body.get("input")
    if not user_input or not isinstance(user_input, str) or not user_input.strip():
        return error_response(400, "input is required (non-empty string)")

    execution_mode = body.get("execution_mode") or "standard"
    context_overrides = body.get("context_overrides") or None
    if context_overrides is not None and not isinstance(context_overrides, dict):
        return error_response(400, "context_overrides must be an object")

    with set_request_context_lambda(event) as ctx:
        ok, info = quota_check(
            user_id=ctx["user_id"], jwt=ctx["jwt"],
            estimated_tokens=4000, operation="workflow_direct",
        )
        if not ok:
            msg = (info or {}).get("message") or "Token quota exceeded"
            return error_response(429, msg, **{k: v for k, v in (info or {}).items() if k != "allowed"})

        try:
            from routes.workflow import run_workflow  # type: ignore
        except Exception as e:
            traceback.print_exc()
            return error_response(500, f"Brain import failed: {e}")

        try:
            result = run_workflow(user_input, context_overrides=context_overrides, execution_mode=execution_mode)
            payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
            return success_response(payload)
        except Exception as e:
            try:
                from llm_error_handler import LLMServiceException, handle_llm_error, is_llm_error  # type: ignore

                if isinstance(e, LLMServiceException):
                    return llm_error_response(e)
                if is_llm_error(e):
                    # Source ``execute_workflow`` wraps unhandled LLM-shaped
                    # errors into LLMServiceException via handle_llm_error
                    # before returning. Mirror that here.
                    err = handle_llm_error(e, context="Workflow Execution")
                    return llm_error_response(LLMServiceException(err))
            except Exception:
                pass
            traceback.print_exc()
            return error_response(500, f"Workflow execution failed: {e}")
