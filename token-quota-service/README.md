# Token Quota Service

Centralized token usage tracking and quota management for the AI Agents microservices architecture.

## Overview

This service provides:
- **Pre-flight quota checks** - Verify quota before LLM operations
- **Usage reporting** - Track token consumption across all services
- **Per-user quotas** - Monthly limits by tier (free, pro, enterprise)
- **Admin endpoints** - Manage quotas and view analytics

## Port: 8011

## Quick Start

```powershell
cd token-quota-service
pip install -r requirements.txt
python app.py
```

## API Endpoints

### Quota Check (Pre-flight)
```http
POST /quota/check
Content-Type: application/json

{
    "user_id": "user_123",
    "estimated_tokens": 1000,
    "service": "knowledge-base",
    "operation": "chat"
}

Response:
{
    "allowed": true,
    "remaining_tokens": 99000,
    "monthly_limit": 100000,
    "current_usage": 1000,
    "percentage_used": 1.0,
    "warning": false,
    "tier": "free",
    "resets_at": "2025-01-01T00:00:00+00:00"
}
```

### Usage Report (Post-operation)
```http
POST /quota/report
Content-Type: application/json

{
    "user_id": "user_123",
    "service": "knowledge-base",
    "operation": "chat",
    "model": "gpt-4o",
    "input_tokens": 500,
    "output_tokens": 300,
    "cost_usd": 0.0043,
    "request_id": "req_abc123",
    "session_id": "sess_xyz"
}

Response:
{
    "success": true,
    "new_usage": 1800,
    "remaining": 98200
}
```

### Get Balance
```http
GET /quota/balance/{user_id}

Response:
{
    "allowed": true,
    "remaining_tokens": 98200,
    "monthly_limit": 100000,
    "current_usage": 1800,
    "percentage_used": 1.8,
    "tier": "free"
}
```

### Admin Endpoints
```http
GET  /quota/admin/users              # List all users
GET  /quota/admin/user/{user_id}     # Get user details
PUT  /quota/admin/user/{user_id}     # Update user quota/tier
POST /quota/admin/user/{user_id}/reset  # Reset user's usage
GET  /quota/admin/summary            # Aggregate usage stats
GET  /quota/admin/top-users          # Top users by usage
```

## Quota Tiers

| Tier       | Monthly Limit | Price |
|------------|--------------|-------|
| Free       | 100,000 tokens | $0 |
| Pro        | 1,000,000 tokens | TBD |
| Enterprise | 10,000,000 tokens | TBD |
| Unlimited  | ∞ | Custom |

## Integration with Other Services

### 1. Copy quota_client.py to your service

```powershell
copy token-quota-service\quota_client.py knowledge-base\utils\
copy token-quota-service\quota_client.py supervisor-agent\
```

### 2. Add environment variable

```env
QUOTA_SERVICE_URL=http://localhost:8011
```

### 3. Use in your code

```python
from quota_client import QuotaClient, QuotaExceededException

quota = QuotaClient()

# Before LLM call
try:
    await quota.check(user_id, estimated_tokens=1000)
except QuotaExceededException as e:
    raise HTTPException(status_code=429, detail=str(e))

# Make LLM call...
response = await llm.complete(...)

# After LLM call
await quota.report(
    user_id=user_id,
    service="knowledge-base",
    model=response.model,
    input_tokens=response.usage.prompt_tokens,
    output_tokens=response.usage.completion_tokens,
    operation="chat"
)
```

## Database Schema

Located in `quota.db` (SQLite):

```sql
-- User quotas and current usage
CREATE TABLE user_quotas (
    user_id TEXT PRIMARY KEY,
    org_id TEXT,
    tier TEXT DEFAULT 'free',
    monthly_limit INTEGER DEFAULT 100000,
    current_usage INTEGER DEFAULT 0,
    current_cost_usd REAL DEFAULT 0.0,
    reset_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Detailed usage log
CREATE TABLE usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    service TEXT NOT NULL,
    operation TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    cost_usd REAL DEFAULT 0.0,
    request_id TEXT,
    session_id TEXT,
    metadata TEXT,
    timestamp TEXT NOT NULL
);
```

## Service Integration Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                          FRONTEND                                     │
│   • Displays quota in header                                         │
│   • Shows warning when approaching limit                             │
│   • Blocks requests when quota exceeded                              │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ X-User-ID header
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      SUPERVISOR (8000)                                │
│                                                                       │
│   1. Extract X-User-ID from request                                  │
│   2. CHECK quota before planning LLM call                            │
│   3. Forward X-User-ID to agent calls                                │
│   4. REPORT usage after LLM calls                                    │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                         ▼
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│   KNOWLEDGE     │       │     GDOCS       │       │    SHEETS       │
│   BASE (8009)   │       │    (8003)       │       │    (8004)       │
│                 │       │                 │       │                 │
│ 1. CHECK quota  │       │ 1. CHECK quota  │       │ 1. CHECK quota  │
│ 2. LLM call     │       │ 2. LLM call     │       │ 2. LLM call     │
│ 3. REPORT usage │       │ 3. REPORT usage │       │ 3. REPORT usage │
└────────┬────────┘       └────────┬────────┘       └────────┬────────┘
         │                         │                         │
         └─────────────────────────┼─────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │   TOKEN QUOTA SERVICE        │
                    │         (8010)               │
                    │                              │
                    │   POST /quota/check          │
                    │   POST /quota/report         │
                    │   GET  /quota/balance        │
                    │                              │
                    │   Database: quota.db         │
                    └──────────────────────────────┘
```

## Files

```
token-quota-service/
├── app.py              # FastAPI application
├── models.py           # Pydantic models
├── database.py         # SQLite database operations
├── quota_client.py     # Client library for other services
├── requirements.txt    # Python dependencies
└── README.md           # This file
```
