# SQLite Log Storage Implementation Summary

## Overview
Implemented SQLite database storage for the logging system with REST API endpoints for querying, searching, and managing logs.

## Files Modified/Created

### 1. `log_storage.py` (NEW - 930+ lines)
SQLite-based log storage with:
- **Tables:**
  - `logs` - Main log entries with FTS5 full-text search
  - `llm_calls` - LLM token usage tracking
  - `agent_calls` - Agent/tool execution tracking
  - `request_summaries` - Per-request aggregates

- **Key Methods:**
  - `insert_log(log_entry)` - Insert log (accepts dict or individual params)
  - `get_logs(...)` - Query logs with filters, returns `(logs, total)` tuple
  - `search_logs(query)` - Full-text search
  - `get_token_summary()` - Token usage statistics
  - `get_request_analytics()` - Per-request analytics
  - `clear_logs(before_time)` - Delete logs
  - `cleanup_old_logs(days)` - Automatic log rotation

### 2. `logging_config.py` (Modified)
- Added lazy-loaded SQLite storage integration
- `_log()` method now writes to both file AND SQLite
- Added `get_log_storage()` function for singleton access

### 3. `log_schema.py` (Modified)
- **Removed duplicate `LogLevel` enum** - now imports from `logging_config.py`
- Single source of truth for LogLevel

### 4. `supervisor_agent.py` (Modified)
Added 5 new API endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/logs` | GET | Query logs with filtering & pagination |
| `/logs/search` | GET | Full-text search across log messages |
| `/logs/stats` | GET | Token usage & cost statistics |
| `/logs/requests/{request_id}` | GET | All logs for a specific request |
| `/logs` | DELETE | Clear logs (with confirmation) |

## API Endpoints Details

### GET /logs
Query logs with filters:
```
?level=ERROR           # Filter by level
?component=llm         # Filter by component
?request_id=req_xxx    # Filter by request ID
?conversation_id=xxx   # Filter by conversation
?thread_id=xxx         # Filter by thread
?start_time=ISO8601    # Filter by time range
?end_time=ISO8601
?limit=100             # Pagination
?offset=0
```

### GET /logs/search
Full-text search:
```
?q=error               # Search query (required)
?level=ERROR           # Optional level filter
?limit=100
```

### GET /logs/stats
Returns:
```json
{
  "token_summary": {
    "totals": {
      "total_calls": 150,
      "total_tokens": 500000,
      "total_cost_usd": 12.50
    },
    "by_model": [...],
    "by_tier": [...]
  },
  "request_analytics": [...]
}
```

### GET /logs/requests/{request_id}
Returns all logs for a request with summary:
```json
{
  "request_id": "req_xxx",
  "logs": [...],
  "summary": {
    "total_tokens": 1500,
    "total_cost_usd": 0.05,
    "llm_calls": 3,
    "agent_calls": 2
  }
}
```

### DELETE /logs
Clear logs (safety measure requires confirm=true):
```
?confirm=true          # Required to actually delete
?before_time=ISO8601   # Optional: only delete logs before this time
```

## Database Schema

### logs table
```sql
CREATE TABLE logs (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    logger TEXT NOT NULL,
    message TEXT NOT NULL,
    request_id TEXT,
    conversation_id TEXT,
    thread_id TEXT,
    component TEXT,
    operation TEXT,
    data TEXT  -- JSON
);
```

### llm_calls table (for token tracking)
```sql
CREATE TABLE llm_calls (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    request_id TEXT,
    model TEXT NOT NULL,
    tier TEXT,
    operation TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    estimated_cost_usd REAL,
    duration_ms REAL,
    success INTEGER,
    ...
);
```

## Testing
- All existing tests pass ✅
- New integration test: `test_log_integration.py`
- Logs are stored in both `agent_outputs/system_logs.jsonl` and `logs.db`

## Duplicate Removal
- `LogLevel` enum was defined in both `logging_config.py` and `log_schema.py`
- Now only defined in `logging_config.py`
- `log_schema.py` imports it: `from logging_config import LogLevel`

## Usage Example

```python
# Logs are automatically saved to SQLite when using the logger
from logging_config import create_logger, request_context

logger = create_logger("my_component")

with request_context(conversation_id="conv_123") as req_id:
    logger.info("Processing request")
    logger.llm_call(
        model="gpt-4o",
        operation="analyze",
        input_tokens=100,
        output_tokens=50,
        duration_ms=500.0
    )
    logger.request_summary()

# Query via API
# GET http://localhost:8000/logs?request_id=req_xxx
# GET http://localhost:8000/logs/search?q=Processing
# GET http://localhost:8000/logs/stats
```
