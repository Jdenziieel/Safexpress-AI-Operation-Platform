# Knowledge-Base Logging Implementation Proposal (REVISED)

## Executive Summary

After deep analysis of the knowledge-base codebase, I've identified that this system has **fundamentally different LLM usage patterns** than the supervisor-agent. This proposal outlines a **tailored logging system** designed specifically for the knowledge-base's unique workflows.

---

## Key Findings from Code Analysis

### 🔍 Two Distinct Workflows with Different LLM Chains

#### **Workflow 1: Document Upload (Admin Only)**
File uploads are **admin-only operations** that trigger a complex LLM chain:

```
PDF Upload → pdfplumber extraction → LLM Chain:
    │
    ├─► LLM Call 1: process_text_only() 
    │   └─ gpt-4o with JSON response format
    │   └─ Structural analysis, chunking, metadata extraction
    │   └─ File: services/chunking_service.py (lines 15-85)
    │
    ├─► LLM Call 2-N: process_images_only() (per image)
    │   └─ gpt-4o with vision capability
    │   └─ Image analysis, description generation
    │   └─ File: services/chunking_service.py (lines 88-180)
    │
    └─► Weaviate embedding (text-embedding-3-small)
        └─ Vector storage via Weaviate auto-vectorization
```

**Files involved:**
- `services/pdf_service.py` - Orchestrates the pipeline
- `services/chunking_service.py` - `process_text_only()`, `process_images_only()`
- `api/pdf_routes.py` - `/pdf/parse-pdf` endpoint
- `api/kb_routes.py` - `/kb/upload-to-kb` endpoint

#### **Workflow 2: Chat/SFXBot (User-Facing)**
User chat sessions trigger a different LLM chain:

```
User Message → Chat Pipeline:
    │
    ├─► LLM Call 1: _resolve_references() (OPTIONAL)
    │   └─ gpt-4o-mini (only for follow-up questions)
    │   └─ Resolves pronouns like "it", "that", "this"
    │   └─ File: services/query_processor.py (lines 78-110)
    │
    ├─► Weaviate hybrid_search()
    │   └─ Vector + BM25 search (uses embeddings, no new LLM call)
    │   └─ File: services/weaviate_search_service.py
    │
    ├─► Local reranking (NO LLM - algorithmic scoring)
    │   └─ query_processor.rerank_results()
    │   └─ Uses section matching, tags, content type, length
    │   └─ File: services/query_processor.py (lines 115-270)
    │
    └─► LLM Call 2: _generate_response()
        └─ gpt-4o (main response generation)
        └─ Uses top 15 chunks as context
        └─ File: services/chat_service.py (lines 200-290)
```

**Files involved:**
- `services/chat_service.py` - Main chat pipeline
- `services/query_processor.py` - Query enhancement, reranking
- `services/weaviate_search_service.py` - Hybrid search
- `api/chat_routes.py` - `/chat/*` endpoints

---

## Why Supervisor Schema Doesn't Fit

| Aspect | Supervisor Agent | Knowledge-Base |
|--------|-----------------|----------------|
| **LLM Pattern** | Agent selection → Tool execution | Multi-stage processing pipelines |
| **Who uses it** | End users via chat | Admins (upload) + Users (chat) |
| **Token tracking** | Per-request cumulative | Per-pipeline-stage tracking needed |
| **Operations** | Agent calls, tool executions | Document processing, search, chat |
| **Error patterns** | Tool failures, API errors | PDF parsing, chunking, Weaviate errors |
| **Cost attribution** | Per conversation | Per document + per chat session |

---

## Proposed Custom Schema for Knowledge-Base

### Database: `knowledge-base/database/kb_logs.db`

### Table 1: `document_processing_logs`
**Purpose:** Track admin document upload operations (full visibility - admins are accountable)

```sql
CREATE TABLE document_processing_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    
    -- Document identification
    document_id TEXT,
    filename TEXT NOT NULL,
    file_size_bytes INTEGER,
    content_hash TEXT,
    
    -- Processing pipeline tracking
    pipeline_id TEXT NOT NULL,          -- Unique ID for this processing run
    stage TEXT NOT NULL,                 -- 'extraction', 'text_chunking', 'image_analysis', 'embedding', 'weaviate_upload'
    stage_order INTEGER,                 -- 1, 2, 3...
    
    -- LLM usage (for chunking/image stages)
    model TEXT,                          -- gpt-4o, gpt-4o-mini, text-embedding-3-small
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    estimated_cost_usd REAL DEFAULT 0.0,
    duration_ms REAL DEFAULT 0.0,
    
    -- Results
    success INTEGER DEFAULT 1,
    chunks_created INTEGER DEFAULT 0,    -- For chunking stages
    images_processed INTEGER DEFAULT 0,  -- For image stages
    error TEXT,
    
    -- Admin who uploaded (VISIBLE - accountability)
    uploaded_by TEXT,                    -- From JWT token
    
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### Table 2: `chat_session_logs`
**Purpose:** Track user chat interactions (privacy-focused - no PII)

```sql
CREATE TABLE chat_session_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    
    -- Session tracking (hashed for privacy)
    session_id_hash TEXT,               -- SHA256 of session_id (no real session ID)
    request_id TEXT NOT NULL,           -- Unique per message
    
    -- Pipeline stages
    stage TEXT NOT NULL,                -- 'query_resolve', 'weaviate_search', 'rerank', 'response_generate'
    stage_order INTEGER,
    
    -- LLM usage
    model TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    estimated_cost_usd REAL DEFAULT 0.0,
    duration_ms REAL DEFAULT 0.0,
    
    -- Search metrics (for search stages)
    chunks_retrieved INTEGER DEFAULT 0,
    chunks_used INTEGER DEFAULT 0,
    
    -- Results
    success INTEGER DEFAULT 1,
    error TEXT,
    
    -- NO user_id, NO message content, NO query text
    
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### Table 3: `system_logs`
**Purpose:** General system events, errors, health

```sql
CREATE TABLE system_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,                -- DEBUG, INFO, WARNING, ERROR, CRITICAL
    component TEXT NOT NULL,            -- 'chat', 'pdf', 'weaviate', 'openai', 'api'
    message TEXT NOT NULL,
    
    -- Optional context
    request_id TEXT,
    pipeline_id TEXT,
    error_type TEXT,
    stack_trace TEXT,
    
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### Table 4: `usage_aggregates`
**Purpose:** Pre-computed stats for fast dashboard loading

```sql
CREATE TABLE usage_aggregates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,                 -- YYYY-MM-DD
    hour INTEGER,                       -- 0-23 (NULL for daily aggregates)
    
    -- Document processing stats (admin operations)
    documents_processed INTEGER DEFAULT 0,
    total_chunks_created INTEGER DEFAULT 0,
    document_tokens INTEGER DEFAULT 0,
    document_cost_usd REAL DEFAULT 0.0,
    
    -- Chat stats (user operations - counts only, no PII)
    chat_sessions INTEGER DEFAULT 0,
    chat_messages INTEGER DEFAULT 0,
    chat_tokens INTEGER DEFAULT 0,
    chat_cost_usd REAL DEFAULT 0.0,
    
    -- Search stats
    total_searches INTEGER DEFAULT 0,
    avg_chunks_retrieved REAL DEFAULT 0.0,
    
    -- Errors
    error_count INTEGER DEFAULT 0,
    
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, hour)
);
```

---

## Admin Monitoring Endpoints

### `/admin/health` - System Health

```json
{
  "status": "All Systems Operational",
  "indicator": "🟢",
  "services": {
    "database": { "status": "connected", "latency_ms": 2 },
    "weaviate": { "status": "connected", "collections": 2 },
    "openai": { "status": "available", "last_call": "2024-12-01T10:30:00Z" }
  },
  "recent_errors": 0,
  "uptime_seconds": 86400
}
```

### `/admin/documents` - Document Processing Stats (Admin Uploads)

```json
{
  "period": "24h",
  "documents_processed": 5,
  "total_chunks": 342,
  "processing_stats": {
    "avg_processing_time_ms": 45000,
    "avg_chunks_per_doc": 68,
    "success_rate": 100
  },
  "llm_usage": {
    "text_chunking": { "calls": 5, "tokens": 45000, "cost": 0.15 },
    "image_analysis": { "calls": 23, "tokens": 12000, "cost": 0.08 },
    "embeddings": { "calls": 342, "tokens": 85000, "cost": 0.01 }
  },
  "recent_uploads": [
    {
      "filename": "Policy_Manual_2024.pdf",
      "uploaded_by": "admin@company.com",  // Visible - admin accountability
      "timestamp": "2024-12-01T09:15:00Z",
      "chunks": 89,
      "processing_time_ms": 52000,
      "tokens_used": 12500,
      "cost_usd": 0.045,
      "status": "success"
    }
  ]
}
```

### `/admin/chat-stats` - Chat Usage (Aggregated, No PII)

```json
{
  "period": "24h",
  "total_sessions": 45,
  "total_messages": 234,
  "unique_users": 12,                    // Count only, no IDs
  "llm_usage": {
    "query_resolution": { "calls": 89, "tokens": 4500, "cost": 0.002 },
    "response_generation": { "calls": 234, "tokens": 156000, "cost": 0.52 }
  },
  "search_stats": {
    "total_searches": 234,
    "avg_chunks_retrieved": 50,
    "avg_chunks_used": 15
  },
  "performance": {
    "avg_response_time_ms": 2300,
    "p95_response_time_ms": 4500
  }
  // NO user IDs, NO message content, NO queries
}
```

### `/admin/errors` - Recent Errors

```json
{
  "period": "1h",
  "total_errors": 2,
  "by_component": {
    "weaviate": 1,
    "openai": 1
  },
  "recent": [
    {
      "timestamp": "2024-12-01T10:25:00Z",
      "component": "weaviate",
      "level": "ERROR",
      "message": "Connection timeout after 30s",
      "pipeline_id": "doc-abc123",        // For document errors
      "count": 1
    }
  ]
}
```

### `/admin/costs` - Cost Breakdown

```json
{
  "period": "30d",
  "total_cost_usd": 45.67,
  "by_operation": {
    "document_processing": 12.34,
    "chat_responses": 28.90,
    "query_resolution": 0.43,
    "embeddings": 4.00
  },
  "by_model": {
    "gpt-4o": 38.50,
    "gpt-4o-mini": 0.67,
    "text-embedding-3-small": 6.50
  },
  "daily_trend": [
    { "date": "2024-12-01", "cost": 1.23 },
    { "date": "2024-11-30", "cost": 2.45 }
  ]
}
```

---

## Implementation Files

### New Files to Create

| File | Purpose |
|------|---------|
| `knowledge-base/database/kb_logs_db.py` | Log storage with custom schema (4 tables) |
| `knowledge-base/utils/kb_logger.py` | Logging wrapper with pipeline tracking |
| `knowledge-base/utils/token_tracker.py` | OpenAI token/cost tracking decorator |
| `knowledge-base/api/admin_routes.py` | Admin monitoring endpoints |

### Files to Modify

| File | Changes |
|------|---------|
| `services/chunking_service.py` | Add logging to `process_text_only()`, `process_images_only()` |
| `services/chat_service.py` | Add logging to `process_message()`, `_generate_response()` |
| `services/query_processor.py` | Log `_resolve_references()` when called |
| `services/openai_service.py` | Wrap with token tracking |
| `app.py` | Register admin routes, initialize logging |

---

## Privacy Model

### What Admins CAN See:

| Data | Visibility | Reason |
|------|------------|--------|
| Document filenames | ✅ Full | Admin uploaded them |
| Who uploaded (admin name) | ✅ Full | Accountability |
| Document processing metrics | ✅ Full | Admin operations |
| Chat session counts | ✅ Aggregate only | Usage monitoring |
| Chat message counts | ✅ Aggregate only | Usage monitoring |
| Token usage & costs | ✅ Full | Budget management |
| Error logs | ✅ Full | Debugging |

### What Admins CANNOT See:

| Data | Visibility | Reason |
|------|------------|--------|
| User IDs | ❌ Hidden | Privacy |
| User email addresses | ❌ Hidden | Privacy |
| Session IDs | ❌ Hashed only | Privacy |
| User messages/queries | ❌ Hidden | Privacy |
| Chat response content | ❌ Hidden | Privacy |
| Which documents users accessed | ❌ Hidden | Privacy |

---

## Frontend Integration

### Recommended: Tabs in LogsPage.jsx

```jsx
const LogsPage = () => {
  const [activeSource, setActiveSource] = useState('agents');
  
  return (
    <div className="logs-page">
      {/* Source Selector */}
      <div className="source-tabs">
        <button 
          className={activeSource === 'agents' ? 'active' : ''}
          onClick={() => setActiveSource('agents')}
        >
          🤖 AI Agents
        </button>
        <button 
          className={activeSource === 'kb' ? 'active' : ''}
          onClick={() => setActiveSource('kb')}
        >
          📚 Knowledge Base
        </button>
      </div>
      
      {/* Content based on source */}
      {activeSource === 'agents' && <AgentsDashboard />}
      {activeSource === 'kb' && <KnowledgeBaseDashboard />}
    </div>
  );
};

const KnowledgeBaseDashboard = () => {
  return (
    <>
      <SystemHealthBanner source="kb" />
      
      {/* Document Processing Section */}
      <section className="documents-section">
        <h2>📄 Document Processing</h2>
        {/* Recent uploads table with admin names */}
        {/* Processing stats */}
        {/* LLM usage for chunking/images */}
      </section>
      
      {/* Chat Statistics Section */}
      <section className="chat-section">
        <h2>💬 Chat Statistics</h2>
        {/* Aggregate stats only - no PII */}
        {/* Session/message counts */}
        {/* Response time metrics */}
      </section>
      
      {/* Cost Breakdown Section */}
      <section className="costs-section">
        <h2>💰 Cost Analysis</h2>
        {/* By operation type */}
        {/* By model */}
        {/* Trend chart */}
      </section>
    </>
  );
};
```

---

## Summary: Key Differences from Original Proposal

| Aspect | Original Proposal | Revised Proposal |
|--------|------------------|------------------|
| **Schema** | Copy supervisor schema | Custom schema for KB workflows |
| **Tables** | 4 generic tables | 4 specialized tables |
| **Document tracking** | Not differentiated | Dedicated `document_processing_logs` |
| **Chat tracking** | Same as supervisor | Privacy-focused `chat_session_logs` |
| **Pipeline tracking** | None | `pipeline_id` and `stage` fields |
| **Admin visibility** | PII redaction | Admin uploads visible, user data hidden |
| **Aggregations** | Compute on-demand | Pre-computed `usage_aggregates` table |
| **Cost tracking** | Basic | Detailed by operation and model |

---

## Implementation Plan

### Phase 1: Database & Logging Core (1.5 hours)
- Create `kb_logs_db.py` with 4 tables
- Create `kb_logger.py` with pipeline tracking
- Create `token_tracker.py` with OpenAI wrapper

### Phase 2: Integrate into Services (2 hours)
- Add logging to `chunking_service.py` (document pipeline)
- Add logging to `chat_service.py` (chat pipeline)
- Add logging to `query_processor.py` (query resolution)
- Wrap OpenAI calls with token tracking

### Phase 3: Admin API Endpoints (1.5 hours)
- Create `admin_routes.py`
- Implement `/admin/health`, `/admin/documents`, `/admin/chat-stats`, `/admin/costs`, `/admin/errors`

### Phase 4: Frontend Integration (1 hour)
- Add tabs to LogsPage.jsx
- Create KnowledgeBaseDashboard component
- Connect to new API endpoints

**Total Estimated Time: 6 hours**

---

## Decision Points for Your Approval

1. **✅ Custom Schema Approach** - Not forcing supervisor schema onto KB
   - Confirmed: Makes sense for different workflows

2. **Document Upload Visibility:**
   - [x] Show admin name who uploaded (recommended - accountability)
   - [ ] Hide admin name

3. **Chat User Tracking:**
   - [x] Counts only - no user IDs visible (recommended)
   - [ ] Hashed user IDs (allows per-user stats)

4. **Cost Tracking:**
   - [x] By operation type (document, chat, query resolution)
   - [x] By model (gpt-4o, gpt-4o-mini, embeddings)

5. **Frontend Approach:**
   - [x] Tabs in existing LogsPage.jsx (recommended)
   - [ ] Separate dedicated page

---

**Please confirm the above decisions and I'll proceed with implementation!**
