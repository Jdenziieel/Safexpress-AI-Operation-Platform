"""
S3-backed temporary file storage for Lambda deployments.

Replaces local tempfile.NamedTemporaryFile with S3 storage so uploaded files
persist across Lambda invocations (e.g., when a conversation needs clarification
before the workflow executes).

SETUP:
  1. Create an S3 bucket (or reuse an existing one).
  2. Apply a lifecycle rule to auto-delete objects under the prefix after N days.
     Example AWS CLI:
       aws s3api put-bucket-lifecycle-configuration --bucket YOUR_BUCKET \
         --lifecycle-configuration '{
           "Rules": [{
             "ID": "cleanup-temp-uploads",
             "Filter": {"Prefix": "temp-uploads/"},
             "Status": "Enabled",
             "Expiration": {"Days": 1}
           }]
         }'
  3. Set env vars:
       TEMP_STORAGE_BACKEND=s3
       S3_TEMP_BUCKET=your-bucket-name
       S3_TEMP_PREFIX=temp-uploads/         (optional, default: temp-uploads/)
       S3_TEMP_TTL_HOURS=24                 (optional, for presigned URL expiry)
       TEMP_MAX_FILE_SIZE_MB=50             (optional, default: 50 MB)

LIMITATIONS:
  - Agents that read file_path from local disk (gdrive-agent upload_file,
    mapping-agent parse_file with path mode) require the file to be downloaded
    from S3 to /tmp first.  The orchestrator handles this automatically via
    resolve_file_to_local_path().
  - Lambda /tmp is capped at 512 MB (default) or 10 GB (with ephemeral storage).
    Files larger than /tmp capacity cannot be processed within a single Lambda.
  - S3 lifecycle rules delete objects on a calendar-day boundary, not exact
    hour.  The TTL_HOURS setting only controls presigned URL expiry and manual
    cleanup scheduling — actual deletion is handled by the lifecycle rule.
  - Cross-region latency: keep the S3 bucket in the same region as Lambda.
  - All services must share the same S3 bucket (or the supervisor must
    download and re-upload when calling remote agents).
"""

import os
import uuid
import tempfile
import shutil
from datetime import datetime
from typing import Optional, Dict, Any
from execution_logger import trace

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STORAGE_BACKEND = os.getenv("TEMP_STORAGE_BACKEND", "local")  # "local" or "s3"
S3_TEMP_BUCKET = os.getenv("S3_TEMP_BUCKET", "")
S3_TEMP_PREFIX = os.getenv("S3_TEMP_PREFIX", "temp-uploads/")
S3_TEMP_TTL_HOURS = int(os.getenv("S3_TEMP_TTL_HOURS", "24"))
MAX_FILE_SIZE_MB = int(os.getenv("TEMP_MAX_FILE_SIZE_MB", "50"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Lazy-init S3 client (only created when backend == "s3")
_s3_client = None


def _get_s3_client():
    """Lazy-init boto3 S3 client — import only when needed."""
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client("s3")
    return _s3_client


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def store_temp_file(file_obj, filename: str, mime_type: str = "application/octet-stream") -> Dict[str, Any]:
    """
    Store an uploaded file and return a metadata dict.

    For local backend:  saves to tempfile, returns {"temp_path": ..., ...}
    For S3 backend:     uploads to S3,      returns {"s3_key": ..., ...}

    Both backends always return:
        filename, size, mime_type, storage_backend
    Plus backend-specific keys (temp_path OR s3_key).

    Args:
        file_obj:  File-like object (from FastAPI UploadFile.file)
        filename:  Original filename
        mime_type: MIME type string

    Raises:
        ValueError: If file exceeds MAX_FILE_SIZE_MB
    """
    if STORAGE_BACKEND == "s3" and S3_TEMP_BUCKET:
        return _store_s3(file_obj, filename, mime_type)
    return _store_local(file_obj, filename, mime_type)


def resolve_file_to_local_path(uploaded_file: Dict[str, Any]) -> str:
    """
    Ensure the uploaded file is available on the local filesystem.

    If already local (temp_path exists on disk), returns that path.
    If stored in S3, downloads to /tmp and returns the local path.

    Use this from IN-PROCESS callers that need to read file bytes themselves
    (e.g. content_enrichment.py extracting text for an LLM). For CROSS-LAMBDA
    dispatch where a sub-agent will open the file on its OWN container, use
    `get_s3_url()` instead — sub-agents have their own `_resolve_to_local_path`
    that downloads from s3:// URLs.

    Returns:
        Absolute local file path (caller is responsible for cleanup).
    """
    local = uploaded_file.get("temp_path")
    if local and os.path.exists(local):
        return local

    s3_key = uploaded_file.get("s3_key")
    if not s3_key:
        raise FileNotFoundError(
            "uploaded_file has no valid temp_path or s3_key — file is unavailable"
        )

    s3 = _get_s3_client()
    ext = os.path.splitext(uploaded_file.get("filename", ""))[-1]
    local_path = os.path.join(tempfile.gettempdir(), f"s3dl_{uuid.uuid4().hex}{ext}")

    trace.step("s3_download", f"Downloading {s3_key} → {local_path}")
    s3.download_file(S3_TEMP_BUCKET, s3_key, local_path)

    uploaded_file["temp_path"] = local_path
    return local_path


def get_s3_url(uploaded_file: Dict[str, Any]) -> Optional[str]:
    """Return an `s3://bucket/key` URL for a stored upload, or None.

    This is the cross-Lambda transport handle: the orchestrator passes this
    URL into a sub-agent's `file_path` argument, and the sub-agent (gmail,
    drive, docs, mapping) downloads it on its own container via its local
    `_resolve_to_local_path` helper. Mirrors the same pattern gmail-agent's
    `_upload_attachment_to_s3` already uses for attachment handoff into
    mapping-agent — see gmail/tools.py:59 and mapping_agent_api.py:60.

    Returns None when the upload is local-only (no `s3_key`) — callers that
    need the file delivered to a remote container should treat this as a
    hard failure, since a local /tmp path won't exist on the sub-agent's
    container. The current callsite (orchestrator substitution) falls back
    to local `temp_path` only when running in single-container dev mode.
    """
    s3_key = uploaded_file.get("s3_key")
    if not s3_key:
        return None
    if not S3_TEMP_BUCKET:
        return None
    return f"s3://{S3_TEMP_BUCKET}/{s3_key}"


def delete_temp_file(uploaded_file: Dict[str, Any]) -> None:
    """
    Clean up the stored file from both local disk and S3.

    Safe to call multiple times — silently ignores missing files.
    """
    # Local cleanup
    local = uploaded_file.get("temp_path")
    if local:
        try:
            os.unlink(local)
        except OSError:
            pass

    # S3 cleanup
    s3_key = uploaded_file.get("s3_key")
    if s3_key and S3_TEMP_BUCKET:
        try:
            s3 = _get_s3_client()
            s3.delete_object(Bucket=S3_TEMP_BUCKET, Key=s3_key)
            trace.step("s3_cleanup", f"Deleted {s3_key}")
        except Exception as e:
            trace.warning(f"S3 cleanup failed for {s3_key}: {e}")


# ---------------------------------------------------------------------------
# Local backend
# ---------------------------------------------------------------------------

def _store_local(file_obj, filename: str, mime_type: str) -> Dict[str, Any]:
    """Save to local temp file (current dev / same-machine deployment)."""
    ext = os.path.splitext(filename)[-1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        shutil.copyfileobj(file_obj, tmp)
        temp_path = tmp.name

    file_size = os.path.getsize(temp_path)
    if file_size > MAX_FILE_SIZE_BYTES:
        os.unlink(temp_path)
        raise ValueError(
            f"File too large: {file_size / 1024 / 1024:.1f} MB exceeds "
            f"limit of {MAX_FILE_SIZE_MB} MB"
        )

    return {
        "filename": filename,
        "temp_path": temp_path,
        "size": file_size,
        "mime_type": mime_type,
        "storage_backend": "local",
    }


# ---------------------------------------------------------------------------
# S3 backend
# ---------------------------------------------------------------------------

def _store_s3(file_obj, filename: str, mime_type: str) -> Dict[str, Any]:
    """Upload to S3 with a unique key under S3_TEMP_PREFIX."""
    # Read into memory to measure size (files are capped at MAX_FILE_SIZE_MB)
    data = file_obj.read()
    file_size = len(data)

    if file_size > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"File too large: {file_size / 1024 / 1024:.1f} MB exceeds "
            f"limit of {MAX_FILE_SIZE_MB} MB"
        )

    # Embed the original filename in the key path so cross-Lambda consumers
    # (gmail-agent / drive-agent / docs-agent / mapping-agent) that use
    # `os.path.basename(key)` to derive the local /tmp filename get the
    # ORIGINAL name back — not the uuid hex. Without this, Gmail attachment
    # MIME headers carry `aa0bf1...pdf` instead of `NonFood_Requisition.pdf`,
    # and the user sees an unrecognisable filename in the draft. Mirrors the
    # established convention in agent-drive/api.py:_upload_download_to_s3
    # (line ~79: `<prefix>/<run_id>/<safe_name>`) and agent-gmail/tools.py:
    # _upload_attachment_to_s3 (`<prefix>/<run_id>/<msg_id>/<safe_name>`).
    # The uuid stays in the path to guarantee uniqueness across same-named
    # uploads. Slash sanitization mirrors agent-gmail/agent-drive.
    safe_name = filename.replace("/", "_").replace("\\", "_") if filename else uuid.uuid4().hex
    date_prefix = datetime.utcnow().strftime("%Y/%m/%d")
    s3_key = f"{S3_TEMP_PREFIX}{date_prefix}/{uuid.uuid4().hex}/{safe_name}"

    s3 = _get_s3_client()
    s3.put_object(
        Bucket=S3_TEMP_BUCKET,
        Key=s3_key,
        Body=data,
        ContentType=mime_type,
        Metadata={"original-filename": filename},
    )
    trace.step("s3_upload", f"Stored {filename} ({file_size} bytes) → s3://{S3_TEMP_BUCKET}/{s3_key}")

    return {
        "filename": filename,
        "s3_key": s3_key,
        "size": file_size,
        "mime_type": mime_type,
        "storage_backend": "s3",
    }
