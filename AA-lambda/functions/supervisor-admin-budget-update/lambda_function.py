"""supervisor-admin-budget-update — PUT /admin/settings/budget"""
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import boto3

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(_HERE, "shared")
for p in (_SHARED, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.lambda_helpers import (
    success_response,
    error_response,
    options_response,
    parse_body,
    set_request_context_lambda,
    decode_jwt_payload_unsafe,
)
from shared.persistence_factory import get_log_storage
from shared.budget_alert import maybe_send_budget_alert

# Module-scope DDB resource — reused across warm invocations. Same
# pattern as quota-lambda/lambda_admin_update_user.py to keep the audit
# row writer fast and cheap.
_DDB = boto3.resource("dynamodb")
_ADMIN_ACTIONS_TABLE_NAME = os.environ.get(
    "ADMIN_ACTIONS_TABLE", "QuotaAdminActions"
)
# Lazy attribute — table() is cheap but we still defer it so a missing
# DDB resource doesn't break import-time.
_admin_actions_table = None


def _get_admin_actions_table():
    global _admin_actions_table
    if _admin_actions_table is None:
        _admin_actions_table = _DDB.Table(_ADMIN_ACTIONS_TABLE_NAME)
    return _admin_actions_table


def _admin_identity_from_event(event):
    """Best-effort extract who made this change.

    API Gateway puts the requester's JWT (when our Lambda authorizer
    accepted it) in event.requestContext.authorizer.claims; legacy paths
    pass the raw bearer token in headers. We try both so the audit row
    has a real identity when one is available, and falls back to a
    generic anonymous tag rather than crashing.
    """
    rc = event.get("requestContext") or {}
    auth = rc.get("authorizer") or {}
    claims = auth.get("claims") if isinstance(auth, dict) else None
    if isinstance(claims, dict) and claims:
        return {
            "user_id": claims.get("sub") or claims.get("user_id") or "unknown",
            "email": claims.get("email") or claims.get("gmail") or "",
            "name": claims.get("name") or claims.get("fullname") or "",
        }
    headers = event.get("headers") or {}
    auth_header = headers.get("Authorization") or headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        try:
            payload = decode_jwt_payload_unsafe(token) or {}
            if payload:
                return {
                    "user_id": payload.get("sub") or payload.get("user_id") or "unknown",
                    "email": payload.get("email") or payload.get("gmail") or "",
                    "name": payload.get("name") or payload.get("fullname") or "",
                }
        except Exception:
            pass
    return {"user_id": "anonymous", "email": "", "name": ""}


def _log_quota_admin_action(actor, changes, snapshot):
    """Mirror the budget audit row into ``QuotaAdminActions`` so it
    appears in the Token Management page's "Admin Actions" panel.

    Schema matches what ``quota-lambda/lambda_admin_update_user.py``
    produces (action_id, admin_id, admin_name, action, target_user_id,
    target_user_name, details, timestamp) so the existing
    ``quota-admin-action`` reader Lambda + the QuotaPage frontend
    rendering (humanizeDetailKey + from/to delta cells) work as-is
    with no schema changes.

    The write is best-effort — a DDB failure here MUST NOT roll back a
    successful budget save (the user already pressed Save and the new
    value is live). The Sup_Logs audit row written by the caller is
    the source-of-truth audit trail; this row is purely for surfacing
    the change in the Admin Actions UI.
    """
    try:
        details = {}
        for field, delta in (changes or {}).items():
            details[field] = {"from": delta.get("from"), "to": delta.get("to")}
        if snapshot is not None:
            # These help an admin reading the audit row understand
            # whether the new budget left the org over/under threshold.
            if snapshot.get("current_month_cost_usd") is not None:
                details["current_month_cost_usd"] = snapshot.get(
                    "current_month_cost_usd"
                )
            if snapshot.get("pct_used") is not None:
                details["pct_used_after"] = snapshot.get("pct_used")

        _get_admin_actions_table().put_item(Item={
            "action_id": str(uuid.uuid4()),
            "admin_id": (actor or {}).get("user_id") or "system",
            "admin_name": (actor or {}).get("name") or (actor or {}).get("email") or "System",
            "admin_email": (actor or {}).get("email") or "",
            "action": "update_budget",
            # Budget is org-wide, not per-user. We use a stable sentinel
            # so the Admin Actions table renders a consistent
            # "Target User" column ("Monthly Budget" instead of an
            # opaque random value or empty cell).
            "target_user_id": "system_budget",
            "target_user_name": "Monthly Budget",
            "details": json.dumps(details) if details else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        # Match quota-lambda's pattern: log + swallow. The Sup_Logs
        # audit row above is unaffected, and the budget save itself
        # already succeeded.
        print(f"[budget-update] QuotaAdminActions audit write failed (non-fatal): {e}")


def _build_budget_response(storage):
    budget_raw = storage.get_setting("monthly_budget_usd")
    threshold_raw = storage.get_setting("alert_threshold_pct")
    monthly_budget = float(budget_raw) if budget_raw else None
    alert_threshold = float(threshold_raw) if threshold_raw else 80.0
    month_start = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
    token_stats = storage.get_token_usage_stats(start_time=month_start)
    current_month_cost = round(token_stats["totals"].get("total_cost_usd", 0) or 0, 4)
    over_budget = False
    alert_triggered = False
    if monthly_budget and monthly_budget > 0:
        pct_used = (current_month_cost / monthly_budget) * 100
        if pct_used >= 100:
            over_budget = True
        if pct_used >= alert_threshold:
            alert_triggered = True
    else:
        pct_used = 0.0
    return {
        "monthly_budget_usd": monthly_budget,
        "alert_threshold_pct": alert_threshold,
        "current_month_cost_usd": current_month_cost,
        "pct_used": round(pct_used, 1),
        "over_budget": over_budget,
        "alert_triggered": alert_triggered,
    }


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    body = parse_body(event)
    monthly_budget = body.get("monthly_budget_usd")
    alert_threshold = body.get("alert_threshold_pct")

    if monthly_budget is not None:
        try:
            mb = float(monthly_budget)
        except (TypeError, ValueError):
            return error_response(400, "monthly_budget_usd must be a number")
        if mb < 0:
            return error_response(400, "monthly_budget_usd must be >= 0")
    if alert_threshold is not None:
        try:
            at = float(alert_threshold)
        except (TypeError, ValueError):
            return error_response(400, "alert_threshold_pct must be a number")
        if at < 0 or at > 100:
            return error_response(400, "alert_threshold_pct must be between 0 and 100")

    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            # Capture before-values so the audit row records both old and
            # new — without this an admin reviewing the audit trail can't
            # tell whether a change shrank or expanded the budget.
            prev_budget = storage.get_setting("monthly_budget_usd")
            prev_threshold = storage.get_setting("alert_threshold_pct")

            if monthly_budget is not None:
                storage.set_setting("monthly_budget_usd", str(monthly_budget))
            if alert_threshold is not None:
                storage.set_setting("alert_threshold_pct", str(alert_threshold))
            snapshot = _build_budget_response(storage)

            # Audit log — answers "who changed the budget alert and date
            # and time like that?" (user request 2026-05-03). Routes into
            # the same Sup_Logs DDB table the Logs & Analytics page reads,
            # tagged component='admin' / operation='budget_update' so it's
            # easy to filter. Wrapped in try/except — a logging failure
            # MUST NOT roll back a successful budget save.
            try:
                actor = _admin_identity_from_event(event)
                changes = {}
                if monthly_budget is not None:
                    changes["monthly_budget_usd"] = {
                        "from": float(prev_budget) if prev_budget else None,
                        "to": float(monthly_budget),
                    }
                if alert_threshold is not None:
                    changes["alert_threshold_pct"] = {
                        "from": float(prev_threshold) if prev_threshold else None,
                        "to": float(alert_threshold),
                    }
                if changes:
                    msg_parts = []
                    for field, delta in changes.items():
                        msg_parts.append(
                            f"{field}: {delta['from']} -> {delta['to']}"
                        )
                    storage.insert_log(
                        timestamp=datetime.utcnow().isoformat() + "Z",
                        level="INFO",
                        logger="admin.budget",
                        message=(
                            f"Budget settings updated by "
                            f"{actor.get('email') or actor.get('user_id')}: "
                            + "; ".join(msg_parts)
                        ),
                        component="admin",
                        operation="budget_update",
                        data={
                            "actor": actor,
                            "changes": changes,
                            "current_month_cost_usd": snapshot.get(
                                "current_month_cost_usd"
                            ),
                            "pct_used_after": snapshot.get("pct_used"),
                        },
                    )
                    # Mirror into QuotaAdminActions so the Token
                    # Management → Admin Actions panel reflects the
                    # change. Best-effort; see _log_quota_admin_action
                    # for the rationale on swallowing errors here.
                    _log_quota_admin_action(actor, changes, snapshot)
            except Exception as audit_err:
                print(
                    f"[budget-update] audit log write failed (non-fatal): {audit_err}"
                )

            # Saving a tighter budget can immediately push the org over
            # threshold (e.g. spend = $0.50, new budget = $0.40 → 125%).
            # Fire the alert here too so the admin gets the email the
            # moment they hit Save, not on the next dashboard refresh.
            try:
                maybe_send_budget_alert(storage, snapshot)
            except Exception as alert_err:
                print(f"[budget-update] alert dispatch raised (non-fatal): {alert_err}")
            return success_response(snapshot)
        except Exception as e:
            return error_response(500, f"Error updating budget: {e}")
