"""
Models for Supervisor Agent

Contains enums, constants, and data models used across the supervisor agent.
"""

from enum import Enum
from typing import Dict, Optional, Any
from pydantic import BaseModel


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
