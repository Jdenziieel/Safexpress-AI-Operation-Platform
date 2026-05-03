"""
Lambda-runtime helpers shared across every supervisor-* Lambda function.

Provides:
  - parse_body(event)             — handle both stringified-body and direct dict
  - get_user_from_authorizer(event) — extract user_id / role / email / jwt
  - success_response, error_response, options_response
  - quota_check / quota_report     — sync urllib wrappers (Phase 2.5.B/C)
  - set_request_context_lambda     — try/finally context manager that sets
    request context AND drains pending quota reports on exit (Phase 2.5.C)
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
from contextlib import contextmanager
from typing import Any, Dict, Optional, Tuple


# ----------------------------------------------------------------------
# CORS / response shaping
# ----------------------------------------------------------------------

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Requested-With",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
}


def options_response() -> Dict[str, Any]:
    return {
        "statusCode": 200,
        "headers": CORS_HEADERS,
        "body": "",
    }


def success_response(body: Any, status_code: int = 200) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body, default=str) if not isinstance(body, str) else body,
    }


def error_response(
    status_code: int, message: str, **extra
) -> Dict[str, Any]:
    payload = {"success": False, "error": message}
    payload.update(extra)
    return {
        "statusCode": status_code,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


def llm_error_response(exc) -> Dict[str, Any]:
    """Mirror source ``main.py:llm_exception_handler`` \u2014 returns a JSON
    response carrying the structured ``is_llm_error: True`` flag the FE
    uses to render its ``LLMErrorModal``. Pass the raised
    ``LLMServiceException``; this function reads ``status_code`` and
    ``to_dict()`` off it.

    Falls back to a generic 500 if the exception lacks the expected
    interface (e.g. a different exception subclass slipped through)."""
    try:
        status = getattr(exc, "status_code", 500) or 500
        body = exc.to_dict() if hasattr(exc, "to_dict") else {
            "is_llm_error": True,
            "user_message": str(exc),
            "status_code": status,
        }
    except Exception:
        status = 500
        body = {
            "is_llm_error": True,
            "user_message": str(exc),
            "status_code": status,
        }
    return {
        "statusCode": int(status),
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


# ----------------------------------------------------------------------
# Request parsing
# ----------------------------------------------------------------------


def parse_body(event: Dict[str, Any]) -> Dict[str, Any]:
    body = event.get("body")
    if body is None:
        return {}
    if isinstance(body, dict):
        return body
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8")
    if isinstance(body, str):
        body = body.strip()
        if not body:
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"_raw": body}
    return {}


def get_user_from_authorizer(event: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Pulls user identity from the Lambda authorizer's `requestContext.authorizer.claims`
    (works for the `jwt-api-authorizer` set up by the kb stack).

    Per ``lambda_deployment_reference.md`` §3.1 the JWT payload itself uses
    the key ``gmail`` (not ``email``); the authorizer output sometimes
    surfaces it as ``email`` and sometimes as ``gmail`` depending on which
    auth-lambda function rebuilt the context. We accept either and treat
    them as the same value — the authenticated user's primary Google
    email, which is also the partition key of the ``SocialTokens`` table.
    """
    rc = event.get("requestContext") or {}
    authz = rc.get("authorizer") or {}
    # Some authorizers nest under "claims", others put fields directly under authorizer
    claims = authz.get("claims") or authz.get("lambda") or authz
    user_id = (
        claims.get("user_id")
        or claims.get("sub")
        or claims.get("userId")
        or claims.get("uid")
    )
    role = claims.get("role") or claims.get("user_role")
    # ``gmail`` is the canonical claim name in this stack; ``email`` is a
    # backwards-compat alias some downstream functions emit.
    email = (
        claims.get("gmail")
        or claims.get("email")
        or claims.get("user_email")
    )
    jwt = _extract_jwt(event)
    return {
        "user_id": user_id,
        "role": role,
        "email": email,
        "jwt": jwt,
    }


def _extract_jwt(event: Dict[str, Any]) -> Optional[str]:
    """Pulls the bearer token from headers / query string."""
    headers = event.get("headers") or {}
    headers_lower = {k.lower(): v for k, v in headers.items()}
    auth = headers_lower.get("authorization")
    if auth:
        parts = auth.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return auth.strip()

    qs = event.get("queryStringParameters") or {}
    if qs.get("token"):
        return qs["token"]
    return None


def decode_jwt_payload_unsafe(jwt: Optional[str]) -> Dict[str, Any]:
    """Decode a JWT *payload* without verifying the signature.

    Safe to use here because the API Gateway authorizer already validated
    the signature + expiry before the request reached this Lambda, so we're
    only re-reading already-trusted claims (e.g. ``gmail``) that the
    authorizer happened to drop from its output.

    Used by ``supervisor-ws-chat`` to recover the user's gmail from the
    JWT stashed on the WebSocket connection record at $connect time —
    the kb-stack's $connect lambda doesn't write ``user_email`` into the
    connection row, but the JWT it stores does carry the ``gmail`` claim.

    Returns ``{}`` for any malformed input rather than raising.
    """
    if not jwt or not isinstance(jwt, str):
        return {}
    parts = jwt.split(".")
    if len(parts) < 2:
        return {}
    payload_b64 = parts[1]
    # JWT uses base64url with no padding. Re-pad to make stdlib b64 happy.
    pad = "=" * (-len(payload_b64) % 4)
    try:
        import base64

        raw = base64.urlsafe_b64decode(payload_b64 + pad)
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def get_path_param(event: Dict[str, Any], name: str) -> Optional[str]:
    pp = event.get("pathParameters") or {}
    val = pp.get(name)
    if val is None:
        return None
    try:
        from urllib.parse import unquote
        return unquote(val)
    except Exception:
        return val


def get_query_param(event: Dict[str, Any], name: str, default: Optional[str] = None) -> Optional[str]:
    qs = event.get("queryStringParameters") or {}
    return qs.get(name, default)


# ----------------------------------------------------------------------
# Quota service — sync urllib wrappers (Phase 2.5.B/C)
# ----------------------------------------------------------------------

QUOTA_BASE = os.environ.get("QUOTA_SERVICE_URL", "").rstrip("/")
QUOTA_ENABLED = os.environ.get("QUOTA_ENABLED", "true").lower() == "true"
QUOTA_TIMEOUT = float(os.environ.get("QUOTA_TIMEOUT_SECONDS", "5"))


def quota_check(
    user_id: Optional[str],
    jwt: Optional[str],
    estimated_tokens: int = 2000,
    operation: str = "tool_call",
    service: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Pre-flight quota check. Returns (allowed, response_dict).
    Fail-open: returns (True, {}) on any service error per QUOTA_SERVICE_REFERENCE §2.4."""
    if not QUOTA_ENABLED or not user_id or not QUOTA_BASE:
        return True, {}

    payload = {
        "user_id": user_id,
        "estimated_tokens": int(estimated_tokens),
        "operation": operation,
        "service": service or os.environ.get("SERVICE_NAME", "supervisor"),
    }
    headers = {"Content-Type": "application/json"}
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"

    req = urllib.request.Request(
        f"{QUOTA_BASE}/quota/check",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=QUOTA_TIMEOUT) as r:
            data = json.loads(r.read())
            return bool(data.get("allowed", True)), data
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {"status_code": e.code}
        # 404 -> deactivated user
        if e.code == 404:
            body["user_deactivated"] = True
            return False, body
        # 429 / 403 -> quota exceeded
        if e.code in (429, 403):
            body["quota_exceeded"] = True
            return False, body
        return True, {}
    except Exception as e:
        print(f"[quota_check] failed: {e}")
        return True, {}


def quota_report(
    user_id: Optional[str],
    jwt: Optional[str],
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    operation: str = "tool_call",
    service: Optional[str] = None,
    request_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    success: bool = True,
    error: Optional[str] = None,
) -> bool:
    """Synchronous post-LLM token report. Best-effort — never raises."""
    if not QUOTA_ENABLED or not user_id or not QUOTA_BASE:
        return False

    payload = {
        "user_id": user_id,
        "service": service or os.environ.get("SERVICE_NAME", "supervisor"),
        "operation": operation,
        "model": model,
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "cached_tokens": int(cached_tokens or 0),
        "duration_ms": duration_ms,
        "success": bool(success),
        "error": error,
        "request_id": request_id,
    }
    headers = {"Content-Type": "application/json"}
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"

    req = urllib.request.Request(
        f"{QUOTA_BASE}/quota/report",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    try:
        urllib.request.urlopen(req, timeout=QUOTA_TIMEOUT).read()
        return True
    except Exception as e:
        print(f"[quota_report] failed: {e}")
        return False


# ----------------------------------------------------------------------
# Persistence backend swap — Docker Lambdas only (no brain edit needed)
# ----------------------------------------------------------------------


def install_persistence_backend() -> None:
    """When ``PERSISTENCE_BACKEND=dynamodb``, replaces the ``thread_manager``
    and ``log_storage`` modules in ``sys.modules`` so that subsequent
    ``from thread_manager import ThreadManager`` / ``from log_storage import
    LogStorage`` imports inside the brain (conversational_agent.py,
    supervisor_agent.py, routes/*) resolve to the DynamoDB-backed
    implementations.

    Idempotent. Safe to call before importing the brain.
    """
    if os.environ.get("PERSISTENCE_BACKEND", "sqlite").lower() != "dynamodb":
        return
    import sys

    try:
        import dynamodb_thread_manager  # type: ignore

        sys.modules["thread_manager"] = dynamodb_thread_manager
    except Exception as e:
        print(f"[install_persistence_backend] thread_manager swap failed: {e}")

    try:
        import dynamodb_log_storage  # type: ignore

        sys.modules["log_storage"] = dynamodb_log_storage
    except Exception as e:
        print(f"[install_persistence_backend] log_storage swap failed: {e}")


# ----------------------------------------------------------------------
# Lambda-friendly request context manager (Phase 2.5.C)
# ----------------------------------------------------------------------


@contextmanager
def set_request_context_lambda(event: Dict[str, Any], **overrides):
    """Wrap every Lambda handler body with this. It:
      1. Builds a request_id (uuid)
      2. Pulls user_id + jwt from the event authorizer
      3. Calls logging_config.set_request_context(jwt=...)
      4. On exit, drains flush_pending_quota_reports(timeout=3.0)

    Usage:
        def lambda_handler(event, context):
            with set_request_context_lambda(event) as ctx:
                user_id = ctx["user_id"]
                ...
    """
    # Lazy import — keeps lambda_helpers usable from sub-agents that don't bring
    # the full brain along.
    try:
        from logging_config import (
            set_request_context,
            clear_request_context,
            flush_pending_quota_reports,
        )
    except ImportError:
        # Sub-agent path — no logging_config available.
        set_request_context = None
        clear_request_context = None
        flush_pending_quota_reports = None

    user = get_user_from_authorizer(event)
    user_id = overrides.get("user_id", user["user_id"])
    jwt = overrides.get("jwt", user["jwt"])
    user_email = overrides.get("user_email", user["email"])
    thread_id = overrides.get("thread_id")
    conversation_id = overrides.get("conversation_id")

    request_id = None
    if set_request_context is not None:
        # ``user_email`` is propagated through ``logging_config._user_email_var``
        # so ``config.get_google_credentials()`` can resolve the right
        # SocialTokens row downstream without changing every brain call site.
        request_id = set_request_context(
            request_id=overrides.get("request_id"),
            user_id=user_id,
            jwt=jwt,
            user_email=user_email,
            thread_id=thread_id,
            conversation_id=conversation_id,
        )

    ctx = {
        "user_id": user_id,
        "role": user["role"],
        "email": user_email,
        "jwt": jwt,
        "request_id": request_id,
        "started_at": time.time(),
    }
    try:
        yield ctx
    finally:
        if flush_pending_quota_reports is not None:
            try:
                flush_pending_quota_reports(timeout=3.0)
            except Exception as e:
                print(f"[set_request_context_lambda] flush failed: {e}")
        if clear_request_context is not None:
            try:
                clear_request_context()
            except Exception:
                pass
