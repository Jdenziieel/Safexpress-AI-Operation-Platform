"""supervisor-admin-budget-update — PUT /admin/settings/budget"""
import os
import sys
from datetime import datetime, timedelta

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
)
from shared.persistence_factory import get_log_storage
from shared.budget_alert import maybe_send_budget_alert


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
            if monthly_budget is not None:
                storage.set_setting("monthly_budget_usd", str(monthly_budget))
            if alert_threshold is not None:
                storage.set_setting("alert_threshold_pct", str(alert_threshold))
            snapshot = _build_budget_response(storage)
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
