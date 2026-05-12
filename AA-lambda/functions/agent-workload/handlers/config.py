"""GET / POST / DELETE /api/config handler. Per-user.

Each user has their own rate-config row keyed by `userId` (taken from the
JWT authorizer context). When a user has no personal row, the storage
layer falls back to the org-default row (configKey='__default__') and
finally to the hard-coded `DEFAULT_RATES`.

DELETE /api/config resets the user's personal row so they go back to
inheriting the org default."""
from __future__ import annotations

import json
from typing import Any, Dict

from .auth      import extract_user_id
from .responses import bad_request, make_response, server_error
from .storage   import get_storage


def handle_get_config(event: Dict[str, Any]) -> Dict[str, Any]:
    user_id = extract_user_id(event)
    try:
        cfg = get_storage().get_config(user_id=user_id)
        return make_response(200, {"success": True, "data": cfg})
    except Exception as e:  # noqa: BLE001
        return server_error(str(e))


def handle_post_config(event: Dict[str, Any]) -> Dict[str, Any]:
    body = _parse_body(event)
    if body is None:
        return bad_request("Body must be valid JSON")
    user_id    = extract_user_id(event)
    updated_by = body.pop("updatedBy", None) or user_id or "user"
    try:
        cfg = get_storage().update_config(body, updated_by, user_id=user_id)
        return make_response(200, {
            "success": True,
            "message": "Configuration saved for this user",
            "data":    cfg,
        })
    except Exception as e:  # noqa: BLE001
        return server_error(str(e))


def handle_delete_config(event: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the caller's personal config row so they go back to inheriting
    the org default. No-op for anonymous callers (they're already on the
    default)."""
    user_id = extract_user_id(event)
    try:
        cfg = get_storage().reset_config(user_id=user_id)
        return make_response(200, {
            "success": True,
            "message": "Reverted to organization-default rates",
            "data":    cfg,
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
