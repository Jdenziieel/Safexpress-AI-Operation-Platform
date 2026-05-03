"""
Persistence backend factory.

Picks SQLite (`thread_manager.ThreadManager` / `log_storage.LogStorage`) or
DynamoDB (`dynamodb_thread_manager.ThreadManager` / `dynamodb_log_storage.LogStorage`)
based on the `PERSISTENCE_BACKEND` env var.

  PERSISTENCE_BACKEND=sqlite      (default for local dev — mirrors supervisor-agent)
  PERSISTENCE_BACKEND=dynamodb    (default for Lambda)

Singletons by default — one ThreadManager / LogStorage per Lambda container,
re-used across warm invocations.
"""

from __future__ import annotations

import os
from typing import Optional

_thread_manager_singleton = None
_log_storage_singleton = None


def _backend() -> str:
    return os.environ.get("PERSISTENCE_BACKEND", "sqlite").lower()


def get_thread_manager(db_path: Optional[str] = None):
    global _thread_manager_singleton
    if _thread_manager_singleton is not None:
        return _thread_manager_singleton

    backend = _backend()
    if backend == "dynamodb":
        from dynamodb_thread_manager import ThreadManager  # type: ignore

        _thread_manager_singleton = ThreadManager(db_path or "threads.db")
    else:
        from thread_manager import ThreadManager  # type: ignore

        _thread_manager_singleton = ThreadManager(db_path or "threads.db")
    return _thread_manager_singleton


def get_log_storage(db_path: Optional[str] = None):
    global _log_storage_singleton
    if _log_storage_singleton is not None:
        return _log_storage_singleton

    backend = _backend()
    if backend == "dynamodb":
        from dynamodb_log_storage import LogStorage  # type: ignore

        _log_storage_singleton = LogStorage(db_path or "logs.db")
    else:
        from log_storage import LogStorage  # type: ignore

        _log_storage_singleton = LogStorage(db_path or "logs.db")
    return _log_storage_singleton


def reset_singletons() -> None:
    """Test hook — drops the cached instances so the next get_* call re-initializes."""
    global _thread_manager_singleton, _log_storage_singleton
    _thread_manager_singleton = None
    _log_storage_singleton = None
