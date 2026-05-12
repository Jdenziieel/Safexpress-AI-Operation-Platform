"""Smoke tests for the lambda_function handler.

Covers JSON-with-base64 and multipart/form-data input shapes plus the
OPTIONS preflight, all simulated locally without API Gateway.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_MODULE_DIR = _HERE.parent.parent
sys.path.insert(0, str(_MODULE_DIR))


@pytest.fixture(autouse=True)
def _isolate_lambda_module(monkeypatch):
    """Force re-import of `lambda_function` from THIS dir, even if a sibling
    test suite (agent-workload) loaded its own `lambda_function` first.

    Also disables real S3 by default so the upload call in lambda_handler
    just records `uploaded=False` instead of hitting AWS. Individual tests
    can flip this back on and inject a fake client."""
    monkeypatch.setenv("WORKLOAD_S3_ENABLED", "0")
    if sys.path[0] != str(_MODULE_DIR):
        sys.path.insert(0, str(_MODULE_DIR))
    for mod in list(sys.modules):
        if mod in ("lambda_function", "pdf_extractor", "s3_storage"):
            del sys.modules[mod]
    yield


def _get_handler():
    from lambda_function import lambda_handler  # imported lazily, per-test
    return lambda_handler

_REPO_ROOT = _MODULE_DIR.parent.parent.parent
FOOD_PDF = _REPO_ROOT / "Documents" / "workload pdf" / "Food_Requisition.pdf"


@pytest.mark.skipif(not FOOD_PDF.exists(), reason="Food sample PDF missing")
def test_handler_json_base64():
    pdf_bytes = FOOD_PDF.read_bytes()
    event = {
        "httpMethod": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
            "filename": "Food_Requisition.pdf",
        }),
        "isBase64Encoded": False,
    }
    resp = _get_handler()(event, None)
    assert resp["statusCode"] == 200, resp
    body = json.loads(resp["body"])
    assert body["success"] is True
    assert body["palletId"] == "VRMSDSF26427"
    assert len(body["items"]) == 40


@pytest.mark.skipif(not FOOD_PDF.exists(), reason="Food sample PDF missing")
def test_handler_multipart():
    pdf_bytes = FOOD_PDF.read_bytes()
    boundary = "----PytestBoundary12345"
    body_parts = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="Food_Requisition.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode("ascii") + pdf_bytes + f"\r\n--{boundary}--\r\n".encode("ascii")

    event = {
        "httpMethod": "POST",
        "headers": {"Content-Type": f"multipart/form-data; boundary={boundary}"},
        "body": base64.b64encode(body_parts).decode("ascii"),
        "isBase64Encoded": True,
    }
    resp = _get_handler()(event, None)
    assert resp["statusCode"] == 200, resp
    body = json.loads(resp["body"])
    assert body["success"] is True
    assert body["palletId"] == "VRMSDSF26427"
    assert len(body["items"]) == 40


def test_handler_options_preflight():
    event = {"httpMethod": "OPTIONS", "headers": {}, "body": None}
    resp = _get_handler()(event, None)
    assert resp["statusCode"] == 200
    assert "Access-Control-Allow-Origin" in resp["headers"]


def test_handler_missing_body():
    event = {"httpMethod": "POST", "headers": {}, "body": None}
    resp = _get_handler()(event, None)
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert body["success"] is False


@pytest.mark.skipif(not FOOD_PDF.exists(), reason="Food sample PDF missing")
def test_handler_uploads_to_s3_when_enabled(monkeypatch):
    """End-to-end through the handler with S3 turned on + a fake client.

    Verifies that put_object is called with the right bucket/key and that
    the JSON response carries s3Bucket + s3Key the frontend can persist.
    """
    monkeypatch.setenv("WORKLOAD_S3_ENABLED", "1")
    monkeypatch.setenv("WORKLOAD_S3_BUCKET", "frontend-safexpress")
    monkeypatch.setenv("WORKLOAD_S3_PREFIX", "workload-uploads/")
    # Re-import so the env vars take effect.
    for mod in list(sys.modules):
        if mod in ("lambda_function", "pdf_extractor", "s3_storage"):
            del sys.modules[mod]

    import s3_storage
    from unittest.mock import MagicMock
    fake = MagicMock()
    s3_storage.reset_client_for_tests(fake)

    pdf_bytes = FOOD_PDF.read_bytes()
    event = {
        "httpMethod": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
            "filename":   "Food_Requisition.pdf",
        }),
        "isBase64Encoded": False,
    }

    from lambda_function import lambda_handler
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 200, resp
    body = json.loads(resp["body"])

    assert body["s3Bucket"] == "frontend-safexpress"
    assert body["s3Key"].startswith("workload-uploads/")
    assert body["s3Key"].endswith("/Food_Requisition.pdf")

    fake.put_object.assert_called_once()
    kw = fake.put_object.call_args.kwargs
    assert kw["Bucket"]      == "frontend-safexpress"
    assert kw["ContentType"] == "application/pdf"
    assert kw["Body"]        == pdf_bytes
    assert kw["Key"]         == body["s3Key"]


@pytest.mark.skipif(not FOOD_PDF.exists(), reason="Food sample PDF missing")
def test_handler_succeeds_when_s3_disabled():
    """When S3 is off, parse still works; s3Key just isn't in the response."""
    pdf_bytes = FOOD_PDF.read_bytes()
    event = {
        "httpMethod": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
        }),
        "isBase64Encoded": False,
    }
    resp = _get_handler()(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["success"] is True
    assert len(body["items"]) == 40
    # Top-level convenience keys are absent because upload was skipped.
    assert body.get("s3Key") in (None, "")
    # The full s3 info block is still attached so the frontend can show why.
    assert body["s3"]["uploaded"] is False
    assert "disabled" in (body["s3"]["reason"] or "").lower()
