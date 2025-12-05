# Workflow Data Flow Documentation

## Overview

This document details the complete data flow from workflow completion through user-friendly summary generation and the final response to the frontend. It covers success scenarios, failure scenarios, and all intermediate data transformations.

---

## 📊 High-Level Architecture

```
┌─────────────┐    ┌──────────────────┐    ┌───────────────────┐    ┌──────────────┐
│   Frontend  │───▶│  Supervisor API  │───▶│  Orchestrator     │───▶│ Agent APIs   │
│  (React)    │    │  (FastAPI)       │    │  (LangGraph Node) │    │ (Microservices)│
└─────────────┘    └──────────────────┘    └───────────────────┘    └──────────────┘
       ▲                   │                        │                       │
       │                   │                        │                       │
       │                   ▼                        ▼                       │
       │           ┌──────────────────┐    ┌───────────────────┐            │
       │           │ Conversational   │    │  Variable Context │◀──────────┘
       │           │ Agent (Summary)  │    │  (Step Results)   │
       │           └──────────────────┘    └───────────────────┘
       │                   │
       └───────────────────┘
              Final Response
```

---

## 🔄 Complete Data Flow Sequence

### Phase 1: Workflow Execution (Orchestrator Node)

```
orchestrator_node(state: SharedState) → SharedState
```

**Input State:**
```python
SharedState = {
    "input": str,           # Original user request
    "plan": dict,           # Generated execution plan
    "context": dict,        # Variable context (dates, etc.)
    "memory": dict,         # Conversation memory
    "policy": list,         # Access control policies
    "final_context": dict   # Will be populated with results
}
```

**Plan Structure:**
```python
{
    "plan": [
        {
            "step_number": 1,
            "agent": "gmail_agent",
            "tool": "search_emails",
            "description": "Search for emails from Mike",
            "inputs": {
                "query": "from:mike",
                "max_results": 5
            },
            "output_variables": {
                "found_emails": "emails",      # Map "emails" from result → "found_emails"
                "email_count": "total_count"
            }
        },
        # ... more steps
    ]
}
```

---

### Phase 2: Per-Step Execution & Variable Context Building

For each step in the plan:

```
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP EXECUTION FLOW                                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. VARIABLE SUBSTITUTION                                                │
│     ┌─────────────────┐                                                  │
│     │ inputs: {       │    Jinja2 Template    ┌─────────────────────┐   │
│     │   "to": "{{     │ ─────────────────────▶│ substituted_inputs: │   │
│     │   recipient}}"  │                       │   "to": "mike@x.com"│   │
│     │ }               │                       └─────────────────────┘   │
│     └─────────────────┘                                                  │
│                                                                          │
│  2. AGENT API CALL                                                       │
│     ┌─────────────────────────────────────────────────────────────────┐ │
│     │ POST http://localhost:5001/api/tool                             │ │
│     │ {                                                               │ │
│     │   "tool": "search_emails",                                      │ │
│     │   "inputs": { "query": "from:mike", "max_results": 5 },         │ │
│     │   "credentials_dict": {                                         │ │
│     │     "access_token": "...",                                      │ │
│     │     "refresh_token": "...",                                     │ │
│     │     ...                                                         │ │
│     │   }                                                             │ │
│     │ }                                                               │ │
│     └─────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  3. AGENT RESPONSE                                                       │
│     ┌─────────────────────────────────────────────────────────────────┐ │
│     │ SUCCESS:                          │ FAILURE:                    │ │
│     │ {                                 │ {                           │ │
│     │   "success": true,                │   "success": false,         │ │
│     │   "emails": [...],                │   "error": "Auth failed",   │ │
│     │   "total_count": 5,               │   "no_results": false       │ │
│     │   "result": { ... }               │ }                           │ │
│     │ }                                 │                             │ │
│     └─────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  4. VARIABLE EXTRACTION                                                  │
│     Agent Result → Variable Context                                      │
│     ┌─────────────────────────────────────────────────────────────────┐ │
│     │ output_variables: {                                             │ │
│     │   "found_emails": "emails",        # Simple field mapping       │ │
│     │   "first_email_id": "emails[0].id" # Nested path extraction     │ │
│     │ }                                                               │ │
│     │                                                                 │ │
│     │ Result: variable_context["found_emails"] = result["emails"]     │ │
│     │         variable_context["first_email_id"] = result["emails"][0]["id"]│
│     └─────────────────────────────────────────────────────────────────┘ │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### Phase 3: Step Result Recording

Each step produces a result entry:

```python
# SUCCESS Result
{
    "step": 1,
    "agent": "gmail_agent",
    "tool": "search_emails",
    "description": "Search for emails from Mike",
    "inputs": {"query": "from:mike", "max_results": 5},
    "output": {
        "emails": [
            {
                "message_id": "abc123",
                "subject": "Meeting Tomorrow",
                "from": "mike@company.com",
                "date": "2025-11-29T10:30:00Z",
                "snippet": "Let's discuss the project..."
            }
        ],
        "total_count": 1
    },
    "status": "success"
}

# NO_RESULTS Result (Valid operation, but empty data)
{
    "step": 1,
    "agent": "gmail_agent",
    "tool": "search_emails",
    "description": "Search for emails from unknown@test.com",
    "inputs": {"query": "from:unknown@test.com"},
    "status": "no_results",
    "message": "No emails found matching the criteria",
    "output": {"emails": [], "total_count": 0}
}

# ERROR Result (Operation failed)
{
    "step": 1,
    "agent": "gmail_agent",
    "tool": "search_emails",
    "description": "Search for emails",
    "inputs": {"query": "from:mike"},
    "status": "error",
    "error": "Authentication failed: Invalid refresh token"
}
```

---

### Phase 4: Orchestrator Completion

**Successful Completion:**
```python
{
    "final_context": {
        # All accumulated variables from all steps
        "today_date": "2025-11-30",
        "emails": [...],
        "total_count": 5,
        "found_emails": [...],    # Renamed variable
        "first_email_id": "abc123",
        "draft_id": "draft_xyz",
        # ... more variables
    },
    "context": { ... },  # Same as final_context
    "results": [
        # Array of all step results (see above)
    ]
}
```

**Error Completion (Stopped Early):**
```python
{
    "final_context": {
        # Only variables from completed steps
        "today_date": "2025-11-30",
        "emails": [...]
    },
    "context": { ... },
    "results": [
        {"step": 1, "status": "success", ...},
        {"step": 2, "status": "error", "error": "HTTP timeout", ...}
    ],
    "stopped_at_step": 2,
    "error": "HTTP error calling docs_agent: Connection timeout"
}
```

---

## 📝 Phase 5: User-Friendly Summary Generation

### 5.1 Context Filtering

The `_filter_context_for_user()` method removes technical fields:

```python
# Fields REMOVED from user summary:
EXCLUDED_FIELDS = [
    "today_date", "yesterday_date", "current_year", 
    "current_month", "current_day",
    "message_id", "thread_id", "draft_id", "document_id",
    "access_token", "refresh_token", "credentials"
]

# Filtered context example:
{
    "emails": [
        {
            "subject": "Meeting Tomorrow",
            "from": "mike@company.com",
            "date": "2025-11-29",
            "body": "Let's discuss the project..."
        }
    ],
    "total_count": 1
}
```

### 5.2 Summary Generation Strategy

The system uses a **smart routing approach** to save tokens and provide faster responses:

| Scenario | Uses LLM? | Reason |
|----------|-----------|--------|
| ✅ Success with data | Yes | Rich, contextual summary with actual data |
| ℹ️ No results found | **No** | Template-based - predictable message |
| ❌ Error occurred | **No** | Template-based - error categorization |
| ⏸️ Workflow stopped | **No** | Template-based - show partial progress |

**For SUCCESS - LLM Summary:**
```
System Prompt: "You are a concise AI assistant summarizing task results..."
User Prompt: "Task: {request}\nStatus: success\nContext: {actual_data}..."

Generated: "✅ Successfully found 1 email from Mike.
**Email Found:**
- **Subject:** Meeting Tomorrow
- **From:** mike@company.com..."
```

**For ERRORS - Template-Based (No LLM):**
```python
# Error categorization determines user message:
error_categories = {
    "auth": "Authentication failed. Please reconnect your account.",
    "not_found": "Resource not found. Please verify the ID.",
    "timeout": "Operation took too long. Please try again.",
    "connection": "Service unavailable. Check if services are running.",
    "permission": "Access denied. Verify your permissions.",
    "rate_limit": "Too many requests. Please wait and retry."
}
```

---

## 📤 Phase 6: Response to Frontend

### 6.1 ConversationResponse Model

```python
class ConversationResponse(BaseModel):
    response: str                    # User-friendly summary (LLM or template)
    conversation_id: str             # For continuing conversation
    ready_for_execution: bool        # False after execution
    intent: str                      # "search_email", "send_email", etc.
    extracted_info: Dict[str, Any]   # Structured extracted parameters
    execution_summary: Optional[str] # Raw execution status
```

### 6.2 Successful Response Example

```json
{
    "response": "✅ Successfully found 1 email from Mike.\n\n**Email Found:**\n- **Subject:** Meeting Tomorrow\n- **From:** mike@company.com\n- **Date:** November 29, 2025\n- **Preview:** \"Let's discuss the project timeline...\"",
    "conversation_id": "conv_abc123",
    "ready_for_execution": false,
    "intent": "search_email",
    "extracted_info": {
        "query": "from:mike",
        "max_results": 5
    },
    "execution_summary": "Workflow executed successfully"
}
```

### 6.3 Error Response Example (No LLM Used)

```json
{
    "response": "❌ **Unable to complete your request**\n\n**Issue:** Could not connect to the required service.\n**Suggestion:** Please check if all services are running and try again.\n\n---\n**What was completed before the error:**\n  ✅ Search for emails from Mike\n\n**Failed at step 2:** Create summary document\n\n---\n*Original request: \"Find emails from Mike and create a summary doc\"*",
    "conversation_id": "conv_abc123",
    "ready_for_execution": false,
    "intent": "multi_step_workflow",
    "extracted_info": {},
    "execution_summary": "HTTP error calling docs_agent: Connection refused"
}
```

### 6.4 No Results Response Example (No LLM Used)

```json
{
    "response": "ℹ️ **Search completed - No results found**\n\nNo emails were found matching your search criteria.\n  • Search query: `from:unknown@test.com`\n\n**Suggestions:**\n  • Try broadening your search terms\n  • Check the date range if specified\n  • Verify the sender's email address spelling\n\n---\n*Original request: \"Find emails from unknown@test.com\"*",
    "conversation_id": "conv_abc123",
    "ready_for_execution": false,
    "intent": "search_email",
    "extracted_info": {"query": "from:unknown@test.com"},
    "execution_summary": "No emails found matching criteria"
}
```

### 6.5 Thread Message Response (via /threads/{id}/messages)

```json
{
    "thread_id": "thread_xyz789",
    "bot_response": "✅ Successfully found 1 email from Mike...",
    "ready_for_execution": false,
    "conversation_id": "conv_abc123",
    "request_id": "req_20251130_143022_a1b2c3",
    "token_usage": {
        "total_tokens": 1247,
        "total_cost_usd": 0.0124,
        "llm_call_count": 3
    }
}
```

---

## ❌ Error Handling & Graceful Responses

### Error Response Flow (No LLM)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ERROR RESPONSE GENERATION (Template-Based - Saves Tokens!)             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. DETECT ERROR TYPE                                                    │
│     ┌───────────────────────────────────────────────────────────────┐   │
│     │ final_context = {                                             │   │
│     │   "error": "Connection refused",                              │   │
│     │   "stopped_at_step": 2,                                       │   │
│     │   "results": [                                                │   │
│     │     {"step": 1, "status": "success", "description": "..."},  │   │
│     │     {"step": 2, "status": "error", "error": "..."}           │   │
│     │   ]                                                           │   │
│     │ }                                                             │   │
│     └───────────────────────────────────────────────────────────────┘   │
│                          │                                               │
│                          ▼                                               │
│  2. CATEGORIZE ERROR                                                     │
│     ┌───────────────────────────────────────────────────────────────┐   │
│     │ _categorize_error("Connection refused")                       │   │
│     │                                                               │   │
│     │ Keywords checked:                                             │   │
│     │   • "auth", "token", "401" → "auth"                          │   │
│     │   • "not found", "404" → "not_found"                         │   │
│     │   • "timeout" → "timeout"                                     │   │
│     │   • "connection", "refused" → "connection" ✓                 │   │
│     │   • "permission", "denied" → "permission"                    │   │
│     │   • "rate limit", "429" → "rate_limit"                       │   │
│     └───────────────────────────────────────────────────────────────┘   │
│                          │                                               │
│                          ▼                                               │
│  3. BUILD STRUCTURED RESPONSE                                            │
│     ┌───────────────────────────────────────────────────────────────┐   │
│     │ ❌ **Unable to complete your request**                        │   │
│     │                                                               │   │
│     │ **Issue:** Could not connect to the required service.        │   │
│     │ **Suggestion:** Check if all services are running.           │   │
│     │                                                               │   │
│     │ ---                                                           │   │
│     │ **What was completed before the error:**                     │   │
│     │   ✅ Search for emails from Mike                             │   │
│     │                                                               │   │
│     │ **Failed at step 2:** Create summary document                │   │
│     │                                                               │   │
│     │ ---                                                           │   │
│     │ *Original request: "Find emails from Mike and create..."*   │   │
│     └───────────────────────────────────────────────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Scenario 1: Agent HTTP Error

**When:** Agent microservice is down or returns HTTP error

```
Orchestrator Flow:
┌────────────────────────────────────────┐
│ Step 1: gmail_agent.search_emails      │
│ Status: ✅ success                      │
├────────────────────────────────────────┤
│ Step 2: docs_agent.create_doc          │
│ HTTP 500 - Internal Server Error       │
│ Status: ❌ error                        │
│ 🛑 WORKFLOW STOPPED                    │
└────────────────────────────────────────┘
```

**final_context passed to summarize_execution:**
```python
{
    "emails": [...],  # From step 1
    "results": [
        {"step": 1, "status": "success", "description": "Search emails"},
        {"step": 2, "status": "error", "error": "HTTP 500"}
    ],
    "stopped_at_step": 2,
    "error": "HTTP error calling docs_agent: Internal Server Error"
}
```

**User Response (Template - No LLM):**
```markdown
❌ **Unable to complete your request**

**Issue:** Could not connect to the required service.
**Suggestion:** Please check if all services are running and try again.

---
**What was completed before the error:**
  ✅ Search for emails from Mike

**Failed at step 2:** Create summary document

---
*Original request: "Find emails from Mike and create a summary doc"*
```

### Scenario 2: Agent Returns Error

**When:** Agent executes but returns `success: false`

```python
# Agent Response:
{
    "success": false,
    "error": "Document not found: doc_invalid123",
    "no_results": false
}
```

**User Response (Template - No LLM):**
```markdown
❌ **Unable to complete your request**

**Issue:** The requested resource could not be found.
**Suggestion:** Please verify the ID or name and try again.

---
*Original request: "Edit document doc_invalid123"*
```

### Scenario 3: Timeout Error

**When:** Agent takes too long (>320 seconds)

```python
# utils.py - call_agent_with_retry()
timeout_config = httpx.Timeout(
    timeout=320.0,    # Total timeout
    connect=10.0,     # Connection timeout
    read=320.0,       # Read timeout
    write=30.0        # Write timeout
)
```

**After 3 retries with exponential backoff:**
```python
{
    "step": 2,
    "agent": "mapping_agent",
    "tool": "parse_file",
    "status": "error",
    "error": "HTTP timeout calling mapping_agent after 3 retries"
}
```

**User Response (Template - No LLM):**
```markdown
❌ **Unable to complete your request**

**Issue:** The operation took too long to complete.
**Suggestion:** The service may be busy. Please try again in a moment.

---
*Original request: "Parse the uploaded file"*
```

### Scenario 4: No Results (Graceful - Continues Workflow)

**When:** Search returns empty but operation was valid

```python
# Agent Response:
{
    "success": false,
    "error": "No emails found matching criteria",
    "no_results": true,  # Key flag - allows workflow to continue!
    "emails": [],
    "total_count": 0
}
```

**Orchestrator Behavior:**
- Does NOT stop workflow ✅
- Adds empty context variables
- Continues to next step (if any)

**User Response (Template - No LLM):**
```markdown
ℹ️ **Search completed - No results found**

No emails were found matching your search criteria.
  • Search query: `from:unknown@test.com`

**Suggestions:**
  • Try broadening your search terms
  • Check the date range if specified
  • Verify the sender's email address spelling

---
*Original request: "Find emails from unknown@test.com"*
```

---

## 🔄 Retry Logic (call_agent_with_retry)

```
┌─────────────────────────────────────────────────────────────────┐
│  RETRY FLOW                                                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Attempt 1 ──▶ Timeout/Error ──▶ Wait 1s                        │
│       │                              │                           │
│       ▼                              ▼                           │
│  Attempt 2 ──▶ Timeout/Error ──▶ Wait 2s (backoff_factor^1)     │
│       │                              │                           │
│       ▼                              ▼                           │
│  Attempt 3 ──▶ Timeout/Error ──▶ FAIL (all retries exhausted)   │
│       │                                                          │
│       ▼                                                          │
│  SUCCESS ──▶ Return result                                       │
│                                                                  │
│  Retry Conditions:                                               │
│  ✅ Timeout exceptions                                           │
│  ✅ HTTP 5xx errors                                              │
│  ✅ HTTP 429 (rate limit)                                        │
│  ❌ HTTP 4xx errors (except 429) - No retry                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📊 Complete Field Reference

### Variable Context Fields

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `today_date` | string | System | Current date (YYYY-MM-DD) |
| `yesterday_date` | string | System | Yesterday's date |
| `emails` | array | gmail_agent | List of email objects |
| `total_count` | int | gmail_agent | Number of results |
| `draft_id` | string | gmail_agent | Created draft ID |
| `document_id` | string | docs_agent | Created/edited doc ID |
| `document_content` | string | docs_agent | Document text content |
| `events` | array | calendar_agent | Calendar events |
| `file_id` | string | drive_agent | Uploaded file ID |
| `mapped_data` | array | mapping_agent | Transformed data |

### Step Result Fields

| Field | Type | Description |
|-------|------|-------------|
| `step` | int | Step number (1-indexed) |
| `agent` | string | Agent name (gmail_agent, etc.) |
| `tool` | string | Tool/function called |
| `description` | string | Human-readable description |
| `inputs` | dict | Substituted input parameters |
| `output` | dict | Agent response data (success only) |
| `status` | string | "success", "error", "no_results" |
| `error` | string | Error message (error only) |
| `message` | string | Info message (no_results only) |

### Frontend Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `response` | string | User-friendly summary (markdown) |
| `conversation_id` | string | Session identifier |
| `ready_for_execution` | bool | False after execution |
| `intent` | string | Detected user intent |
| `extracted_info` | dict | Parsed parameters |
| `execution_summary` | string | Raw status message |
| `request_id` | string | For log correlation |
| `token_usage` | dict | LLM token consumption |

---

## 🔌 WebSocket Progress Updates

Real-time progress via WebSocket (`/ws/progress/{thread_id}`):

```json
{
    "type": "progress",
    "data": {
        "current_step": 2,
        "total_steps": 5,
        "step_name": "Creating document",
        "agent": "docs_agent",
        "status": "executing"
    }
}
```

**Status Values:**
- `executing` - Step in progress
- `completed` - All steps done
- `error` - Step failed
- `approval_required` - Waiting for user approval

---

## 📋 Summary Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        COMPLETE DATA FLOW                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  User Input: "Find emails from Mike and create a summary doc"               │
│       │                                                                      │
│       ▼                                                                      │
│  ┌─────────────────┐                                                         │
│  │ Supervisor Node │ → Generate execution plan                               │
│  └────────┬────────┘                                                         │
│           │                                                                  │
│           ▼                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐            │
│  │                    ORCHESTRATOR NODE                         │            │
│  │                                                              │            │
│  │  Step 1: gmail_agent.search_emails                          │            │
│  │     Input: {query: "from:mike"}                             │            │
│  │     Output: {emails: [...], total_count: 3}                 │            │
│  │     Status: ✅ success                                       │            │
│  │     Context += {emails, total_count, found_emails}          │            │
│  │                          │                                   │            │
│  │                          ▼                                   │            │
│  │  Step 2: docs_agent.create_doc                              │            │
│  │     Input: {title: "Email Summary", content: "{{emails}}"}  │            │
│  │     Output: {document_id: "doc_123", url: "..."}            │            │
│  │     Status: ✅ success                                       │            │
│  │     Context += {document_id, doc_url}                       │            │
│  │                                                              │            │
│  └──────────────────────────┬──────────────────────────────────┘            │
│                             │                                                │
│                             ▼                                                │
│  ┌─────────────────────────────────────────────────────────────┐            │
│  │                   FINAL CONTEXT                              │            │
│  │  {                                                           │            │
│  │    emails: [{subject: "...", from: "mike@..."}],            │            │
│  │    total_count: 3,                                          │            │
│  │    document_id: "doc_123",                                  │            │
│  │    doc_url: "https://docs.google.com/..."                   │            │
│  │  }                                                           │            │
│  └──────────────────────────┬──────────────────────────────────┘            │
│                             │                                                │
│                             ▼                                                │
│  ┌─────────────────────────────────────────────────────────────┐            │
│  │              CONVERSATIONAL AGENT                            │            │
│  │              summarize_execution()                           │            │
│  │                                                              │            │
│  │  1. Filter context (remove IDs, dates, tokens)              │            │
│  │  2. Build readable context text                             │            │
│  │  3. Call LLM for user-friendly summary                      │            │
│  │  4. Return markdown-formatted response                      │            │
│  └──────────────────────────┬──────────────────────────────────┘            │
│                             │                                                │
│                             ▼                                                │
│  ┌─────────────────────────────────────────────────────────────┐            │
│  │              FINAL RESPONSE TO FRONTEND                      │            │
│  │                                                              │            │
│  │  {                                                           │            │
│  │    "response": "✅ Found 3 emails from Mike and created     │            │
│  │                 a summary document.\n\n**Document:**         │            │
│  │                 [View Document](https://docs...)",           │            │
│  │    "conversation_id": "conv_abc123",                        │            │
│  │    "ready_for_execution": false,                            │            │
│  │    "intent": "multi_step_workflow",                         │            │
│  │    "execution_summary": "Workflow executed successfully"    │            │
│  │  }                                                           │            │
│  └─────────────────────────────────────────────────────────────┘            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚨 Error Response Examples

### HTTP 500 - Internal Error
```json
{
    "detail": "Workflow execution failed: HTTP error calling gmail_agent: Connection refused"
}
```

### HTTP 409 - Conflict (Already Executing)
```json
{
    "detail": "Conversation is currently executing. Please wait until the operation completes."
}
```

### HTTP 202 - Approval Required
```json
{
    "status": "approval_required",
    "action_id": "action_a1b2c3d4",
    "step_info": {
        "step_number": 2,
        "agent": "gmail_agent",
        "tool": "send_email",
        "description": "Send email to client",
        "inputs": {"to": "client@company.com", "subject": "..."},
        "risk_level": "DANGEROUS"
    },
    "approval_endpoint": "/action/approve/action_a1b2c3d4",
    "next_steps": [
        "Review the action details at GET /action/action_a1b2c3d4",
        "Approve with POST /action/approve/action_a1b2c3d4",
        "Include decision: 'approve', 'reject', or 'skip'"
    ]
}
```

---

## 💡 Error Handling Design Principles

### Why Template-Based Error Responses?

| Aspect | LLM-Based | Template-Based |
|--------|-----------|----------------|
| **Speed** | ~2-3 seconds | Instant |
| **Cost** | ~$0.01 per error | $0.00 |
| **Consistency** | Variable wording | Predictable format |
| **Debugging** | Hard to trace | Easy to trace |
| **User Experience** | Good but slow | Fast and clear |

### Error Categorization Logic

```python
def _categorize_error(error_msg: str) -> str:
    error_lower = error_msg.lower()
    
    if "auth" or "token" or "401" or "403" in error_lower:
        return "auth"          # Authentication issues
    elif "not found" or "404" in error_lower:
        return "not_found"     # Resource doesn't exist
    elif "timeout" in error_lower:
        return "timeout"       # Operation took too long
    elif "connection" or "refused" in error_lower:
        return "connection"    # Service unavailable
    elif "permission" or "denied" in error_lower:
        return "permission"    # Access control issues
    elif "rate limit" or "429" in error_lower:
        return "rate_limit"    # Too many requests
    else:
        return "unknown"       # Generic error
```

### Graceful Degradation Strategy

```
┌─────────────────────────────────────────────────────────────────────┐
│                    GRACEFUL DEGRADATION                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  SUCCESS PATH                                                        │
│  ─────────────                                                       │
│  ✅ LLM generates rich, contextual summary                          │
│  ✅ Actual data values shown (names, subjects, dates)               │
│  ✅ Full markdown formatting                                         │
│                                                                      │
│  ERROR PATH (Fallback - No LLM)                                      │
│  ─────────────────────────────                                       │
│  ❌ Template-based response (instant, free)                         │
│  ❌ Error categorization for user-friendly message                  │
│  ❌ Shows what completed before failure                             │
│  ❌ Actionable suggestions                                          │
│                                                                      │
│  NO RESULTS PATH (Fallback - No LLM)                                 │
│  ─────────────────────────────────                                   │
│  ℹ️ Template-based "no results" response                            │
│  ℹ️ Context-aware suggestions (email vs calendar vs docs)           │
│  ℹ️ Shows original search criteria                                  │
│                                                                      │
│  LLM FAILURE PATH (Double Fallback)                                  │
│  ─────────────────────────────────                                   │
│  ⚠️ If LLM call fails during success summary                        │
│  ⚠️ Falls back to simple formatted context text                     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

*Last Updated: November 30, 2025*
