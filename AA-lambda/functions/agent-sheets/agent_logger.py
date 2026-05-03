"""
Agent Execution Logger — Lightweight structured logging for agent microservices.

Provides request-correlated logging so that a single supervisor request
can be traced across gmail_agent → docs_agent → drive_agent etc.

Correlation is driven by HTTP headers set by the supervisor orchestrator:
    X-Request-ID    — unique ID for the entire user request
    X-Step-Number   — which plan step this call belongs to
    X-Total-Steps   — how many steps the plan has

Usage in an agent's api.py:
    from agent_logger import AgentLogger
    logger = AgentLogger("gmail_agent")

    @app.post("/execute_task")
    async def execute_task(request: AgentTaskRequest, raw_request: Request):
        ctx = logger.from_headers(raw_request.headers)
        ctx.log_input(request.tool, request.inputs)
        ...
        ctx.log_output(result, duration_ms)
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Mapping


_LOGS_DIR_NAME = "execution_logs"
_MAX_VALUE_PREVIEW = 500


def _truncate(value: Any, max_len: int = _MAX_VALUE_PREVIEW) -> str:
    """Produce a human-readable, length-capped representation."""
    if isinstance(value, str):
        return value[:max_len] + ("..." if len(value) > max_len else "")
    if isinstance(value, list):
        return f"[{len(value)} items]"
    if isinstance(value, dict):
        keys = list(value.keys())
        return f"{{{', '.join(keys[:8])}}}" + (f" (+{len(keys)-8} more)" if len(keys) > 8 else "")
    return str(value)[:max_len]


def _format_inputs(inputs: Dict[str, Any]) -> str:
    """Pretty-print tool inputs, redacting credentials."""
    lines = []
    for k, v in inputs.items():
        if k in ("credentials_dict", "credentials", "access_token", "refresh_token"):
            lines.append(f"  {k}: [REDACTED]")
        else:
            lines.append(f"  {k}: {_truncate(v)}")
    return "\n".join(lines) if lines else "  (none)"


def _format_output_summary(output: Any) -> str:
    """Summarise the output dict for logging."""
    if not isinstance(output, dict):
        return f"  {_truncate(output)}"
    lines = []
    for k, v in output.items():
        if k in ("credentials_dict",):
            continue
        lines.append(f"  {k}: {_truncate(v)}")
    return "\n".join(lines) if lines else "  (empty)"


class ExecutionContext:
    """Holds correlation info for a single /execute_task call."""

    def __init__(
        self,
        agent_name: str,
        log_path: str,
        request_id: str,
        step_number: Optional[int],
        total_steps: Optional[int],
    ):
        self.agent_name = agent_name
        self.log_path = log_path
        self.request_id = request_id
        self.step_number = step_number
        self.total_steps = total_steps
        self._start_time: Optional[float] = None

    def _write(self, text: str):
        """Append text to the log file and also print to console."""
        print(text)
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass

    def _header(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        step_info = ""
        if self.step_number is not None and self.total_steps is not None:
            step_info = f" | STEP {self.step_number}/{self.total_steps}"
        return f"[{ts}] [{self.request_id}]{step_info}"

    def log_input(self, tool_name: str, inputs: Dict[str, Any]):
        """Log the incoming request (call this at the start of execute_task)."""
        self._start_time = time.time()
        block = (
            f"\n{'='*70}\n"
            f"{self._header()}\n"
            f"AGENT: {self.agent_name} | TOOL: {tool_name}\n"
            f"{'─'*70}\n"
            f"INPUT:\n{_format_inputs(inputs)}\n"
            f"{'─'*70}"
        )
        self._write(block)

    def log_output(self, output: Any, duration_ms: Optional[float] = None, error: Optional[str] = None):
        """Log the response (call this after tool execution completes)."""
        if duration_ms is None and self._start_time is not None:
            duration_ms = (time.time() - self._start_time) * 1000

        success = True
        if isinstance(output, dict):
            success = output.get("success", True)

        status = "SUCCESS" if success and not error else "ERROR"
        dur_str = f"{duration_ms:.0f}ms" if duration_ms is not None else "?"

        block = (
            f"OUTPUT ({dur_str}): {status}\n"
            f"{_format_output_summary(output)}\n"
        )
        if error:
            block += f"ERROR: {error}\n"
        block += f"{'='*70}"
        self._write(block)

    def log_llm_call(self, model: str, operation: str, input_tokens: int, output_tokens: int, duration_ms: float, cost: float = 0.0):
        """Log an LLM call made within the agent (e.g. email body transformation)."""
        block = (
            f"  LLM [{self.request_id}] {model} | {operation} "
            f"| in={input_tokens} out={output_tokens} | ${cost:.4f} | {duration_ms:.0f}ms"
        )
        self._write(block)


class AgentLogger:
    """
    Factory that creates per-request ExecutionContext instances.

    Instantiate once at module level:
        logger = AgentLogger("gmail_agent")

    Then for each request:
        ctx = logger.from_headers(request.headers)
    """

    def __init__(self, agent_name: str, log_dir: Optional[str] = None):
        self.agent_name = agent_name
        if log_dir is None:
            base = os.path.dirname(os.path.abspath(__file__))
            log_dir = os.path.join(base, _LOGS_DIR_NAME)
        os.makedirs(log_dir, exist_ok=True)
        self.log_path = os.path.join(log_dir, "execution.log")

    def from_headers(self, headers: Mapping[str, str]) -> ExecutionContext:
        """Extract correlation info from HTTP headers and build a context."""
        request_id = headers.get("x-request-id", "no-request-id")
        step_number = headers.get("x-step-number")
        total_steps = headers.get("x-total-steps")

        return ExecutionContext(
            agent_name=self.agent_name,
            log_path=self.log_path,
            request_id=request_id,
            step_number=int(step_number) if step_number else None,
            total_steps=int(total_steps) if total_steps else None,
        )

    def standalone(self, request_id: str = "standalone") -> ExecutionContext:
        """Create a context without HTTP headers (for testing / direct calls)."""
        return ExecutionContext(
            agent_name=self.agent_name,
            log_path=self.log_path,
            request_id=request_id,
            step_number=None,
            total_steps=None,
        )
