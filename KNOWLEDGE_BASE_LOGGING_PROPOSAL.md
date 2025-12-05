# Knowledge-Base Logging Implementation Proposal

## Executive Summary

This proposal outlines a strategy to implement comprehensive logging for the **knowledge-base** microservice (SFXBot), which operates independently from the supervisor-agent ecosystem. The solution must:

1. **Work standalone** - Knowledge-base is deployed as a separate microservice
2. **Align with existing schema** - Use the same log structure as `supervisor-agent/log_storage.py`
3. **Support future aggregation** - Allow logs to be combined with agent logs in a unified dashboard
4. **Maintain privacy** - Apply PII redaction for admin viewing

---

## Current Architecture

### Existing Systems

| System | Port | Database | Purpose |
|--------|------|----------|---------|
| **Supervisor Agent** | 8010 | `logs.db` (SQLite) | Agent orchestration, logging |
| **Knowledge-Base (SFXBot)** | 8009 | `chat_sessions.db` (SQLite) | PDF KB, Chat service |
| **Capstone Frontend** | 5173 | N/A | React UI (LogsPage.jsx, SFXBot.jsx) |

### Key Differences

| Aspect | Supervisor Agent | Knowledge-Base |
|--------|-----------------|----------------|
| **Logging** | Full structured logging (`log_storage.py`) | Console print statements only |
| **Token Tracking** | Yes (LLM calls tracked) | Partial (stored in `chat_sessions.db`) |
| **API Endpoints** | `/admin/health`, `/admin/alerts`, etc. | None for monitoring |

---

## Proposed Solution

### Option A: Standalone Logging (Recommended)

Create an **independent logging module** for knowledge-base that:
- Has its own `logs.db` in the `knowledge-base/database/` folder
- Uses the **same schema** as supervisor-agent's `log_storage.py`
- Exposes its own `/admin/*` endpoints for monitoring
- Frontend can aggregate data from both services

```
┌──────────────────────────────────────────────────────────────────┐
│                        CAPSTONE FRONTEND                          │
│                         (LogsPage.jsx)                            │
│    ┌─────────────────────┐    ┌─────────────────────────────┐    │
│    │   Agent Dashboard   │    │   Knowledge-Base Dashboard  │    │
│    │   (localhost:8010)  │    │   (localhost:8009)          │    │
│    └─────────────────────┘    └─────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
           │                              │
           ▼                              ▼
┌─────────────────────┐        ┌─────────────────────────────┐
│  SUPERVISOR AGENT   │        │      KNOWLEDGE-BASE         │
│    (Port 8010)      │        │       (Port 8009)           │
│                     │        │                             │
│  - log_storage.py   │        │  - kb_log_storage.py (NEW)  │
│  - logs.db          │        │  - kb_logs.db (NEW)         │
│  - /admin/* APIs    │        │  - /admin/* APIs (NEW)      │
│  - pii_redactor.py  │        │  - pii_redactor.py (COPY)   │
└─────────────────────┘        └─────────────────────────────┘
```

### Option B: Centralized Logging Server (Alternative)

Create a separate logging microservice that both systems push to:
- More complex deployment
- Single source of truth
- Higher latency for writes
- **NOT RECOMMENDED** for initial implementation

---

## Implementation Plan

### Phase 1: Backend Logging Module (Knowledge-Base)

#### 1.1 Create `knowledge-base/utils/logging_config.py`

A simplified version of supervisor's logging module:

```python
# Key components:
- LogLevel enum (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- StructuredLogger class
- TokenTracker for chat LLM calls
- RequestContext for correlation IDs
```

#### 1.2 Create `knowledge-base/database/kb_log_storage.py`

SQLite storage with **same schema** as supervisor:

```python
# Tables (matching supervisor-agent schema):
- logs            # General logs
- llm_calls       # OpenAI API calls with tokens/cost
- agent_calls     # N/A for KB (can skip or repurpose for "search" operations)
- request_summaries  # Per-request aggregates
```

#### 1.3 Create `knowledge-base/utils/pii_redactor.py`

Copy from supervisor-agent with KB-specific patterns:

```python
# PII patterns to redact:
- User IDs from JWT
- Session IDs
- Document names (optional based on sensitivity)
- User messages (redact for admin view)
```

#### 1.4 Integrate Logging into Existing Services

| File | Changes |
|------|---------|
| `services/chat_service.py` | Replace `print()` with structured logging, track LLM tokens |
| `services/openai_service.py` | Add token tracking wrapper |
| `services/weaviate_search_service.py` | Log search operations |
| `api/chat_routes.py` | Add request context middleware |
| `app.py` | Initialize logging on startup |

### Phase 2: Admin API Endpoints (Knowledge-Base)

Create `knowledge-base/api/admin_routes.py`:

```python
# Endpoints (matching supervisor structure):
GET /admin/health         # System health status
GET /admin/stats          # Usage statistics
GET /admin/alerts         # Recent errors/warnings
GET /admin/activity       # Recent activity (redacted)
GET /admin/metrics        # LLM token usage, search counts
```

### Phase 3: Frontend Integration

#### 3.1 Update `LogsPage.jsx`

Add a **source selector** to choose which system to monitor:

```jsx
// Options:
- "AI Agents" (port 8010 - existing)
- "Knowledge Base" (port 8009 - new)
- "All Systems" (aggregate both - future)
```

#### 3.2 Create Shared API Client

```jsx
// New: src/utils/logsApi.js
const ENDPOINTS = {
  agents: 'http://localhost:8010',
  knowledgeBase: 'http://localhost:8009'
};

export const fetchHealthStatus = async (source) => {
  const url = ENDPOINTS[source];
  return fetch(`${url}/admin/health`);
};
```

---

## Files to Create/Modify

### New Files (Knowledge-Base)

| File | Purpose |
|------|---------|
| `knowledge-base/utils/logging_config.py` | Structured logger, token tracker |
| `knowledge-base/utils/pii_redactor.py` | PII redaction for admin APIs |
| `knowledge-base/database/kb_log_storage.py` | SQLite log storage |
| `knowledge-base/api/admin_routes.py` | Admin monitoring endpoints |

### Modified Files (Knowledge-Base)

| File | Changes |
|------|---------|
| `knowledge-base/app.py` | Register admin routes, init logging |
| `knowledge-base/services/chat_service.py` | Add structured logging |
| `knowledge-base/services/openai_service.py` | Add token tracking |
| `knowledge-base/api/chat_routes.py` | Add request context |

### Modified Files (Frontend)

| File | Changes |
|------|---------|
| `Capstone/src/components/LogsPage.jsx` | Add source selector, multi-API support |
| `Capstone/src/api.js` or new file | Add knowledge-base API helpers |

---

## Database Schema Alignment

The knowledge-base will use the **same schema** as supervisor-agent for consistency:

### `logs` Table
```sql
CREATE TABLE logs (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    logger TEXT NOT NULL,
    message TEXT NOT NULL,
    request_id TEXT,
    conversation_id TEXT,  -- Maps to session_id in KB
    thread_id TEXT,
    component TEXT,        -- 'chat', 'search', 'pdf', 'openai'
    operation TEXT,
    data TEXT,             -- JSON for extra context
    created_at TEXT
);
```

### `llm_calls` Table
```sql
CREATE TABLE llm_calls (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    request_id TEXT,
    conversation_id TEXT,  -- session_id
    model TEXT NOT NULL,   -- gpt-4o, gpt-4o-mini
    tier TEXT,             -- 'chat', 'rerank', 'embed'
    operation TEXT,        -- 'chat_response', 'rerank_chunks'
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    estimated_cost_usd REAL,
    duration_ms REAL,
    success INTEGER,
    prompt_summary TEXT,   -- Redacted summary
    error TEXT,
    created_at TEXT
);
```

---

## API Response Examples

### GET /admin/health (Knowledge-Base)

```json
{
  "status": "All Systems Operational",
  "indicator": "🟢",
  "checks": {
    "database": "Connected",
    "weaviate": "Connected",
    "openai": "Available",
    "recent_errors": 0
  },
  "uptime_seconds": 3600,
  "version": "1.0.0"
}
```

### GET /admin/stats (Knowledge-Base)

```json
{
  "period": "24h",
  "total_chats": 150,
  "total_messages": 890,
  "total_searches": 445,
  "llm_usage": {
    "total_tokens": 125000,
    "total_cost_usd": 0.45,
    "by_model": {
      "gpt-4o": { "tokens": 100000, "cost": 0.35 },
      "gpt-4o-mini": { "tokens": 25000, "cost": 0.10 }
    }
  },
  "avg_response_time_ms": 1250,
  "success_rate": 98.5
}
```

### GET /admin/activity (Knowledge-Base)

```json
{
  "entries": [
    {
      "timestamp": "2024-12-01T10:30:00Z",
      "type": "chat",
      "description": "User chat session",  // Redacted - no message content
      "session_id_hash": "a1b2c3...",       // Hashed for privacy
      "tokens_used": 450,
      "success": true
    }
  ]
}
```

---

## Deployment Considerations

### Environment Variables (knowledge-base/.env)

```env
# Logging Configuration
LOG_LEVEL=INFO
LOG_DB_PATH=database/kb_logs.db
ENABLE_PII_REDACTION=true

# Admin API (optional auth)
ADMIN_API_KEY=your-secret-key  # Optional: protect admin endpoints
```

### Microservice Independence

The knowledge-base logging will:
- ✅ Work completely standalone
- ✅ Not require supervisor-agent to be running
- ✅ Have its own database (`kb_logs.db`)
- ✅ Expose its own admin endpoints
- ✅ Be deployable to separate infrastructure

---

## Timeline Estimate

| Phase | Tasks | Effort |
|-------|-------|--------|
| **Phase 1** | Backend logging module | 2-3 hours |
| **Phase 2** | Admin API endpoints | 1-2 hours |
| **Phase 3** | Frontend integration | 1-2 hours |
| **Testing** | End-to-end validation | 1 hour |
| **Total** | | **5-8 hours** |

---

## Decision Points for Your Review

1. **PII Redaction Level**: Should admin see:
   - [1] No user messages at all (just counts)
   - [ ] Truncated/summarized messages
   - [ ] Full messages (not recommended)

2. **Document Name Visibility**: Should admin see:
   - [ ] Full document names
   - [ ] Redacted/hashed document names

3. **Session Correlation**: Should logs include:
   - [ ] Hashed session IDs (for correlation without PII)
   - [ ] No session info at all

4. **Frontend Approach**:
   - [ ] Tabs for each service (recommended)
   - [ ] Unified view aggregating both
   - [ ] Separate page for knowledge-base

5. **Authentication for Admin APIs**:
   - [ ] No auth (development only)
   - [ ] API key in header
   - [ ] JWT (same as user auth)

---

## Next Steps

Once you approve this proposal:

1. ✅ Create the logging module files in knowledge-base
2. ✅ Integrate logging into chat_service.py and other services
3. ✅ Create admin API routes
4. ✅ Update frontend LogsPage.jsx with source selector
5. ✅ Test end-to-end

---

**Please review and let me know:**
1. Which option do you prefer (A: Standalone or B: Centralized)?
2. Your answers to the Decision Points above
3. Any additional requirements or concerns

Once approved, I'll proceed with the implementation.
