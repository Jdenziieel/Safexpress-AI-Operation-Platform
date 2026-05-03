"""supervisor-health — GET / and GET /health"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(_HERE, "shared")
for p in (_SHARED, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.lambda_helpers import success_response, options_response


def lambda_handler(event, context):
    method = (event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method") or "").upper()
    if method == "OPTIONS":
        return options_response()

    path = event.get("path") or event.get("rawPath") or ""
    if path.endswith("/health"):
        return success_response({"status": "healthy", "service": "supervisor-agent"})

    return success_response({
        "service": "Supervisor Agent API",
        "version": "1.0.0-aa-lambda",
        "endpoints": {
            "workflow": "/workflow (POST)",
            "threads": "/threads (GET/POST)",
            "logs": "/logs (GET)",
            "logs_search": "/logs/search (GET)",
            "logs_stats": "/logs/stats (GET)",
            "logs_request": "/logs/requests/{request_id} (GET)",
            "admin_logs": "/admin/logs (GET)",
            "admin_activity": "/admin/activity (GET)",
            "admin_health": "/admin/health (GET)",
            "admin_alerts": "/admin/alerts (GET)",
            "admin_metrics": "/admin/metrics (GET)",
            "health": "/health (GET)",
        },
    })
