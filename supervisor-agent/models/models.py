"""
Models for Supervisor Agent

Contains enums, constants, and data models used across the supervisor agent.
All model classes (Pydantic BaseModel, Enum, dataclass, TypedDict) are
centralized here for organization.
"""

from enum import Enum
from typing import Dict, List, Optional, Any, TypedDict
from dataclasses import dataclass, field
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# Action / Risk Models
# =============================================================================

class ActionRiskLevel(str, Enum):
    """Risk levels for agent actions"""
    SAFE = "safe"              # Read-only, no approval needed
    MODERATE = "moderate"       # Modifies data, optional approval
    DANGEROUS = "dangerous"     # Sends data out, always requires approval
    CRITICAL = "critical"       # Irreversible actions, requires approval + confirmation


class ActionApprovalRequest(BaseModel):
    """Request to approve or reject a specific action"""
    action_id: str
    decision: str  # "approve", "reject", "skip"
    modified_inputs: Optional[Dict[str, Any]] = None
    rejection_reason: Optional[str] = None


class ActionApprovalResponse(BaseModel):
    """Response for action requiring approval"""
    action_id: str
    status: str
    step_info: Dict[str, Any]
    message: str
    approval_endpoint: str
    timeout_seconds: int = 300  # 5 minutes default


# Risk classification decision tree — USE THIS when adding a new tool:
#
#   SAFE        → Read-only external API calls, in-memory transforms, or
#                 local-only side effects (downloading an attachment to a
#                 temp dir, writing to a local SQLite metadata DB). No
#                 visible change to the user's Google account state.
#
#   MODERATE    → Creates a NEW artifact in the user's account that is
#                 easy to reverse by the user (a new folder, a new draft,
#                 a new sheet, a new calendar event, a rename, a move).
#                 Also: adding a label, creating a doc from a template.
#                 MODERATE tools DO NOT pause by default
#                 (auto_approve_moderate=True in requires_approval).
#
#   DANGEROUS   → Sends data OUTWARD (email to another party) OR rewrites
#                 EXISTING shared/collaborative content in place (edit_doc,
#                 update_doc, append to sheet, update sheet, write delivery
#                 order data). Always pauses for approval.
#
#   CRITICAL    → Permanent, irreversible data loss (delete_*, clear_sheet,
#                 permanent-trash remove). Pauses for approval + explicit
#                 confirmation flow.
#
# When in doubt, choose the MORE conservative tier. Any tool not listed here
# falls back to get_action_risk_level() in supervisor_agent.py, which applies
# name-based heuristics (tools starting with 'delete_'/'purge_'/'wipe_'
# escalate to CRITICAL; 'send_'/'forward_'/'update_'/'edit_'/'append_'/
# 'write_'/'share_'/'replace_'/'publish_' escalate to DANGEROUS) before
# defaulting to MODERATE. Those heuristics are a safety net only — you
# should still register new DANGEROUS/CRITICAL tools here explicitly so the
# classification is deterministic and auditable.
ACTION_RISK_LEVELS: Dict[str, ActionRiskLevel] = {
    # ===============================================================
    # SAFE — read-only + local-only mutations
    # ===============================================================
    # Gmail (read-only)
    "read_recent_emails": ActionRiskLevel.SAFE,
    "search_emails": ActionRiskLevel.SAFE,
    "search_drafts": ActionRiskLevel.SAFE,
    "get_thread_conversation": ActionRiskLevel.SAFE,
    "download_attachment": ActionRiskLevel.SAFE,            # writes to local temp
    "save_attachment_metadata": ActionRiskLevel.SAFE,       # local SQLite write
    "search_emails_with_delivery_order_attachments": ActionRiskLevel.SAFE,  # search + local downloads
    # Docs (read-only)
    "read_doc": ActionRiskLevel.SAFE,
    "list_my_docs": ActionRiskLevel.SAFE,
    "extract_template_format": ActionRiskLevel.SAFE,
    # Drive (read-only)
    "list_files": ActionRiskLevel.SAFE,
    "list_folders": ActionRiskLevel.SAFE,
    "search_files": ActionRiskLevel.SAFE,
    "search_template_and_data": ActionRiskLevel.SAFE,
    "get_folder_info": ActionRiskLevel.SAFE,
    "get_file_metadata": ActionRiskLevel.SAFE,
    "read_file_content": ActionRiskLevel.SAFE,
    # Sheets (read-only)
    "read_sheet": ActionRiskLevel.SAFE,
    "get_sheet_metadata": ActionRiskLevel.SAFE,
    "get_sheet_headers": ActionRiskLevel.SAFE,
    "validate_delivery_sheet": ActionRiskLevel.SAFE,
    "preview_delivery_order_insertion": ActionRiskLevel.SAFE,
    # Calendar (read-only)
    "list_events": ActionRiskLevel.SAFE,
    "get_event": ActionRiskLevel.SAFE,
    "list_calendars": ActionRiskLevel.SAFE,
    # Mapping (pure transforms on local data)
    "parse_file": ActionRiskLevel.SAFE,
    "parse_delivery_order_pdfs": ActionRiskLevel.SAFE,
    "smart_column_mapping": ActionRiskLevel.SAFE,
    "transform_data": ActionRiskLevel.SAFE,
    "extract_dates_from_all_rows": ActionRiskLevel.SAFE,
    "extract_date_from_data": ActionRiskLevel.SAFE,
    # LLM + KB
    "search_knowledge_base": ActionRiskLevel.SAFE,
    "transform_text": ActionRiskLevel.SAFE,

    # ===============================================================
    # MODERATE — new artifact in user's account (reversible)
    # ===============================================================
    # Gmail
    "create_draft_email": ActionRiskLevel.MODERATE,  # draft, not sent
    "add_label": ActionRiskLevel.MODERATE,
    "remove_label": ActionRiskLevel.MODERATE,
    # Docs (new doc; content additions to a NEW doc are still MODERATE)
    "create_doc": ActionRiskLevel.MODERATE,
    "create_doc_with_content": ActionRiskLevel.MODERATE,
    "create_from_my_template": ActionRiskLevel.MODERATE,
    "create_from_template_and_data_ids": ActionRiskLevel.MODERATE,
    "create_from_uploaded_template": ActionRiskLevel.MODERATE,
    # Drive (new artifact or reversible reparenting/rename)
    "upload_file": ActionRiskLevel.MODERATE,
    "upload_template": ActionRiskLevel.MODERATE,
    "create_folder": ActionRiskLevel.MODERATE,
    "rename_file": ActionRiskLevel.MODERATE,
    "move_file": ActionRiskLevel.MODERATE,
    # Sheets (new spreadsheet)
    "create_sheet": ActionRiskLevel.MODERATE,
    # Calendar (new or modified event; update_event rewrites but events
    # have change history and attendee notifications can be recalled)
    "create_event": ActionRiskLevel.MODERATE,
    "update_event": ActionRiskLevel.MODERATE,
    "create_calendar": ActionRiskLevel.MODERATE,
    "rename_calendar": ActionRiskLevel.MODERATE,
    "resolve_conflict": ActionRiskLevel.MODERATE,

    # ===============================================================
    # DANGEROUS — sends outward or rewrites existing shared content
    # ===============================================================
    # Gmail (outbound email)
    "send_draft_email": ActionRiskLevel.DANGEROUS,
    "reply_to_email": ActionRiskLevel.DANGEROUS,
    "forward_email": ActionRiskLevel.DANGEROUS,
    "send_email_with_attachment": ActionRiskLevel.DANGEROUS,
    "send_email": ActionRiskLevel.DANGEROUS,
    # Docs (in-place content mutation)
    "add_text": ActionRiskLevel.DANGEROUS,
    "add_text_from_file": ActionRiskLevel.DANGEROUS,
    "edit_doc": ActionRiskLevel.DANGEROUS,
    "update_doc": ActionRiskLevel.DANGEROUS,
    # Sheets (in-place row mutation)
    "update_sheet": ActionRiskLevel.DANGEROUS,
    "append_rows": ActionRiskLevel.DANGEROUS,
    "upload_mapped_data": ActionRiskLevel.DANGEROUS,
    "update_by_date_match": ActionRiskLevel.DANGEROUS,
    "write_delivery_order_data": ActionRiskLevel.DANGEROUS,

    # ===============================================================
    # CRITICAL — permanent data loss
    # ===============================================================
    "delete_email": ActionRiskLevel.CRITICAL,
    "delete_file": ActionRiskLevel.CRITICAL,
    "delete_event": ActionRiskLevel.CRITICAL,
    "confirm_delete_event": ActionRiskLevel.CRITICAL,
    "clear_sheet": ActionRiskLevel.CRITICAL,
    "remove_label_TRASH": ActionRiskLevel.CRITICAL,
}


# =============================================================================
# Conversational Agent Models
# =============================================================================

class ConversationIntent(str, Enum):
    """Intent classification for conversation state"""
    NEEDS_CLARIFICATION = "needs_clarification"  # Missing info, ask user
    NOT_FEASIBLE = "not_feasible"  # Can't do with current tools
    TOO_COMPLEX = "too_complex"  # Vague/unbounded request that can't be turned into a concrete plan
    READY_TO_EXECUTE = "ready_to_execute"  # All info present, proceed
    SMALL_TALK = "small_talk"  # Not a task request
    CANCELLED = "cancelled"  # User cancelled the request but data preserved
    TEMPLATE_UPLOAD = "template_upload" 


class ConversationState(BaseModel):
    """Tracks conversation history and extracted information"""
    extracted_info: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    intent: Optional[ConversationIntent] = None
    clarification_question: Optional[str] = None
    ready_for_execution: bool = False
    execution_summary: Optional[str] = None  # Human-readable summary
    execution_mode: str = "standard"  # "standard" or "react"
    # Execution metadata
    execution_history: List[Dict[str, Any]] = Field(default_factory=list)  # For future DB observability
    completed_tasks: List[Dict[str, Any]] = Field(default_factory=list)  # Compact task records for LLM context (capped at 10)
    has_executed: bool = False
    last_executed_at: Optional[str] = None
    last_execution_status: Optional[str] = None   # "success" | "error" | etc.
    last_execution_message: Optional[str] = None   # Human-readable result/error
    executing: bool = False
    
    # Pending action approval state (chat-based approval flow)
    pending_actions: List[Dict[str, Any]] = Field(default_factory=list)
    workflow_paused: bool = False
    remaining_steps: List[Dict[str, Any]] = Field(default_factory=list)
    workflow_context: Optional[Dict[str, Any]] = None  # Saved variable_context for resumption

    # Disambiguation state (multi-result pause)
    disambiguation_options: List[Dict[str, Any]] = Field(default_factory=list)
    disambiguation_variable: Optional[str] = None

    # NEW: Memory manager state (for persistence)
    memory_state: Optional[Dict[str, Any]] = None


class ConversationAnalysis(BaseModel):
    """LLM's analysis of the user request"""
    intent: ConversationIntent
    task_type: str  # e.g., "send_email", "search_emails", "manage_calendar"
    extracted_info: Dict[str, Any]
    missing_fields: List[str]
    clarification_question: Optional[str] = None
    response_text: Optional[str] = None  # Pre-built response for non-task intents (greetings, help, capabilities)
    reasoning: str
    suggested_alternatives: Optional[List[str]] = None
    execution_ready: bool
    execution_summary: Optional[str] = None
    execution_mode: str = "standard"  # "standard" or "react"


# =============================================================================
# Supervisor Agent API Models (moved from supervisor_agent.py)
# =============================================================================

class UserRequest(BaseModel):
    """Pydantic model for API user request"""
    input: str


class CreateThreadRequest(BaseModel):
    """Request to create a new conversation thread"""
    user_id: str
    message: Optional[str] = None


class WorkflowResponse(BaseModel):
    """Response from workflow execution"""
    status: str
    final_context: Dict[str, Any]
    plan: Dict[str, Any]
    message: str


class SharedState(TypedDict):
    """SharedState TypedDict for workflow"""
    input: str
    plan: dict
    context: dict
    final_context: dict
    execution_mode: str  # "standard" or "react"
    # Orchestrator output fields
    results: list
    error: str
    stopped_at_step: int
    # ReAct-specific fields (only used when execution_mode == "react")
    react_history: list       # accumulated observations from previous react steps
    react_iteration: int      # current iteration counter
    react_done: bool          # True when react planner declares task complete


# =============================================================================
# LLM Error Models (moved from llm_error_handler.py)
# =============================================================================

class LLMErrorType(str, Enum):
    """Types of LLM errors for frontend display"""
    RATE_LIMIT = "rate_limit"
    QUOTA_EXCEEDED = "quota_exceeded"
    SERVICE_UNAVAILABLE = "service_unavailable"
    AUTHENTICATION = "authentication"
    INVALID_REQUEST = "invalid_request"
    CONTEXT_LENGTH = "context_length"
    UNKNOWN = "unknown"


@dataclass
class LLMError:
    """Structured LLM error for consistent API responses"""
    error_type: LLMErrorType
    title: str
    message: str
    user_message: str
    status_code: int
    retry_after: Optional[int] = None
    details: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response"""
        return {
            "error": True,
            "error_type": self.error_type.value,
            "title": self.title,
            "message": self.message,
            "user_message": self.user_message,
            "status_code": self.status_code,
            "retry_after": self.retry_after,
            "details": self.details,
            "is_llm_error": True  # Flag for frontend to show LLM error modal
        }


# =============================================================================
# Thread Manager Models (moved from thread_manager.py)
# =============================================================================

class ThreadMetadata(BaseModel):
    """Metadata for a conversation thread"""
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat()
        }
    )
    
    thread_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    title: Optional[str] = None  # Auto-generated from first message
    message_count: int = 0
    status: str = "active"  # active, archived, deleted
    last_message_preview: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


# =============================================================================
# Conversation Memory Models (moved from conversation_memory.py)
# =============================================================================

class ConversationMemory(BaseModel):
    """
    Manages conversation history with automatic summarization and entity extraction.
    
    Components:
    - raw_history: Complete message history (never truncated, for record-keeping)
    - working_context: Recent messages that fit within token budget
    - entity_memory: Extracted entities (people, dates, tasks, etc.)
    - summary: Condensed summary of old conversations
    - MAX_TOKENS_BEFORE_SUMMARY: Threshold to trigger summarization
    """
    
    # Complete history (never truncated)
    raw_history: List[Dict[str, str]] = Field(default_factory=list)
    
    # Recent messages that fit in context window
    working_context: List[Dict[str, str]] = Field(default_factory=list)
    
    # Extracted entities from conversation
    entity_memory: Dict[str, Any] = Field(default_factory=dict)
    
    # Summary of old conversation turns
    summary: Optional[str] = None
    
    # Token threshold for triggering summarization
    MAX_TOKENS_BEFORE_SUMMARY: int = Field(default=2000)
    
    # Token count of current working context
    current_token_count: int = Field(default=0)
    
    class Config:
        arbitrary_types_allowed = True


# =============================================================================
# Logging Models (moved from logging_config.py)
# =============================================================================

class LogLevel(str, Enum):
    """Custom log levels for the system"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    PROGRESS = "PROGRESS"  # Special level for step tracking
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class QuotaCheckResult:
    """Result of a quota check"""
    def __init__(self, allowed: bool, error: str = None, user_deactivated: bool = False):
        self.allowed = allowed
        self.error = error
        self.user_deactivated = user_deactivated


@dataclass
class TokenUsage:
    """Token usage for a single LLM call"""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    model: str = ""
    estimated_cost: float = 0.0
    call_duration_ms: float = 0.0


@dataclass
class RequestTokenSummary:
    """Cumulative token usage for entire request cycle"""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_cached_tokens: int = 0
    total_estimated_cost: float = 0.0
    llm_calls: List[TokenUsage] = field(default_factory=list)

    def add_call(self, usage: TokenUsage):
        """Add a single LLM call's usage to the summary"""
        self.total_input_tokens += usage.input_tokens
        self.total_output_tokens += usage.output_tokens
        self.total_tokens += usage.total_tokens
        self.total_cached_tokens += usage.cached_tokens
        self.total_estimated_cost += usage.estimated_cost
        self.llm_calls.append(usage)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging"""
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "total_cached_tokens": self.total_cached_tokens,
            "total_estimated_cost_usd": round(self.total_estimated_cost, 6),
            "cache_hit_rate": round(self.total_cached_tokens / max(self.total_input_tokens, 1), 3),
            "llm_call_count": len(self.llm_calls),
            "calls": [
                {
                    "model": call.model,
                    "input_tokens": call.input_tokens,
                    "output_tokens": call.output_tokens,
                    "cached_tokens": call.cached_tokens,
                    "total_tokens": call.total_tokens,
                    "cost_usd": round(call.estimated_cost, 6),
                    "duration_ms": round(call.call_duration_ms, 2)
                }
                for call in self.llm_calls
            ]
        }


# =============================================================================
# Log Schema Models (moved from log_schema.py)
# =============================================================================

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
