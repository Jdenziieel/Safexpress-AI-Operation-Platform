# Token Quota System Design for Microservices Architecture

## ✅ Implementation Status

The Token Quota Service has been implemented! Here's what was created:

### New Service: `token-quota-service/` (Port 8010)
- `app.py` - FastAPI application with all endpoints
- `models.py` - Pydantic models for requests/responses
- `database.py` - SQLite database with quota tables
- `quota_client.py` - Client library for other services
- `requirements.txt` - Dependencies
- `README.md` - Documentation

### Knowledge-Base Integration
- `utils/quota_client.py` - Quota client copied
- `services/chat_service.py` - Updated with quota check before LLM calls
- `api/chat_routes.py` - Added `/chat/quota` endpoint for frontend

### Supervisor-Agent Integration
- `quota_client.py` - Quota client copied (ready for integration)

## Current Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           FRONTEND (Capstone)                                │
│                        React + Vite on port 5173                            │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     SUPERVISOR-AGENT (Orchestrator)                          │
│                         FastAPI on port 8000                                 │
│  • Routes requests to appropriate agents                                     │
│  • Has its own TokenTracker in logging_config.py                            │
│  • Tracks LLM calls for planning, summarization                             │
└────────┬───────────┬────────────┬────────────┬───────────┬──────────────────┘
         │           │            │            │           │
         ▼           ▼            ▼            ▼           ▼
┌─────────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────────┐
│ Gmail Agent │ │ GDrive  │ │ GDocs   │ │ Sheets  │ │  Knowledge-Base │
│  Port 8001  │ │  8002   │ │  8003   │ │  8004   │ │    Port 8009    │
│ (no LLM)    │ │(no LLM) │ │(LLM)    │ │(LLM)    │ │ (LLM for chat,  │
│             │ │         │ │         │ │         │ │  embeddings)    │
└─────────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────────────┘
```

## Current Token Tracking (Per-Service)

### 1. Supervisor-Agent (`logging_config.py`)
- **TokenTracker class**: Tracks LLM calls with `llm_call()` method
- **RequestTokenSummary**: Accumulates per-request token usage
- **Storage**: `logs.db` SQLite

### 2. Knowledge-Base (`utils/token_tracker.py`)
- **TokenTracker class**: Independent implementation
- **Storage**: `kb_logs.db` SQLite via `kb_logs_db.py`

### 3. GDocs/Sheets Agents
- May have their own token tracking (need to verify)

## Problem: No Unified Quota System

Currently:
- ❌ No per-user quotas
- ❌ No organization/team quotas  
- ❌ No billing integration
- ❌ Token tracking is per-service, not aggregated
- ❌ No rate limiting based on token consumption

---

## Proposed Solutions

### Option A: Centralized Quota Service (Recommended)

Create a dedicated **Token Quota Service** that all agents call before/after LLM operations.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TOKEN QUOTA SERVICE                                  │
│                         (New Microservice)                                   │
│                                                                              │
│  • Central SQLite/PostgreSQL database                                        │
│  • User/Org quota tables                                                     │
│  • Real-time balance tracking                                                │
│  • Pre-check: "Can user X spend Y tokens?"                                  │
│  • Post-report: "User X spent Y tokens"                                     │
│  • Admin API for quota management                                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                 ▲
                                 │ HTTP calls
         ┌───────────┬───────────┼───────────┬───────────┐
         │           │           │           │           │
         ▼           ▼           ▼           ▼           ▼
   Supervisor    GDocs       Sheets      KB-Agent    (Future)
```

#### Database Schema

```sql
-- Users and their quotas
CREATE TABLE user_quotas (
    user_id TEXT PRIMARY KEY,
    org_id TEXT,
    monthly_token_limit INTEGER DEFAULT 1000000,  -- 1M tokens
    current_month_usage INTEGER DEFAULT 0,
    current_month_cost_usd REAL DEFAULT 0.0,
    quota_reset_date TEXT,  -- First of next month
    tier TEXT DEFAULT 'free',  -- free, pro, enterprise
    created_at TEXT,
    updated_at TEXT
);

-- Organization quotas (optional, for team limits)
CREATE TABLE org_quotas (
    org_id TEXT PRIMARY KEY,
    name TEXT,
    monthly_token_limit INTEGER DEFAULT 10000000,  -- 10M tokens
    current_month_usage INTEGER DEFAULT 0,
    current_month_cost_usd REAL DEFAULT 0.0,
    quota_reset_date TEXT,
    created_at TEXT
);

-- Detailed usage log (aggregated from all services)
CREATE TABLE token_usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    service TEXT NOT NULL,  -- 'supervisor', 'knowledge-base', 'gdocs', etc.
    operation TEXT,  -- 'chat', 'embedding', 'planning', etc.
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    cost_usd REAL,
    timestamp TEXT,
    request_id TEXT,
    session_id TEXT
);

-- Indexes for fast queries
CREATE INDEX idx_usage_user ON token_usage_log(user_id);
CREATE INDEX idx_usage_timestamp ON token_usage_log(timestamp);
CREATE INDEX idx_usage_service ON token_usage_log(service);
```

#### API Endpoints

```
POST /quota/check
  Body: { user_id, estimated_tokens }
  Response: { allowed: true/false, remaining: 500000, limit: 1000000 }

POST /quota/report
  Body: { user_id, service, model, tokens, cost, operation }
  Response: { success: true, new_balance: 499500 }

GET /quota/usage/{user_id}
  Response: { monthly_usage, monthly_limit, daily_breakdown, by_service }

GET /quota/admin/summary
  Response: { total_users, total_usage, top_users, by_service }

PUT /quota/admin/user/{user_id}
  Body: { monthly_limit, tier }
  Response: { updated: true }
```

---

### Option B: Federated Tracking with Aggregation

Keep tracking in each service, add periodic aggregation.

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ Supervisor  │  │ KB-Agent    │  │ GDocs       │
│   logs.db   │  │ kb_logs.db  │  │  logs.db    │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │
       └────────────────┼────────────────┘
                        ▼
              ┌─────────────────┐
              │   AGGREGATOR    │
              │   (Cron job)    │
              │                 │
              │ Polls each DB   │
              │ Calculates      │
              │   user totals   │
              │ Updates central │
              │   quota DB      │
              └─────────────────┘
```

**Pros:**
- Less latency (no pre-check call)
- Services work offline

**Cons:**
- Quota enforcement is delayed
- Users could exceed limits before aggregation

---

### Option C: Header-Based Tracking (Simplest)

Pass `X-User-ID` and `X-Session-ID` headers through all services.
Each service reports to supervisor, supervisor maintains single quota DB.

```python
# In each agent's API
@app.middleware("http")
async def track_usage(request: Request, call_next):
    user_id = request.headers.get("X-User-ID", "anonymous")
    
    response = await call_next(request)
    
    # If LLM was used, report to supervisor
    if hasattr(request.state, 'token_usage'):
        await report_to_supervisor(user_id, request.state.token_usage)
    
    return response
```

---

## Recommended Implementation: Option A + Header Propagation

### Phase 1: Add User Context Propagation

1. **Frontend** sends `X-User-ID` header with every request
2. **Supervisor** forwards this header to all agent calls
3. **Knowledge-Base** includes `user_id` in all token logs

### Phase 2: Create Token Quota Service

New microservice with:
- SQLite database for quotas
- REST API for check/report
- Admin UI integration

### Phase 3: Integrate Pre-Check

Before expensive LLM calls:
```python
async def check_quota(user_id: str, estimated_tokens: int) -> bool:
    response = await httpx.post(
        "http://localhost:8010/quota/check",
        json={"user_id": user_id, "estimated_tokens": estimated_tokens}
    )
    return response.json()["allowed"]

# In chat_service.py
async def process_query(query: str, user_id: str):
    # Estimate tokens (rough: 4 chars = 1 token)
    estimated = len(query) // 4 + 2000  # Add buffer for response
    
    if not await check_quota(user_id, estimated):
        raise QuotaExceededError("Monthly token limit exceeded")
    
    # Process query...
    result = await llm.complete(query)
    
    # Report actual usage
    await report_usage(user_id, result.usage)
```

---

## Quick Implementation (MVP)

For a fast MVP without a separate service, extend the existing KB logging:

### 1. Add `user_id` to existing tables

```sql
-- In kb_logs.db
ALTER TABLE document_processing_logs ADD COLUMN user_id TEXT DEFAULT 'system';
ALTER TABLE chat_logs ADD COLUMN user_id TEXT;

-- New table for quotas
CREATE TABLE IF NOT EXISTS user_quotas (
    user_id TEXT PRIMARY KEY,
    monthly_limit INTEGER DEFAULT 500000,
    current_usage INTEGER DEFAULT 0,
    reset_date TEXT,
    created_at TEXT
);
```

### 2. Update TokenTracker to include user_id

```python
# In knowledge-base/utils/token_tracker.py
class TokenTracker:
    def track(self, response, user_id: str = None, model: str = None):
        usage = extract_token_usage(response)
        usage["user_id"] = user_id
        # ... rest of tracking
```

### 3. Add quota check endpoint to KB

```python
# In api/admin_routes.py
@admin_router.get('/quota/{user_id}')
async def get_user_quota(user_id: str):
    storage = get_kb_log_storage()
    
    # Get current month usage from chat_logs
    usage = storage.get_user_monthly_usage(user_id)
    limit = storage.get_user_limit(user_id)
    
    return {
        "user_id": user_id,
        "monthly_usage": usage,
        "monthly_limit": limit,
        "remaining": max(0, limit - usage),
        "percentage_used": round(usage / limit * 100, 1)
    }
```

---

## Recommendation for Your Setup

Given that:
1. Knowledge-Base is the primary LLM consumer (chat + embeddings)
2. Supervisor also uses LLM for planning
3. You already have logging infrastructure

**Start with the MVP approach:**

1. Add `user_id` tracking to KB token logs
2. Create quota table in `kb_logs.db`
3. Add quota check before chat responses
4. Add admin endpoint to view/set quotas
5. Display quota in the Capstone admin UI

This gives you 80% of the value with 20% of the effort. You can evolve to a separate quota service later if needed.

---

## Files to Modify

| File | Changes |
|------|---------|
| `knowledge-base/database/kb_logs_db.py` | Add `user_quotas` table, quota methods |
| `knowledge-base/api/chat_routes.py` | Pass `user_id` to chat service |
| `knowledge-base/services/chat_service.py` | Check quota before LLM calls |
| `knowledge-base/api/admin_routes.py` | Add quota endpoints |
| `Capstone/src/pages/KBAnalyticsPage.jsx` | Add quota display/management |
| `supervisor-agent/supervisor_agent.py` | Forward `X-User-ID` header |

Would you like me to implement the MVP quota system?
