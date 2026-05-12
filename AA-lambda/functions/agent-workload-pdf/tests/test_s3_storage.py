"""Tests for s3_storage.upload_pdf.

Uses a fake S3 client (no moto needed) injected via reset_client_for_tests.
Verifies the happy path puts the right bucket / key / body, and that
graceful-degrade paths return uploaded=False without raising.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_MODULE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MODULE_DIR))


def _fresh_module():
    """Re-import s3_storage so its module-level constants pick up the
    current process environment. A previous test in this session may have
    purged it from sys.modules, so we use a robust import (not reload)."""
    sys.modules.pop("s3_storage", None)
    import importlib
    return importlib.import_module("s3_storage")


@pytest.fixture(autouse=True)
def s3_storage(monkeypatch):
    monkeypatch.setenv("WORKLOAD_S3_BUCKET",   "test-bucket")
    monkeypatch.setenv("WORKLOAD_S3_PREFIX",   "workload-uploads/")
    monkeypatch.setenv("WORKLOAD_S3_ENABLED",  "1")
    monkeypatch.setenv("WORKLOAD_S3_MAX_BYTES", str(10 * 1024 * 1024))
    if sys.path[0] != str(_MODULE_DIR):
        sys.path.insert(0, str(_MODULE_DIR))
    mod = _fresh_module()
    mod.reset_client_for_tests(None)
    yield mod
    mod.reset_client_for_tests(None)


def test_upload_happy_path(s3_storage):
    fake = MagicMock()
    s3_storage.reset_client_for_tests(fake)

    info = s3_storage.upload_pdf(b"%PDF-1.4 test bytes", "Food_Requisition.pdf")

    assert info["uploaded"] is True
    assert info["bucket"]   == "test-bucket"
    assert info["filename"] == "Food_Requisition.pdf"
    assert info["size"]     == len(b"%PDF-1.4 test bytes")
    assert info["reason"]   is None
    assert info["uploadedAt"].endswith("Z")
    assert info["key"].startswith("workload-uploads/")
    assert info["key"].endswith("/Food_Requisition.pdf")

    fake.put_object.assert_called_once()
    kwargs = fake.put_object.call_args.kwargs
    assert kwargs["Bucket"]      == "test-bucket"
    assert kwargs["Key"]         == info["key"]
    assert kwargs["Body"]        == b"%PDF-1.4 test bytes"
    assert kwargs["ContentType"] == "application/pdf"
    assert kwargs["Metadata"]["original-filename"] == "Food_Requisition.pdf"


def test_upload_sanitizes_filename(s3_storage):
    fake = MagicMock()
    s3_storage.reset_client_for_tests(fake)

    info = s3_storage.upload_pdf(b"data", "../etc/passwd weird name.pdf")

    assert info["uploaded"] is True
    # No path separators or spaces in the safe name.
    assert "/" not in info["filename"]
    assert "\\" not in info["filename"]
    assert " " not in info["filename"]
    assert info["filename"].endswith(".pdf")


def test_upload_skipped_when_disabled(monkeypatch):
    monkeypatch.setenv("WORKLOAD_S3_ENABLED", "0")
    monkeypatch.setenv("WORKLOAD_S3_BUCKET",  "test-bucket")
    monkeypatch.setenv("WORKLOAD_S3_PREFIX",  "workload-uploads/")
    monkeypatch.setenv("WORKLOAD_S3_MAX_BYTES", str(10 * 1024 * 1024))
    mod = _fresh_module()
    fake = MagicMock()
    mod.reset_client_for_tests(fake)

    info = mod.upload_pdf(b"data", "x.pdf")
    assert info["uploaded"] is False
    assert "disabled" in (info["reason"] or "").lower()
    fake.put_object.assert_not_called()


def test_upload_skipped_when_bucket_empty(monkeypatch):
    monkeypatch.setenv("WORKLOAD_S3_BUCKET",  "")
    monkeypatch.setenv("WORKLOAD_S3_ENABLED", "1")
    monkeypatch.setenv("WORKLOAD_S3_PREFIX",  "workload-uploads/")
    monkeypatch.setenv("WORKLOAD_S3_MAX_BYTES", str(10 * 1024 * 1024))
    mod = _fresh_module()
    fake = MagicMock()
    mod.reset_client_for_tests(fake)

    info = mod.upload_pdf(b"data", "x.pdf")
    assert info["uploaded"] is False
    assert "bucket" in (info["reason"] or "").lower()
    fake.put_object.assert_not_called()


def test_upload_rejects_empty_body(s3_storage):
    fake = MagicMock()
    s3_storage.reset_client_for_tests(fake)
    info = s3_storage.upload_pdf(b"", "x.pdf")
    assert info["uploaded"] is False
    assert "empty" in (info["reason"] or "").lower()
    fake.put_object.assert_not_called()


def test_upload_rejects_oversize(monkeypatch):
    monkeypatch.setenv("WORKLOAD_S3_BUCKET",  "test-bucket")
    monkeypatch.setenv("WORKLOAD_S3_ENABLED", "1")
    monkeypatch.setenv("WORKLOAD_S3_PREFIX",  "workload-uploads/")
    monkeypatch.setenv("WORKLOAD_S3_MAX_BYTES", "10")
    mod = _fresh_module()
    fake = MagicMock()
    mod.reset_client_for_tests(fake)

    info = mod.upload_pdf(b"more than ten bytes", "x.pdf")
    assert info["uploaded"] is False
    assert "exceeds" in (info["reason"] or "").lower()
    fake.put_object.assert_not_called()


def test_upload_swallows_put_object_failure(s3_storage):
    fake = MagicMock()
    fake.put_object.side_effect = RuntimeError("Network down")
    s3_storage.reset_client_for_tests(fake)

    info = s3_storage.upload_pdf(b"data", "x.pdf")
    # Caller must still get the parsed items, so this must NOT raise.
    assert info["uploaded"] is False
    assert "Network down" in (info["reason"] or "")


def test_key_layout_has_date_and_uuid_and_filename(s3_storage):
    fake = MagicMock()
    s3_storage.reset_client_for_tests(fake)
    info = s3_storage.upload_pdf(b"data", "report.pdf")
    parts = info["key"].split("/")
    # workload-uploads / YYYY / MM / DD / <uuid hex> / report.pdf
    assert parts[0] == "workload-uploads"
    assert len(parts[1]) == 4 and parts[1].isdigit()
    assert len(parts[2]) == 2 and parts[2].isdigit()
    assert len(parts[3]) == 2 and parts[3].isdigit()
    assert len(parts[4]) >= 16
    assert parts[5] == "report.pdf"
