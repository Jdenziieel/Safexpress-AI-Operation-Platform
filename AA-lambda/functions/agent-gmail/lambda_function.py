"""
agent-gmail Lambda handler.

Dispatches inbound `(tool, inputs, credentials_dict)` payloads to the gmail
implementation functions in `tools.py`. Mirrors the FastAPI body-rewrite path
in `api.py:103-137` so behavior is byte-for-byte identical to the local agent.

Phase 2.5.B: wraps the body-rewrite LLM call with quota check + report.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback

# Local import path so the function package can resolve siblings
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from tools import (
    _search_emails_impl,
    _send_email_impl,
    _send_email_with_attachments_impl,
    _reply_to_email_impl,
    _forward_email_impl,
    _create_draft_email_impl,
    _create_draft_email_with_attachment_impl,
    _send_draft_email_impl,
    _search_drafts_impl,
    _get_thread_conversation_impl,
    _add_label_impl,
    _remove_label_impl,
    _download_attachment_impl,
    _search_emails_with_delivery_order_attachments_impl,
    _save_attachment_metadata_impl,
)

TOOL_MAP = {
    "search_emails": _search_emails_impl,
    "send_email": _send_email_impl,
    "send_email_with_attachment": _send_email_with_attachments_impl,
    "reply_to_email": _reply_to_email_impl,
    "forward_email": _forward_email_impl,
    "create_draft_email": _create_draft_email_impl,
    "create_draft_email_with_attachment": _create_draft_email_with_attachment_impl,
    "send_draft_email": _send_draft_email_impl,
    "search_drafts": _search_drafts_impl,
    "get_thread_conversation": _get_thread_conversation_impl,
    "add_label": _add_label_impl,
    "remove_label": _remove_label_impl,
    "download_attachment": _download_attachment_impl,
    "search_emails_with_delivery_order_attachments": _search_emails_with_delivery_order_attachments_impl,
    "save_attachment_metadata": _save_attachment_metadata_impl,
}

LLM_TOOLS = {
    "send_draft_email",
    "reply_to_email",
    "forward_email",
    "send_email",
    "create_draft_email",
    "create_draft_email_with_attachment",
}

QUOTA_BASE = (os.environ.get("QUOTA_SERVICE_URL") or "").rstrip("/")
QUOTA_ENABLED = os.environ.get("QUOTA_ENABLED", "true").lower() == "true"
SERVICE_NAME = os.environ.get("SERVICE_NAME", "supervisor-agent-gmail")
TRANSFORM_MODEL = os.environ.get("GMAIL_TRANSFORM_MODEL", "gpt-4o")


# ----------------------------------------------------------------------
# Quota helpers (sync urllib — no langchain dependency in this file)
# ----------------------------------------------------------------------

def _quota_check(user_id, jwt, estimated_tokens=300):
    if not QUOTA_ENABLED or not user_id or not QUOTA_BASE:
        return True, {}
    import urllib.request, urllib.error
    payload = {
        "user_id": user_id,
        "estimated_tokens": int(estimated_tokens),
        "service": SERVICE_NAME,
        "operation": "body_rewrite",
    }
    headers = {"Content-Type": "application/json"}
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"
    req = urllib.request.Request(
        f"{QUOTA_BASE}/quota/check",
        data=json.dumps(payload).encode(),
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
            return bool(data.get("allowed", True)), data
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {}
        if e.code in (404, 403, 429):
            body["quota_exceeded"] = e.code != 404
            body["user_deactivated"] = e.code == 404
            return False, body
        return True, {}
    except Exception as e:
        print(f"[gmail.quota_check] failed: {e}")
        return True, {}


def _quota_report(user_id, jwt, model, input_tokens, output_tokens, **extra):
    if not QUOTA_ENABLED or not user_id or not QUOTA_BASE:
        return
    import urllib.request
    payload = {
        "user_id": user_id,
        "service": SERVICE_NAME,
        "operation": extra.get("operation", "body_rewrite"),
        "model": model,
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "cached_tokens": int(extra.get("cached_tokens") or 0),
        "duration_ms": extra.get("duration_ms"),
        "success": bool(extra.get("success", True)),
        "error": extra.get("error"),
        "request_id": extra.get("request_id"),
    }
    headers = {"Content-Type": "application/json"}
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"
    try:
        req = urllib.request.Request(
            f"{QUOTA_BASE}/quota/report",
            data=json.dumps(payload).encode(),
            method="POST",
            headers=headers,
        )
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as e:
        print(f"[gmail.quota_report] failed: {e}")


# ----------------------------------------------------------------------
# Body-rewrite helper — extracted from gmail-agent/api.py:103-137
# Same prompt, same model — structural refactor only.
# Returns (transformed_inputs, llm_usage_dict | None)
# ----------------------------------------------------------------------

def _maybe_transform_body(tool, inputs):
    """Mirror the FastAPI body-rewrite block in api.py."""
    if tool not in LLM_TOOLS:
        return dict(inputs), None
    transformed = dict(inputs)
    body_field = None
    original_content = ""
    if "body" in transformed:
        body_field = "body"
        original_content = transformed["body"]
    elif "reply_body" in transformed:
        body_field = "reply_body"
        original_content = transformed["reply_body"]
    elif "forward_message" in transformed:
        body_field = "forward_message"
        original_content = transformed["forward_message"]

    if not body_field or not original_content:
        return transformed, None

    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=TRANSFORM_MODEL,
        temperature=0,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
    )
    transform_prompt = (
        "Add this signature to the end of the email body:\n\n"
        "--- \nThis is written by Assistant Agent\n\n"
        f"Original body:\n{original_content}\n\n"
        "Return ONLY the modified body text, nothing else."
    )
    print(f"[agent-gmail] Using LLM to transform email {body_field}...")
    started = time.time()
    response = llm.invoke(transform_prompt)
    transformed[body_field] = response.content.strip()

    # Pull token usage off the langchain response — same shape as api.py used
    in_toks = 0
    out_toks = 0
    cached = 0
    md = getattr(response, "response_metadata", None) or {}
    tu = md.get("token_usage") or {}
    in_toks = int(tu.get("prompt_tokens") or 0)
    out_toks = int(tu.get("completion_tokens") or 0)
    cached = int(((tu.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)

    return transformed, {
        "in": in_toks,
        "out": out_toks,
        "cached": cached,
        "duration_ms": int((time.time() - started) * 1000),
    }


# ----------------------------------------------------------------------
# Handler
# ----------------------------------------------------------------------

def lambda_handler(event, context):
    body = json.loads(event["body"]) if isinstance(event.get("body"), str) else event
    tool = body.get("tool")
    inputs = body.get("inputs") or {}
    creds = dict(body.get("credentials_dict") or {})

    user_id = creds.pop("_user_id", None)
    jwt = creds.pop("_jwt", None)
    request_id = creds.pop("_request_id", None)

    started = time.time()

    if not tool:
        return _err(400, "tool is required")
    if tool not in TOOL_MAP:
        return _err(400, f"Unknown tool: {tool}")

    impl = TOOL_MAP[tool]

    # Quota pre-flight only when LLM is going to fire AND a body field is present
    will_use_llm = tool in LLM_TOOLS and any(
        k in inputs for k in ("body", "reply_body", "forward_message")
    )
    if will_use_llm and user_id:
        allowed, qdata = _quota_check(user_id, jwt, estimated_tokens=300)
        if not allowed:
            return _err(
                429 if qdata.get("quota_exceeded") else 403,
                qdata.get("error", "Quota exceeded"),
                quota=qdata,
            )

    try:
        transformed, llm_usage = _maybe_transform_body(tool, inputs)
        try:
            output = impl(**transformed, credentials_dict=creds)
        finally:
            if llm_usage:
                _quota_report(
                    user_id,
                    jwt,
                    model=TRANSFORM_MODEL,
                    input_tokens=llm_usage["in"],
                    output_tokens=llm_usage["out"],
                    cached_tokens=llm_usage.get("cached", 0),
                    operation=tool,
                    request_id=request_id,
                    duration_ms=llm_usage.get("duration_ms"),
                )

        return {
            "statusCode": 200,
            "body": json.dumps({"output": output, "success": True, **(output if isinstance(output, dict) else {})}, default=str),
        }
    except Exception as e:
        traceback.print_exc()
        return _err(500, str(e))


def _err(code, msg, **extra):
    payload = {"success": False, "error": msg}
    payload.update(extra)
    return {"statusCode": code, "body": json.dumps(payload, default=str)}
