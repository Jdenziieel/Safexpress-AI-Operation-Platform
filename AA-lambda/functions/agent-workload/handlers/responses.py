"""HTTP response helpers shared by every handler.

Returns API-Gateway-style dicts. CORS is always applied so the deployed
frontend (CloudFront) can hit the deployed API Gateway without an OPTIONS
dance per route.
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Dict


CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Amz-Date,X-Api-Key",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
}


def _default_serializer(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        # DynamoDB returns numerics as Decimal; cast to float for JSON.
        return float(obj) if obj % 1 else int(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def make_response(status: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers":   {**CORS_HEADERS, "Content-Type": "application/json"},
        "body":      json.dumps(body, default=_default_serializer),
    }


def ok(data: Any, message: str = "") -> Dict[str, Any]:
    payload: Dict[str, Any] = {"success": True}
    if message:
        payload["message"] = message
    if isinstance(data, dict):
        payload.update(data) if "_inline" in data else payload.update({"data": data})
    else:
        payload["data"] = data
    return make_response(200, payload)


def created(data: Any, message: str = "Created") -> Dict[str, Any]:
    return make_response(201, {"success": True, "message": message, "data": data})


def bad_request(message: str) -> Dict[str, Any]:
    return make_response(400, {"success": False, "message": message})


def not_found(message: str = "Not found") -> Dict[str, Any]:
    return make_response(404, {"success": False, "message": message})


def server_error(message: str) -> Dict[str, Any]:
    return make_response(500, {"success": False, "message": message})
