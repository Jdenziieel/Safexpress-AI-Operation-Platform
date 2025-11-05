from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel


class ActionApprovalRequest(BaseModel):
    """Request to approve or reject a specific action"""
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

class ActionRiskLevel(str, Enum):
    SAFE = "safe"              # Read-only, no approval needed  
    MODERATE = "moderate"       # Modifies data, optional approval
    DANGEROUS = "dangerous"     # Sends data out, always requires approval
    CRITICAL = "critical"       # Irreversible actions, requires approval + confirmation

#In the event of rejecting or cancellation of task, we would perform rollback feature for all task created. Mostly moderate classification??

# Categorize all actions by risk level
ACTION_RISK_LEVELS = {
    # SAFE - Read-only operations
    "read_recent_emails": ActionRiskLevel.SAFE,
    "search_emails": ActionRiskLevel.SAFE,
    "get_thread_conversation": ActionRiskLevel.SAFE,
    "read_doc": ActionRiskLevel.SAFE,
    
    # MODERATE - Modifies internal state
    "create_draft_email": ActionRiskLevel.MODERATE,  # Draft only, not sent
    "add_label": ActionRiskLevel.MODERATE,           # Just labels
    "remove_label": ActionRiskLevel.MODERATE,
    "create_doc": ActionRiskLevel.MODERATE,          # Creates but doesn't share
    
    # DANGEROUS - Sends data externally
    "send_draft_email": ActionRiskLevel.DANGEROUS,
    "reply_to_email": ActionRiskLevel.DANGEROUS,
    "forward_email": ActionRiskLevel.DANGEROUS,
    "send_email_with_attachment": ActionRiskLevel.DANGEROUS,
    "add_text": ActionRiskLevel.DANGEROUS,           # Modifies shared doc
    
    # CRITICAL - Irreversible actions
    "delete_email": ActionRiskLevel.CRITICAL,        # If you add this
    "remove_label_TRASH": ActionRiskLevel.CRITICAL,  # Permanently delete
}

class ApprovalRequiredException(Exception):
    """Raised when an action requires approval"""
    def __init__(self, action_id: str, step_info: dict, message: str):
        self.action_id = action_id
        self.step_info = step_info
        super().__init__(message)