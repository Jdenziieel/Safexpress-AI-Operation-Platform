"""
Models for Supervisor Agent

Contains enums, constants, and data models used across the supervisor agent.
"""

from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


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


# Categorize all actions by risk level
ACTION_RISK_LEVELS: Dict[str, ActionRiskLevel] = {
    # SAFE - Read-only operations
    "read_recent_emails": ActionRiskLevel.SAFE,
    "search_emails": ActionRiskLevel.SAFE,
    "get_thread_conversation": ActionRiskLevel.SAFE,
    "read_doc": ActionRiskLevel.SAFE,
    "list_files": ActionRiskLevel.SAFE,
    "search_files": ActionRiskLevel.SAFE,
    "get_file_metadata": ActionRiskLevel.SAFE,
    "list_events": ActionRiskLevel.SAFE,
    "get_event": ActionRiskLevel.SAFE,
    "search_knowledge_base": ActionRiskLevel.SAFE,
    
    # MODERATE - Modifies internal state
    "create_draft_email": ActionRiskLevel.MODERATE,  # Draft only, not sent
    "add_label": ActionRiskLevel.MODERATE,           # Just labels
    "remove_label": ActionRiskLevel.MODERATE,
    "create_doc": ActionRiskLevel.MODERATE,          # Creates but doesn't share
    "create_event": ActionRiskLevel.MODERATE,
    "update_event": ActionRiskLevel.MODERATE,
    "upload_file": ActionRiskLevel.MODERATE,
    
    # DANGEROUS - Sends data externally
    "send_draft_email": ActionRiskLevel.DANGEROUS,
    "reply_to_email": ActionRiskLevel.DANGEROUS,
    "send_email_with_attachment": ActionRiskLevel.DANGEROUS,
    "add_text": ActionRiskLevel.DANGEROUS,           # Modifies shared doc
    "share_file": ActionRiskLevel.DANGEROUS,
    
    # CRITICAL - Irreversible actions
    "delete_email": ActionRiskLevel.CRITICAL,
    "delete_file": ActionRiskLevel.CRITICAL,
    "delete_event": ActionRiskLevel.CRITICAL,
    "remove_label_TRASH": ActionRiskLevel.CRITICAL,  # Permanently delete
}


# =============================================================================
# Conversational Agent Models
# =============================================================================

class ConversationIntent(str, Enum):
    """Intent classification for conversation state"""
    NEEDS_CLARIFICATION = "needs_clarification"  # Missing info, ask user
    NOT_FEASIBLE = "not_feasible"  # Can't do with current tools
    TOO_COMPLEX = "too_complex"  # Task needs breaking down
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
    # Execution metadata (added to support supervisor execution history)
    execution_history: List[Dict[str, Any]] = Field(default_factory=list)
    executed_count: int = 0
    last_plan_hash: Optional[str] = None
    last_executed_at: Optional[str] = None
    executing: bool = False
    
    # NEW: Memory manager state (for persistence)
    memory_state: Optional[Dict[str, Any]] = None


class ConversationAnalysis(BaseModel):
    """LLM's analysis of the user request"""
    intent: ConversationIntent
    task_type: str  # e.g., "send_email", "search_emails", "manage_calendar"
    extracted_info: Dict[str, Any]
    missing_fields: List[str]
    clarification_question: Optional[str] = None
    reasoning: str
    suggested_alternatives: Optional[List[str]] = None
    execution_ready: bool
    execution_summary: Optional[str] = None
