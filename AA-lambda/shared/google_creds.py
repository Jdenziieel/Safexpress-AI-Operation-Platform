"""
Per-user Google OAuth credentials sourced from the ``SocialTokens`` DynamoDB
table.

Why this exists
---------------
The original `supervisor-agent/config.py:get_google_credentials()` read a
single set of OAuth tokens out of `.env` (`GOOGLE_ACCESS_TOKEN`,
`GOOGLE_REFRESH_TOKEN`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`). That worked
fine on a developer laptop with one Google account, but in production every
user has their own access/refresh tokens — written to the deployed
``SocialTokens`` table by `auth-google-login` at the moment of OAuth callback.

This module:

1. Looks up `(gmail, "google")` in `SocialTokens` and returns the right user's
   creds — keyed off whatever ``user_email`` is propagated through
   ``logging_config._user_email_var`` by ``set_request_context_lambda``.
2. Refreshes the access token in-place (POST to Google's token endpoint) when
   ``expires_at`` has passed. Persists the refreshed token + new expiry back to
   DynamoDB so subsequent requests skip the refresh.
3. Falls back to env vars (legacy behaviour) when no ``user_email`` is set
   (local dev, smoke tests, ad-hoc invocation).

The output shape matches the source ``credentials_dict`` exactly so every
sub-agent's `_build_google_credentials()` keeps working unchanged:

    {
      "access_token": "...",
      "refresh_token": "...",
      "token_uri": "https://oauth2.googleapis.com/token",
      "client_id": "...",
      "client_secret": "...",
    }

SocialTokens schema (from ``lambda_deployment_reference.md`` §2.3):
    PK: gmail (S)        e.g. "ruzzzzs03@gmail.com"
    SK: provider (S)     e.g. "google"
    attrs:
      access_token (S)
      refresh_token (S)
      expires_at (S)     ISO-8601 UTC w/ "Z" suffix
      extra_data (M)     Google profile (name, id, email, picture, ...)
      uid (S)            Google's `sub` claim

The OAuth client_id/client_secret are read from the same Lambda env vars
(`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`) the supervisor already exposes —
populated by the deploy scripts from the `prod/app/google-oauth` Secrets
Manager secret. They are app-wide, not per-user, so they don't live in
SocialTokens.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

# Lazy boto3 import — keeps this module importable from non-Lambda contexts
# (e.g. _sim_*.py smoke scripts that stub the table) without dragging in
# botocore at top-level.
_boto3 = None
_table_lock = threading.Lock()
_table_cache: Dict[str, Any] = {}


SOCIAL_TOKENS_TABLE = os.getenv("SOCIAL_TOKENS_TABLE", "SocialTokens")
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_PROVIDER = "google"

# Refresh access tokens this many seconds BEFORE actual expiry to avoid
# burning a request on a token that expires mid-flight. Google's tokens are
# 1h so a 60s safety margin is generous.
EXPIRY_SAFETY_SECONDS = int(os.getenv("GOOGLE_TOKEN_EXPIRY_SAFETY_SECONDS", "60"))


# ----------------------------------------------------------------------
# Module-level overrides (smoke tests inject a fake table here)
# ----------------------------------------------------------------------

# When set, ``_get_table()`` returns this object instead of calling boto3.
# The smoke test suite (``_sim_socialtokens.py``) uses this to feed a fake
# resource that records `get_item`/`update_item` calls and returns canned
# rows. Production code never touches this — it's `None` at runtime.
_TABLE_OVERRIDE: Any = None


def _set_table_override(fake_table: Any) -> None:
    """Smoke-test hook: install a fake DynamoDB table object."""
    global _TABLE_OVERRIDE
    _TABLE_OVERRIDE = fake_table
    # Bust the cached real-table reference too so subsequent calls see the
    # override.
    with _table_lock:
        _table_cache.clear()


def _clear_table_override() -> None:
    """Smoke-test hook: remove the fake table installed by
    ``_set_table_override``."""
    global _TABLE_OVERRIDE
    _TABLE_OVERRIDE = None
    with _table_lock:
        _table_cache.clear()


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------


def _get_table():
    """Return a cached ``boto3.dynamodb.Table`` for SocialTokens (or a fake
    one in tests)."""
    if _TABLE_OVERRIDE is not None:
        return _TABLE_OVERRIDE

    global _boto3
    with _table_lock:
        cached = _table_cache.get("table")
        if cached is not None:
            return cached
        if _boto3 is None:
            import boto3  # type: ignore
            _boto3 = boto3
        region = os.getenv("AWS_REGION") or os.getenv("DYNAMODB_REGION") or "ap-southeast-1"
        ddb = _boto3.resource("dynamodb", region_name=region)
        table = ddb.Table(SOCIAL_TOKENS_TABLE)
        _table_cache["table"] = table
        return table


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_expires_at(value: Any) -> Optional[datetime]:
    """Best-effort parse the SocialTokens ``expires_at`` field. Accepts ISO
    strings (with or without trailing ``Z``), unix epoch seconds (int /
    float / Decimal — boto3 returns DynamoDB Numbers as ``Decimal``).
    Returns ``None`` if unparseable so the caller can refresh proactively."""
    if value is None:
        return None
    # Numeric epoch (DynamoDB Number → Decimal — Decimal is NOT an int/float
    # subclass so we have to test it via duck-typing on float()).
    if not isinstance(value, str):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    s = value.strip()
    if not s:
        return None
    # Strict ISO with 'Z' suffix → swap for '+00:00' so fromisoformat accepts.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_expired(expires_at: Any) -> bool:
    """True if the token's effective expiry (with safety margin) has passed
    OR can't be parsed (forces a refresh in unknown-state cases)."""
    parsed = _parse_expires_at(expires_at)
    if parsed is None:
        return True
    safe_now = _now_utc().timestamp() + EXPIRY_SAFETY_SECONDS
    return safe_now >= parsed.timestamp()


def _fetch_social_token(
    gmail: str, provider: str = DEFAULT_PROVIDER
) -> Optional[Dict[str, Any]]:
    """GetItem from SocialTokens. Returns the raw item dict or ``None``."""
    if not gmail:
        return None
    try:
        table = _get_table()
        resp = table.get_item(Key={"gmail": gmail, "provider": provider})
    except Exception as e:
        print(f"[google_creds] SocialTokens GetItem failed for {gmail!r}: {e}")
        return None
    return resp.get("Item")


def _refresh_access_token(
    refresh_token: str, client_id: str, client_secret: str
) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    """Hit Google's token endpoint. Returns ``(new_access_token,
    expires_in_seconds, rotated_refresh_token)``. The third element is the
    new refresh_token IF Google rotated it (rare — usually only on
    re-consent, but documented as possible); ``None`` otherwise. On any
    failure returns ``(None, None, None)``. Does NOT raise — the caller
    decides whether to fall back to the (potentially stale) cached token
    or fail the request."""
    if not (refresh_token and client_id and client_secret):
        return None, None, None
    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode("utf-8")
    req = urllib.request.Request(
        GOOGLE_TOKEN_URI,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        print(f"[google_creds] OAuth refresh HTTP {e.code}: {err_body}")
        return None, None, None
    except Exception as e:
        print(f"[google_creds] OAuth refresh failed: {e}")
        return None, None, None

    new_access = payload.get("access_token")
    expires_in = payload.get("expires_in")
    try:
        expires_in = int(expires_in) if expires_in is not None else None
    except (TypeError, ValueError):
        expires_in = None
    # Refresh token rotation: only persist if Google returned a fresh one
    # AND it differs from what we sent (defensive — some OAuth providers
    # echo the same value back).
    rotated_refresh = payload.get("refresh_token")
    if rotated_refresh == refresh_token:
        rotated_refresh = None
    return new_access, expires_in, rotated_refresh


def _persist_refreshed_token(
    gmail: str,
    provider: str,
    new_access_token: str,
    new_expires_at_iso: str,
    new_refresh_token: Optional[str] = None,
) -> None:
    """UpdateItem with the new access_token + expires_at, plus the rotated
    refresh_token when Google returned one. Best-effort; errors are logged,
    never raised — a failed write doesn't invalidate the in-memory creds we
    already have."""
    try:
        table = _get_table()
        update_expr = "SET access_token = :a, expires_at = :e"
        attr_values: Dict[str, Any] = {
            ":a": new_access_token,
            ":e": new_expires_at_iso,
        }
        if new_refresh_token:
            update_expr += ", refresh_token = :r"
            attr_values[":r"] = new_refresh_token
        table.update_item(
            Key={"gmail": gmail, "provider": provider},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=attr_values,
        )
    except Exception as e:
        print(f"[google_creds] SocialTokens UpdateItem failed for {gmail!r}: {e}")


def _build_creds_dict(
    access_token: str,
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> Dict[str, str]:
    """Same shape the source `get_google_credentials()` returns."""
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_uri": GOOGLE_TOKEN_URI,
        "client_id": client_id,
        "client_secret": client_secret,
    }


# ----------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------


def get_google_credentials_for_user(user_email: str) -> Optional[Dict[str, str]]:
    """Look up the SocialTokens row for ``user_email`` (the gmail PK),
    refresh the access token if needed, and return a creds dict ready to be
    passed to a sub-agent.

    Returns ``None`` when:
      * ``user_email`` is empty
      * the SocialTokens row doesn't exist (user hasn't completed Google OAuth)
      * refresh failed AND the cached access_token is also expired/missing
      * OAuth client_id/client_secret env vars are missing in the Lambda

    The caller (``config.get_google_credentials()``) decides whether to fall
    back to env-based creds or surface a "Google account not linked" error.
    """
    if not user_email:
        return None

    item = _fetch_social_token(user_email)
    if not item:
        print(
            f"[google_creds] no SocialTokens row for {user_email!r}; user must"
            " complete Google OAuth login first."
        )
        return None

    access_token = item.get("access_token")
    refresh_token = item.get("refresh_token")
    expires_at = item.get("expires_at")

    client_id = (
        os.getenv("GOOGLE_CLIENT_ID")
        or os.getenv("OAUTH_CLIENT_ID")
        or ""
    )
    client_secret = (
        os.getenv("GOOGLE_CLIENT_SECRET")
        or os.getenv("OAUTH_CLIENT_SECRET")
        or ""
    )

    if not (client_id and client_secret):
        print(
            "[google_creds] GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set"
            " in the Lambda env. Token refresh impossible. Returning"
            " whatever cached access_token we have (may be expired)."
        )
        if access_token and refresh_token:
            return _build_creds_dict(access_token, refresh_token, client_id, client_secret)
        return None

    if _is_expired(expires_at):
        new_access, expires_in, rotated_refresh = _refresh_access_token(
            refresh_token or "", client_id, client_secret
        )
        if new_access:
            new_expires_dt = _now_utc().timestamp() + (
                int(expires_in) if expires_in else 3600
            )
            new_expires_iso = (
                datetime.fromtimestamp(new_expires_dt, tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )
            _persist_refreshed_token(
                user_email,
                DEFAULT_PROVIDER,
                new_access,
                new_expires_iso,
                new_refresh_token=rotated_refresh,
            )
            access_token = new_access
            if rotated_refresh:
                refresh_token = rotated_refresh
        else:
            # Refresh failed. If the cached token might still work (clock skew
            # / very-recent expiry) we hand it back; otherwise nothing.
            if not access_token:
                return None
            print(
                f"[google_creds] refresh failed for {user_email!r};"
                " returning the cached (possibly expired) access_token as last resort."
            )

    if not access_token or not refresh_token:
        print(
            f"[google_creds] SocialTokens row for {user_email!r} is missing"
            " access_token or refresh_token; cannot build creds dict."
        )
        return None

    return _build_creds_dict(access_token, refresh_token, client_id, client_secret)
