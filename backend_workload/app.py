"""
Workload Analysis - local Flask dev server.

This is a THIN shim around the same handler modules used by the deployed
Lambda (`AA-lambda/functions/agent-workload/`). The Flask app translates
each HTTP request into a Lambda-shaped event, calls `lambda_handler`, and
returns the response. This keeps business logic in one place so the local
dev experience and prod behaviour can never drift.

Run:
    python backend_workload/app.py

Configuration (env vars; all optional):
    WORKLOAD_STORAGE=sqlite|dynamodb   default sqlite (local) / dynamodb (Lambda)
    WORKLOAD_SQLITE_PATH=workload.db   path for the sqlite fallback file
    WORKLOAD_DEV_PORT=5003             match the frontend's VITE_WORKLOAD_API_BASE
    WORKLOAD_PDF_HANDLER=1             also mount /api/workload/pdf-parse
                                       (set to 0 if you don't have pdfplumber installed)
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

# Make the deployed-Lambda code importable WITHOUT packaging.
_REPO_ROOT          = Path(__file__).resolve().parent.parent
_AGENT_WORKLOAD_DIR = _REPO_ROOT / "AA-lambda" / "functions" / "agent-workload"
_PDF_AGENT_DIR      = _REPO_ROOT / "AA-lambda" / "functions" / "agent-workload-pdf"

sys.path.insert(0, str(_AGENT_WORKLOAD_DIR))

os.environ.setdefault("WORKLOAD_STORAGE",      "sqlite")
os.environ.setdefault("WORKLOAD_SQLITE_PATH",  str(Path(__file__).resolve().parent / "workload.db"))

from flask import Flask, jsonify, request  # noqa: E402
from flask_cors import CORS                # noqa: E402

# Both lambdas use the AWS convention of `lambda_function.lambda_handler`,
# which collides in Python's module cache. Load each one under a unique
# alias via importlib.util so we can call both from the same process.
import importlib.util  # noqa: E402


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_workload_module = _load_module(
    "_workload_lambda_module",
    _AGENT_WORKLOAD_DIR / "lambda_function.py",
)
workload_handler = _workload_module.lambda_handler

_PDF_HANDLER_AVAILABLE = False
pdf_handler = None
if os.environ.get("WORKLOAD_PDF_HANDLER", "1") == "1":
    sys.path.insert(0, str(_PDF_AGENT_DIR))
    try:
        _pdf_module = _load_module(
            "_pdf_lambda_module",
            _PDF_AGENT_DIR / "lambda_function.py",
        )
        pdf_handler = _pdf_module.lambda_handler
        _PDF_HANDLER_AVAILABLE = True
    except ImportError as e:
        print(f"[backend_workload] PDF handler disabled: {e}")


app = Flask(__name__)
CORS(app)  # mirror the production API Gateway CORS


def _flask_to_lambda_event() -> dict:
    """Build a Lambda-API-Gateway-shaped event from the current Flask request."""
    body = request.get_data() or b""
    is_b64 = False
    payload = None
    if body:
        # If the body is text (JSON), keep it as-is. If binary (multipart PDF
        # upload), base64-encode it and set isBase64Encoded so the Lambda
        # handler decodes it correctly.
        try:
            body.decode("utf-8")
            payload = body.decode("utf-8")
        except UnicodeDecodeError:
            payload = base64.b64encode(body).decode("ascii")
            is_b64 = True

    return {
        "httpMethod": request.method,
        "path":       request.path,
        "headers":    {k: v for k, v in request.headers.items()},
        "body":       payload,
        "isBase64Encoded": is_b64,
        "queryStringParameters": request.args.to_dict(flat=True) or None,
    }


def _lambda_to_flask(resp: dict):
    body = resp.get("body") or ""
    headers = {k: v for k, v in (resp.get("headers") or {}).items()
               if k.lower() != "content-type"}
    return (
        body,
        resp.get("statusCode", 200),
        {"Content-Type": (resp.get("headers") or {}).get("Content-Type", "application/json"), **headers},
    )


# ------------------------------------------------------------------
# Workload routes (config / uom / history / calculate / health)
# ------------------------------------------------------------------


@app.route("/api/health",                           methods=["GET", "OPTIONS"])
@app.route("/api/config",                           methods=["GET", "POST", "OPTIONS"])
@app.route("/api/uom",                              methods=["GET", "POST", "OPTIONS"])
@app.route("/api/uom/<uom>",                        methods=["DELETE", "OPTIONS"])
@app.route("/api/workload/calculate",               methods=["POST", "OPTIONS"])
@app.route("/api/workload/history",                 methods=["GET", "OPTIONS"])
@app.route("/api/workload/history/<history_id>",    methods=["GET", "DELETE", "OPTIONS"])
def workload_routes(*args, **kwargs):  # noqa: D401, ARG001
    event = _flask_to_lambda_event()
    return _lambda_to_flask(workload_handler(event, None))


# ------------------------------------------------------------------
# PDF parsing route (optional - requires pdfplumber)
# ------------------------------------------------------------------


@app.route("/api/workload/pdf-parse", methods=["POST", "OPTIONS"])
def pdf_route():
    if not _PDF_HANDLER_AVAILABLE:
        return jsonify({
            "success": False,
            "message": "PDF handler not installed. Run 'pip install pdfplumber' and set WORKLOAD_PDF_HANDLER=1.",
        }), 503
    event = _flask_to_lambda_event()
    return _lambda_to_flask(pdf_handler(event, None))


# ------------------------------------------------------------------
# Catch-all (mirrors Lambda's 404)
# ------------------------------------------------------------------


@app.errorhandler(404)
def _not_found(_):
    return jsonify({"success": False, "message": "Not found"}), 404


def _print_banner(port: int) -> None:
    storage = os.environ["WORKLOAD_STORAGE"]
    print("=" * 60)
    print("  Workload Analysis - local dev server")
    print("=" * 60)
    print(f"  Storage backend  : {storage}")
    if storage == "sqlite":
        print(f"  SQLite file      : {os.environ['WORKLOAD_SQLITE_PATH']}")
    print(f"  PDF handler      : {'enabled' if _PDF_HANDLER_AVAILABLE else 'disabled'}")
    print(f"  Listening on     : http://localhost:{port}")
    print("  Frontend env var : VITE_WORKLOAD_API_BASE=http://localhost:" + str(port) + "/api")
    print("=" * 60)


if __name__ == "__main__":
    port = int(os.environ.get("WORKLOAD_DEV_PORT", "5003"))
    _print_banner(port)
    app.run(debug=True, port=port, host="0.0.0.0")
