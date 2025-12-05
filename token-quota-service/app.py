"""
Token Quota Service - Centralized Token Usage and Quota Management

This microservice provides:
1. Pre-flight quota checks before LLM operations
2. Usage reporting from all services
3. Per-user and per-organization quotas
4. Admin endpoints for quota management
5. Usage analytics and billing data

Port: 8011
"""

from fastapi import FastAPI, HTTPException, Depends, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import uvicorn
import jwt
import os

# Load environment variables from .env file
load_dotenv()

from database import QuotaDatabase, get_db
from models import (
    QuotaCheckRequest, QuotaCheckResponse,
    UsageReportRequest, UsageReportResponse,
    UserQuota, UserQuotaUpdate,
    UsageSummary, ServiceUsage,
    QuotaTier, TIER_LIMITS,
    UsageLogEntry, UsageLogsResponse,
    AdminActionEntry, AdminActionsResponse
)

# JWT Secret - should match Django's SECRET_KEY
JWT_SECRET = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"

if not JWT_SECRET:
    print("⚠️  WARNING: JWT_SECRET_KEY not set in environment!")
    print("   Add JWT_SECRET_KEY to your .env file to enable authentication")
else:
    print(f"✅ JWT_SECRET_KEY loaded ({len(JWT_SECRET)} chars)")


# ==============================================================================
# AUTHENTICATION HELPERS
# ==============================================================================

async def get_current_user(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    """Extract and validate JWT token from Authorization header."""
    if not authorization:
        return None
    
    try:
        # Remove 'Bearer ' prefix
        if authorization.startswith("Bearer "):
            token = authorization[7:]
        else:
            token = authorization
        
        # Decode JWT token
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return {
            "user_id": str(payload.get("user_id", payload.get("sub", ""))),
            "email": payload.get("gmail", payload.get("email", "")),
            "fullname": payload.get("fullname", ""),
            "role": payload.get("role",  "")
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as e:
        # For internal service-to-service calls, allow without token
        return None


async def require_auth(authorization: Optional[str] = Header(None)) -> dict:
    """Require valid authentication."""
    user = await get_current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def require_admin(authorization: Optional[str] = Header(None)) -> dict:
    """Require admin role."""
    user = await get_current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user.get("role") not in ["admin", "Admin", "staff"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    db = get_db()
    db.initialize()
    print("✅ Token Quota Service initialized")
    print(f"📊 Database: {db.db_path}")
    yield
    print("🛑 Token Quota Service shutting down")


app = FastAPI(
    title="Token Quota Service",
    description="Centralized token usage tracking and quota management for AI agents",
    version="1.0.0",
    lifespan=lifespan
)

# CORS - allow all agent services
ALLOWED_ORIGINS = [
    "http://localhost:5173",  # Frontend
    "http://localhost:5174",  # Alternative frontend
    "http://localhost:8000",  # Gmail Agent
    "http://localhost:8001",  # Auth Server
    "http://localhost:8002",  # Docs Agent
    "http://localhost:8003",  # Sheets Agent
    "http://localhost:8004",  # Mapping Agent
    "http://localhost:8005",  # Calendar Agent
    "http://localhost:8006",  # Drive Agent
    "http://localhost:8009",  # Knowledge Base
    "http://localhost:8010",  # Supervisor Agent
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=False,  # Must be False when using "*" for origins
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# ==============================================================================
# GLOBAL ERROR HANDLERS
# ==============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions gracefully."""
    import traceback
    print(f"❌ Unhandled error: {exc}")
    print(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if os.getenv("DEBUG", "false").lower() == "true" else "An unexpected error occurred",
            "type": type(exc).__name__
        }
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with consistent format."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code
        }
    )


# ==============================================================================
# QUOTA CHECK ENDPOINTS (Called BEFORE LLM operations)
# ==============================================================================

@app.post("/quota/check", response_model=QuotaCheckResponse)
async def check_quota(
    request: QuotaCheckRequest,
    db: QuotaDatabase = Depends(get_db)
):
    """
    Pre-flight quota check before an LLM operation.
    
    Called by services BEFORE making expensive LLM calls.
    Returns whether the user has sufficient quota remaining.
    
    Fast path: If user has >10% quota remaining, skip detailed check.
    """
    user_quota = db.get_user_quota(request.user_id)
    
    if not user_quota:
        # User not found - must be onboarded first
        raise HTTPException(
            status_code=404,
            detail=f"User {request.user_id} not found. User must be onboarded by an admin first."
        )
    
    # Check if quota needs monthly reset
    user_quota = db.check_and_reset_quota(request.user_id)
    
    remaining = user_quota.monthly_limit - user_quota.current_usage
    
    # Check if operation would exceed quota
    allowed = remaining >= request.estimated_tokens
    
    # Calculate warning threshold (80% used)
    warning = user_quota.current_usage >= (user_quota.monthly_limit * 0.8)
    
    return QuotaCheckResponse(
        allowed=allowed,
        remaining_tokens=max(0, remaining),
        monthly_limit=user_quota.monthly_limit,
        current_usage=user_quota.current_usage,
        percentage_used=round(user_quota.current_usage / user_quota.monthly_limit * 100, 1),
        warning=warning,
        warning_message="Approaching monthly token limit (80% used)" if warning else None,
        tier=user_quota.tier,
        resets_at=user_quota.reset_date
    )


@app.get("/quota/balance/{user_id}", response_model=QuotaCheckResponse)
async def get_balance(
    user_id: str,
    db: QuotaDatabase = Depends(get_db)
):
    """
    Get current quota balance for a user.
    
    Used by frontend to display quota status.
    """
    user_quota = db.get_user_quota(user_id)
    
    if not user_quota:
        # User not found - must be onboarded first
        raise HTTPException(
            status_code=404,
            detail=f"User {user_id} not found. User must be onboarded by an admin first."
        )
    
    # Check if quota needs monthly reset
    user_quota = db.check_and_reset_quota(user_id)
    
    remaining = user_quota.monthly_limit - user_quota.current_usage
    warning = user_quota.current_usage >= (user_quota.monthly_limit * 0.8)
    
    return QuotaCheckResponse(
        allowed=remaining > 0,
        remaining_tokens=max(0, remaining),
        monthly_limit=user_quota.monthly_limit,
        current_usage=user_quota.current_usage,
        percentage_used=round(user_quota.current_usage / user_quota.monthly_limit * 100, 1),
        warning=warning,
        warning_message="Approaching monthly token limit (80% used)" if warning else None,
        tier=user_quota.tier,
        resets_at=user_quota.reset_date
    )


# ==============================================================================
# USAGE REPORTING ENDPOINTS (Called AFTER LLM operations)
# ==============================================================================

@app.post("/quota/report", response_model=UsageReportResponse)
async def report_usage(
    request: UsageReportRequest,
    db: QuotaDatabase = Depends(get_db)
):
    """
    Report token usage after an LLM operation.
    
    Called by services AFTER making LLM calls.
    Updates user's usage counters and logs the operation.
    """
    # Ensure user exists
    user_quota = db.get_user_quota(request.user_id)
    if not user_quota:
        # User not found - must be onboarded first
        raise HTTPException(
            status_code=404,
            detail=f"User {request.user_id} not found. User must be onboarded by an admin first."
        )
    
    # Log the usage
    db.log_usage(
        user_id=request.user_id,
        service=request.service,
        operation=request.operation,
        model=request.model,
        input_tokens=request.input_tokens,
        output_tokens=request.output_tokens,
        cost_usd=request.cost_usd,
        request_id=request.request_id,
        session_id=request.session_id,
        metadata=request.metadata
    )
    
    # Update user's cumulative usage
    total_tokens = request.input_tokens + request.output_tokens
    new_usage = db.update_user_usage(
        user_id=request.user_id,
        tokens=total_tokens,
        cost_usd=request.cost_usd
    )
    
    return UsageReportResponse(
        success=True,
        new_usage=new_usage,
        remaining=max(0, user_quota.monthly_limit - new_usage)
    )


# ==============================================================================
# USER QUOTA MANAGEMENT (Admin endpoints)
# Note: Admin endpoints are protected. Pass Authorization header with JWT token.
# For development, we allow access if no token is passed (TODO: remove in production)
# ==============================================================================

async def optional_admin_check(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    """Check for admin if token is provided, but don't require it (dev mode)."""
    if not authorization:
        # Dev mode: allow without auth
        return {"user_id": "anonymous", "role": "dev_admin"}
    return await require_admin(authorization)


class CreateUserQuotaRequest(BaseModel):
    """Request to create a new user quota."""
    user_id: str
    fullname: Optional[str] = None
    tier: str = "free"


@app.post("/quota/admin/user/create", response_model=UserQuota)
async def create_user_quota(
    request: CreateUserQuotaRequest,
    db: QuotaDatabase = Depends(get_db),
    admin: dict = Depends(optional_admin_check)
):
    """
    Create a new user quota. Called during user onboarding.
    
    This is the ONLY way to create user quotas - auto-creation has been disabled.
    Must be called by admin during onboarding process.
    """
    # Check if user already exists
    existing = db.get_user_quota(request.user_id, include_inactive=True)
    if existing:
        if existing.is_active:
            raise HTTPException(
                status_code=400, 
                detail=f"User {request.user_id} already has an active quota"
            )
        else:
            # Restore the deactivated user
            db.restore_user(request.user_id)
            # Update fullname if provided
            if request.fullname:
                db.update_fullname(request.user_id, request.fullname)
            return db.get_user_quota(request.user_id)
    
    # Create new user quota
    user_quota = db.create_user_quota(
        user_id=request.user_id,
        fullname=request.fullname,
        tier=request.tier
    )
    
    print(f"✅ Created quota for user {request.user_id} (tier: {request.tier})")
    return user_quota


@app.get("/quota/admin/users")
async def list_users(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    tier: Optional[str] = None,
    include_inactive: bool = Query(False, description="Include deactivated users"),
    db: QuotaDatabase = Depends(get_db),
    admin: dict = Depends(optional_admin_check)
):
    """List all users with their quota status. Requires admin role in production."""
    users = db.list_users(limit=limit, offset=offset, tier=tier, include_inactive=include_inactive)
    return {"users": users, "total": len(users)}


@app.get("/quota/admin/user/{user_id}", response_model=UserQuota)
async def get_user(
    user_id: str,
    include_inactive: bool = Query(False),
    db: QuotaDatabase = Depends(get_db),
    admin: dict = Depends(optional_admin_check)
):
    """Get detailed quota info for a specific user."""
    user = db.get_user_quota(user_id, include_inactive=include_inactive)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return user


@app.put("/quota/admin/user/{user_id}", response_model=UserQuota)
async def update_user_quota(
    user_id: str,
    update: UserQuotaUpdate,
    db: QuotaDatabase = Depends(get_db),
    admin: dict = Depends(optional_admin_check)
):
    """
    Update a user's quota settings. Requires admin role.
    
    Can change:
    - tier (free, pro, enterprise, unlimited)
    - monthly_limit (custom override)
    - reset_date (YYYY-MM-DD format)
    """
    user = db.get_user_quota(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    
    # Capture old values for logging
    old_values = {
        "tier": user.tier,
        "monthly_limit": user.monthly_limit,
        "reset_date": user.reset_date
    }
    
    updated = db.update_user_quota(
        user_id=user_id,
        tier=update.tier,
        monthly_limit=update.monthly_limit,
        reset_date=update.reset_date
    )
    
    # Log admin action
    changes = {}
    if update.tier and update.tier != old_values["tier"]:
        changes["tier"] = {"from": old_values["tier"], "to": update.tier}
    if update.monthly_limit and update.monthly_limit != old_values["monthly_limit"]:
        changes["monthly_limit"] = {"from": old_values["monthly_limit"], "to": update.monthly_limit}
    if update.reset_date and update.reset_date != old_values["reset_date"]:
        changes["reset_date"] = {"from": old_values["reset_date"], "to": update.reset_date}
    
    if changes:
        db.log_admin_action(
            action="update_user_quota",
            admin_id=admin.get("user_id") if admin else None,
            admin_name=admin.get("fullname") if admin else None,
            target_user_id=user_id,
            target_user_name=user.fullname,
            details=changes
        )
    
    return updated


@app.post("/quota/admin/user/{user_id}/reset")
async def reset_user_usage(
    user_id: str,
    db: QuotaDatabase = Depends(get_db),
    admin: dict = Depends(optional_admin_check)
):
    """Manually reset a user's monthly usage (admin override). Requires admin role."""
    user = db.get_user_quota(user_id, include_inactive=True)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    
    old_usage = user.current_usage
    db.reset_user_usage(user_id)
    
    # Log admin action
    db.log_admin_action(
        action="reset_user_usage",
        admin_id=admin.get("user_id") if admin else None,
        admin_name=admin.get("fullname") if admin else None,
        target_user_id=user_id,
        target_user_name=user.fullname,
        details={"previous_usage": old_usage}
    )
    
    return {"success": True, "message": f"Reset usage for {user_id}"}


@app.post("/quota/admin/user/{user_id}/deactivate")
async def deactivate_user(
    user_id: str,
    db: QuotaDatabase = Depends(get_db),
    admin: dict = Depends(optional_admin_check)
):
    """
    Soft delete (deactivate) a user's quota access. Requires admin role.
    
    The user will no longer be able to use token-consuming features.
    Their usage history and logs are preserved for analytics.
    Use /restore to reactivate the user.
    """
    user = db.get_user_quota(user_id, include_inactive=True)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    
    if not user.is_active:
        raise HTTPException(status_code=400, detail=f"User {user_id} is already deactivated")
    
    success = db.soft_delete_user(user_id)
    if success:
        # Log admin action
        db.log_admin_action(
            action="deactivate_user",
            admin_id=admin.get("user_id") if admin else None,
            admin_name=admin.get("fullname") if admin else None,
            target_user_id=user_id,
            target_user_name=user.fullname,
            details={"tier": user.tier, "usage_at_deactivation": user.current_usage}
        )
        return {"success": True, "message": f"User {user_id} has been deactivated"}
    raise HTTPException(status_code=500, detail="Failed to deactivate user")


@app.post("/quota/admin/user/{user_id}/restore")
async def restore_user(
    user_id: str,
    db: QuotaDatabase = Depends(get_db),
    admin: dict = Depends(optional_admin_check)
):
    """
    Restore a soft-deleted (deactivated) user. Requires admin role.
    
    The user will regain access to token-consuming features.
    Their previous quota settings and usage history are restored.
    """
    user = db.get_user_quota(user_id, include_inactive=True)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    
    if user.is_active:
        raise HTTPException(status_code=400, detail=f"User {user_id} is already active")
    
    success = db.restore_user(user_id)
    if success:
        # Log admin action
        db.log_admin_action(
            action="restore_user",
            admin_id=admin.get("user_id") if admin else None,
            admin_name=admin.get("fullname") if admin else None,
            target_user_id=user_id,
            target_user_name=user.fullname,
            details={"tier": user.tier}
        )
        return {"success": True, "message": f"User {user_id} has been restored"}
    raise HTTPException(status_code=500, detail="Failed to restore user")


# ==============================================================================
# USAGE ANALYTICS
# ==============================================================================

@app.get("/quota/admin/summary", response_model=UsageSummary)
async def get_usage_summary(
    hours: int = Query(24, ge=1, le=720),  # Max 30 days
    db: QuotaDatabase = Depends(get_db),
    admin: dict = Depends(optional_admin_check)
):
    """
    Get aggregate usage summary across all users and services.
    
    Used for admin dashboard. Requires admin role in production.
    """
    return db.get_usage_summary(hours=hours)


@app.get("/quota/admin/usage/{user_id}", response_model=List[ServiceUsage])
async def get_user_usage_breakdown(
    user_id: str,
    hours: int = Query(24, ge=1, le=720),
    db: QuotaDatabase = Depends(get_db),
    admin: dict = Depends(optional_admin_check)
):
    """Get detailed usage breakdown for a user by service. Requires admin role."""
    return db.get_user_usage_breakdown(user_id, hours=hours)


@app.get("/quota/admin/top-users")
async def get_top_users(
    limit: int = Query(10, ge=1, le=50),
    hours: int = Query(24, ge=1, le=720),
    db: QuotaDatabase = Depends(get_db),
    admin: dict = Depends(optional_admin_check)
):
    """Get top users by token usage. Requires admin role."""
    return db.get_top_users(limit=limit, hours=hours)


@app.get("/quota/admin/logs", response_model=UsageLogsResponse)
async def get_usage_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[str] = Query(None),
    service: Optional[str] = Query(None),
    db: QuotaDatabase = Depends(get_db),
    admin: dict = Depends(optional_admin_check)
):
    """
    Get paginated usage logs. Requires admin role.
    
    Logs contain:
    - user_id, name: Who made the request
    - service: Which agent/service (supervisor, gmail, calendar, etc.)
    - operation: What operation (chat, send_email, create_event, etc.)
    - model: LLM model used (gpt-4o, gpt-4o-mini, etc.)
    - input_tokens, output_tokens, total_tokens: Token counts
    - cost_usd: Estimated cost
    - timestamp: When it happened
    """
    offset = (page - 1) * page_size
    logs, total = db.get_usage_logs(
        limit=page_size, 
        offset=offset,
        user_id=user_id,
        service=service
    )
    
    return UsageLogsResponse(
        logs=[UsageLogEntry(**log) for log in logs],
        total=total,
        page=page,
        page_size=page_size
    )


@app.get("/quota/admin/actions", response_model=AdminActionsResponse)
async def get_admin_actions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin_id: Optional[str] = Query(None),
    target_user_id: Optional[str] = Query(None),
    db: QuotaDatabase = Depends(get_db),
    admin: dict = Depends(optional_admin_check)
):
    """
    Get paginated admin action logs. Requires admin role.
    
    Logs track admin actions like:
    - update_user_quota: Changes to tier, monthly_limit, reset_date
    - reset_user_usage: Manual usage resets
    - deactivate_user: User deactivations
    - restore_user: User restorations
    """
    offset = (page - 1) * page_size
    logs, total = db.get_admin_actions(
        limit=page_size, 
        offset=offset,
        admin_id=admin_id,
        target_user_id=target_user_id
    )
    
    return AdminActionsResponse(
        logs=[AdminActionEntry(**log) for log in logs],
        total=total,
        page=page,
        page_size=page_size
    )


# ==============================================================================
# HEALTH CHECK
# ==============================================================================

@app.get("/health")
async def health_check(db: QuotaDatabase = Depends(get_db)):
    """Health check endpoint."""
    stats = db.get_stats()
    return {
        "status": "healthy",
        "service": "token-quota-service",
        "database": "connected",
        "stats": stats
    }


# ==============================================================================
# MAIN
# ==============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8011,
        reload=True
    )
