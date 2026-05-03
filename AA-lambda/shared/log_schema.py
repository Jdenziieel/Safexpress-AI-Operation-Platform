"""
Log Schema for AI Agents System

Models are centralized in models/models.py.
This module re-exports them and provides helper functions for creating log entries.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

# All log schema models centralized in models/models.py
from models.models import (
    LogLevel,
    BaseLogEntry,
    TokenUsageSchema,
    LLMLogEntry,
    AgentLogEntry,
    ProgressLogEntry,
    TokenSummarySchema,
    RequestLogEntry,
    ErrorLogEntry,
    AuditLogEntry,
)


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
