"""
agent-workload-pdf Lambda handler.

Receives a PDF via API Gateway (POST /api/workload/pdf-parse) and returns
the extracted items list using `pdf_extractor.extract`.

Accepts the PDF as either:
- JSON body with a `pdf_base64` (or `file_data`) field, OR
- multipart/form-data with a `file` part.

CORS is handled inline for both preflight (OPTIONS) and actual POST responses
so the deployed frontend (CloudFront) can call the deployed API Gateway.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import traceback
from typing import Any, Dict, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

os.environ.setdefault("TMPDIR", "/tmp")

from pdf_extractor import extract  # noqa: E402
from s3_storage    import upload_pdf  # noqa: E402


_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Amz-Date,X-Api-Key",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def _resp(status: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {**_CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def _extract_pdf_bytes(event: Dict[str, Any]) -> Optional[bytes]:
    """Pull the PDF bytes out of either a JSON body or a multipart body."""
    body = event.get("body")
    if body is None:
        return None

    # API Gateway sometimes base64-encodes the entire body (binary support).
    raw_body = (
        base64.b64decode(body) if event.get("isBase64Encoded") else (
            body.encode("utf-8") if isinstance(body, str) else body
        )
    )

    headers = event.get("headers") or {}
    content_type = (
        headers.get("content-type")
        or headers.get("Content-Type")
        or ""
    ).lower()

    if "multipart/form-data" in content_type:
        return _parse_multipart(raw_body, content_type)

    # Otherwise assume JSON.
    try:
        payload = json.loads(raw_body)
    except (ValueError, TypeError):
        return None

    for key in ("pdf_base64", "file_data", "fileData"):
        if key in payload and payload[key]:
            try:
                return base64.b64decode(payload[key])
            except Exception:
                return None
    return None


def _parse_multipart(raw_body: bytes, content_type: str) -> Optional[bytes]:
    """Minimal multipart parser that pulls the first file part out of a
    multipart/form-data body. We avoid email/cgi here because email mangles
    binary data and cgi is removed in Python 3.13."""
    boundary_marker = "boundary="
    idx = content_type.find(boundary_marker)
    if idx < 0:
        return None
    boundary = content_type[idx + len(boundary_marker):].strip().strip('"')
    if not boundary:
        return None

    delim = b"--" + boundary.encode("ascii")
    parts = raw_body.split(delim)
    for part in parts:
        # A valid part is "<crlf>headers<crlf><crlf>body<crlf>"
        if not part or part in (b"--\r\n", b"--"):
            continue
        # Strip leading CRLF after the boundary
        part = part.lstrip(b"\r\n")
        # Trailing CRLF before next boundary
        if part.endswith(b"\r\n"):
            part = part[:-2]

        header_end = part.find(b"\r\n\r\n")
        if header_end < 0:
            continue
        header_block = part[:header_end].decode("latin-1", errors="replace").lower()
        body_block = part[header_end + 4:]
        if "filename=" in header_block or "application/pdf" in header_block:
            return body_block
    return None


def _filename_from_event(event: Dict[str, Any]) -> Optional[str]:
    """Best-effort original filename pull. Multipart parts have a
    `filename=...` in their Content-Disposition header; JSON callers may
    pass `filename` alongside `pdf_base64`."""
    body = event.get("body")
    if isinstance(body, str):
        # Quick JSON peek (cheap; we already parse the body in _extract_pdf_bytes
        # but doing it once here avoids decoding binary bodies as JSON).
        if body.startswith("{"):
            try:
                payload = json.loads(body)
                if isinstance(payload, dict):
                    name = payload.get("filename") or payload.get("fileName")
                    if name:
                        return str(name)
            except (ValueError, TypeError):
                pass
    # Try the multipart Content-Disposition header (already parsed bytes
    # in _extract_pdf_bytes; here we just scan the header text).
    headers = event.get("headers") or {}
    content_type = (headers.get("content-type") or headers.get("Content-Type") or "").lower()
    if "multipart/form-data" in content_type and isinstance(body, str):
        try:
            raw = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode("utf-8")
            m = _MULTIPART_FILENAME_RE.search(raw[:4096].decode("latin-1", errors="replace"))
            if m:
                return m.group(1)
        except Exception:  # noqa: BLE001
            pass
    return None


_MULTIPART_FILENAME_RE = re.compile(r'filename="([^"]+)"', re.IGNORECASE)


def lambda_handler(event, context):  # noqa: D401, ANN001 - AWS Lambda signature
    method = (event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method") or "POST").upper()
    if method == "OPTIONS":
        return _resp(200, {"ok": True})

    try:
        pdf_bytes = _extract_pdf_bytes(event)
        if not pdf_bytes:
            return _resp(400, {
                "success": False,
                "message": "No PDF data found in request. Send either JSON {pdf_base64: ...} or multipart/form-data with a 'file' part.",
            })

        result = extract(pdf_bytes)

        # Audit-trail upload. Best-effort: if S3 isn't reachable (local dev,
        # creds missing, etc.) we still return the parsed items so the user
        # gets their autofill. The lifecycle rule on the bucket prefix is
        # what guarantees eventual cleanup - we don't delete here.
        original_filename = _filename_from_event(event)
        s3_info = upload_pdf(pdf_bytes, original_filename)
        result["s3"] = s3_info
        if s3_info.get("uploaded"):
            result["s3Bucket"] = s3_info["bucket"]
            result["s3Key"]    = s3_info["key"]

        return _resp(200 if result["success"] else 422, result)

    except Exception as e:  # noqa: BLE001 - we want the full message in the response
        return _resp(500, {
            "success": False,
            "message": f"PDF parsing failed: {e!s}",
            "traceback": traceback.format_exc(),
        })
