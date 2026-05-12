"""End-to-end handler tests using the SQLite storage backend in a tmp dir.

Exercises the full API surface (config/uom/history/calculate) through the
Lambda router (`lambda_function.lambda_handler`) without ever touching AWS.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

_MODULE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MODULE_DIR))


@pytest.fixture(autouse=True)
def _fresh_sqlite_storage(tmp_path, monkeypatch):
    """Each test gets its own SQLite file + a freshly imported handlers module."""
    db = tmp_path / "workload.db"
    monkeypatch.setenv("WORKLOAD_STORAGE", "sqlite")
    monkeypatch.setenv("WORKLOAD_SQLITE_PATH", str(db))
    # Make agent-workload's lambda_function win module resolution even when
    # the sibling agent-workload-pdf tests have already polluted sys.path.
    if sys.path[0] != str(_MODULE_DIR):
        sys.path.insert(0, str(_MODULE_DIR))
    # Reset cached module state so the storage singleton picks up new env
    # vars AND so 'lambda_function' is re-imported from the directory above.
    for mod in list(sys.modules):
        if mod.startswith(("handlers", "lambda_function")):
            del sys.modules[mod]
    yield


def _invoke(method: str, path: str, body=None, qs=None, user_id=None):
    """Mirror an API Gateway HTTP API v2 event. When `user_id` is provided
    we drop it into the same `requestContext.authorizer.lambda` slot the
    real JWT authorizer fills in, so the per-user code paths get exercised."""
    from lambda_function import lambda_handler  # imported per-test (cache reset above)
    event = {
        "httpMethod": method,
        "path":       path,
        "headers":    {"Content-Type": "application/json"},
        "body":       json.dumps(body) if body is not None else None,
        "queryStringParameters": qs or {},
    }
    if user_id is not None:
        event["requestContext"] = {
            "authorizer": {"lambda": {"userId": user_id, "userEmail": user_id}}
        }
    return lambda_handler(event, None)


def _body(resp):
    return json.loads(resp["body"])


# ---------- health -----------------------------------------------------


def test_health_route():
    resp = _invoke("GET", "/api/health")
    assert resp["statusCode"] == 200
    assert _body(resp)["success"] is True


# ---------- config -----------------------------------------------------


def test_get_config_returns_defaults():
    resp = _invoke("GET", "/api/config")
    assert resp["statusCode"] == 200
    cfg = _body(resp)["data"]
    assert cfg["inboundCheckingSecPerPallet"] == 215.07
    assert cfg["pickingSecPerPiece"]          == 5.72


def test_post_config_persists_and_get_returns_new_value():
    resp = _invoke("POST", "/api/config", body={
        "inboundCheckingSecPerPallet": 250.5,
        "updatedBy": "tester",
    })
    assert resp["statusCode"] == 200

    resp = _invoke("GET", "/api/config")
    cfg = _body(resp)["data"]
    assert cfg["inboundCheckingSecPerPallet"] == 250.5
    # Untouched rates fall back to default.
    assert cfg["putAwaySecPerPallet"] == 118.95
    assert cfg["updatedBy"] == "tester"


# ---------- uom --------------------------------------------------------


def test_uom_default_list_contains_seed():
    resp = _invoke("GET", "/api/uom")
    uoms = _body(resp)["data"]
    for required in ("Pack", "Case", "Can", "Bottle", "Container", "Pcs", "Pallet"):
        assert required in uoms


def test_uom_add_and_delete_roundtrip():
    add = _invoke("POST", "/api/uom", body={"uom": "Sachet"})
    assert add["statusCode"] == 200
    assert "Sachet" in _body(add)["data"]

    delete = _invoke("DELETE", "/api/uom/Sachet")
    assert delete["statusCode"] == 200
    assert "Sachet" not in _body(delete)["data"]


def test_uom_add_rejects_blank():
    resp = _invoke("POST", "/api/uom", body={"uom": "   "})
    assert resp["statusCode"] == 400


# ---------- calculate + history ----------------------------------------


_PAYLOAD = {
    "mode":    "inbound",
    "basis":   "per_pallet",
    "workers": 4,
    "pallets": [{
        "palletId": "VRMSDSF26427",
        "sourceFilename": "Food_Requisition.pdf",
        "items": [
            {"itemCode": "RMFD00810030020", "description": "Bread Crumbs", "qty": 10, "uom": "Pack"},
        ],
    }],
}


def test_calculate_returns_breakdown_and_saves_history():
    resp = _invoke("POST", "/api/workload/calculate", body=_PAYLOAD)
    assert resp["statusCode"] == 200, resp
    data = _body(resp)["data"]
    assert data["palletCount"] == 1
    assert "id" in data
    history_id = data["id"]

    # List should have 1 record
    listing = _invoke("GET", "/api/workload/history", qs={"limit": "10"})
    body = _body(listing)
    assert body["pagination"]["total"] == 1
    assert body["data"][0]["id"] == history_id

    # Single GET
    single = _invoke("GET", f"/api/workload/history/{history_id}")
    assert single["statusCode"] == 200

    # Delete
    deleted = _invoke("DELETE", f"/api/workload/history/{history_id}")
    assert deleted["statusCode"] == 200

    # Now missing
    after = _invoke("GET", f"/api/workload/history/{history_id}")
    assert after["statusCode"] == 404


def test_calculate_validation_error_returns_400():
    bad = {**_PAYLOAD, "mode": "sideways"}
    resp = _invoke("POST", "/api/workload/calculate", body=bad)
    assert resp["statusCode"] == 400


def test_calculate_with_save_false_does_not_persist():
    payload = {**_PAYLOAD, "save": False}
    resp = _invoke("POST", "/api/workload/calculate", body=payload)
    assert resp["statusCode"] == 200
    data = _body(resp)["data"]
    assert "id" not in data
    listing = _invoke("GET", "/api/workload/history")
    assert _body(listing)["pagination"]["total"] == 0


def test_history_filter_by_mode():
    _invoke("POST", "/api/workload/calculate", body=_PAYLOAD)
    outbound = {**_PAYLOAD, "mode": "outbound", "basis": "per_piece"}
    _invoke("POST", "/api/workload/calculate", body=outbound)

    in_list  = _body(_invoke("GET", "/api/workload/history", qs={"mode": "inbound"}))
    out_list = _body(_invoke("GET", "/api/workload/history", qs={"mode": "outbound"}))
    assert in_list["pagination"]["total"]  == 1
    assert out_list["pagination"]["total"] == 1
    assert in_list["data"][0]["mode"]  == "inbound"
    assert out_list["data"][0]["mode"] == "outbound"


def test_unknown_route_returns_404():
    resp = _invoke("GET", "/api/does-not-exist")
    assert resp["statusCode"] == 404


def test_options_preflight_returns_cors_headers():
    from lambda_function import lambda_handler
    event = {"httpMethod": "OPTIONS", "path": "/api/config", "body": None}
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 200
    assert resp["headers"]["Access-Control-Allow-Origin"] == "*"


# ---------- per-user isolation -----------------------------------------


def test_config_isolation_per_user():
    """Saving rates as user A must NOT change what user B sees."""
    a, b = "alice@safexpress", "bob@safexpress"

    # Both users start on the org default (215.07).
    assert _body(_invoke("GET", "/api/config", user_id=a))["data"]["inboundCheckingSecPerPallet"] == 215.07
    assert _body(_invoke("GET", "/api/config", user_id=b))["data"]["inboundCheckingSecPerPallet"] == 215.07

    # Alice customises.
    _invoke("POST", "/api/config", body={"inboundCheckingSecPerPallet": 300.0}, user_id=a)

    cfg_a = _body(_invoke("GET", "/api/config", user_id=a))["data"]
    cfg_b = _body(_invoke("GET", "/api/config", user_id=b))["data"]

    assert cfg_a["inboundCheckingSecPerPallet"] == 300.0
    assert cfg_a["isDefault"] is False
    assert cfg_a["inheritedFromDefault"] is False
    # Bob STILL sees the org default, untouched.
    assert cfg_b["inboundCheckingSecPerPallet"] == 215.07
    assert cfg_b["inheritedFromDefault"] is True


def test_config_delete_reverts_to_org_default():
    user = "carol@safexpress"
    _invoke("POST", "/api/config", body={"pickingSecPerPiece": 9.99}, user_id=user)
    assert _body(_invoke("GET", "/api/config", user_id=user))["data"]["pickingSecPerPiece"] == 9.99

    delete = _invoke("DELETE", "/api/config", user_id=user)
    assert delete["statusCode"] == 200

    after = _body(_invoke("GET", "/api/config", user_id=user))["data"]
    assert after["pickingSecPerPiece"] == 5.72  # back to org default
    assert after["inheritedFromDefault"] is True


def test_history_isolation_list():
    """User A's calc must not appear in User B's history listing."""
    a, b = "alice@safexpress", "bob@safexpress"
    _invoke("POST", "/api/workload/calculate", body=_PAYLOAD, user_id=a)
    _invoke("POST", "/api/workload/calculate", body=_PAYLOAD, user_id=b)
    _invoke("POST", "/api/workload/calculate", body=_PAYLOAD, user_id=a)

    list_a = _body(_invoke("GET", "/api/workload/history", user_id=a))
    list_b = _body(_invoke("GET", "/api/workload/history", user_id=b))

    assert list_a["pagination"]["total"] == 2
    assert list_b["pagination"]["total"] == 1
    assert all(r["userId"] == a for r in list_a["data"])
    assert all(r["userId"] == b for r in list_b["data"])


def test_history_isolation_cross_user_get_returns_404():
    """User B must not be able to GET user A's calc via direct ID."""
    a, b = "alice@safexpress", "bob@safexpress"
    resp = _invoke("POST", "/api/workload/calculate", body=_PAYLOAD, user_id=a)
    hid = _body(resp)["data"]["id"]

    # Alice can read her own
    assert _invoke("GET", f"/api/workload/history/{hid}", user_id=a)["statusCode"] == 200
    # Bob cannot
    assert _invoke("GET", f"/api/workload/history/{hid}", user_id=b)["statusCode"] == 404


def test_history_isolation_cross_user_delete_returns_404():
    """User B cannot delete user A's calc — and it stays alive."""
    a, b = "alice@safexpress", "bob@safexpress"
    resp = _invoke("POST", "/api/workload/calculate", body=_PAYLOAD, user_id=a)
    hid = _body(resp)["data"]["id"]

    forbidden = _invoke("DELETE", f"/api/workload/history/{hid}", user_id=b)
    assert forbidden["statusCode"] == 404

    # Alice's row is still there
    still = _invoke("GET", f"/api/workload/history/{hid}", user_id=a)
    assert still["statusCode"] == 200


def test_calculate_uses_callers_personal_rates_not_org_default():
    """If user A has set a personal rate, their /calculate call must use it."""
    user = "alice@safexpress"
    _invoke("POST", "/api/config",
            body={"inboundCheckingSecPerPallet": 1000.0, "putAwaySecPerPallet": 0.0},
            user_id=user)

    resp = _invoke("POST", "/api/workload/calculate", body={
        **_PAYLOAD, "save": False,
    }, user_id=user)
    data = _body(resp)["data"]
    # With 1 pallet, 4 workers, inbound per-pallet: total = 1000 / 4 = 250
    assert data["totalSeconds"] == 250.0


def test_anonymous_caller_lands_on_default_partition():
    """An anonymous request reads the org default but writes to it too —
    so the test confirms the legacy single-tenant behaviour still works
    when there's no authorizer in front."""
    assert _body(_invoke("GET", "/api/config"))["data"]["isDefault"] is True
    _invoke("POST", "/api/config", body={"inboundCheckingSecPerPallet": 111.0})
    assert _body(_invoke("GET", "/api/config"))["data"]["inboundCheckingSecPerPallet"] == 111.0
