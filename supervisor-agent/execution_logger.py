"""
Execution Trace Logger — Simple file-based tracing for real-time observability.

Writes timestamped, structured entries to execution_logs/trace.log.
Each request gets a clear visual section so you can follow the flow.

Usage:
    from execution_logger import trace

    trace.request_start("POST /threads", {"user_id": "abc123"})
    trace.step("quota_check", "Passed — 95000 tokens remaining")
    trace.llm_call("gpt-4o", "tier1_analysis", input_tokens=320, output_tokens=150)
    trace.agent_call("gmail_agent", "search_emails", {"query": "invoices"})
    trace.request_end("200 OK", duration_ms=4500)

View live:
    Get-Content execution_logs/trace.log -Wait          # PowerShell
    tail -f execution_logs/trace.log                     # Unix
"""

import os
import sys
import time
import json
import threading
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager


LOG_DIR = os.path.join(os.path.dirname(__file__), "execution_logs")
LOG_FILE = os.path.join(LOG_DIR, "trace.log")
os.makedirs(LOG_DIR, exist_ok=True)

# Thread-local storage for per-request context
_local = threading.local()


class ExecutionTracer:
    """Append-only trace logger that writes structured lines to a log file."""

    def __init__(self, log_path: str = LOG_FILE, max_size_mb: int = 10):
        self.log_path = log_path
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self._lock = threading.Lock()

    def _write(self, level: str, category: str, message: str, data: dict = None):
        """Write a single trace line."""
        now = datetime.now()
        ts = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        # Get per-request context
        req_id = getattr(_local, "request_id", "-")
        thread_id = getattr(_local, "thread_id", "-")

        parts = [f"[{ts}]", f"[{level}]", f"[{req_id}]"]
        if thread_id != "-":
            parts.append(f"[T:{thread_id[-8:]}]")
        parts.append(f"{category}: {message}")

        line = " ".join(parts)
        if data:
            # Compact JSON on same line for simple data, indented for complex
            try:
                data_str = json.dumps(data, default=str, ensure_ascii=False)
                if len(data_str) < 200:
                    line += f"  | {data_str}"
                else:
                    line += f"\n    ↳ {data_str[:500]}"
            except Exception:
                pass

        with self._lock:
            self._rotate_if_needed()
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def _rotate_if_needed(self):
        """Rotate log file if it exceeds max size."""
        try:
            if os.path.exists(self.log_path) and os.path.getsize(self.log_path) > self.max_size_bytes:
                backup = self.log_path + ".1"
                if os.path.exists(backup):
                    os.remove(backup)
                os.rename(self.log_path, backup)
        except Exception:
            pass

    # ── Context management ──────────────────────────────────────────────

    def set_context(self, request_id: str = None, thread_id: str = None):
        """Set per-request context for subsequent trace calls."""
        if request_id:
            _local.request_id = request_id
        if thread_id:
            _local.thread_id = thread_id

    def clear_context(self):
        """Clear per-request context."""
        _local.request_id = "-"
        _local.thread_id = "-"

    # ── HTTP Request tracing ────────────────────────────────────────────

    def request_start(self, method_path: str, data: dict = None):
        """Log start of an HTTP request (only log POST/PUT/DELETE, skip GET/OPTIONS noise)."""
        # Skip noisy read-only and preflight requests
        if any(skip_method in method_path.upper() for skip_method in ["OPTIONS", "GET"]):
            return
        self._write("INFO", "→ REQUEST", method_path, data)

    def request_end(self, status: str, duration_ms: float = None):
        """Log end of an HTTP request (only log if request_start was logged)."""
        # Note: request_end is only called if request_start was called (middleware guards it)
        # but add guard here anyway for safety
        msg = status
        if duration_ms is not None:
            msg += f" ({duration_ms:.0f}ms)"
        self._write("INFO", "← RESPONSE", msg)
        self._write("INFO", "─────────", "─" * 50)

    # ── Execution flow tracing ──────────────────────────────────────────

    def step(self, name: str, detail: str = "", data: dict = None):
        """Log a named execution step."""
        self._write("INFO", f"  STEP [{name}]", detail, data)

    def decision(self, name: str, result: str, data: dict = None):
        """Log a decision point (e.g., quota check, route classification)."""
        self._write("INFO", f"  DECISION [{name}]", result, data)

    def llm_call(self, model: str, operation: str, input_tokens: int = 0,
                 output_tokens: int = 0, duration_ms: float = 0, success: bool = True):
        """Log an LLM API call."""
        status = "" if success else ""
        total = input_tokens + output_tokens
        msg = f"{status} {model} → {operation} ({total} tokens, {duration_ms:.0f}ms)"
        self._write("LLM", "  LLM", msg, {
            "input": input_tokens, "output": output_tokens,
            "duration_ms": round(duration_ms), "success": success
        })

    def agent_call(self, agent: str, tool: str, inputs: dict = None,
                   success: bool = None, duration_ms: float = None):
        """Log an agent/tool call."""
        status = ""
        if success is True:
            status = " "
        elif success is False:
            status = " "
        msg = f"{status}{agent}.{tool}"
        if duration_ms is not None:
            msg += f" ({duration_ms:.0f}ms)"
        # Redact large input values for readability
        safe_inputs = None
        if inputs:
            safe_inputs = {}
            for k, v in inputs.items():
                sv = str(v)
                safe_inputs[k] = sv[:100] + "..." if len(sv) > 100 else sv
        self._write("AGENT", "  AGENT", msg, safe_inputs)

    def workflow_start(self, user_input: str, plan_steps: int = 0):
        """Log workflow execution start."""
        preview = user_input[:80] + "..." if len(user_input) > 80 else user_input
        self._write("INFO", "  WORKFLOW START", f'"{preview}" ({plan_steps} steps)')

    def workflow_end(self, status: str, steps_completed: int = 0, total_steps: int = 0):
        """Log workflow execution end."""
        self._write("INFO", "  WORKFLOW END", f"{status} ({steps_completed}/{total_steps} steps)")

    # ── Conversational flow ─────────────────────────────────────────────

    def user_message(self, message: str, thread_id: str = None):
        """Log incoming user message."""
        preview = message[:100] + "..." if len(message) > 100 else message
        self._write("INFO", "  USER MSG", f'"{preview}"')

    def bot_response(self, response: str, ready_for_execution: bool = False):
        """Log bot response."""
        preview = response[:100] + "..." if len(response) > 100 else response
        exec_flag = " [READY TO EXECUTE]" if ready_for_execution else ""
        self._write("INFO", f"  BOT RESP{exec_flag}", f'"{preview}"')

    def analysis_result(self, intent: str, ready: bool, missing_fields: list = None):
        """Log conversation analysis result."""
        self._write("INFO", "  ANALYSIS", f"intent={intent}, ready={ready}", {
            "missing_fields": missing_fields or []
        })

    # ── Errors and warnings ─────────────────────────────────────────────

    def error(self, message: str, exception: Exception = None, data: dict = None):
        """Log an error."""
        msg = message
        if exception:
            msg += f" | {type(exception).__name__}: {str(exception)[:200]}"
        self._write("ERROR", " ERROR", msg, data)

    def warning(self, message: str, data: dict = None):
        """Log a warning."""
        self._write("WARN", " WARN", message, data)

    def info(self, message: str, data: dict = None):
        """Log general info."""
        self._write("INFO", "  INFO", message, data)


# ── Global singleton ────────────────────────────────────────────────────
trace = ExecutionTracer()


# ── TeeWriter: Capture all print() output into trace log + SQLite ──────
class TeeWriter:
    """
    Wraps sys.stdout so every print() also gets written to the trace log
    AND to SQLite LogStorage for full observability via the /logs API.

    Terminal output is unchanged — the log file and database get copies.
    """

    def __init__(self, original_stdout, log_path: str, lock: threading.Lock):
        self.original = original_stdout
        self.log_path = log_path
        self._lock = lock
        self._max_size_bytes = 10 * 1024 * 1024  # 10 MB
        self._in_write = False  # Recursion guard (prevents infinite loops)
        self._storage_fn = None  # Lazy-loaded reference to get_log_storage
        self._context_fns = None  # Lazy-loaded references to context getters

    def _ensure_imports(self):
        """Lazy-load logging_config references to avoid circular imports."""
        if self._storage_fn is not None:
            return
        try:
            from logging_config import (
                get_log_storage,
                get_current_request_id,
                get_current_thread_id,
                get_current_conversation_id,
            )
            self._storage_fn = get_log_storage
            self._context_fns = {
                "request_id": get_current_request_id,
                "thread_id": get_current_thread_id,
                "conversation_id": get_current_conversation_id,
            }
        except Exception:
            self._storage_fn = False  # Mark as failed, don't retry

    def write(self, text):
        # Always write to original terminal
        self.original.write(text)

        # Skip empty / whitespace-only writes (print's newlines etc.)
        stripped = text.rstrip("\n\r")
        if not stripped:
            return

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        # Get request context from execution_logger's thread-local
        req_id = getattr(_local, "request_id", None)
        thread_id = getattr(_local, "thread_id", None)

        with self._lock:
            try:
                # Simple size-based rotation
                if os.path.exists(self.log_path) and os.path.getsize(self.log_path) > self._max_size_bytes:
                    backup = self.log_path + ".1"
                    if os.path.exists(backup):
                        os.remove(backup)
                    os.rename(self.log_path, backup)

                with open(self.log_path, "a", encoding="utf-8") as f:
                    for line in stripped.split("\n"):
                        f.write(f"[{ts}] [PRINT] {line}\n")
            except Exception:
                pass  # Never break the app because of logging

        # Write to SQLite LogStorage (with recursion guard)
        if not self._in_write:
            self._in_write = True
            try:
                self._write_to_storage(stripped, ts, req_id, thread_id)
            except Exception:
                pass  # Never break the app
            finally:
                self._in_write = False

    def _write_to_storage(self, text: str, timestamp: str, local_req_id, local_thread_id):
        """Write print output to SQLite LogStorage for full observability."""
        self._ensure_imports()
        if not self._storage_fn or self._storage_fn is False:
            return

        storage = self._storage_fn()
        if not storage:
            return

        # Prefer contextvars (async-safe) over thread-local
        req_id = None
        thread_id = None
        conv_id = None
        if self._context_fns:
            try:
                req_id = self._context_fns["request_id"]() or local_req_id
                thread_id = self._context_fns["thread_id"]() or local_thread_id
                conv_id = self._context_fns["conversation_id"]()
            except Exception:
                req_id = local_req_id
                thread_id = local_thread_id

        # Infer log level from emoji/content
        level = "INFO"
        if any(marker in text for marker in ("", "ERROR", "CRITICAL", "")):
            level = "ERROR"
        elif any(marker in text for marker in ("", "WARN", "")):
            level = "WARNING"

        storage.insert_log({
            "timestamp": timestamp,
            "level": level,
            "logger": "print",
            "message": text[:2000],  # Cap message length
            "request_id": req_id if req_id and req_id != "-" else None,
            "conversation_id": conv_id,
            "thread_id": thread_id if thread_id and thread_id != "-" else None,
            "component": "system",
            "operation": "print_capture",
        })

    def flush(self):
        self.original.flush()

    # Forward any other attribute access to the original stdout
    def __getattr__(self, name):
        return getattr(self.original, name)


def enable_print_capture():
    """Redirect print() to also write to the trace log file and SQLite."""
    if not isinstance(sys.stdout, TeeWriter):
        sys.stdout = TeeWriter(sys.stdout, LOG_FILE, trace._lock)


# Auto-enable on import
enable_print_capture()
