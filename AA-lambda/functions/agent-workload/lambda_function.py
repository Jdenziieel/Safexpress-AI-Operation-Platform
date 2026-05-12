"""
agent-workload Lambda entrypoint.

Routes API Gateway events to the right handler based on the resource path
and HTTP method. Supports both API Gateway REST (`resource`/`pathParameters`)
and HTTP API v2 (`routeKey`) event shapes so the same code works whichever
integration is chosen at deploy time.

Recognised routes:

    GET    /api/health
    GET    /api/config           (per-user)
    POST   /api/config           (per-user; saves caller's personal rates)
    DELETE /api/config           (per-user; reverts to org default)
    GET    /api/uom
    POST   /api/uom
    DELETE /api/uom/{uom}
    POST   /api/workload/calculate
    GET    /api/workload/history
    GET    /api/workload/history/{id}
    DELETE /api/workload/history/{id}

Any unknown route returns 404 with CORS headers attached so the frontend can
see the body.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Any, Dict

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

os.environ.setdefault("TMPDIR", "/tmp")

from handlers.config   import (
    handle_delete_config, handle_get_config, handle_post_config,
)
from handlers.history  import (
    handle_calculate, handle_delete_history,
    handle_get_history, handle_list_history,
)
from handlers.responses import make_response, not_found
from handlers.uom      import handle_add_uom, handle_delete_uom, handle_list_uoms


def _method(event: Dict[str, Any]) -> str:
    return (
        event.get("httpMethod")
        or event.get("requestContext", {}).get("http", {}).get("method")
        or "GET"
    ).upper()


def _path(event: Dict[str, Any]) -> str:
    # API Gateway REST: `path` or `resource`. HTTP API v2: `rawPath` or
    # routeKey like "POST /api/workload/calculate".
    path = (
        event.get("path")
        or event.get("rawPath")
        or event.get("requestContext", {}).get("http", {}).get("path")
    )
    if path:
        return path
    route_key = event.get("routeKey") or ""
    if " " in route_key:
        return route_key.split(" ", 1)[1]
    return event.get("resource") or "/"


# ----- route matchers --------------------------------------------------


_UOM_RE      = re.compile(r"^/api/uom/(?P<uom>[^/]+)/?$")
_HISTORY_RE  = re.compile(r"^/api/workload/history/(?P<id>[^/]+)/?$")


def lambda_handler(event, context):  # noqa: ANN001
    method = _method(event)
    path   = _path(event).rstrip("/") or "/"

    if method == "OPTIONS":
        return make_response(200, {"ok": True})

    if path == "/api/health":
        return make_response(200, {"success": True,
                                   "message": "Workload Analysis API is running"})

    if path == "/api/config":
        if method == "GET":
            return handle_get_config(event)
        if method == "POST":
            return handle_post_config(event)
        if method == "DELETE":
            return handle_delete_config(event)

    if path == "/api/uom":
        if method == "GET":
            return handle_list_uoms(event)
        if method == "POST":
            return handle_add_uom(event)

    m = _UOM_RE.match(path)
    if m and method == "DELETE":
        return handle_delete_uom(event, m.group("uom"))

    if path == "/api/workload/calculate" and method == "POST":
        return handle_calculate(event)

    if path == "/api/workload/history" and method == "GET":
        return handle_list_history(event)

    m = _HISTORY_RE.match(path)
    if m:
        if method == "GET":
            return handle_get_history(event, m.group("id"))
        if method == "DELETE":
            return handle_delete_history(event, m.group("id"))

    return not_found(f"No route matches {method} {path}")
