"""
Logging Configuration Module for AI Agents System

This module provides:
- StructuredLogger: JSON-formatted logging with correlation IDs
- TokenTracker: Tracks LLM token usage per call and per request cycle
- RequestContext: Context manager for request-level tracking
- LLMWrapper: Wrapper for ChatOpenAI with automatic token tracking

Features:
- Request ID tracking across all components
- Token usage tracking (input, output, total per call and cumulative)
- Cost estimation based on model pricing
- Progress logging (step-based, no percentages)
- JSON-formatted logs for easy parsing
- SQLite database storage for log persistence and querying
"""

import json
import logging
import uuid
import time
import os
import httpx
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from contextlib import contextmanager
from functools import wraps
from enum import Enum
import threading
from contextvars import ContextVar

# Use contextvars for async-safe context storage (instead of threading.local)
_request_id_var: ContextVar[Optional[str]] = ContextVar('request_id', default=None)
_conversation_id_var: ContextVar[Optional[str]] = ContextVar('conversation_id', default=None)
_thread_id_var: ContextVar[Optional[str]] = ContextVar('thread_id', default=None)
_user_id_var: ContextVar[Optional[str]] = ContextVar('user_id', default=None)
_token_summary_var: ContextVar[Optional[Any]] = ContextVar('token_summary', default=None)
_start_time_var: ContextVar[Optional[float]] = ContextVar('start_time', default=None)

# Keep thread-local as fallback for non-async code
_request_context = threading.local()

# Lazy-loaded log storage (initialized on first use)
_log_storage = None
_log_storage_lock = threading.Lock()

# Token Quota Service configuration
QUOTA_SERVICE_URL = os.getenv("QUOTA_SERVICE_URL", "http://localhost:8011")
QUOTA_ENABLED = os.getenv("QUOTA_ENABLED", "true").lower() in ("true", "1", "yes")


# ============================================================================
# LOG LEVELS
# ============================================================================

class LogLevel(str, Enum):
    """Custom log levels for the system"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    PROGRESS = "PROGRESS"  # Special level for step tracking
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# ============================================================================
# TOKEN PRICING (per 1K tokens) - Updated for GPT-4o
# ============================================================================

MODEL_PRICING = {
    "gpt-4o": {"input": 0.0025, "output": 0.01},        # $2.50/1M input, $10/1M output
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006}, # $0.15/1M input, $0.60/1M output
    "gpt-4": {"input": 0.03, "output": 0.06},           # $30/1M input, $60/1M output
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},     # $10/1M input, $30/1M output
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015}, # $0.50/1M input, $1.50/1M output
    "default": {"input": 0.01, "output": 0.03}          # Fallback pricing
}


def get_log_storage():
    """Get or create the log storage instance (lazy initialization)"""
    global _log_storage
    if _log_storage is None:
        with _log_storage_lock:
            if _log_storage is None:
                try:
                    from log_storage import LogStorage
                    _log_storage = LogStorage()
                except ImportError:
                    # log_storage module not available, SQLite storage disabled
                    _log_storage = False
                except Exception as e:
                    # Error initializing storage, disable it
                    print(f"Warning: Could not initialize log storage: {e}")
                    _log_storage = False
    return _log_storage if _log_storage else None


class QuotaCheckResult:
    """Result of a quota check"""
    def __init__(self, allowed: bool, error: str = None, user_deactivated: bool = False):
        self.allowed = allowed
        self.error = error
        self.user_deactivated = user_deactivated


def check_user_quota(user_id: str, estimated_tokens: int = 1000) -> QuotaCheckResult:
    """
    Check if user has sufficient quota before making LLM calls.
    
    Args:
        user_id: User ID to check
        estimated_tokens: Estimated tokens for the operation
        
    Returns:
        QuotaCheckResult with allowed status and any error message
    """
    if not QUOTA_ENABLED:
        return QuotaCheckResult(allowed=True)
    
    if not user_id:
        return QuotaCheckResult(allowed=True)  # No user_id means anonymous, allow for now
    
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(
                f"{QUOTA_SERVICE_URL}/quota/check",
                json={
                    "user_id": user_id,
                    "estimated_tokens": estimated_tokens,
                    "service": "supervisor",
                    "operation": "chat"
                }
            )
            
            # User not found = deactivated
            if response.status_code == 404:
                return QuotaCheckResult(
                    allowed=False,
                    error="Your account has been deactivated. Please contact an administrator.",
                    user_deactivated=True
                )
            
            if response.status_code == 200:
                data = response.json()
                if not data.get("allowed", True):
                    return QuotaCheckResult(
                        allowed=False,
                        error=f"Token quota exceeded. {data.get('remaining_tokens', 0)} tokens remaining of {data.get('monthly_limit', 0)} monthly limit."
                    )
                return QuotaCheckResult(allowed=True)
            
            # Other errors - fail open
            print(f"⚠️ Quota check returned {response.status_code}, allowing operation")
            return QuotaCheckResult(allowed=True)
            
    except Exception as e:
        # Quota service unavailable - fail open
        print(f"⚠️ Quota service unavailable for check: {e}. Allowing operation.")
        return QuotaCheckResult(allowed=True)


def _report_quota_usage(
    user_id: str,
    service: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    operation: str = "unknown",
    cost_usd: float = None,
    request_id: str = None,
    session_id: str = None,
    metadata: Dict[str, Any] = None
):
    """
    Report token usage to the Token Quota Service (synchronous).
    Uses httpx sync client for simplicity in logging context.
    """
    if not QUOTA_ENABLED:
        return
    
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(
                f"{QUOTA_SERVICE_URL}/quota/report",
                json={
                    "user_id": user_id,
                    "service": service,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "operation": operation,
                    "cost_usd": cost_usd,
                    "request_id": request_id,
                    "session_id": session_id,
                    "metadata": metadata
                }
            )
            if response.status_code == 200:
                print(f"📊 Reported {input_tokens + output_tokens} tokens to quota service for user {user_id}")
            elif response.status_code == 404:
                print(f"⚠️ User {user_id} not found in quota service")
            else:
                print(f"⚠️ Quota report failed with status {response.status_code}")
    except Exception as e:
        print(f"⚠️ Failed to report quota usage: {e}")


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class TokenUsage:
    """Token usage for a single LLM call"""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    estimated_cost: float = 0.0
    call_duration_ms: float = 0.0


@dataclass
class RequestTokenSummary:
    """Cumulative token usage for entire request cycle"""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_estimated_cost: float = 0.0
    llm_calls: List[TokenUsage] = field(default_factory=list)
    
    def add_call(self, usage: TokenUsage):
        """Add a single LLM call's usage to the summary"""
        self.total_input_tokens += usage.input_tokens
        self.total_output_tokens += usage.output_tokens
        self.total_tokens += usage.total_tokens
        self.total_estimated_cost += usage.estimated_cost
        self.llm_calls.append(usage)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging"""
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "total_estimated_cost_usd": round(self.total_estimated_cost, 6),
            "llm_call_count": len(self.llm_calls),
            "calls": [
                {
                    "model": call.model,
                    "input_tokens": call.input_tokens,
                    "output_tokens": call.output_tokens,
                    "total_tokens": call.total_tokens,
                    "cost_usd": round(call.estimated_cost, 6),
                    "duration_ms": round(call.call_duration_ms, 2)
                }
                for call in self.llm_calls
            ]
        }


# ============================================================================
# REQUEST CONTEXT MANAGER
# ============================================================================

def generate_request_id() -> str:
    """Generate unique request ID"""
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    unique = uuid.uuid4().hex[:8]
    return f"req_{timestamp}_{unique}"


def get_current_request_id() -> Optional[str]:
    """Get current request ID from context (async-safe)"""
    return _request_id_var.get()


def get_current_conversation_id() -> Optional[str]:
    """Get current conversation ID from context (async-safe)"""
    return _conversation_id_var.get()


def get_current_thread_id() -> Optional[str]:
    """Get current thread ID from context (async-safe)"""
    return _thread_id_var.get()


def get_current_user_id() -> Optional[str]:
    """Get current user ID from context (async-safe)"""
    return _user_id_var.get()


def get_token_summary() -> Optional['RequestTokenSummary']:
    """Get current request's token summary (async-safe)"""
    return _token_summary_var.get()


@contextmanager
def request_context(
    request_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    thread_id: Optional[str] = None
):
    """
    Context manager for request-level tracking.
    
    Usage:
        with request_context(request_id="req_123", conversation_id="conv_456"):
            # All logging within this block will include these IDs
            logger.info("Processing request")
    """
    # Generate request_id if not provided
    if request_id is None:
        request_id = generate_request_id()
    
    # Store in thread-local
    old_request_id = getattr(_request_context, 'request_id', None)
    old_conversation_id = getattr(_request_context, 'conversation_id', None)
    old_thread_id = getattr(_request_context, 'thread_id', None)
    old_token_summary = getattr(_request_context, 'token_summary', None)
    
    _request_context.request_id = request_id
    _request_context.conversation_id = conversation_id
    _request_context.thread_id = thread_id
    _request_context.token_summary = RequestTokenSummary()
    _request_context.start_time = time.time()
    
    try:
        yield request_id
    finally:
        # Restore previous context
        _request_context.request_id = old_request_id
        _request_context.conversation_id = old_conversation_id
        _request_context.thread_id = old_thread_id
        _request_context.token_summary = old_token_summary
        _request_context.start_time = None


def set_request_context(
    request_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    user_id: Optional[str] = None
):
    """
    Set request context (async-safe using contextvars).
    Useful for HTTP requests where context spans multiple function calls.
    """
    if request_id is None:
        request_id = generate_request_id()
    
    # Set context vars for async code
    _request_id_var.set(request_id)
    _conversation_id_var.set(conversation_id)
    _thread_id_var.set(thread_id)
    _user_id_var.set(user_id)
    _token_summary_var.set(RequestTokenSummary())
    _start_time_var.set(time.time())
    
    # Also set thread-local for compatibility
    _request_context.request_id = request_id
    _request_context.conversation_id = conversation_id
    _request_context.thread_id = thread_id
    _request_context.user_id = user_id
    _request_context.token_summary = RequestTokenSummary()
    _request_context.start_time = time.time()
    
    print(f"[CONTEXT SET] request_id={request_id}, user_id={user_id}, thread_id={thread_id}")
    
    return request_id


def clear_request_context():
    """Clear request context after request completes (async-safe)"""
    # Clear context vars
    _request_id_var.set(None)
    _conversation_id_var.set(None)
    _thread_id_var.set(None)
    _user_id_var.set(None)
    _token_summary_var.set(None)
    _start_time_var.set(None)
    
    # Clear thread-local for compatibility
    _request_context.request_id = None
    _request_context.conversation_id = None
    _request_context.thread_id = None
    _request_context.user_id = None
    _request_context.token_summary = None
    _request_context.start_time = None


# ============================================================================
# STRUCTURED LOGGER
# ============================================================================

class StructuredLogger:
    """
    JSON-formatted structured logger with correlation ID support.
    
    Outputs logs in JSON format for easy parsing and analysis.
    Automatically includes request_id, conversation_id, thread_id from context.
    """
    
    def __init__(self, name: str, log_file: Optional[str] = None):
        """
        Initialize structured logger.
        
        Args:
            name: Logger name (typically module name)
            log_file: Optional file path for log output
        """
        self.name = name
        self.log_file = log_file
        
        # Setup Python logger for console output
        self._logger = logging.getLogger(name)
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('%(message)s'))
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.DEBUG)
    
    def _build_log_entry(
        self,
        level: LogLevel,
        message: str,
        component: Optional[str] = None,
        operation: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Build a structured log entry"""
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": level.value,
            "logger": self.name,
            "message": message,
            "request_id": get_current_request_id(),
            "conversation_id": get_current_conversation_id(),
            "thread_id": get_current_thread_id(),
        }
        
        if component:
            entry["component"] = component
        if operation:
            entry["operation"] = operation
        if extra:
            entry["data"] = extra
        
        # Remove None values for cleaner output
        entry = {k: v for k, v in entry.items() if v is not None}
        
        return entry
    
    def _log(self, level: LogLevel, message: str, **kwargs):
        """Internal logging method"""
        entry = self._build_log_entry(level, message, **kwargs)
        json_str = json.dumps(entry)
        
        # Map to Python logging level
        py_level = getattr(logging, level.value if level.value != "PROGRESS" else "INFO")
        self._logger.log(py_level, json_str)
        
        # Also write to file if configured
        if self.log_file:
            try:
                with open(self.log_file, 'a') as f:
                    f.write(json_str + '\n')
            except Exception:
                pass  # Don't fail on log write errors
        
        # Store in SQLite database
        try:
            storage = get_log_storage()
            if storage:
                storage.insert_log(entry)
        except Exception:
            pass  # Don't fail on database write errors
    
    def debug(self, message: str, **kwargs):
        """Log debug message"""
        self._log(LogLevel.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs):
        """Log info message"""
        self._log(LogLevel.INFO, message, **kwargs)
    
    def progress(self, message: str, current_step: int, total_steps: int, step_name: str = "", **kwargs):
        """
        Log progress message (step-based, no percentage).
        
        Args:
            message: Progress message
            current_step: Current step number (1-indexed)
            total_steps: Total number of steps
            step_name: Name/description of current step
        """
        extra = kwargs.pop('extra', {})
        extra.update({
            "current_step": current_step,
            "total_steps": total_steps,
            "step_name": step_name,
            "steps_remaining": total_steps - current_step
        })
        self._log(LogLevel.PROGRESS, message, extra=extra, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log warning message"""
        self._log(LogLevel.WARNING, message, **kwargs)
    
    def error(self, message: str, error: Optional[Exception] = None, **kwargs):
        """Log error message"""
        extra = kwargs.pop('extra', {})
        if error:
            extra.update({
                "error_type": type(error).__name__,
                "error_message": str(error)
            })
        self._log(LogLevel.ERROR, message, extra=extra, **kwargs)
    
    def critical(self, message: str, **kwargs):
        """Log critical message"""
        self._log(LogLevel.CRITICAL, message, **kwargs)
    
    def llm_call(
        self,
        model: str,
        operation: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float,
        tier: Optional[str] = None,
        prompt_summary: Optional[str] = None,
        success: bool = True,
        error: Optional[str] = None
    ):
        """
        Log LLM call with token usage.
        
        Args:
            model: Model name (e.g., "gpt-4o")
            operation: What the LLM call was for (e.g., "tier_0.5_check", "plan_generation")
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            duration_ms: Call duration in milliseconds
            tier: Execution tier (0, 0.5, 1, supervisor)
            prompt_summary: Brief summary of prompt (truncated)
            success: Whether call succeeded
            error: Error message if failed
        """
        # Calculate cost
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
        cost = (input_tokens * pricing["input"] / 1000) + (output_tokens * pricing["output"] / 1000)
        
        # Create token usage record
        usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            model=model,
            estimated_cost=cost,
            call_duration_ms=duration_ms
        )
        
        # Add to request summary
        token_summary = get_token_summary()
        if token_summary:
            token_summary.add_call(usage)
        
        # Report to Token Quota Service if user_id is available
        user_id = get_current_user_id()
        request_id = get_current_request_id()
        conversation_id = get_current_conversation_id()
        
        # DEBUG: Print token reporting context
        print(f"[TOKEN REPORTING] user_id={user_id}, success={success}, operation={operation}, tokens={input_tokens + output_tokens}")
        
        if user_id and success:
            try:
                _report_quota_usage(
                    user_id=user_id,
                    service="supervisor",
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    operation=operation,
                    cost_usd=cost,
                    request_id=request_id,
                    session_id=conversation_id
                )
            except Exception as e:
                print(f"⚠️ Failed to report quota usage: {e}")
        else:
            if not user_id:
                print(f"⚠️ [TOKEN REPORTING SKIPPED] No user_id in context")
            if not success:
                print(f"⚠️ [TOKEN REPORTING SKIPPED] LLM call not successful")
        
        # Log the call
        extra = {
            "model": model,
            "tier": tier,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "estimated_cost_usd": round(cost, 6),
            "duration_ms": round(duration_ms, 2),
            "success": success
        }
        
        if prompt_summary:
            extra["prompt_summary"] = prompt_summary[:100]  # Truncate
        if error:
            extra["error"] = error
        if token_summary:
            extra["cumulative_tokens"] = token_summary.total_tokens
            extra["cumulative_cost_usd"] = round(token_summary.total_estimated_cost, 6)
        
        level = LogLevel.INFO if success else LogLevel.ERROR
        self._log(level, f"LLM call: {operation}", component="llm", operation=operation, extra=extra)
        
        return usage
    
    def agent_call(
        self,
        agent_name: str,
        tool_name: str,
        step_number: int,
        total_steps: int,
        inputs: Dict[str, Any],
        success: bool,
        duration_ms: float,
        output_summary: Optional[str] = None,
        error: Optional[str] = None
    ):
        """Log agent/tool execution"""
        extra = {
            "agent": agent_name,
            "tool": tool_name,
            "step": step_number,
            "total_steps": total_steps,
            "duration_ms": round(duration_ms, 2),
            "success": success,
            "inputs": {k: str(v)[:50] for k, v in inputs.items()}  # Truncate input values
        }
        
        if output_summary:
            extra["output_summary"] = output_summary[:200]
        if error:
            extra["error"] = error
        
        level = LogLevel.INFO if success else LogLevel.ERROR
        message = f"Agent call: {agent_name}.{tool_name} (step {step_number}/{total_steps})"
        self._log(level, message, component="orchestrator", operation="agent_call", extra=extra)
    
    def request_summary(self):
        """Log end-of-request summary with total token usage"""
        token_summary = get_token_summary()
        start_time = getattr(_request_context, 'start_time', None)
        
        extra = {
            "request_complete": True
        }
        
        if start_time:
            extra["total_duration_ms"] = round((time.time() - start_time) * 1000, 2)
        
        if token_summary:
            extra["token_summary"] = token_summary.to_dict()
        
        self._log(LogLevel.INFO, "Request completed", component="system", operation="request_complete", extra=extra)


# ============================================================================
# TOKEN TRACKER (LLM WRAPPER)
# ============================================================================

class TokenTracker:
    """
    Wrapper for ChatOpenAI that automatically tracks token usage.
    
    Usage:
        from logging_config import TokenTracker
        
        llm = ChatOpenAI(model="gpt-4o", ...)
        tracker = TokenTracker(llm, logger, "conversational_agent")
        
        # Use tracker.invoke() instead of llm.invoke()
        response = tracker.invoke(messages, tier="0.5", operation="unified_check")
    """
    
    def __init__(
        self,
        llm,
        logger: StructuredLogger,
        component: str = "llm"
    ):
        """
        Initialize token tracker.
        
        Args:
            llm: ChatOpenAI instance
            logger: StructuredLogger instance
            component: Component name for logging
        """
        self.llm = llm
        self.logger = logger
        self.component = component
        self._model = getattr(llm, 'model_name', 'unknown')
    
    def invoke(
        self,
        messages: List[Dict[str, str]],
        config: Optional[Dict] = None,
        tier: Optional[str] = None,
        operation: str = "llm_call"
    ):
        """
        Invoke LLM with automatic token tracking.
        
        Args:
            messages: List of message dicts [{"role": "user", "content": "..."}]
            config: Optional config dict with timeout, max_tokens, etc.
            tier: Execution tier for logging (0, 0.5, 1, supervisor)
            operation: Operation name for logging
            
        Returns:
            LLM response object
        """
        start_time = time.time()
        success = True
        error_msg = None
        input_tokens = 0
        output_tokens = 0
        
        try:
            # Make the actual LLM call
            if config:
                response = self.llm.invoke(messages, config=config)
            else:
                response = self.llm.invoke(messages)
            
            # Extract token usage from response
            if hasattr(response, 'response_metadata'):
                metadata = response.response_metadata
                token_usage = metadata.get('token_usage', {})
                input_tokens = token_usage.get('prompt_tokens', 0)
                output_tokens = token_usage.get('completion_tokens', 0)
            
            # Fallback: estimate tokens if not provided
            if input_tokens == 0:
                # Rough estimate: 4 chars per token
                total_input = sum(len(str(m.get('content', ''))) for m in messages)
                input_tokens = total_input // 4
            
            if output_tokens == 0 and hasattr(response, 'content'):
                output_tokens = len(response.content) // 4
            
            return response
            
        except Exception as e:
            success = False
            error_msg = str(e)
            raise
            
        finally:
            duration_ms = (time.time() - start_time) * 1000
            
            # Generate prompt summary
            prompt_summary = ""
            if messages:
                last_msg = messages[-1] if isinstance(messages, list) else messages
                content = last_msg.get('content', '') if isinstance(last_msg, dict) else str(last_msg)
                prompt_summary = content[:100] + "..." if len(content) > 100 else content
            
            # Log the call
            self.logger.llm_call(
                model=self._model,
                operation=operation,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
                tier=tier,
                prompt_summary=prompt_summary,
                success=success,
                error=error_msg
            )


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def create_logger(name: str, log_file: Optional[str] = None) -> StructuredLogger:
    """Create a structured logger instance"""
    return StructuredLogger(name, log_file)


def wrap_llm(llm, logger: StructuredLogger, component: str = "llm") -> TokenTracker:
    """Wrap a ChatOpenAI instance with token tracking"""
    return TokenTracker(llm, logger, component)


# ============================================================================
# GLOBAL LOGGERS (Initialize in your modules)
# ============================================================================

# Default log file path - use absolute path relative to this file's directory
import os as _os
_LOG_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "agent_outputs")
_os.makedirs(_LOG_DIR, exist_ok=True)
DEFAULT_LOG_FILE = _os.path.join(_LOG_DIR, "system_logs.jsonl")

# Create default loggers for each component
supervisor_logger = create_logger("supervisor_agent", DEFAULT_LOG_FILE)
conversational_logger = create_logger("conversational_agent", DEFAULT_LOG_FILE)
orchestrator_logger = create_logger("orchestrator", DEFAULT_LOG_FILE)
memory_logger = create_logger("conversation_memory", DEFAULT_LOG_FILE)
utils_logger = create_logger("utils", DEFAULT_LOG_FILE)


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == "__main__":
    # Demo usage
    print("=== Logging Config Demo ===\n")
    
    # Create logger
    logger = create_logger("demo", "demo_logs.jsonl")
    
    # Simulate request
    with request_context(conversation_id="conv_abc123", thread_id="thread_xyz"):
        logger.info("Starting request processing", component="api")
        
        # Simulate LLM calls
        logger.llm_call(
            model="gpt-4o",
            operation="tier_0.5_unified_check",
            input_tokens=150,
            output_tokens=50,
            duration_ms=850,
            tier="0.5"
        )
        
        logger.llm_call(
            model="gpt-4o",
            operation="tier_1_full_analysis",
            input_tokens=800,
            output_tokens=200,
            duration_ms=2300,
            tier="1"
        )
        
        # Log progress (step-based, no percentage)
        logger.progress("Executing plan", current_step=1, total_steps=3, step_name="search_emails")
        logger.progress("Executing plan", current_step=2, total_steps=3, step_name="get_thread")
        logger.progress("Executing plan", current_step=3, total_steps=3, step_name="reply_email")
        
        # Log request summary
        logger.request_summary()
    
    print("\n=== Demo Complete ===")
