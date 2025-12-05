"""
Pydantic Models for Token Quota Service
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ==============================================================================
# QUOTA TIERS
# ==============================================================================

class QuotaTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"
    UNLIMITED = "unlimited"


# Token limits per tier (monthly)
TIER_LIMITS = {
    QuotaTier.FREE: 100_000,        # 100K tokens/month
    QuotaTier.PRO: 1_000_000,       # 1M tokens/month
    QuotaTier.ENTERPRISE: 10_000_000,  # 10M tokens/month
    QuotaTier.UNLIMITED: 999_999_999,  # Effectively unlimited
}


# ==============================================================================
# REQUEST/RESPONSE MODELS
# ==============================================================================

class QuotaCheckRequest(BaseModel):
    """Request to check if user has sufficient quota."""
    user_id: str = Field(..., description="Unique user identifier from JWT")
    estimated_tokens: int = Field(0, ge=0, description="Estimated tokens for operation")
    service: Optional[str] = Field(None, description="Service making the request")
    operation: Optional[str] = Field(None, description="Type of operation")


class QuotaCheckResponse(BaseModel):
    """Response from quota check."""
    allowed: bool = Field(..., description="Whether the operation is allowed")
    remaining_tokens: int = Field(..., description="Tokens remaining in quota")
    monthly_limit: int = Field(..., description="Monthly token limit")
    current_usage: int = Field(..., description="Current month's usage")
    percentage_used: float = Field(..., description="Percentage of quota used")
    warning: bool = Field(False, description="True if approaching limit")
    warning_message: Optional[str] = None
    tier: str = Field(..., description="User's quota tier")
    resets_at: str = Field(..., description="ISO timestamp when quota resets")


class UsageReportRequest(BaseModel):
    """Report token usage after an LLM operation."""
    user_id: str = Field(..., description="Unique user identifier from JWT")
    service: str = Field(..., description="Service that used tokens (supervisor, knowledge-base, etc.)")
    operation: str = Field(..., description="Type of operation (chat, embedding, planning, etc.)")
    model: str = Field(..., description="LLM model used (gpt-4o, gpt-4o-mini, etc.)")
    input_tokens: int = Field(..., ge=0, description="Number of input tokens")
    output_tokens: int = Field(..., ge=0, description="Number of output tokens")
    cost_usd: Optional[float] = Field(None, ge=0, description="Estimated cost in USD")
    request_id: Optional[str] = Field(None, description="Request correlation ID")
    session_id: Optional[str] = Field(None, description="Session ID (hashed)")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class UsageReportResponse(BaseModel):
    """Response from usage report."""
    success: bool
    new_usage: int = Field(..., description="New total usage after this operation")
    remaining: int = Field(..., description="Remaining tokens in quota")


# ==============================================================================
# USER QUOTA MODELS
# ==============================================================================

class UserQuota(BaseModel):
    """User quota information."""
    user_id: str
    fullname: Optional[str] = None
    tier: str = QuotaTier.FREE.value
    monthly_limit: int
    current_usage: int
    current_cost_usd: float
    reset_date: str
    created_at: str
    updated_at: str
    is_active: Optional[bool] = True
    deactivated_at: Optional[str] = None


class UserQuotaUpdate(BaseModel):
    """Update user quota settings."""
    tier: Optional[str] = Field(None, description="New tier (free, pro, enterprise, unlimited)")
    monthly_limit: Optional[int] = Field(None, ge=0, description="Custom monthly limit override")
    reset_date: Optional[str] = Field(None, description="Custom reset date (YYYY-MM-DD format)")


# ==============================================================================
# ANALYTICS MODELS
# ==============================================================================

class ServiceUsage(BaseModel):
    """Usage breakdown by service."""
    service: str
    total_tokens: int
    total_cost_usd: float
    call_count: int
    models_used: List[str]


class UsageSummary(BaseModel):
    """Aggregate usage summary."""
    period_hours: int
    total_users: int
    total_tokens: int
    total_cost_usd: float
    total_operations: int
    by_service: List[ServiceUsage]
    by_tier: Dict[str, int]


class TopUser(BaseModel):
    """Top user by usage."""
    user_id: str
    total_tokens: int
    total_cost_usd: float
    tier: str


class UsageLogEntry(BaseModel):
    """Individual usage log entry."""
    id: int
    user_id: str
    fullname: Optional[str] = None
    service: str
    operation: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Optional[str] = None
    timestamp: str


class UsageLogsResponse(BaseModel):
    """Response containing usage logs."""
    logs: List[UsageLogEntry]
    total: int
    page: int
    page_size: int


# ==============================================================================
# ADMIN ACTION LOGGING
# ==============================================================================

class AdminActionEntry(BaseModel):
    """Individual admin action log entry."""
    id: int
    admin_id: Optional[str] = None
    admin_name: Optional[str] = None
    action: str
    target_user_id: Optional[str] = None
    target_user_name: Optional[str] = None
    details: Optional[dict] = None
    timestamp: str


class AdminActionsResponse(BaseModel):
    """Response containing admin action logs."""
    logs: List[AdminActionEntry]
    total: int
    page: int
    page_size: int
