"""supervisor-admin-alerts — GET /admin/alerts"""
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(_HERE, "shared")
for p in (_SHARED, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.lambda_helpers import (
    success_response,
    error_response,
    options_response,
    get_query_param,
    set_request_context_lambda,
)
from shared.persistence_factory import get_log_storage


_RECOMMENDATIONS = {
    "gmail": "Check Gmail API credentials and quota",
    "calendar": "Check Calendar API credentials",
    "gdocs": "Check Google Docs API permissions",
    "sheets": "Check Sheets API permissions",
    "gdrive": "Check Drive API permissions",
    "llm": "Check OpenAI API key and quota",
    "orchestrator": "Review workflow configuration",
}


def lambda_handler(event, context):
    method = (event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return options_response()

    try:
        from pii_redactor import PIIRedactor  # type: ignore
    except ImportError as e:
        return error_response(500, f"PIIRedactor not available: {e}")

    try:
        hours = min(int(get_query_param(event, "hours") or 1), 24)
    except (TypeError, ValueError):
        return error_response(400, "hours must be an integer")

    start_time = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"
    storage = get_log_storage()
    with set_request_context_lambda(event):
        try:
            error_logs, _ = storage.get_logs(level="ERROR", start_time=start_time, limit=100)
            critical_logs, _ = storage.get_logs(level="CRITICAL", start_time=start_time, limit=100)
            warning_logs, _ = storage.get_logs(level="WARNING", start_time=start_time, limit=100)
        except Exception as e:
            return error_response(500, f"Error retrieving alerts: {e}")

    error_groups = defaultdict(list)
    for log in error_logs + critical_logs:
        component = log.get("component", "system")
        error_groups[component].append(log)

    alerts = []
    for component, logs in error_groups.items():
        agent_info = PIIRedactor.get_agent_friendly_name(component)
        critical_count = sum(1 for l in logs if l.get("level") == "CRITICAL")
        severity = "critical" if critical_count > 0 else "high"
        message = (
            f"{agent_info['name']} encountered an error" if len(logs) == 1
            else f"{agent_info['name']} encountered {len(logs)} errors"
        )
        alerts.append({
            "type": "error",
            "severity": severity,
            "icon": agent_info["icon"],
            "component": component,
            "component_friendly": agent_info["name"],
            "message": message,
            "count": len(logs),
            "first_occurred": logs[-1].get("timestamp") if logs else None,
            "last_occurred": logs[0].get("timestamp") if logs else None,
            "recommendation": _RECOMMENDATIONS.get(component, "Review system logs"),
        })
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    alerts.sort(key=lambda x: (severity_order.get(x["severity"], 99), -x["count"]))

    return success_response({
        "alerts": alerts,
        "summary": {
            "critical_count": sum(1 for a in alerts if a["severity"] == "critical"),
            "error_count": len(error_logs) + len(critical_logs),
            "warning_count": len(warning_logs),
            "time_period_hours": hours,
        },
        "time_range": {"start": start_time, "end": datetime.utcnow().isoformat() + "Z"},
        "_privacy": {"pii_redacted": True, "error_details_hidden": True, "safe_for_admin_viewing": True},
    })
