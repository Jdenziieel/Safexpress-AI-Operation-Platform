# Token Quota System - Current State vs Planned Implementation Analysis

**Date:** October 31, 2025  
**Status:** Pre-Implementation Review

---

## Executive Summary

The TOKEN_QUOTA_SYSTEM.md plan outlines a comprehensive 3-layer quota and rate limiting system. After reviewing your current supervisor agent implementation, **none of the quota system features have been implemented yet**. This analysis documents what needs to be added and provides updated recommendations based on your current architecture.

---

## 1. Current System State

### ✅ What You Have (Related Infrastructure)

1. **Django Backend with SQLite Database** (`backend/`)
   - Database: `db.sqlite3`
   - User management infrastructure exists
   - Can be leveraged for quota tracking

2. **FastAPI Supervisor Agent** (`supervisor-agent/`)
   - Conversational agent layer (pre-validation)
   - Multi-step workflow orchestration
   - Agent classification system (using `gpt-3.5-turbo` for cost optimization)
   - Retry logic with exponential backoff
   - Human-in-the-loop approval system for risky actions
   - In-memory conversation storage

3. **Configuration Management**
   - `.env` file with credentials
   - `config.py` with environment variables
   - Already using `LLM_MODEL` (gpt-4) and `CLASSIFIER_MODEL` (gpt-3.5-turbo)

4. **Current Cost Optimization**
   - Agent classification to filter capabilities (reduces context size)
   - Cheaper model (gpt-3.5-turbo) for agent identification
   - Retry logic with backoff (prevents redundant costly calls)

### ❌ What's Missing (Quota System Components)

**None of the quota system is implemented:**

- ❌ No token counting (`tiktoken` not installed)
- ❌ No per-request limits
- ❌ No per-user daily quotas
- ❌ No system-wide hourly limits
- ❌ No usage tracking/logging
- ❌ No quota enforcement
- ❌ No quota monitoring endpoints
- ❌ No database schema for quotas
- ❌ No middleware for checking limits

---

## 2. Architecture Alignment

### Current Architecture Matches Plan ✅

Your current system architecture **aligns well** with the planned quota system:

```
User Request
    ↓
Conversational Agent (Pre-validation) ← NEW: Add token estimation
    ↓
Supervisor Agent Planning ← NEW: Add token counting + quota check
    ↓
Orchestrator (Agent Execution) ← NEW: Add per-agent call token tracking
    ↓
Response
```

### Integration Points Identified

The quota system can integrate at these existing points:

1. **Before Conversational Agent Analysis** (`conversational_agent.py`)
   - Count tokens in user message
   - Check if user has quota remaining
   
2. **Before Supervisor Planning** (`supervisor_node()`)
   - Estimate planning token cost
   - Check per-request planning limit (8K tokens)
   - Check user's daily quota
   
3. **Before Agent Execution** (`orchestrator_node()`)
   - Track tokens for each agent call
   - Update user's daily usage
   - Log to database

4. **API Endpoints** (FastAPI middleware)
   - Add quota check middleware
   - Add quota status endpoints
   - Add admin quota management endpoints

---

## 3. Updated Recommendations vs Original Plan

### Changes from Original Plan

#### 3.1 Database Choice

**Original Plan:** Suggested PostgreSQL/MySQL for production

**Current Reality:** You have Django with SQLite already

**Recommendation:** 
- **Phase 1 (Now):** Use your existing Django SQLite database for quota tables
- **Phase 2 (Later):** Migrate to PostgreSQL when scaling up
- **Advantage:** Leverage existing Django ORM, models, and migrations

#### 3.2 Storage Architecture

**Original Plan:** In-memory storage for development

**Current Reality:** 
- You already have Django backend with database
- Supervisor uses in-memory for conversations (acceptable for now)

**Recommendation:**
- Store quota data in Django database immediately
- Keep conversation state in-memory (it's temporary)
- Sync quota checks between Django backend and FastAPI supervisor

#### 3.3 User Management

**Original Plan:** Assumed simple user_id strings

**Current Reality:** Django backend likely has User model already

**Recommendation:**
- Integrate with Django's User model
- Use Django user IDs for quota tracking
- Add quota fields to existing User model or create related QuotaProfile model

#### 3.4 Model Usage

**Original Plan:** Assumed GPT-4 for everything

**Current Reality:** 
- You use `gpt-4` for planning (defined in config)
- You use `gpt-3.5-turbo` for agent classification (cheaper)
- Conversational agent uses `gpt-4o` by default

**Updated Cost Estimates:**
```
Supervisor Planning: gpt-4 (~$0.03/1K tokens input, $0.06/1K output)
Classification: gpt-3.5-turbo (~$0.0015/1K tokens input, $0.002/1K output)
Conversational: gpt-4o (~$0.0025/1K tokens input, $0.01/1K output)
Agents: Varies by agent (Gmail/Docs use GPT-4)
```

**Revised Daily Cost Estimate (50% quota usage):**
- Mixed model usage: ~$0.015 average per 1K tokens
- 250K tokens/user/day × $0.015 = **~$3.75/user/day**
- 5 users × 22 days = **~$412.50/month** (vs $550 in original plan)

---

## 4. Implementation Priority & Phases

### Phase 1: Critical Quota System (Week 1-2)

**Priority: HIGH** - Cost control and abuse prevention

1. **Install Dependencies**
   ```bash
   pip install tiktoken sqlalchemy
   ```

2. **Create Django Models** (in `backend/api/models.py`)
   - `UserQuotaProfile` (extends User with quota limits)
   - `DailyQuotaUsage` (tracks daily token usage)
   - `UsageLog` (detailed logging)
   - `SystemHourlyUsage` (system-wide tracking)

3. **Create Quota Manager** (`supervisor-agent/quota_manager.py`)
   - Token counting using tiktoken
   - Quota checking logic
   - Database read/write operations

4. **Integrate into Supervisor** (`supervisor_agent.py`)
   - Add quota check before `supervisor_node()`
   - Add token tracking in `orchestrator_node()`
   - Add error responses for quota exceeded

5. **Add Basic Endpoints**
   ```
   GET /quota/status/{user_id}
   GET /quota/system
   ```

### Phase 2: Monitoring & Admin Tools (Week 3-4)

**Priority: MEDIUM** - Operational visibility

1. **Admin Endpoints**
   ```
   POST /admin/quota/reset
   POST /admin/quota/increase
   GET /admin/usage/summary
   ```

2. **Usage Dashboard** (Optional: Django Admin integration)
   - View user quota usage
   - View system-wide statistics
   - Export usage reports

3. **Automated Alerts**
   - Email when user reaches 80% quota
   - Alert admin when system approaches hourly limit
   - Daily usage summary emails

### Phase 3: Advanced Features (Month 2+)

**Priority: LOW** - Nice to have

1. **Role-based quotas**
   - Different limits for admin/manager/user roles
   - Team-based quota sharing

2. **Predictive analytics**
   - Forecast monthly costs
   - Identify usage patterns

3. **Real-time monitoring**
   - WebSocket connection for live quota updates
   - Dashboard with charts

---

## 5. Updated Quota Limits (Based on Current Usage)

### Recommended Limits (Updated)

```python
# config.py additions

# Per-Request Limits
MAX_TOKENS_PER_PLANNING = 8000          # Supervisor planning
MAX_TOKENS_PER_CLASSIFICATION = 1000    # Agent classification (new)
MAX_TOKENS_PER_CONVERSATION = 2000      # Conversational agent (new)
MAX_TOKENS_PER_AGENT_CALL = 4000        # Individual agent calls
MAX_STEPS_PER_WORKFLOW = 20             # Workflow steps

# Per-User Daily Limits
MAX_TOKENS_PER_USER_PER_DAY = 500000    # ~$7.50/day with mixed models
MAX_REQUESTS_PER_USER_PER_DAY = 100     # Conversations + workflows

# System-Wide Limits
MAX_TOKENS_PER_HOUR_SYSTEM_WIDE = 1000000  # System capacity
MAX_CONCURRENT_WORKFLOWS = 10              # Active workflows
MAX_CONCURRENT_CONVERSATIONS = 20          # Active conversations (new)

# Logging
ENABLE_USAGE_LOGGING = True
USAGE_LOG_DB = True  # Use Django DB instead of CSV
```

### Rationale Updates

1. **Added Conversation Limit (2K tokens)**
   - Your conversational agent does pre-validation
   - Typically uses 500-1500 tokens per turn
   - 2K provides comfortable headroom

2. **Added Classification Limit (1K tokens)**
   - Agent classification is a cheap operation
   - Uses gpt-3.5-turbo
   - 1K is more than enough

3. **Concurrent Conversations (20)**
   - Conversations are lighter than full workflows
   - Multiple users may be chatting simultaneously
   - 20 allows good user experience

---

## 6. Database Schema (Django Models)

### Proposed Django Models

**File: `backend/api/models.py`**

```python
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class UserQuotaProfile(models.Model):
    """Quota settings per user"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='quota_profile')
    role = models.CharField(
        max_length=20, 
        choices=[('admin', 'Admin'), ('manager', 'Manager'), ('user', 'User')],
        default='user'
    )
    daily_token_limit = models.IntegerField(default=500000)
    daily_request_limit = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.role}"

class DailyQuotaUsage(models.Model):
    """Daily token and request usage tracking"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='daily_usage')
    date = models.DateField(default=timezone.now)
    tokens_used = models.IntegerField(default=0)
    requests_made = models.IntegerField(default=0)
    conversations_count = models.IntegerField(default=0)
    workflows_count = models.IntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'date']
        indexes = [
            models.Index(fields=['user', 'date']),
            models.Index(fields=['date']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.date}"

class UsageLog(models.Model):
    """Detailed usage logging"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='usage_logs')
    workflow_id = models.CharField(max_length=100, null=True, blank=True)
    conversation_id = models.CharField(max_length=100, null=True, blank=True)
    operation = models.CharField(
        max_length=50,
        choices=[
            ('planning', 'Supervisor Planning'),
            ('classification', 'Agent Classification'),
            ('conversation', 'Conversational Turn'),
            ('agent_call', 'Agent Execution'),
        ]
    )
    agent_name = models.CharField(max_length=100, null=True, blank=True)
    tool_name = models.CharField(max_length=100, null=True, blank=True)
    model_used = models.CharField(max_length=50)  # gpt-4, gpt-3.5-turbo, etc.
    tokens_used = models.IntegerField()
    cost_estimate = models.DecimalField(max_digits=10, decimal_places=6)
    status = models.CharField(
        max_length=20,
        choices=[
            ('success', 'Success'),
            ('error', 'Error'),
            ('quota_exceeded', 'Quota Exceeded'),
        ]
    )
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['workflow_id']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.operation} - {self.created_at}"

class SystemHourlyUsage(models.Model):
    """System-wide hourly usage tracking"""
    hour_timestamp = models.DateTimeField(unique=True)
    tokens_used = models.IntegerField(default=0)
    requests_made = models.IntegerField(default=0)
    active_workflows = models.IntegerField(default=0)
    active_conversations = models.IntegerField(default=0)
    unique_users = models.IntegerField(default=0)
    
    class Meta:
        indexes = [
            models.Index(fields=['hour_timestamp']),
        ]
    
    def __str__(self):
        return f"System Usage - {self.hour_timestamp}"
```

### Migration Command

```bash
cd backend
python manage.py makemigrations
python manage.py migrate
```

---

## 7. Integration with Existing Features

### 7.1 Conversational Agent Integration

**File: `conversational_agent.py`**

Add quota checking in `analyze_request()`:

```python
def analyze_request(self, user_message: str, conversation_state: ConversationState, user_id: str):
    """Analyze with quota check"""
    
    # NEW: Check quota before processing
    quota_check = check_user_quota(user_id, operation='conversation')
    if not quota_check['allowed']:
        raise QuotaExceededException(quota_check['message'])
    
    # Count tokens in user message
    input_tokens = count_tokens(user_message)
    
    # Existing analysis logic...
    llm_response = self.llm.invoke(...)
    
    # Count response tokens
    output_tokens = count_tokens(llm_response.content)
    
    # NEW: Record usage
    record_usage(
        user_id=user_id,
        operation='conversation',
        tokens=input_tokens + output_tokens,
        model='gpt-4o',
        conversation_id=conversation_state.conversation_id
    )
```

### 7.2 Supervisor Agent Integration

**File: `supervisor_agent.py`**

Add quota checking in `supervisor_node()`:

```python
def supervisor_node(state: SharedState, user_id: str) -> SharedState:
    """Planning with quota enforcement"""
    
    user_input = state["input"]
    
    # NEW: Estimate planning tokens
    system_prompt = f"..." # Your current prompt
    estimated_tokens = count_tokens(system_prompt + user_input)
    
    # Check per-request limit
    if estimated_tokens > MAX_TOKENS_PER_PLANNING:
        raise RequestTokenLimitExceeded(
            f"Request would use {estimated_tokens} tokens, "
            f"exceeding limit of {MAX_TOKENS_PER_PLANNING}"
        )
    
    # Check user's daily quota
    quota_check = check_user_quota(user_id, operation='planning')
    if not quota_check['allowed']:
        raise QuotaExceededException(quota_check['message'])
    
    # Existing planning logic...
    llm_response = llm.invoke(...)
    
    # Count actual tokens used
    actual_tokens = count_tokens(llm_response.content) + estimated_tokens
    
    # NEW: Record usage
    record_usage(
        user_id=user_id,
        operation='planning',
        tokens=actual_tokens,
        model=LLM_MODEL,
        status='success'
    )
    
    return {"plan": plan, "context": state.get("context", {})}
```

### 7.3 Human-in-the-Loop Approval System

**Existing Feature:** You have `ACTION_RISK_LEVELS` and approval flow

**Integration:** Token usage should continue being tracked even during approval wait:

```python
def orchestrator_node(state: SharedState, user_id: str):
    """Execute plan with quota tracking"""
    
    for step in plan['plan']:
        # Check quota before each step
        quota_check = check_user_quota(user_id, operation='agent_call')
        if not quota_check['allowed']:
            # Return partial results + quota error
            return {
                "status": "quota_exceeded",
                "completed_steps": step_number,
                "error": quota_check['message']
            }
        
        # Your existing approval logic
        if requires_approval(tool_name):
            # Wait for approval (doesn't consume quota)
            await_approval(action_id)
        
        # Execute and track tokens
        result = call_agent_with_retry(...)
        tokens_used = estimate_agent_tokens(step, result)
        
        record_usage(
            user_id=user_id,
            operation='agent_call',
            agent_name=agent_name,
            tool_name=tool_name,
            tokens=tokens_used,
            status='success' if result['success'] else 'error'
        )
```

---

## 8. Key Differences from Original Plan

### What's Better Than Original Plan

1. **Django Integration** - You have a real database, not just in-memory
2. **Model Optimization Already Implemented** - You're using cheaper models smartly
3. **Approval System Exists** - Reduces risk of costly mistakes
4. **Retry Logic Exists** - Prevents wasted retries on quota errors

### What Needs Adjustment

1. **User ID Source** - Need to pass Django user_id through supervisor
2. **API Authentication** - Supervisor endpoints need auth middleware
3. **Database Access** - Supervisor needs to query Django database
4. **Shared State** - Quota data must be accessible to both Django and FastAPI

### Architectural Decision Needed

**Question:** How should Supervisor access Django database?

**Option A: Direct Database Access** (Recommended)
- Supervisor imports Django models directly
- Configure Django in supervisor's Python environment
- Pros: Fast, simple, no network overhead
- Cons: Tight coupling

**Option B: REST API Between Services**
- Django exposes quota API endpoints
- Supervisor calls Django API for quota checks
- Pros: Loose coupling, clear separation
- Cons: Network latency, more complexity

**Option C: Shared Database with SQLAlchemy**
- Both Django and Supervisor use same SQLite database
- Supervisor uses SQLAlchemy ORM
- Pros: Independence
- Cons: Schema sync issues, transaction conflicts

**Recommendation:** Start with **Option A** (direct access) since both services run on same machine. Move to Option B when you deploy to separate servers.

---

## 9. Action Items Before Implementation

### Prerequisites Checklist

- [ ] Decide user authentication flow (how user_id reaches supervisor)
- [ ] Decide database access method (Option A, B, or C above)
- [ ] Review and approve updated quota limits
- [ ] Confirm monthly budget allocation
- [ ] Set up monitoring/alerting email addresses

### Files to Create

1. `backend/api/models.py` - Django quota models
2. `supervisor-agent/quota_manager.py` - Token counting and quota logic
3. `supervisor-agent/quota_middleware.py` - FastAPI middleware for checks
4. `supervisor-agent/quota_exceptions.py` - Custom exception classes

### Files to Modify

1. `supervisor-agent/config.py` - Add quota limit constants
2. `supervisor-agent/supervisor_agent.py` - Add quota checks in nodes
3. `supervisor-agent/conversational_agent.py` - Add quota tracking
4. `supervisor-agent/utils.py` - Add token counting utilities
5. `supervisor-agent/requirements.txt` - Add tiktoken, sqlalchemy

### Environment Variables to Add (.env)

```bash
# Quota System
MAX_TOKENS_PER_PLANNING=8000
MAX_TOKENS_PER_CLASSIFICATION=1000
MAX_TOKENS_PER_CONVERSATION=2000
MAX_TOKENS_PER_AGENT_CALL=4000
MAX_STEPS_PER_WORKFLOW=20
MAX_TOKENS_PER_USER_PER_DAY=500000
MAX_REQUESTS_PER_USER_PER_DAY=100
MAX_TOKENS_PER_HOUR_SYSTEM_WIDE=1000000
MAX_CONCURRENT_WORKFLOWS=10
MAX_CONCURRENT_CONVERSATIONS=20
ENABLE_USAGE_LOGGING=true

# Django Database (if using Option A)
DJANGO_SETTINGS_MODULE=backend.settings
```

---

## 10. Cost Projections (Updated)

### Conservative Estimate (50% quota usage)

```
Assumptions:
- 5 active users
- 250K tokens/user/day (50% of 500K limit)
- Mixed model usage: gpt-4o (conversation), gpt-4 (planning), gpt-3.5-turbo (classification)
- Average cost: $0.015 per 1K tokens

Calculation:
- Daily: 5 users × 250K tokens × $0.015/1K = $18.75/day
- Monthly: $18.75 × 22 working days = $412.50/month
```

### Peak Estimate (100% quota usage)

```
- Daily: 5 users × 500K tokens × $0.015/1K = $37.50/day
- Monthly: $37.50 × 22 working days = $825/month
```

### Recommended Budget

**Set monthly budget: $1,000**
- Covers 100% quota usage comfortably
- Includes 20% buffer for spikes
- Alert at $800 (80% of budget)

---

## 11. Next Steps

### Immediate (This Week)

1. **Review this analysis** with team
2. **Make architectural decisions**:
   - User authentication method
   - Database access pattern
   - Approved quota limits
3. **Set up development environment**:
   - Install dependencies
   - Create Django migrations
4. **Implement Phase 1** (Critical quota system)

### Short-term (Next 2 Weeks)

1. **Test quota system** with simulated load
2. **Add monitoring endpoints**
3. **Create admin tools**
4. **Document for team**

### Long-term (Next Month+)

1. **Monitor actual usage** vs projections
2. **Adjust limits** based on real data
3. **Add advanced features** (Phase 3)
4. **Consider migration** to PostgreSQL if needed

---

## 12. Risk Assessment

### Risks from NOT Implementing Quota System

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Runaway costs** from bugs | High | Critical | Implement quota system ASAP |
| **Abuse** of system | Medium | High | User limits + system-wide caps |
| **No usage visibility** | High | Medium | Usage logging and monitoring |
| **Difficult billing** | Medium | Medium | Per-user usage tracking |

### Risks from Implementing Quota System

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Legitimate users blocked** | Low | Medium | Set generous limits, easy increase process |
| **Implementation bugs** | Medium | Medium | Thorough testing, gradual rollout |
| **Performance overhead** | Low | Low | Optimize token counting, cache quota checks |
| **User confusion** | Medium | Low | Clear error messages, quota dashboard |

---

## 13. Summary & Recommendation

### Current State
✅ **Strong foundation:** Conversational layer, approval system, retry logic  
❌ **No quota system:** Zero token tracking or cost control

### Recommendation
**PROCEED with implementation** with these modifications:

1. **Integrate with Django database** (don't use in-memory storage)
2. **Use direct database access** (Option A) initially
3. **Track multiple model types** (gpt-4, gpt-4o, gpt-3.5-turbo)
4. **Lower cost estimates** (~$400-800/month vs original $550-1,100)
5. **Add conversation-specific limits** (your system is unique)

### Priority Order
1. **Week 1:** Token counting + per-user daily quotas (CRITICAL)
2. **Week 2:** System-wide limits + usage logging (HIGH)
3. **Week 3:** Monitoring dashboard + admin tools (MEDIUM)
4. **Week 4+:** Advanced features (LOW)

### Success Criteria
- ✅ No unexpected cost spikes over $1,000/month
- ✅ All token usage logged and attributable
- ✅ Users understand their quota status
- ✅ Admins can monitor and adjust quotas
- ✅ System-wide capacity protected

---

## Questions to Resolve Before Implementation

1. **User Authentication:** How will supervisor API identify users? JWT tokens? API keys?
2. **Database Access:** Use Django directly, REST API, or shared SQLAlchemy?
3. **Quota Limits:** Approve the updated limits (500K tokens, 100 requests/day)?
4. **Budget:** Confirm $1,000/month budget allocation?
5. **Alerting:** Who receives quota alerts (email addresses)?
6. **Admin Access:** Who has permission to adjust user quotas?

---

**Next Action:** Schedule implementation kickoff meeting to resolve questions and begin Phase 1.
