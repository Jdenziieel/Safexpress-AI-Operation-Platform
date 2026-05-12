"""POST /api/workload/calculate
GET  /api/workload/history
GET  /api/workload/history/{id}
DELETE /api/workload/history/{id}

Every route is scoped to the caller's userId so users only ever see and
manage their own calculations.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from .auth      import extract_user_id
from .calculate import calculate, CalculationError, DEFAULT_RATES
from .responses import bad_request, make_response, not_found, server_error
from .storage   import get_storage


def handle_calculate(event: Dict[str, Any]) -> Dict[str, Any]:
    body = _parse_body(event)
    if body is None:
        return bad_request("Body must be valid JSON")

    user_id = extract_user_id(event)
    store = get_storage()
    # Stored config is the caller's personal rate set (or the org default
    # if they haven't customised). Per-request overrides via `body.rates`
    # let the user experiment without persisting changes.
    # Merge order: hard-coded defaults < user/org row < per-request overrides.
    stored_cfg     = store.get_config(user_id=user_id)
    stored_rates   = {k: stored_cfg[k] for k in DEFAULT_RATES if k in stored_cfg}
    override_rates = {k: v for k, v in (body.get("rates") or {}).items()
                      if k in DEFAULT_RATES}
    rates = {**stored_rates, **override_rates}

    try:
        result = calculate(body, rates)
    except CalculationError as e:
        return bad_request(str(e))
    except Exception as e:  # noqa: BLE001
        return server_error(str(e))

    save_result = None
    if body.get("save", True):
        try:
            save_result = store.save_history(
                result,
                notes=str(body.get("notes") or ""),
                created_by=str(body.get("createdBy") or user_id or "user"),
                user_id=user_id,
            )
            result["id"]        = save_result["id"]
            result["createdAt"] = save_result["createdAt"]
            result["userId"]    = save_result["userId"]
        except Exception as e:  # noqa: BLE001
            return server_error(f"Calculation succeeded but save failed: {e}")

    return make_response(200, {
        "success": True,
        "message": "Calculation saved successfully" if save_result else "Calculation computed (not saved)",
        "data":    result,
    })


def handle_list_history(event: Dict[str, Any]) -> Dict[str, Any]:
    qs = event.get("queryStringParameters") or {}
    mode    = qs.get("mode")
    limit   = _safe_int(qs.get("limit"),  default=50, lo=1, hi=500)
    offset  = _safe_int(qs.get("offset"), default=0,  lo=0, hi=10000)
    user_id = extract_user_id(event)
    try:
        page = get_storage().list_history(
            mode=mode, limit=limit, offset=offset, user_id=user_id,
        )
        return make_response(200, {
            "success":    True,
            "data":       page["records"],
            "pagination": {
                "total":  page["total"],
                "limit":  page["limit"],
                "offset": page["offset"],
            },
        })
    except Exception as e:  # noqa: BLE001
        return server_error(str(e))


def handle_get_history(event: Dict[str, Any], history_id: str) -> Dict[str, Any]:
    user_id = extract_user_id(event)
    try:
        rec = get_storage().get_history(history_id, user_id=user_id)
        if rec is None:
            # Same 404 whether the row doesn't exist or it belongs to
            # somebody else — avoids leaking the existence of other users'
            # calculation IDs.
            return not_found(f"Calculation {history_id!r} not found")
        return make_response(200, {"success": True, "data": rec})
    except Exception as e:  # noqa: BLE001
        return server_error(str(e))


def handle_delete_history(event: Dict[str, Any], history_id: str) -> Dict[str, Any]:
    user_id = extract_user_id(event)
    try:
        deleted = get_storage().delete_history(history_id, user_id=user_id)
        if not deleted:
            return not_found(f"Calculation {history_id!r} not found")
        return make_response(200, {
            "success": True,
            "message": "Calculation deleted successfully",
        })
    except Exception as e:  # noqa: BLE001
        return server_error(str(e))


# helpers


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


def _safe_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))
