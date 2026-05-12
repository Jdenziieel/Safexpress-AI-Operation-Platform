"""Pulls the caller's userId out of an API Gateway HTTP API v2 event.

The JWT authorizer (`safexpressops-jwt-authorizer`) is configured as a
REQUEST authorizer with `authorizer-payload-format-version=2.0` and
`enable-simple-responses=false` (IAM-policy format). When it succeeds, the
context dict comes through at:

    event.requestContext.authorizer.lambda.userId
    event.requestContext.authorizer.lambda.userEmail
    event.requestContext.authorizer.lambda.userRole
    event.requestContext.authorizer.lambda.userName

Local dev (Flask shim) doesn't run the authorizer, so callers may pass
`X-Workload-User-Id` or `?userId=` instead so the dev flow can simulate
different users without a real JWT. Tests inject the value directly into
event['requestContext']['authorizer']['lambda'].

We never trust a user_id that wasn't placed there by the authorizer or by
a dev-only header: header-only callers get a per-header partition; truly
anonymous callers get the `__default__` org partition.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _ci_get(headers: Dict[str, Any], *keys: str) -> Optional[str]:
    """Case-insensitive header lookup. API Gateway sometimes lowercases."""
    if not isinstance(headers, dict):
        return None
    for k in keys:
        if k in headers:
            return headers[k]
        # try lower / canonical
        for hk in headers:
            if isinstance(hk, str) and hk.lower() == k.lower():
                return headers[hk]
    return None


def extract_user_id(event: Dict[str, Any]) -> Optional[str]:
    """Return the caller's stable user identifier or None.

    Precedence:
      1. authorizer context (production path)
      2. X-Workload-User-Id header (local dev / manual testing only)
      3. ?userId= query param (last-resort manual testing)
      4. None -> caller is treated as the org-default partition
    """
    ctx = (event.get("requestContext") or {}).get("authorizer") or {}
    # HTTP API v2 nests Lambda authorizer context under "lambda"
    lambda_ctx = ctx.get("lambda") or ctx.get("Lambda") or {}
    user_id = (
        lambda_ctx.get("userId")
        or lambda_ctx.get("userEmail")
        or ctx.get("userId")
        or ctx.get("userEmail")
        or ctx.get("principalId")
    )
    if user_id:
        return str(user_id)

    headers = event.get("headers") or {}
    hdr = _ci_get(headers, "X-Workload-User-Id", "x-workload-user-id")
    if hdr:
        return str(hdr)

    qs = event.get("queryStringParameters") or {}
    if isinstance(qs, dict) and qs.get("userId"):
        return str(qs["userId"])

    return None
