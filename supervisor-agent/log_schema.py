"""
Log Schema Models for AI Agents System

Pydantic models for structured log entries.
These models define the shape of log data for type safety and validation.

Features:
- BaseLogEntry: Common fields for all log types
- LLMLogEntry: Token usage and cost tracking
- AgentLogEntry: Agent/tool execution tracking
- ProgressLogEntry: Step-based progress (no percentage)
- RequestLogEntry: Request-level summary
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

# Import LogLevel from logging_config to avoid duplication
from logging_config import LogLevel


class BaseLogEntry(BaseModel):
    """
    Base log entry with common fields.
    All other log entries inherit from this.
    """
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    level: LogLevel = LogLevel.INFO
    logger: str = Field(..., description="Logger name (component)")
    message: str = Field(..., description="Log message")
    
    # Correlation IDs
    request_id: Optional[str] = Field(None, description="Unique request identifier")
    conversation_id: Optional[str] = Field(None, description="Conversation/session ID")
    thread_id: Optional[str] = Field(None, description="Thread ID for persistence")
    
    # Optional context
    component: Optional[str] = Field(None, description="System component")
    operation: Optional[str] = Field(None, description="Operation being performed")
    
    class Config:
        use_enum_values = True


class TokenUsageSchema(BaseModel):
    """Token usage details for a single LLM call"""
    model: str = Field(..., description="Model name (e.g., gpt-4o)")
    input_tokens: int = Field(0, ge=0, description="Input/prompt tokens")
    output_tokens: int = Field(0, ge=0, description="Output/completion tokens")
    total_tokens: int = Field(0, ge=0, description="Total tokens used")
    estimated_cost_usd: float = Field(0.0, ge=0, description="Estimated cost in USD")
    duration_ms: float = Field(0.0, ge=0, description="Call duration in milliseconds")


class LLMLogEntry(BaseLogEntry):
    """
    Log entry for LLM (Language Model) calls.
    Tracks token usage, cost, and performance.
    """
    component: str = "llm"
    
    # LLM-specific fields
    model: str = Field(..., description="Model name")
    tier: Optional[str] = Field(None, description="Execution tier (0, 0.5, 1, supervisor)")
    
    # Token usage
    input_tokens: int = Field(0, ge=0)
    output_tokens: int = Field(0, ge=0)
    total_tokens: int = Field(0, ge=0)
    estimated_cost_usd: float = Field(0.0, ge=0)
    
    # Performance
    duration_ms: float = Field(0.0, ge=0)
    success: bool = Field(True)
    
    # Cumulative (for request tracking)
    cumulative_tokens: Optional[int] = Field(None, description="Total tokens so far in request")
    cumulative_cost_usd: Optional[float] = Field(None, description="Total cost so far in request")
    
    # Optional details
    prompt_summary: Optional[str] = Field(None, max_length=200)
    error: Optional[str] = Field(None)


class AgentLogEntry(BaseLogEntry):
    """
    Log entry for agent/tool executions.
    Tracks which agents are called and their results.
    """
    component: str = "orchestrator"
    operation: str = "agent_call"
    
    # Agent/tool info
    agent: str = Field(..., description="Agent name")
    tool: str = Field(..., description="Tool name")
    
    # Execution context
    step: int = Field(..., ge=1, description="Step number in plan")
    total_steps: int = Field(..., ge=1, description="Total steps in plan")
    
    # Inputs (sanitized)
    inputs: Dict[str, str] = Field(default_factory=dict, description="Input parameters (truncated)")
    
    # Results
    success: bool = Field(True)
    duration_ms: float = Field(0.0, ge=0)
    output_summary: Optional[str] = Field(None, max_length=200)
    error: Optional[str] = Field(None)


class ProgressLogEntry(BaseLogEntry):
    """
    Log entry for progress tracking.
    Step-based tracking WITHOUT percentage.
    """
    level: LogLevel = LogLevel.PROGRESS
    component: str = "system"
    operation: str = "progress"
    
    # Step-based progress (NO percentage)
    current_step: int = Field(..., ge=0, description="Current step number")
    total_steps: int = Field(..., ge=1, description="Total number of steps")
    step_name: str = Field("", description="Name/description of current step")
    steps_remaining: int = Field(..., ge=0, description="Steps remaining")


class TokenSummarySchema(BaseModel):
    """Summary of all token usage in a request"""
    total_input_tokens: int = Field(0, ge=0)
    total_output_tokens: int = Field(0, ge=0)
    total_tokens: int = Field(0, ge=0)
    total_estimated_cost_usd: float = Field(0.0, ge=0)
    llm_call_count: int = Field(0, ge=0)
    calls: List[TokenUsageSchema] = Field(default_factory=list)


class RequestLogEntry(BaseLogEntry):
    """
    Log entry for request-level summary.
    Captures total token usage and cost for entire request cycle.
    """
    component: str = "system"
    operation: str = "request_complete"
    
    # Request completion
    request_complete: bool = Field(True)
    total_duration_ms: float = Field(0.0, ge=0)
    
    # Token summary
    token_summary: Optional[TokenSummarySchema] = Field(None)


class ErrorLogEntry(BaseLogEntry):
    """Log entry for errors"""
    level: LogLevel = LogLevel.ERROR
    
    error_type: str = Field(..., description="Exception type name")
    error_message: str = Field(..., description="Error message")
    stack_trace: Optional[str] = Field(None, description="Stack trace if available")
    
    # Recovery info
    recoverable: bool = Field(True, description="Whether error is recoverable")
    retry_count: int = Field(0, ge=0, description="Number of retries attempted")


class AuditLogEntry(BaseLogEntry):
    """
    Audit log entry for security-sensitive operations.
    Used for tracking user actions and data access.
    """
    level: LogLevel = LogLevel.INFO
    component: str = "audit"
    
    # Audit fields
    user_id: Optional[str] = Field(None, description="User identifier")
    action: str = Field(..., description="Action performed")
    resource_type: str = Field(..., description="Type of resource accessed")
    resource_id: Optional[str] = Field(None, description="Resource identifier")
    
    # Result
    success: bool = Field(True)
    access_level: Optional[str] = Field(None, description="Permission level used")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_llm_log(
    model: str,
    operation: str,
    input_tokens: int,
    output_tokens: int,
    duration_ms: float,
    **kwargs
) -> LLMLogEntry:
    """Helper to create LLM log entry"""
    return LLMLogEntry(
        message=f"LLM call: {operation}",
        model=model,
        operation=operation,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        duration_ms=duration_ms,
        **kwargs
    )


def create_agent_log(
    agent: str,
    tool: str,
    step: int,
    total_steps: int,
    inputs: Dict[str, Any],
    success: bool,
    duration_ms: float,
    **kwargs
) -> AgentLogEntry:
    """Helper to create agent log entry"""
    # Sanitize inputs (truncate long values)
    sanitized_inputs = {k: str(v)[:50] for k, v in inputs.items()}
    
    return AgentLogEntry(
        message=f"Agent call: {agent}.{tool} (step {step}/{total_steps})",
        agent=agent,
        tool=tool,
        step=step,
        total_steps=total_steps,
        inputs=sanitized_inputs,
        success=success,
        duration_ms=duration_ms,
        **kwargs
    )


def create_progress_log(
    message: str,
    current_step: int,
    total_steps: int,
    step_name: str = "",
    **kwargs
) -> ProgressLogEntry:
    """Helper to create progress log entry (step-based, no percentage)"""
    return ProgressLogEntry(
        message=message,
        current_step=current_step,
        total_steps=total_steps,
        step_name=step_name,
        steps_remaining=total_steps - current_step,
        **kwargs
    )


# ============================================================================
# TYPE EXPORTS
# ============================================================================

__all__ = [
    "LogLevel",
    "BaseLogEntry",
    "TokenUsageSchema",
    "LLMLogEntry",
    "AgentLogEntry",
    "ProgressLogEntry",
    "TokenSummarySchema",
    "RequestLogEntry",
    "ErrorLogEntry",
    "AuditLogEntry",
    "create_llm_log",
    "create_agent_log",
    "create_progress_log",
]
