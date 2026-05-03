"""
Smoke test for the LIGHT-ZIP supervisor functions after the requirements
tiering split.

Validates that:
  1. The light requirements.txt set is sufficient — none of the 31 light
     functions transitively pull in LangChain / OpenAI / LangGraph /
     tiktoken / jinja2 / pdfplumber / pymupdf during import.
  2. ``set_request_context_lambda`` (which lazy-imports logging_config)
     only needs httpx + pydantic + boto3, all of which ARE in the light
     set.
  3. ``get_thread_manager()`` / ``get_log_storage()`` resolve to the
     DynamoDB backend without dragging in the brain.

Run with the build/<function-name>/ folder on PYTHONPATH so we exercise
the same site-packages set that the deployed ZIP would have.

Usage:
    python scripts\_smoke_light.py supervisor-list-threads
"""
from __future__ import annotations

import importlib
import os
import sys
import traceback
from pathlib import Path


HEAVY_FORBIDDEN = {
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langgraph",
    "langgraph_checkpoint",
    "langgraph_prebuilt",
    "langgraph_sdk",
    "openai",
    "tiktoken",
    "jinja2",
    "MarkupSafe",
    "tenacity",
    "orjson",
    "ormsgpack",
    "regex",
    "pdfplumber",
    "pymupdf",
    "fitz",
    "pandas",
    "numpy",
    "fastapi",
    "starlette",
    "uvicorn",
}


def smoke(function_name: str) -> int:
    root = Path(__file__).resolve().parent.parent
    build_dir = root / "build" / function_name
    if not build_dir.is_dir():
        print(f"[fail] build dir missing: {build_dir}")
        print(f"       run `.\\build-lambda.ps1 -Function {function_name}` first")
        return 1

    # Mimic the Lambda runtime layout: /var/task is on sys.path with the
    # function folder + installed deps flattened together. Each light
    # lambda_function.py also adds _HERE/shared to sys.path so the brain
    # modules under build/<fn>/shared/ resolve as top-level imports
    # (e.g. ``from models.models import ...``, ``from dynamodb_thread_manager
    # import ...``) — replicate that here so the smoke test exercises the
    # exact runtime import chain.
    sys.path.insert(0, str(build_dir))
    shared_dir = build_dir / "shared"
    if shared_dir.is_dir():
        sys.path.insert(0, str(shared_dir))

    # Force the DDB backend so persistence_factory resolves to
    # dynamodb_thread_manager. We don't actually call AWS — just confirm
    # the import chain works.
    os.environ.setdefault("PERSISTENCE_BACKEND", "dynamodb")
    os.environ.setdefault("AWS_LAMBDA_FUNCTION_NAME", "smoke-test")
    # Stop boto3 from looking up real creds at import time.
    os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-1")

    try:
        # The standard prelude that EVERY light Lambda runs.
        from shared.lambda_helpers import (  # noqa: F401
            success_response,
            error_response,
            options_response,
            parse_body,
            set_request_context_lambda,
            quota_check,
            install_persistence_backend,
        )
        from shared.persistence_factory import (  # noqa: F401
            get_thread_manager,
            get_log_storage,
        )
        from models.models import ThreadMetadata  # noqa: F401

        # Trigger the lazy import inside set_request_context_lambda so we
        # surface any logging_config import failure here rather than at
        # runtime.
        from logging_config import set_request_context  # noqa: F401

        # Touch the DDB modules so we know they parse end-to-end.
        from dynamodb_thread_manager import ThreadManager  # noqa: F401
        from dynamodb_log_storage import LogStorage  # noqa: F401

    except Exception as e:
        print(f"[fail] import chain broken for {function_name}: {e}")
        traceback.print_exc()
        return 1

    # Now check no forbidden heavy modules ended up in sys.modules.
    leaked = sorted(m for m in HEAVY_FORBIDDEN if m in sys.modules)
    if leaked:
        print(f"[fail] heavy module(s) leaked into light import chain:")
        for m in leaked:
            print(f"         {m}")
        return 1

    print(f"[ok] {function_name} import chain is clean — no heavy deps pulled in")
    print(f"     loaded modules: {len(sys.modules)} total")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/_smoke_light.py <function-name>")
        sys.exit(2)
    sys.exit(smoke(sys.argv[1]))
