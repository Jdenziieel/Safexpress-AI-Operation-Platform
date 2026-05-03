"""Budget alert email dispatch via AWS SES.

Sent automatically whenever the admin dashboard refreshes its budget
panel (``supervisor-admin-budget-get`` and ``-update`` both call this
module from the end of ``_build_budget_response``).

Two thresholds, each fired once per calendar month, deduped via the
``Sup_SystemSettings`` table:

  * ``warning``  – ``pct_used >= alert_threshold_pct`` (default 80%)
  * ``critical`` – ``pct_used >= 100%`` (over budget)

If the user later raises the budget so the warning condition no longer
holds, the dedupe key is reset so a future re-crossing fires again.

Configuration (all env vars; safe defaults provided):

    BUDGET_ALERT_TO_EMAIL    (default sadmin@safexpressops.com)
    BUDGET_ALERT_FROM_EMAIL  (default noreply@safexpressops.com)
    BUDGET_ALERT_REGION      (default uses Lambda's AWS_REGION)
    BUDGET_ALERTS_ENABLED    ("0" disables; default enabled)
    APP_NAME                 (default "SafeExpress Ops AI Assistant")
    APP_DASHBOARD_URL        (rendered as a "Open dashboard" link)

IAM the executing Lambda role MUST grant:

    {
      "Effect": "Allow",
      "Action": ["ses:SendEmail", "ses:SendRawEmail"],
      "Resource": "*"
    }

SES sandbox: until the account is moved out of SES sandbox, BOTH the
sender AND each recipient address must be verified in SES. The default
``noreply@safexpressops.com`` sender therefore needs a one-time verified
identity in the same region as the Lambda.

Errors are swallowed and printed to CloudWatch — a failed email must
never break a budget GET/PUT request to the admin dashboard.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

# Lazy-import boto3 so unit tests on machines without it still import the
# module. The Lambda runtime always has boto3 available.
try:
    import boto3  # type: ignore
    from botocore.exceptions import BotoCoreError, ClientError  # type: ignore
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore
    BotoCoreError = ClientError = Exception  # type: ignore


# Default recipient — admin@safexpressops.com is the active mailbox the
# operator monitors AND is already a SES-verified identity in
# ap-southeast-1, so alerts deliver out of the box without a second
# verification round-trip. Override per-environment via the
# BUDGET_ALERT_TO_EMAIL env var on the budget-get / budget-update
# Lambdas if you need a different inbox in dev/staging.
#
# Default sender — same address is used as both From and To. SES is fine
# with this (a domain owner sending to themselves) and it sidesteps
# needing a separate verified noreply@ identity. Override via
# BUDGET_ALERT_FROM_EMAIL once you verify a dedicated noreply@ identity
# (recommended for production so replies don't loop back into the alert
# mailbox).
_DEFAULT_TO = "admin@safexpressops.com"
_DEFAULT_FROM = "admin@safexpressops.com"
_DEDUPE_KEY = "last_budget_alert"  # value: "YYYY-MM:<level>"


def _env(name: str, default: str = "") -> str:
    val = os.environ.get(name)
    return val if val else default


def _alerts_enabled() -> bool:
    flag = (os.environ.get("BUDGET_ALERTS_ENABLED") or "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def _ses_client():
    if boto3 is None:
        return None
    region = _env("BUDGET_ALERT_REGION") or _env("AWS_REGION") or _env("AWS_DEFAULT_REGION") or "ap-southeast-1"
    return boto3.client("ses", region_name=region)


def _yyyymm(now: Optional[datetime] = None) -> str:
    return (now or datetime.utcnow()).strftime("%Y-%m")


def _classify_state(pct_used: float, alert_threshold: float) -> Optional[str]:
    """Return 'critical' (>=100%), 'warning' (>=threshold), or None."""
    if pct_used >= 100.0:
        return "critical"
    if pct_used >= alert_threshold:
        return "warning"
    return None


def _should_send(storage, current_level: Optional[str]) -> bool:
    """True iff this month's dedupe slot doesn't already cover this level.

    Critical supersedes warning: once a critical alert has fired in
    month X, we don't downgrade back to warning if the user briefly
    bumps the budget — they get one alert per crossing per level per
    month, max two emails per month.
    """
    if not current_level:
        return False
    last = (storage.get_setting(_DEDUPE_KEY) or "").strip()
    last_month, _, last_level = last.partition(":")
    this_month = _yyyymm()
    if last_month != this_month:
        return True
    if current_level == "critical" and last_level != "critical":
        return True
    return False


def _record_sent(storage, level: str) -> None:
    try:
        storage.set_setting(_DEDUPE_KEY, f"{_yyyymm()}:{level}")
    except Exception as e:  # pragma: no cover
        print(f"[budget_alert] failed to persist dedupe key: {e}")


def _reset_if_no_longer_alerting(storage, current_level: Optional[str]) -> None:
    """Wipe this month's dedupe slot when the user dropped back below
    the threshold (e.g. raised the budget). This lets a future
    re-crossing fire a fresh alert instead of being silently muted by
    last week's record."""
    if current_level is not None:
        return
    last = (storage.get_setting(_DEDUPE_KEY) or "").strip()
    last_month, _, _ = last.partition(":")
    if last_month == _yyyymm():
        try:
            storage.set_setting(_DEDUPE_KEY, "")
        except Exception:
            pass


def _format_money(v: float) -> str:
    if v >= 100:
        return f"${v:,.2f}"
    if v >= 1:
        return f"${v:.2f}"
    return f"${v:.4f}"


def _render_email(level: str, snapshot: Dict[str, Any]) -> Dict[str, str]:
    app = _env("APP_NAME", "SafeExpress Ops AI Assistant")
    dashboard = _env("APP_DASHBOARD_URL", "")
    pct = snapshot.get("pct_used") or 0.0
    spend = _format_money(snapshot.get("current_month_cost_usd") or 0.0)
    budget = _format_money(snapshot.get("monthly_budget_usd") or 0.0)
    threshold = snapshot.get("alert_threshold_pct") or 80.0

    if level == "critical":
        subject = f"[{app}] Monthly budget EXCEEDED: {pct:.1f}% used"
        headline = "Monthly budget exceeded"
        tone_color = "#b91c1c"
        explanation = (
            f"The AI Assistant has used <strong>{spend}</strong> against the "
            f"<strong>{budget}</strong> monthly budget — that is "
            f"<strong>{pct:.1f}%</strong>, over the 100% ceiling."
        )
    else:
        subject = f"[{app}] Monthly budget alert: {pct:.1f}% used"
        headline = "Monthly budget threshold reached"
        tone_color = "#b45309"
        explanation = (
            f"The AI Assistant has used <strong>{spend}</strong> against the "
            f"<strong>{budget}</strong> monthly budget — <strong>{pct:.1f}%</strong>, "
            f"which crossed the configured alert threshold of "
            f"<strong>{threshold:.0f}%</strong>."
        )

    cta_html = (
        f'<a href="{dashboard}" style="display:inline-block;padding:10px 20px;'
        f'background:#3b82f6;color:#fff;text-decoration:none;border-radius:6px;'
        f'font-weight:600;font-size:14px;">Open admin dashboard</a>'
    ) if dashboard else ""

    cta_text = f"\nDashboard: {dashboard}\n" if dashboard else ""

    html = f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f3f4f6;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;">
  <div style="max-width:560px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.06);">
    <div style="padding:24px 28px;background:{tone_color};color:#fff;">
      <div style="font-size:12px;letter-spacing:0.5px;text-transform:uppercase;opacity:0.9;">{app}</div>
      <h1 style="margin:8px 0 0 0;font-size:22px;line-height:1.3;">{headline}</h1>
    </div>
    <div style="padding:24px 28px;color:#111827;font-size:14px;line-height:1.6;">
      <p style="margin:0 0 16px 0;">{explanation}</p>
      <table style="width:100%;border-collapse:collapse;margin:16px 0;font-size:13px;">
        <tr style="background:#f9fafb;"><td style="padding:8px 12px;color:#6b7280;">This-month spend</td><td style="padding:8px 12px;text-align:right;font-weight:600;">{spend}</td></tr>
        <tr><td style="padding:8px 12px;color:#6b7280;">Monthly budget</td><td style="padding:8px 12px;text-align:right;font-weight:600;">{budget}</td></tr>
        <tr style="background:#f9fafb;"><td style="padding:8px 12px;color:#6b7280;">Used</td><td style="padding:8px 12px;text-align:right;font-weight:600;color:{tone_color};">{pct:.1f}%</td></tr>
        <tr><td style="padding:8px 12px;color:#6b7280;">Alert threshold</td><td style="padding:8px 12px;text-align:right;font-weight:600;">{threshold:.0f}%</td></tr>
      </table>
      <p style="margin:16px 0;color:#6b7280;font-size:13px;">
        Review the breakdown by model and tier in the admin dashboard,
        and either raise the budget or investigate which workflows are
        burning tokens.
      </p>
      {cta_html}
    </div>
    <div style="padding:16px 28px;background:#f9fafb;color:#9ca3af;font-size:11px;">
      Sent automatically by the {app} budget guardrail.
      Configure recipient via the BUDGET_ALERT_TO_EMAIL env var.
    </div>
  </div>
</body></html>"""

    text = (
        f"{headline}\n\n"
        f"{explanation}\n\n"
        f"  This-month spend: {spend}\n"
        f"  Monthly budget:   {budget}\n"
        f"  Used:             {pct:.1f}%\n"
        f"  Alert threshold:  {threshold:.0f}%\n"
        f"{cta_text}"
        f"\nReview your usage breakdown by model and tier in the admin dashboard.\n"
        f"\n— {app} budget guardrail"
    )

    return {"subject": subject, "html": html, "text": text}


def _send_via_ses(to_addr: str, from_addr: str, subject: str, html: str, text: str) -> Dict[str, Any]:
    client = _ses_client()
    if client is None:
        return {"sent": False, "reason": "boto3 not available"}
    try:
        resp = client.send_email(
            Source=from_addr,
            Destination={"ToAddresses": [to_addr]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text, "Charset": "UTF-8"},
                    "Html": {"Data": html, "Charset": "UTF-8"},
                },
            },
        )
        return {"sent": True, "message_id": resp.get("MessageId")}
    except (BotoCoreError, ClientError) as e:
        return {"sent": False, "reason": str(e)}


def maybe_send_budget_alert(storage, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Idempotent budget-alert dispatch.

    ``snapshot`` is the dict returned by ``_build_budget_response`` in the
    budget GET/PUT lambdas (must contain ``pct_used``,
    ``alert_threshold_pct``, ``monthly_budget_usd``, and
    ``current_month_cost_usd``).

    Returns a status dict that the caller can OPTIONALLY surface back to
    the dashboard for debugging (currently the lambdas do not — we keep
    the response shape identical to before adding alerts).
    """
    status: Dict[str, Any] = {"alerts_enabled": _alerts_enabled()}
    if not _alerts_enabled():
        return status

    pct_used = float(snapshot.get("pct_used") or 0.0)
    threshold = float(snapshot.get("alert_threshold_pct") or 80.0)
    monthly_budget = snapshot.get("monthly_budget_usd")
    if not monthly_budget or monthly_budget <= 0:
        # No budget configured → nothing to alert on.
        status["reason"] = "no_budget_set"
        return status

    level = _classify_state(pct_used, threshold)
    status["level"] = level

    # Reset dedupe slot when we drop back below threshold (e.g. budget raised)
    _reset_if_no_longer_alerting(storage, level)

    if not _should_send(storage, level):
        status["sent"] = False
        status["reason"] = "deduped_or_below_threshold"
        return status

    to_addr = _env("BUDGET_ALERT_TO_EMAIL", _DEFAULT_TO)
    from_addr = _env("BUDGET_ALERT_FROM_EMAIL", _DEFAULT_FROM)
    rendered = _render_email(level, snapshot)
    result = _send_via_ses(to_addr, from_addr, rendered["subject"], rendered["html"], rendered["text"])
    status.update(result)
    status["to"] = to_addr
    status["from"] = from_addr

    if result.get("sent"):
        _record_sent(storage, level)
        print(f"[budget_alert] sent {level} alert to {to_addr} (message_id={result.get('message_id')})")
    else:
        # SES failure should NOT block the dashboard — log only.
        print(f"[budget_alert] SES send failed: {json.dumps(result)}")

    return status
