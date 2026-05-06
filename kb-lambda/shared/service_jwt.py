"""
Service-to-service JWT minter for kb-lambda → quota service calls.

WHY THIS EXISTS
---------------
The `/api/quota/*` routes are JWT-gated by the `jwt-api-authorizer` Lambda.
For REST handlers we *could* forward the user's inbound `Authorization`
header, but that breaks two ways:

  1. WebSocket handlers (e.g. `ws_chat_stream`) don't carry the user's
     JWT past the `$connect` handshake — there's nothing to forward on
     subsequent `sendMessage` events.
  2. Some quota routes (`/quota/report`, `/quota/usage`) require role
     `admin` or `manager`; a regular `user` JWT would 403.

The clean fix: every internal kb-lambda → quota call mints its own
short-lived HS256 JWT signed with the same `JWT_SECRET_KEY` the authorizer
uses to verify user tokens. From the authorizer's perspective it's an
ordinary admin-role JWT; from ours it's just "log in as ourselves".

DESIGN NOTES
------------
* Pure stdlib (`hmac`, `hashlib`, `base64`, `json`) — adding PyJWT to every
  kb-lambda Docker image would mean rebuilding all of them just for this.
  HS256 is trivial to implement directly; ~30 LOC.
* TTL is 60s. The longest internal call (PDF parse → /quota/report) is
  well under a second; 60s is a comfortable buffer for clock skew without
  giving a leaked token any meaningful useful life.
* `role='admin'` so the token can hit any `/api/quota/*` path the
  authorizer's `ROLE_PERMISSIONS` map gates. The body's `user_id` (the
  end user being billed) is independent of the JWT's `user_id` (the
  calling service).
* When `JWT_SECRET_KEY` is missing we return an empty token. Callers
  that send `Authorization: Bearer ` (empty token) will get a clean 401
  from the authorizer — matched by `raise_for_status()` so misconfig is
  loud, not silent.

USAGE
-----
    from shared.service_jwt import service_auth_headers

    response = client.post(
        f"{QUOTA_SERVICE_URL}/quota/report",
        json={...},
        headers=service_auth_headers(),
    )
    response.raise_for_status()
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

# Same env var name as the authorizer Lambda — set this on every kb-lambda
# function that calls /api/quota/*. Value MUST be byte-identical to what
# `jwt-api-authorizer` reads (a trailing space breaks HMAC verification).
JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', '')

# 60s is enough headroom for the slowest inter-Lambda call we make
# (~5s timeout on httpx) and tight enough that a leaked token is
# practically useless.
SERVICE_JWT_TTL_SECONDS = 60

# Stable principal label so admin dashboards and CloudTrail / authorizer
# logs can attribute traffic back to the calling service.
DEFAULT_SERVICE_PRINCIPAL = 'kb-lambda-service'


def _b64url(data) -> str:
    """Base64-URL encode without padding (RFC 7515 §2)."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def mint_service_jwt(principal: str = DEFAULT_SERVICE_PRINCIPAL) -> str:
    """
    Mint a short-lived HS256 JWT for a service-to-service /quota/* call.

    Returns empty string when `JWT_SECRET_KEY` is unset — callers should
    treat that as "no auth header" and rely on `response.raise_for_status()`
    to surface the resulting 401 in CloudWatch.

    Claims match what `authorizer/lambda_authorizer.py:decode_jwt` requires:
    `user_id`, `role`, `gmail`, `fullname`, `is_active`, `token_type='access'`,
    `iat`, `exp`. `role='admin'` allows the token to hit any /api/quota/* path
    the authorizer's `ROLE_PERMISSIONS` map gates.

    Args:
        principal: identifier baked into the JWT's `user_id` claim, useful
                   for distinguishing which calling Lambda generated the
                   token in authorizer logs. Defaults to `DEFAULT_SERVICE_PRINCIPAL`.
    """
    if not JWT_SECRET_KEY:
        return ''
    now = int(time.time())
    header = _b64url(json.dumps(
        {'alg': 'HS256', 'typ': 'JWT'}, separators=(',', ':')
    ))
    payload = _b64url(json.dumps({
        'user_id': principal,
        'role': 'admin',
        'gmail': f'{principal}@kb-lambda.internal',
        'fullname': f'{principal} (service)',
        'is_active': True,
        'token_type': 'access',
        'iat': now,
        'exp': now + SERVICE_JWT_TTL_SECONDS,
    }, separators=(',', ':')))
    signing_input = f'{header}.{payload}'.encode('ascii')
    signature = hmac.new(
        JWT_SECRET_KEY.encode('utf-8'), signing_input, hashlib.sha256
    ).digest()
    return f'{header}.{payload}.{_b64url(signature)}'


def service_auth_headers(principal: str = DEFAULT_SERVICE_PRINCIPAL) -> dict:
    """
    Build `Authorization: Bearer <minted-jwt>` headers for outbound
    /quota/* calls. Returns empty dict when `JWT_SECRET_KEY` is unset
    so the request still goes through (and 401s loudly).
    """
    token = mint_service_jwt(principal)
    return {'Authorization': f'Bearer {token}'} if token else {}
