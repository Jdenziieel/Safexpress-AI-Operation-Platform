"""
S3 storage helper for the agent-workload-pdf Lambda.

Uploads the PMRL PDF that arrived on the parse call so the workload history
record can link back to the original document for audit purposes. Lives
under a dedicated prefix on the project's shared bucket so a 1-day
lifecycle rule can sweep stale uploads without touching anything else.

Bucket convention (see .cursor/rules/system-architecture.mdc and
AA-lambda/functions/agent-drive/api.py:49-99):
    - `frontend-safexpress` is the project's shared bucket
    - The AA-Lambda-Execution-Role already has S3 r/w on it
    - Each feature gets its own prefix (gmail-attachments/, drive-downloads/...)
    - We add `workload-uploads/` for PMRL PDFs

Design goals:
    1. Lazy boto3 import - parse still works without AWS creds (local dev).
    2. Graceful degrade - if the upload fails or the bucket env var is
       unset, the parse response just lacks the s3Key. The user still gets
       the extracted items.
    3. Key layout matches the rest of the project:
       `workload-uploads/<YYYY>/<MM>/<DD>/<uuid>/<safe_filename>`
       - Per-upload uuid prevents collisions
       - Date prefix keeps the bucket browsable
       - Original filename preserved for audit
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Project's shared bucket. Override per-environment via WORKLOAD_S3_BUCKET.
# Default mirrors the bucket the AA-Lambda-Execution-Role already has access to.
S3_BUCKET = os.environ.get("WORKLOAD_S3_BUCKET", "frontend-safexpress")

# New prefix dedicated to this feature; won't collide with gmail-attachments/
# drive-downloads/ temp-uploads/. The trailing slash is required so the
# lifecycle rule's Filter.Prefix matches every object inside.
S3_PREFIX = os.environ.get("WORKLOAD_S3_PREFIX", "workload-uploads/").rstrip("/") + "/"

# Skip the upload entirely (and silently) when this is "0". Useful for the
# local Flask dev shim where AWS creds may be absent.
S3_ENABLED = os.environ.get("WORKLOAD_S3_ENABLED", "1") not in ("0", "false", "False", "")

# Hard cap so a maliciously huge file can't blow the Lambda's memory.
MAX_PDF_BYTES = int(os.environ.get("WORKLOAD_S3_MAX_BYTES", str(50 * 1024 * 1024)))

_s3_client = None


def _get_client():
    """Lazy boto3 init. Returns None if boto3 isn't importable so the parse
    response can still be returned to the user."""
    global _s3_client
    if _s3_client is not None:
        return _s3_client
    try:
        import boto3
        _s3_client = boto3.client("s3")
    except Exception as e:  # noqa: BLE001 - any import/init failure is non-fatal
        print(f"[workload-pdf-s3] boto3 unavailable, S3 disabled: {e}")
        _s3_client = None
    return _s3_client


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(filename: Optional[str]) -> str:
    """Strip path separators / weird chars so the key stays well-formed."""
    if not filename:
        return "upload.pdf"
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return _SAFE_NAME_RE.sub("_", base) or "upload.pdf"


def upload_pdf(pdf_bytes: bytes, original_filename: Optional[str]) -> Dict[str, Any]:
    """Upload the PDF and return an audit-trail descriptor.

    The return shape is always identical so the Lambda handler doesn't need
    branching - missing keys just mean "we couldn't upload". A `disabled`
    field is included so the frontend / test can tell the difference between
    "feature off" and "upload failed".

    Returns:
        {
            "uploaded": bool,
            "bucket":   str | None,
            "key":      str | None,
            "size":     int,
            "filename": str,
            "uploadedAt": ISO timestamp | None,
            "reason":   str | None,   # populated when uploaded=False
        }
    """
    safe_name = _safe_filename(original_filename)
    size = len(pdf_bytes or b"")
    result: Dict[str, Any] = {
        "uploaded":   False,
        "bucket":     None,
        "key":        None,
        "size":       size,
        "filename":   safe_name,
        "uploadedAt": None,
        "reason":     None,
    }

    if not S3_ENABLED:
        result["reason"] = "S3 disabled via WORKLOAD_S3_ENABLED=0"
        return result
    if not S3_BUCKET:
        result["reason"] = "WORKLOAD_S3_BUCKET env var is empty"
        return result
    if size == 0:
        result["reason"] = "Empty PDF body"
        return result
    if size > MAX_PDF_BYTES:
        result["reason"] = f"PDF exceeds WORKLOAD_S3_MAX_BYTES ({MAX_PDF_BYTES} bytes)"
        return result

    client = _get_client()
    if client is None:
        result["reason"] = "boto3 client unavailable"
        return result

    now = datetime.now(timezone.utc)
    key = f"{S3_PREFIX}{now:%Y/%m/%d}/{uuid.uuid4().hex}/{safe_name}"

    try:
        client.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=pdf_bytes,
            ContentType="application/pdf",
            # Metadata is also stored on the object so the s3 cli/console
            # shows the original filename even if our key gets sanitized.
            Metadata={
                "original-filename": (original_filename or "upload.pdf")[:1024],
                "uploaded-by":       "agent-workload-pdf",
            },
        )
    except Exception as e:  # noqa: BLE001 - any S3 failure is non-fatal
        print(f"[workload-pdf-s3] put_object failed for {key}: {e}")
        result["reason"] = f"S3 put_object failed: {e}"
        return result

    result["uploaded"]   = True
    result["bucket"]     = S3_BUCKET
    result["key"]        = key
    result["uploadedAt"] = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return result


def reset_client_for_tests(client_obj=None) -> None:
    """Tests inject a mocked boto3 client through this hook so put_object is
    exercised without touching real AWS."""
    global _s3_client
    _s3_client = client_obj
