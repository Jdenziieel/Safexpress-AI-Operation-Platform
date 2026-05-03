"""Offline smoke test for the SocialTokens-backed Google credentials flow.

Covers:
  T01  generate_gmail_tokens.py never made it into AA-lambda (regression net)
  T02  refresh_token.py CLI scripts no longer ship in AA-lambda
  T03  google_creds._is_expired honours the safety margin
  T04  get_google_credentials_for_user() returns full creds for a fresh row
  T05  expired token triggers a refresh + a DynamoDB UpdateItem write-back
  T06  refresh failure with valid cached token returns the cached creds
  T07  missing SocialTokens row returns None
  T08  config.get_google_credentials() prefers user_email arg over contextvar
  T09  config.get_google_credentials() falls back to env when no user_email
  T10  config.get_google_credentials() reads gmail from contextvar
  T11  get_user_from_authorizer recognises the JWT 'gmail' claim
  T12  set_request_context_lambda propagates user_email to logging contextvar
  T13  decode_jwt_payload_unsafe pulls gmail out of a real-shape JWT
"""
from __future__ import annotations

import base64
import importlib
import json
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------- bootstrap
HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.join(HERE, "shared")
for p in (SHARED, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

# Wipe any residual modules the other sim scripts might have polluted.
for mod in list(sys.modules):
    if mod.startswith(("config", "logging_config", "lambda_helpers", "google_creds")):
        sys.modules.pop(mod, None)

# Prevent google_creds from importing real boto3 — we'll inject a fake table.
os.environ.pop("GOOGLE_ACCESS_TOKEN", None)
os.environ.pop("GOOGLE_REFRESH_TOKEN", None)
os.environ.pop("GOOGLE_CLIENT_ID", None)
os.environ.pop("GOOGLE_CLIENT_SECRET", None)


# ---------------------------------------------------------------- helpers


PASS: List[str] = []
FAIL: List[str] = []


def _record(name: str, ok: bool, detail: str = "") -> None:
    line = f"[{'PASS' if ok else 'FAIL'}] {name}"
    if detail:
        line += f"  -- {detail}"
    print(line)
    (PASS if ok else FAIL).append(name)


def _assert(name: str, cond: bool, detail: str = "") -> None:
    _record(name, bool(cond), detail)


def _now_z(offset_seconds: int = 0) -> str:
    dt = datetime.now(tz=timezone.utc) + timedelta(seconds=offset_seconds)
    return dt.isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------- tests


def t01_generate_script_not_migrated() -> None:
    """The original ``gmail-agent/generate_gmail_tokens.py`` was a one-off
    OAuth-bootstrap CLI we didn't want shipped to Lambda."""
    bad: List[str] = []
    for root, dirs, files in os.walk(HERE):
        for f in files:
            if f.startswith("generate_gmail_tokens"):
                bad.append(os.path.join(root, f))
    _assert("T01 generate_gmail_tokens absent from AA-lambda",
            not bad, detail=f"found: {bad}" if bad else "")


def t02_refresh_token_scripts_removed() -> None:
    bad: List[str] = []
    for root, dirs, files in os.walk(HERE):
        for f in files:
            if f == "refresh_token.py":
                bad.append(os.path.join(root, f))
    _assert("T02 refresh_token.py CLI scripts removed",
            not bad, detail=f"found: {bad}" if bad else "")


def t03_is_expired_safety_margin() -> None:
    import google_creds as gc

    _assert("T03 unparseable expires_at -> expired",
            gc._is_expired(None) is True)
    _assert("T03 future expiry -> not expired",
            gc._is_expired(_now_z(3600)) is False)
    _assert("T03 past expiry -> expired",
            gc._is_expired(_now_z(-60)) is True)
    # Within safety margin → treated as expired.
    _assert("T03 expiry inside safety margin -> expired",
            gc._is_expired(_now_z(10)) is True)


# A simple fake DynamoDB table that records calls so we can assert.
class FakeTable:
    def __init__(self, items: Optional[Dict[tuple, Dict[str, Any]]] = None):
        self.items = dict(items or {})
        self.gets: List[Dict[str, Any]] = []
        self.updates: List[Dict[str, Any]] = []

    def get_item(self, Key):
        self.gets.append(Key)
        item = self.items.get((Key["gmail"], Key["provider"]))
        return {"Item": item} if item else {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, **_):
        self.updates.append({
            "Key": Key,
            "UpdateExpression": UpdateExpression,
            "ExpressionAttributeValues": ExpressionAttributeValues,
        })
        existing = self.items.get((Key["gmail"], Key["provider"]), {})
        existing = dict(existing)
        existing["access_token"] = ExpressionAttributeValues[":a"]
        existing["expires_at"] = ExpressionAttributeValues[":e"]
        self.items[(Key["gmail"], Key["provider"])] = existing


def _row(access="acc-1", refresh="ref-1", expires_at=None, **extra):
    row = {
        "gmail": "alice@example.com",
        "provider": "google",
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": expires_at or _now_z(3600),
        "uid": "100037862079398927883",
    }
    row.update(extra)
    return row


def t04_fresh_creds_dict() -> None:
    import google_creds as gc

    fake = FakeTable({("alice@example.com", "google"): _row()})
    gc._set_table_override(fake)
    os.environ["GOOGLE_CLIENT_ID"] = "cid"
    os.environ["GOOGLE_CLIENT_SECRET"] = "csecret"
    try:
        creds = gc.get_google_credentials_for_user("alice@example.com")
        ok = (
            creds is not None
            and creds["access_token"] == "acc-1"
            and creds["refresh_token"] == "ref-1"
            and creds["client_id"] == "cid"
            and creds["client_secret"] == "csecret"
            and creds["token_uri"] == "https://oauth2.googleapis.com/token"
        )
        _assert("T04 fresh row returns full creds dict", ok, detail=str(creds))
        _assert("T04 no UpdateItem when token still valid",
                len(fake.updates) == 0)
    finally:
        gc._clear_table_override()
        os.environ.pop("GOOGLE_CLIENT_ID", None)
        os.environ.pop("GOOGLE_CLIENT_SECRET", None)


def t05_expired_triggers_refresh_and_writeback() -> None:
    import google_creds as gc

    # Set up: expired row, fake refresh endpoint via monkey patch.
    fake = FakeTable({
        ("alice@example.com", "google"): _row(
            access="OLD",
            expires_at=_now_z(-300),  # 5 min ago
        )
    })
    gc._set_table_override(fake)
    os.environ["GOOGLE_CLIENT_ID"] = "cid"
    os.environ["GOOGLE_CLIENT_SECRET"] = "csecret"

    refresh_calls: List[Dict[str, str]] = []

    def fake_refresh(refresh_token, client_id, client_secret):
        refresh_calls.append({
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        })
        return ("NEW-FRESH", 3600, None)

    orig = gc._refresh_access_token
    gc._refresh_access_token = fake_refresh
    try:
        creds = gc.get_google_credentials_for_user("alice@example.com")
        _assert("T05 access_token rotated to refreshed value",
                creds and creds["access_token"] == "NEW-FRESH")
        _assert("T05 refresh endpoint called once",
                len(refresh_calls) == 1
                and refresh_calls[0]["refresh_token"] == "ref-1")
        _assert("T05 SocialTokens UpdateItem performed",
                len(fake.updates) == 1
                and fake.updates[0]["ExpressionAttributeValues"][":a"] == "NEW-FRESH")
        _assert("T05 expires_at written back as ISO Z",
                fake.updates[0]["ExpressionAttributeValues"][":e"].endswith("Z"))
        _assert("T05 refresh_token NOT updated when not rotated",
                ":r" not in fake.updates[0]["ExpressionAttributeValues"])
    finally:
        gc._refresh_access_token = orig
        gc._clear_table_override()
        os.environ.pop("GOOGLE_CLIENT_ID", None)
        os.environ.pop("GOOGLE_CLIENT_SECRET", None)


def t05b_rotated_refresh_token_persisted() -> None:
    """Google occasionally returns a NEW refresh_token in the refresh
    response. We must persist it; otherwise the next refresh will fail
    against the now-invalidated old refresh_token."""
    import google_creds as gc

    fake = FakeTable({
        ("alice@example.com", "google"): _row(
            access="OLD",
            refresh="OLD-REFRESH",
            expires_at=_now_z(-300),
        )
    })
    gc._set_table_override(fake)
    os.environ["GOOGLE_CLIENT_ID"] = "cid"
    os.environ["GOOGLE_CLIENT_SECRET"] = "csecret"

    def fake_refresh(refresh_token, client_id, client_secret):
        return ("NEW-A", 3600, "NEW-REFRESH")  # Google rotated the refresh token

    orig = gc._refresh_access_token
    gc._refresh_access_token = fake_refresh
    try:
        creds = gc.get_google_credentials_for_user("alice@example.com")
        _assert("T05b returned creds carry the rotated refresh_token",
                creds and creds["refresh_token"] == "NEW-REFRESH")
        _assert("T05b SocialTokens UpdateItem includes refresh_token",
                len(fake.updates) == 1
                and fake.updates[0]["ExpressionAttributeValues"].get(":r") == "NEW-REFRESH")
    finally:
        gc._refresh_access_token = orig
        gc._clear_table_override()
        os.environ.pop("GOOGLE_CLIENT_ID", None)
        os.environ.pop("GOOGLE_CLIENT_SECRET", None)


def t05c_decimal_expires_at_parses() -> None:
    """boto3 returns DynamoDB Number values as ``decimal.Decimal``, NOT
    int/float. Make sure ``_parse_expires_at`` accepts that shape."""
    import google_creds as gc
    from decimal import Decimal

    future_epoch = Decimal(str(int(datetime.now(tz=timezone.utc).timestamp()) + 3600))
    past_epoch = Decimal(str(int(datetime.now(tz=timezone.utc).timestamp()) - 3600))
    _assert("T05c Decimal future epoch parses as not-expired",
            gc._is_expired(future_epoch) is False,
            detail=str(future_epoch))
    _assert("T05c Decimal past epoch parses as expired",
            gc._is_expired(past_epoch) is True)


def t06_refresh_failure_returns_cached_when_present() -> None:
    import google_creds as gc

    fake = FakeTable({
        ("alice@example.com", "google"): _row(
            access="STALE",
            expires_at=_now_z(-60),
        )
    })
    gc._set_table_override(fake)
    os.environ["GOOGLE_CLIENT_ID"] = "cid"
    os.environ["GOOGLE_CLIENT_SECRET"] = "csecret"

    orig = gc._refresh_access_token
    gc._refresh_access_token = lambda *_a, **_k: (None, None, None)
    try:
        creds = gc.get_google_credentials_for_user("alice@example.com")
        _assert("T06 refresh failure -> returns stale cached token",
                creds is not None and creds["access_token"] == "STALE")
        _assert("T06 no UpdateItem on failed refresh",
                len(fake.updates) == 0)
    finally:
        gc._refresh_access_token = orig
        gc._clear_table_override()
        os.environ.pop("GOOGLE_CLIENT_ID", None)
        os.environ.pop("GOOGLE_CLIENT_SECRET", None)


def t07_missing_row_returns_none() -> None:
    import google_creds as gc

    gc._set_table_override(FakeTable({}))
    os.environ["GOOGLE_CLIENT_ID"] = "cid"
    os.environ["GOOGLE_CLIENT_SECRET"] = "csecret"
    try:
        creds = gc.get_google_credentials_for_user("nobody@example.com")
        _assert("T07 missing SocialTokens row -> None", creds is None)
    finally:
        gc._clear_table_override()
        os.environ.pop("GOOGLE_CLIENT_ID", None)
        os.environ.pop("GOOGLE_CLIENT_SECRET", None)


def t08_config_uses_explicit_user_email_arg() -> None:
    import google_creds as gc
    import config

    fake = FakeTable({("bob@example.com", "google"): _row(access="BOB-TOK")})
    fake.items[("bob@example.com", "google")]["gmail"] = "bob@example.com"
    gc._set_table_override(fake)
    os.environ["GOOGLE_CLIENT_ID"] = "cid"
    os.environ["GOOGLE_CLIENT_SECRET"] = "csecret"
    try:
        creds = config.get_google_credentials(user_email="bob@example.com")
        _assert("T08 explicit user_email arg routes to SocialTokens",
                creds.get("access_token") == "BOB-TOK")
    finally:
        gc._clear_table_override()
        os.environ.pop("GOOGLE_CLIENT_ID", None)
        os.environ.pop("GOOGLE_CLIENT_SECRET", None)


def t08b_user_email_present_but_no_row_fails_closed() -> None:
    """Security-critical: an authenticated request whose SocialTokens row
    is missing must NOT silently fall back to env creds (would leak the
    deploy-seeded account's tokens). Empty dict → orchestrator emits
    'Missing required Google credentials'."""
    import google_creds as gc
    import config

    gc._set_table_override(FakeTable({}))  # empty table
    # Env has admin's leftover creds — this is the danger scenario.
    os.environ["GOOGLE_ACCESS_TOKEN"] = "ADMIN-LEAK-TOKEN"
    os.environ["GOOGLE_REFRESH_TOKEN"] = "ADMIN-LEAK-REFRESH"
    os.environ["GOOGLE_CLIENT_ID"] = "cid"
    os.environ["GOOGLE_CLIENT_SECRET"] = "csecret"
    try:
        creds = config.get_google_credentials(user_email="nobody@example.com")
        _assert("T08b unmatched user_email -> fail-closed (no env leak)",
                "access_token" not in creds,
                detail=str(creds))
    finally:
        gc._clear_table_override()
        for k in ("GOOGLE_ACCESS_TOKEN", "GOOGLE_REFRESH_TOKEN",
                  "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
            os.environ.pop(k, None)


def t09_config_env_fallback_when_no_user_email() -> None:
    import google_creds as gc
    import config

    gc._set_table_override(FakeTable({}))
    os.environ["GOOGLE_ACCESS_TOKEN"] = "ENV-A"
    os.environ["GOOGLE_REFRESH_TOKEN"] = "ENV-R"
    os.environ["GOOGLE_CLIENT_ID"] = "ENV-CID"
    os.environ["GOOGLE_CLIENT_SECRET"] = "ENV-CSECRET"
    try:
        creds = config.get_google_credentials()  # no arg, no contextvar
        _assert("T09 env fallback when no user_email",
                creds.get("access_token") == "ENV-A"
                and creds.get("refresh_token") == "ENV-R"
                and creds.get("client_id") == "ENV-CID")
    finally:
        gc._clear_table_override()
        for k in ("GOOGLE_ACCESS_TOKEN", "GOOGLE_REFRESH_TOKEN",
                  "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
            os.environ.pop(k, None)


def t10_config_reads_user_email_from_contextvar() -> None:
    import google_creds as gc
    import config
    import logging_config

    fake = FakeTable({("carol@example.com", "google"): _row(access="CAROL-TOK")})
    fake.items[("carol@example.com", "google")]["gmail"] = "carol@example.com"
    gc._set_table_override(fake)
    os.environ["GOOGLE_CLIENT_ID"] = "cid"
    os.environ["GOOGLE_CLIENT_SECRET"] = "csecret"
    try:
        logging_config.set_request_context(
            user_id="carol-uid",
            user_email="carol@example.com",
        )
        creds = config.get_google_credentials()  # no arg
        _assert("T10 contextvar drives SocialTokens lookup",
                creds.get("access_token") == "CAROL-TOK")
    finally:
        logging_config.clear_request_context()
        gc._clear_table_override()
        os.environ.pop("GOOGLE_CLIENT_ID", None)
        os.environ.pop("GOOGLE_CLIENT_SECRET", None)


def t11_authorizer_extracts_gmail_claim() -> None:
    import lambda_helpers as lh

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "user_id": "u-1",
                    "gmail": "dave@example.com",
                    "role": "user",
                }
            }
        },
        "headers": {"Authorization": "Bearer junk.payload.sig"},
    }
    info = lh.get_user_from_authorizer(event)
    _assert("T11 authorizer recognises 'gmail' claim",
            info["email"] == "dave@example.com",
            detail=str(info))


def t12_lambda_context_propagates_user_email() -> None:
    import lambda_helpers as lh
    import logging_config

    captured: Dict[str, Any] = {}

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "user_id": "u-1",
                    "gmail": "eve@example.com",
                }
            }
        },
        "headers": {"Authorization": "Bearer abc.def.ghi"},
    }
    with lh.set_request_context_lambda(event) as ctx:
        captured["ctx_email"] = ctx["email"]
        captured["cv_email"] = logging_config.get_current_user_email()
    _assert("T12 ctx['email'] populated", captured["ctx_email"] == "eve@example.com")
    _assert("T12 _user_email_var set inside context",
            captured["cv_email"] == "eve@example.com")
    _assert("T12 _user_email_var cleared after context",
            logging_config.get_current_user_email() is None)


def t13_decode_jwt_payload_unsafe() -> None:
    import lambda_helpers as lh

    payload = {
        "user_id": "u-9",
        "gmail": "frank@example.com",
        "role": "admin",
        "exp": 9999999999,
    }
    body = base64.urlsafe_b64encode(
        json.dumps(payload).encode("utf-8")
    ).decode("utf-8").rstrip("=")
    token = f"eyJhbGciOiJIUzI1NiJ9.{body}.notarealsig"
    decoded = lh.decode_jwt_payload_unsafe(token)
    _assert("T13 decode_jwt_payload_unsafe returns gmail",
            decoded.get("gmail") == "frank@example.com",
            detail=str(decoded))
    _assert("T13 decode_jwt_payload_unsafe handles garbage",
            lh.decode_jwt_payload_unsafe("not-a-jwt") == {})


def t14_contextvar_survives_asyncio_run_to_thread_boundary() -> None:
    """End-to-end: simulate the create-thread Lambda flow.

      main thread:
        logging_config.set_request_context(user_email="grace@example.com")
        asyncio.run(coro)
          coro:
            await asyncio.to_thread(get_google_credentials)
              # in worker thread → must still see contextvar

    Source ``routes/threads.py:_run_workflow_and_update_state`` uses exactly
    this nesting (asyncio.run → await asyncio.to_thread(run_workflow, ...)),
    so this guards the production path."""
    import asyncio
    import google_creds as gc
    import config
    import logging_config

    fake = FakeTable({("grace@example.com", "google"): _row(access="GRACE-TOK")})
    fake.items[("grace@example.com", "google")]["gmail"] = "grace@example.com"
    gc._set_table_override(fake)
    os.environ["GOOGLE_CLIENT_ID"] = "cid"
    os.environ["GOOGLE_CLIENT_SECRET"] = "csecret"

    captured: Dict[str, Any] = {}

    async def coro() -> None:
        # Mirror _run_workflow_and_update_state's pattern.
        creds = await asyncio.to_thread(config.get_google_credentials)
        captured["creds"] = creds
        captured["cv_in_thread"] = await asyncio.to_thread(
            logging_config.get_current_user_email
        )

    try:
        logging_config.set_request_context(
            user_id="grace-uid",
            user_email="grace@example.com",
        )
        asyncio.run(coro())
        _assert(
            "T14 contextvar visible inside asyncio.to_thread worker",
            captured.get("cv_in_thread") == "grace@example.com",
            detail=str(captured),
        )
        _assert(
            "T14 SocialTokens resolved via contextvar across asyncio boundary",
            (captured.get("creds") or {}).get("access_token") == "GRACE-TOK",
        )
    finally:
        logging_config.clear_request_context()
        gc._clear_table_override()
        os.environ.pop("GOOGLE_CLIENT_ID", None)
        os.environ.pop("GOOGLE_CLIENT_SECRET", None)


# ---------------------------------------------------------------- runner


def main() -> int:
    tests = [
        t01_generate_script_not_migrated,
        t02_refresh_token_scripts_removed,
        t03_is_expired_safety_margin,
        t04_fresh_creds_dict,
        t05_expired_triggers_refresh_and_writeback,
        t05b_rotated_refresh_token_persisted,
        t05c_decimal_expires_at_parses,
        t06_refresh_failure_returns_cached_when_present,
        t07_missing_row_returns_none,
        t08_config_uses_explicit_user_email_arg,
        t08b_user_email_present_but_no_row_fails_closed,
        t09_config_env_fallback_when_no_user_email,
        t10_config_reads_user_email_from_contextvar,
        t11_authorizer_extracts_gmail_claim,
        t12_lambda_context_propagates_user_email,
        t13_decode_jwt_payload_unsafe,
        t14_contextvar_survives_asyncio_run_to_thread_boundary,
    ]
    for t in tests:
        try:
            t()
        except Exception as e:
            traceback.print_exc()
            _record(f"{t.__name__} (exception)", False, detail=str(e))

    print("\n" + "=" * 60)
    print(f"PASS: {len(PASS)}   FAIL: {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print(f"   - {f}")
    print("=" * 60)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
