"""GET / POST / DELETE /api/uom handlers."""
from __future__ import annotations

import json
from typing import Any, Dict

from .responses import bad_request, make_response, server_error
from .storage import get_storage


def handle_list_uoms(event: Dict[str, Any]) -> Dict[str, Any]:
    try:
        uoms = get_storage().list_uoms()
        return make_response(200, {"success": True, "data": uoms})
    except Exception as e:  # noqa: BLE001
        return server_error(str(e))


def handle_add_uom(event: Dict[str, Any]) -> Dict[str, Any]:
    body = _parse_body(event)
    if body is None:
        return bad_request("Body must be valid JSON")
    uom = (body.get("uom") or "").strip()
    if not uom:
        return bad_request("uom is required")
    try:
        uoms = get_storage().add_uom(uom)
        return make_response(200, {
            "success": True,
            "message": f"UOM {uom!r} added",
            "data":    uoms,
        })
    except Exception as e:  # noqa: BLE001
        return server_error(str(e))


def handle_delete_uom(event: Dict[str, Any], uom: str) -> Dict[str, Any]:
    try:
        uoms = get_storage().delete_uom(uom)
        return make_response(200, {
            "success": True,
            "message": f"UOM {uom!r} deleted",
            "data":    uoms,
        })
    except Exception as e:  # noqa: BLE001
        return server_error(str(e))


def _parse_body(event: Dict[str, Any]) -> Any:
    body = event.get("body")
    if body is None:
        return {}
    if isinstance(body, (dict, list)):
        return body
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        return None
