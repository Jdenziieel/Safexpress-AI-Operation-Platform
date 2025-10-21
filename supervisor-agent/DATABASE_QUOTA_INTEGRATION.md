# Database-Integrated Quota System - Implementation Guide

## Overview

This document explains how to integrate the token quota system with a database, track user daily quotas, implement checks before agent execution, update usage after operations, and handle automatic midnight resets.

---

## 1. Database Schema

### Tables Required

#### Table 1: `users`
```sql
CREATE TABLE users (
    user_id VARCHAR(255) PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    role VARCHAR(50) DEFAULT 'user',  -- 'admin', 'manager', 'user'
    daily_token_limit INTEGER DEFAULT 500000,
    daily_request_limit INTEGER DEFAULT 100,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

#### Table 2: `user_daily_quotas`
```sql
CREATE TABLE user_daily_quotas (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    date DATE NOT NULL,
    tokens_used INTEGER DEFAULT 0,
    requests_made INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE KEY unique_user_date (user_id, date),
    INDEX idx_user_date (user_id, date)
);
```

#### Table 3: `usage_logs`
```sql
CREATE TABLE usage_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    workflow_id VARCHAR(255),
    operation VARCHAR(50) NOT NULL,  -- 'planning', 'agent_call', 'classification'
    agent_name VARCHAR(100),
    tool_name VARCHAR(100),
    tokens_used INTEGER NOT NULL,
    cost_estimate DECIMAL(10, 6),
    status VARCHAR(20) NOT NULL,  -- 'success', 'error', 'quota_exceeded'
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    INDEX idx_user_created (user_id, created_at),
    INDEX idx_workflow (workflow_id),
    INDEX idx_created_at (created_at)
);
```

#### Table 4: `system_hourly_usage`
```sql
CREATE TABLE system_hourly_usage (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    hour_timestamp TIMESTAMP NOT NULL,
    tokens_used INTEGER DEFAULT 0,
    requests_made INTEGER DEFAULT 0,
    active_workflows INTEGER DEFAULT 0,
    
    UNIQUE KEY unique_hour (hour_timestamp),
    INDEX idx_hour (hour_timestamp)
);
```

---

## 2. Database Connection Setup

### Install Dependencies

```bash
pip install sqlalchemy pymysql python-dotenv
```

### Environment Variables (.env)

```bash
# Database Configuration
DB_HOST=localhost
DB_PORT=3306
DB_NAME=supervisor_agent_db
DB_USER=your_db_user
DB_PASSWORD=your_db_password

# Or use connection string
DATABASE_URL=mysql+pymysql://user:password@localhost:3306/supervisor_agent_db
```

### Database Connection Module

**File: `supervisor-agent/database.py`**

```python
"""
Database connection and session management
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import QueuePool
import os
from dotenv import load_dotenv

load_dotenv()

# Database URL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@"
    f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '3306')}/"
    f"{os.getenv('DB_NAME')}"
)

# Create engine with connection pooling
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Check connection health before using
    pool_recycle=3600,   # Recycle connections every hour
    echo=False           # Set to True for SQL debugging
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Thread-safe session
db_session = scoped_session(SessionLocal)

# Base class for models
Base = declarative_base()

def get_db():
    """
    Dependency for FastAPI endpoints.
    Yields a database session and ensures it's closed after use.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)
```

---

## 3. Database Models

**File: `supervisor-agent/db_models.py`**

```python
"""
SQLAlchemy ORM models for quota tracking
"""
from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, DECIMAL, Text, ForeignKey, Index
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"
    
    user_id = Column(String(255), primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(255))
    role = Column(String(50), default="user")
    daily_token_limit = Column(Integer, default=500000)
    daily_request_limit = Column(Integer, default=100)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class UserDailyQuota(Base):
    __tablename__ = "user_daily_quotas"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    tokens_used = Column(Integer, default=0)
    requests_made = Column(Integer, default=0)
    last_updated = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        Index('idx_user_date', 'user_id', 'date'),
        {'mysql_engine': 'InnoDB'}
    )

class UsageLog(Base):
    __tablename__ = "usage_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    workflow_id = Column(String(255))
    operation = Column(String(50), nullable=False)
    agent_name = Column(String(100))
    tool_name = Column(String(100))
    tokens_used = Column(Integer, nullable=False)
    cost_estimate = Column(DECIMAL(10, 6))
    status = Column(String(20), nullable=False)
    error_message = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    
    __table_args__ = (
        Index('idx_user_created', 'user_id', 'created_at'),
        Index('idx_workflow', 'workflow_id'),
        Index('idx_created_at', 'created_at'),
        {'mysql_engine': 'InnoDB'}
    )

class SystemHourlyUsage(Base):
    __tablename__ = "system_hourly_usage"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    hour_timestamp = Column(DateTime, nullable=False, unique=True)
    tokens_used = Column(Integer, default=0)
    requests_made = Column(Integer, default=0)
    active_workflows = Column(Integer, default=0)
    
    __table_args__ = (
        Index('idx_hour', 'hour_timestamp'),
        {'mysql_engine': 'InnoDB'}
    )
```

---

## 4. Quota Manager with Database Integration

**File: `supervisor-agent/quota_manager_db.py`**

```python
"""
Database-integrated quota manager for token tracking and rate limiting
"""
import os
import tiktoken
from datetime import datetime, date, timedelta
from typing import Dict, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db, SessionLocal
from db_models import User, UserDailyQuota, UsageLog, SystemHourlyUsage

class QuotaManagerDB:
    """Manages token quotas with database persistence"""
    
    def __init__(self):
        # Load limits from environment
        self.max_tokens_per_planning = int(os.getenv("MAX_TOKENS_PER_PLANNING", 8000))
        self.max_tokens_per_agent_call = int(os.getenv("MAX_TOKENS_PER_AGENT_CALL", 4000))
        self.max_steps_per_workflow = int(os.getenv("MAX_STEPS_PER_WORKFLOW", 20))
        self.max_tokens_per_hour_system_wide = int(os.getenv("MAX_TOKENS_PER_HOUR_SYSTEM_WIDE", 1000000))
        self.max_concurrent_workflows = int(os.getenv("MAX_CONCURRENT_WORKFLOWS", 10))
        
        # GPT-4 token encoder
        try:
            self.encoding = tiktoken.encoding_for_model("gpt-4")
        except KeyError:
            self.encoding = tiktoken.get_encoding("cl100k_base")
    
    def count_tokens(self, text: str) -> int:
        """Count tokens in text"""
        return len(self.encoding.encode(text))
    
    def get_or_create_daily_quota(self, db: Session, user_id: str, today: date) -> UserDailyQuota:
        """
        Get today's quota record for user, create if doesn't exist.
        This automatically handles daily resets!
        """
        quota = db.query(UserDailyQuota).filter(
            UserDailyQuota.user_id == user_id,
            UserDailyQuota.date == today
        ).first()
        
        if not quota:
            # Create new quota record for today (automatically resets!)
            quota = UserDailyQuota(
                user_id=user_id,
                date=today,
                tokens_used=0,
                requests_made=0
            )
            db.add(quota)
            db.commit()
            db.refresh(quota)
            
            print(f"✅ Created new daily quota for user {user_id} on {today}")
        
        return quota
    
    def check_user_quota(self, db: Session, user_id: str, estimated_tokens: int) -> Tuple[bool, Optional[Dict]]:
        """
        Check if user has enough quota for this request.
        Returns (allowed, error_details)
        
        THIS IS WHERE THE QUOTA CHECK HAPPENS BEFORE EXECUTION!
        """
        today = date.today()
        
        # Get user limits
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            return False, {
                "error_code": "USER_NOT_FOUND",
                "message": f"User {user_id} not found in database"
            }
        
        if not user.is_active:
            return False, {
                "error_code": "USER_INACTIVE",
                "message": "Your account is inactive. Contact administrator."
            }
        
        # Get or create today's quota record
        quota = self.get_or_create_daily_quota(db, user_id, today)
        
        # Check token limit
        tokens_after_request = quota.tokens_used + estimated_tokens
        if tokens_after_request > user.daily_token_limit:
            midnight = datetime.combine(today + timedelta(days=1), datetime.min.time())
            hours_until_reset = (midnight - datetime.now()).total_seconds() / 3600
            
            return False, {
                "error_code": "DAILY_TOKEN_QUOTA_EXCEEDED",
                "message": "You have exceeded your daily token quota.",
                "details": {
                    "tokens_used_today": quota.tokens_used,
                    "daily_limit": user.daily_token_limit,
                    "tokens_requested": estimated_tokens,
                    "tokens_over_limit": tokens_after_request - user.daily_token_limit,
                    "requests_made_today": quota.requests_made,
                    "requests_limit": user.daily_request_limit,
                    "quota_resets_at": midnight.isoformat(),
                    "hours_until_reset": round(hours_until_reset, 1)
                }
            }
        
        # Check request limit
        if quota.requests_made >= user.daily_request_limit:
            midnight = datetime.combine(today + timedelta(days=1), datetime.min.time())
            hours_until_reset = (midnight - datetime.now()).total_seconds() / 3600
            
            return False, {
                "error_code": "DAILY_REQUEST_QUOTA_EXCEEDED",
                "message": "You have exceeded your daily request quota.",
                "details": {
                    "requests_made_today": quota.requests_made,
                    "requests_limit": user.daily_request_limit,
                    "tokens_used_today": quota.tokens_used,
                    "quota_resets_at": midnight.isoformat(),
                    "hours_until_reset": round(hours_until_reset, 1)
                }
            }
        
        # Check system-wide hourly limit
        current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
        system_usage = db.query(SystemHourlyUsage).filter(
            SystemHourlyUsage.hour_timestamp == current_hour
        ).first()
        
        if system_usage and system_usage.tokens_used >= self.max_tokens_per_hour_system_wide:
            next_hour = current_hour + timedelta(hours=1)
            minutes_until_reset = (next_hour - datetime.now()).total_seconds() / 60
            
            return False, {
                "error_code": "SYSTEM_HOURLY_LIMIT_EXCEEDED",
                "message": "System is at capacity. Please try again shortly.",
                "details": {
                    "system_tokens_this_hour": system_usage.tokens_used,
                    "hourly_limit": self.max_tokens_per_hour_system_wide,
                    "retry_after_minutes": round(minutes_until_reset, 1)
                }
            }
        
        # All checks passed!
        return True, None
    
    def record_usage(
        self, 
        db: Session, 
        user_id: str, 
        workflow_id: str, 
        operation: str,
        tokens_used: int,
        agent_name: Optional[str] = None,
        tool_name: Optional[str] = None,
        status: str = "success",
        error_message: Optional[str] = None
    ):
        """
        Record token usage and update quotas.
        THIS IS WHERE USAGE IS ADDED AFTER EXECUTION!
        """
        today = date.today()
        current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
        
        # Calculate cost estimate (GPT-4 Turbo rates)
        cost_per_1k_tokens = 0.02  # Average of input/output
        cost_estimate = (tokens_used / 1000) * cost_per_1k_tokens
        
        # 1. Update user's daily quota
        quota = self.get_or_create_daily_quota(db, user_id, today)
        quota.tokens_used += tokens_used
        quota.requests_made += 1
        
        # 2. Update system hourly usage
        system_usage = db.query(SystemHourlyUsage).filter(
            SystemHourlyUsage.hour_timestamp == current_hour
        ).first()
        
        if not system_usage:
            system_usage = SystemHourlyUsage(
                hour_timestamp=current_hour,
                tokens_used=tokens_used,
                requests_made=1
            )
            db.add(system_usage)
        else:
            system_usage.tokens_used += tokens_used
            system_usage.requests_made += 1
        
        # 3. Create usage log entry
        log_entry = UsageLog(
            user_id=user_id,
            workflow_id=workflow_id,
            operation=operation,
            agent_name=agent_name,
            tool_name=tool_name,
            tokens_used=tokens_used,
            cost_estimate=cost_estimate,
            status=status,
            error_message=error_message
        )
        db.add(log_entry)
        
        # Commit all changes
        db.commit()
        
        print(f"📊 Recorded usage: {tokens_used} tokens for user {user_id} (operation: {operation})")
        print(f"   Daily total: {quota.tokens_used}/{quota.requests_made} requests")
    
    def check_per_request_limit(self, estimated_tokens: int, operation: str) -> Tuple[bool, Optional[Dict]]:
        """
        Check if request is within per-request token limit.
        Call this BEFORE estimating tokens to validate the operation type.
        """
        if operation == "planning":
            limit = self.max_tokens_per_planning
        elif operation == "agent_call":
            limit = self.max_tokens_per_agent_call
        else:
            limit = max(self.max_tokens_per_planning, self.max_tokens_per_agent_call)
        
        if estimated_tokens > limit:
            return False, {
                "error_code": "REQUEST_TOKEN_LIMIT_EXCEEDED",
                "message": f"This request would use {estimated_tokens} tokens, exceeding the limit of {limit} tokens per {operation}.",
                "details": {
                    "tokens_required": estimated_tokens,
                    "tokens_limit": limit,
                    "tokens_over": estimated_tokens - limit,
                    "operation": operation
                }
            }
        
        return True, None
    
    def get_user_quota_status(self, db: Session, user_id: str) -> Dict:
        """Get current quota status for a user"""
        today = date.today()
        user = db.query(User).filter(User.user_id == user_id).first()
        
        if not user:
            return {"error": "User not found"}
        
        quota = self.get_or_create_daily_quota(db, user_id, today)
        
        midnight = datetime.combine(today + timedelta(days=1), datetime.min.time())
        hours_until_reset = (midnight - datetime.now()).total_seconds() / 3600
        
        return {
            "user_id": user_id,
            "date": today.isoformat(),
            "tokens_used": quota.tokens_used,
            "tokens_limit": user.daily_token_limit,
            "tokens_remaining": user.daily_token_limit - quota.tokens_used,
            "token_usage_percent": round((quota.tokens_used / user.daily_token_limit) * 100, 1),
            "requests_made": quota.requests_made,
            "requests_limit": user.daily_request_limit,
            "requests_remaining": user.daily_request_limit - quota.requests_made,
            "quota_resets_at": midnight.isoformat(),
            "hours_until_reset": round(hours_until_reset, 1)
        }


# Global instance
quota_manager = QuotaManagerDB()
```

---

## 5. Integration into supervisor_agent.py

### Step 1: Add Database Dependency

```python
# At the top of supervisor_agent.py, add imports
from database import get_db, init_db
from quota_manager_db import quota_manager
from sqlalchemy.orm import Session
from fastapi import Depends
import uuid
```

### Step 2: Initialize Database on Startup

```python
# Add this after creating the FastAPI app
@app.on_event("startup")
async def startup_event():
    """Initialize database on application startup"""
    print("🔄 Initializing database...")
    init_db()
    print("✅ Database initialized")
```

### Step 3: Update UserRequest Model

```python
class UserRequest(BaseModel):
    input: str
    user_id: str  # ADD THIS - Required for quota tracking
    memory: Optional[Dict[str, Any]] = {}
    policies: Optional[List[Dict[str, Any]]] = [{"rule": "allow all for demo"}]
```

### Step 4: Add Quota Check BEFORE Planning (supervisor_node)

```python
def supervisor_node(state: SharedState, db: Session) -> SharedState:
    """
    STEP 1: Supervisor generates a plan based on user input
    WITH QUOTA CHECKING
    """
    print("\n" + "="*60)
    print("🧠 SUPERVISOR NODE - Planning Phase")
    print("="*60)
    
    user_input = state["input"]
    user_id = state.get("user_id", "unknown")  # Get user_id from state
    context = state.get("context", {})
    
    # Generate workflow ID for tracking
    workflow_id = f"wf_{uuid.uuid4().hex[:12]}"
    state["workflow_id"] = workflow_id
    
    print(f"📥 User Input: {user_input}")
    print(f"👤 User ID: {user_id}")
    print(f"🆔 Workflow ID: {workflow_id}\n")
    
    # STEP 1: ESTIMATE TOKENS FOR PLANNING
    relevant_agents = identify_relevant_agents(user_input)
    filtered_capabilities = get_filtered_capabilities(relevant_agents)
    
    capability_summary = json.dumps(filtered_capabilities, indent=2)
    schema_text = json.dumps(plan_schema, indent=2)
    
    system_prompt = f"""You are the Supervisor agent..."""  # Your existing prompt
    
    # Estimate tokens for this planning request
    estimated_tokens = quota_manager.count_tokens(system_prompt)
    estimated_tokens += quota_manager.count_tokens(user_input)
    estimated_tokens += 2000  # Estimated response size
    
    print(f"📊 Estimated tokens for planning: {estimated_tokens}")
    
    # STEP 2: CHECK PER-REQUEST LIMIT
    per_request_allowed, per_request_error = quota_manager.check_per_request_limit(
        estimated_tokens, 
        "planning"
    )
    
    if not per_request_allowed:
        print(f"❌ Per-request limit exceeded!")
        raise HTTPException(status_code=429, detail=per_request_error)
    
    # STEP 3: CHECK USER DAILY QUOTA
    quota_allowed, quota_error = quota_manager.check_user_quota(
        db, 
        user_id, 
        estimated_tokens
    )
    
    if not quota_allowed:
        print(f"❌ User quota exceeded!")
        # Record failed attempt
        quota_manager.record_usage(
            db=db,
            user_id=user_id,
            workflow_id=workflow_id,
            operation="planning",
            tokens_used=0,
            status="quota_exceeded",
            error_message=quota_error["message"]
        )
        raise HTTPException(status_code=429, detail=quota_error)
    
    print(f"✅ Quota check passed - proceeding with planning")
    
    # STEP 4: CALL LLM (existing code)
    llm_response = llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input}
    ])
    
    # STEP 5: COUNT ACTUAL TOKENS USED
    actual_tokens = quota_manager.count_tokens(system_prompt)
    actual_tokens += quota_manager.count_tokens(user_input)
    actual_tokens += quota_manager.count_tokens(llm_response.content)
    
    print(f"📊 Actual tokens used: {actual_tokens}")
    
    # STEP 6: RECORD USAGE
    quota_manager.record_usage(
        db=db,
        user_id=user_id,
        workflow_id=workflow_id,
        operation="planning",
        tokens_used=actual_tokens,
        status="success"
    )
    
    # Parse plan and continue (existing code)
    try:
        response_text = llm_response.content.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:-3].strip()
        elif response_text.startswith("```"):
            response_text = response_text[3:-3].strip()
            
        plan = json.loads(response_text)
        
        print("✅ Plan generated successfully!")
        # ... rest of existing code
        
    except json.JSONDecodeError as e:
        # Record error
        quota_manager.record_usage(
            db=db,
            user_id=user_id,
            workflow_id=workflow_id,
            operation="planning",
            tokens_used=actual_tokens,
            status="error",
            error_message=str(e)
        )
        raise ValueError(f"Failed to parse LLM response as JSON: {e}")
    
    return {"plan": plan, "context": context, "workflow_id": workflow_id}
```

### Step 5: Update execute_workflow Endpoint

```python
@app.post("/workflow", response_model=WorkflowResponse)
async def execute_workflow(request: UserRequest, db: Session = Depends(get_db)):
    """
    Main endpoint with database-integrated quota tracking
    """
    try:
        print(f"\n📥 Received request from user: {request.user_id}")
        
        # Get current date for context
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        # Prepare initial state WITH user_id
        initial_state: SharedState = {
            "input": request.input,
            "user_id": request.user_id,  # ADD THIS
            "plan": {},
            "context": {
                "today_date": today,
                "yesterday_date": yesterday,
                "current_year": datetime.now().year,
                "current_month": datetime.now().month,
                "current_day": datetime.now().day
            },
            "memory": request.memory,
            "policy": request.policies,
            "final_context": {},
            "workflow_id": None  # Will be set by supervisor_node
        }
        
        print(f"📅 Date context: today={today}, yesterday={yesterday}")
        
        # Execute workflow (pass db session)
        print("🚀 Starting workflow execution...")
        result_state = workflow.invoke(initial_state, config={"configurable": {"db": db}})
        
        print("\n✅ Workflow completed successfully")
        
        return WorkflowResponse(
            status="success",
            final_context=result_state.get("final_context", {}),
            plan=result_state.get("plan", {}),
            message="Workflow executed successfully"
        )
    
    except HTTPException as http_ex:
        # Already handled quota errors - just re-raise
        raise http_ex
    
    except Exception as e:
        print(f"\n❌ Error executing workflow: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Workflow execution failed: {str(e)}"
        )
```

### Step 6: Add Quota Status Endpoint

```python
@app.get("/quota/status")
async def get_quota_status(user_id: str, db: Session = Depends(get_db)):
    """Get current quota status for a user"""
    try:
        status = quota_manager.get_user_quota_status(db, user_id)
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

## 6. Automatic Midnight Reset

### How It Works

**The midnight reset happens AUTOMATICALLY** through the database design:

1. **Date-based partitioning**: Each day has a unique record in `user_daily_quotas` table
2. **Automatic creation**: When `get_or_create_daily_quota()` is called with today's date, it either:
   - Returns existing record for today (if exists)
   - Creates NEW record with `tokens_used=0` and `requests_made=0` (if today's record doesn't exist)

3. **No manual reset needed**: At midnight, the first request will automatically create a new record for the new day!

### Optional: Scheduled Cleanup Task

To keep database size manageable, add a cleanup task:

```python
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import date, timedelta

def cleanup_old_quota_records():
    """Delete quota records older than 90 days"""
    db = SessionLocal()
    try:
        cutoff_date = date.today() - timedelta(days=90)
        deleted = db.query(UserDailyQuota).filter(
            UserDailyQuota.date < cutoff_date
        ).delete()
        
        db.commit()
        print(f"🧹 Cleaned up {deleted} old quota records (before {cutoff_date})")
    except Exception as e:
        print(f"❌ Error during cleanup: {e}")
        db.rollback()
    finally:
        db.close()

# Start scheduler on app startup
@app.on_event("startup")
async def start_scheduler():
    scheduler = BackgroundScheduler()
    # Run cleanup daily at 2 AM
    scheduler.add_job(cleanup_old_quota_records, 'cron', hour=2, minute=0)
    scheduler.start()
    print("✅ Scheduled cleanup task started (runs daily at 2 AM)")
```

---

## 7. Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    USER REQUEST ARRIVES                      │
│             POST /workflow {user_id, input}                  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              1. SUPERVISOR_NODE (Planning)                   │
├─────────────────────────────────────────────────────────────┤
│  a. Generate workflow_id                                     │
│  b. Estimate tokens for planning                             │
│  c. CHECK: Per-request limit (8K tokens)                     │
│  d. CHECK: User daily quota (DB query)                       │
│  e. If checks fail → Return 429 error                        │
│  f. If checks pass → Call LLM for planning                   │
│  g. Count actual tokens used                                 │
│  h. RECORD USAGE in database:                                │
│     - Update user_daily_quotas.tokens_used                   │
│     - Update user_daily_quotas.requests_made                 │
│     - Insert into usage_logs                                 │
│     - Update system_hourly_usage                             │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│            2. ORCHESTRATOR_NODE (Execution)                  │
├─────────────────────────────────────────────────────────────┤
│  FOR EACH STEP IN PLAN:                                      │
│    a. Estimate tokens for agent call                         │
│    b. CHECK: Per-request limit (4K tokens)                   │
│    c. CHECK: User daily quota (DB query)                     │
│    d. If checks fail → Log error, skip step                  │
│    e. If checks pass → Call agent microservice               │
│    f. Count actual tokens from agent response                │
│    g. RECORD USAGE in database                               │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                3. RETURN FINAL RESULT                        │
│         {status, final_context, plan, message}               │
└─────────────────────────────────────────────────────────────┘

                     DATABASE OPERATIONS
┌─────────────────────────────────────────────────────────────┐
│  get_or_create_daily_quota(user_id, today)                   │
│  ├─ Query: SELECT * FROM user_daily_quotas                   │
│  │         WHERE user_id=? AND date=?                         │
│  ├─ If found: Return existing record                         │
│  └─ If not found: INSERT new record with zeros               │
│     (THIS IS THE AUTOMATIC RESET!)                           │
└─────────────────────────────────────────────────────────────┘

                   MIDNIGHT BEHAVIOR
┌─────────────────────────────────────────────────────────────┐
│  Oct 20, 11:59 PM → Query returns record for Oct 20          │
│  Oct 21, 12:01 AM → Query finds NO record for Oct 21         │
│                  → Creates NEW record with tokens_used=0     │
│                  → AUTOMATIC RESET! No cron job needed       │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. Summary of Key Points

### ✅ WHERE quota checking happens:
1. **Before planning** (supervisor_node) - Check user quota + per-request limit
2. **Before each agent call** (orchestrator_node) - Check user quota + per-request limit

### ✅ HOW usage is recorded (AFTER execution):
```python
quota_manager.record_usage(
    db=db,
    user_id=user_id,
    workflow_id=workflow_id,
    operation="planning",  # or "agent_call"
    tokens_used=actual_tokens,
    agent_name=agent_name,  # if agent call
    tool_name=tool_name,    # if agent call
    status="success"        # or "error", "quota_exceeded"
)
```

This function:
- Updates `user_daily_quotas.tokens_used` (adds tokens)
- Updates `user_daily_quotas.requests_made` (increments by 1)
- Inserts row into `usage_logs` (for analytics)
- Updates `system_hourly_usage` (for system-wide tracking)

### ✅ HOW midnight reset works:
- **NO cron job needed!**
- Database stores separate record for each date
- `get_or_create_daily_quota(user_id, today)` automatically creates new record with zeros if today's record doesn't exist
- First request after midnight automatically gets fresh quota

### ✅ Optional cleanup:
- Use `apscheduler` to delete records older than 90 days
- Runs daily at 2 AM
- Keeps database size manageable

---

## 9. Next Steps

1. **Run database migrations** to create tables
2. **Seed initial users** in `users` table
3. **Update supervisor_agent.py** with quota checks
4. **Test quota limits** with sample workflows
5. **Monitor usage** through database queries

This implementation is production-ready and scales to hundreds of users!
