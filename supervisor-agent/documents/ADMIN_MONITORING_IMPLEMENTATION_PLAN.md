# Admin Monitoring Dashboard - Implementation Plan

## Executive Summary

This document provides a comprehensive analysis of the current logging system and proposes a plan to transform the technical logs dashboard into an **admin-friendly monitoring interface**. The goal is to make the system usable by administrators who are NOT developers.

---

## Part 1: Current Logging System Analysis

### 1.1 Database Schema Overview

The system uses **SQLite** with **5 tables** for log storage:

| Table | Purpose | Admin Value |
|-------|---------|-------------|
| `logs` | General system logs | ⚠️ Low - Too technical |
| `llm_calls` | LLM API usage & costs | ✅ High - Cost tracking |
| `agent_calls` | Agent execution tracking | ✅ High - Performance metrics |
| `request_summaries` | Per-request aggregations | ✅ High - Request success tracking |
| `pending_actions` | Human-in-the-loop approvals | ✅ High - Action management |

---

### 1.2 Field-by-Field Analysis

#### Table: `logs` (General Logs)

| Field | Type | Admin Relevance | Recommendation |
|-------|------|-----------------|----------------|
| `id` | INTEGER | ❌ None | Hide |
| `timestamp` | TEXT | ✅ Essential | Show as readable date/time |
| `level` | TEXT | ⚠️ Medium | Show only ERROR, WARNING, CRITICAL |
| `logger` | TEXT | ❌ Technical | Hide |
| `message` | TEXT | ⚠️ Medium | Simplify or translate to plain language |
| `request_id` | TEXT | ❌ Technical | Hide (use internally only) |
| `conversation_id` | TEXT | ⚠️ Medium | Show as "Session ID" |
| `thread_id` | TEXT | ❌ Technical | Hide |
| `component` | TEXT | ⚠️ Medium | Translate to friendly names |
| `operation` | TEXT | ⚠️ Medium | Translate to actions |
| `data` | TEXT (JSON) | ❌ Technical | Hide unless critical |

**Log Levels Available:**
- `DEBUG` - ❌ Hide from admins (developer only)
- `INFO` - ⚠️ Selectively show (major events only)
- `PROGRESS` - ✅ Show as activity indicators
- `WARNING` - ✅ Show with explanations
- `ERROR` - ✅ Show prominently with actions
- `CRITICAL` - ✅ Alert immediately

---

#### Table: `llm_calls` (LLM Usage Tracking)

| Field | Type | Admin Relevance | Recommendation |
|-------|------|-----------------|----------------|
| `id` | INTEGER | ❌ None | Hide |
| `timestamp` | TEXT | ✅ Essential | Show |
| `request_id` | TEXT | ❌ Technical | Hide |
| `conversation_id` | TEXT | ⚠️ Medium | Link to session |
| `model` | TEXT | ✅ High | Show as "AI Model Used" |
| `tier` | TEXT | ❌ Technical | Hide |
| `operation` | TEXT | ⚠️ Medium | Translate to action |
| `input_tokens` | INTEGER | ⚠️ Medium | Show in summary only |
| `output_tokens` | INTEGER | ⚠️ Medium | Show in summary only |
| `total_tokens` | INTEGER | ✅ High | Show for cost awareness |
| `estimated_cost_usd` | REAL | ✅ Very High | Show prominently |
| `duration_ms` | REAL | ✅ High | Show as "Response Time" |
| `success` | INTEGER | ✅ Very High | Show as status indicator |
| `prompt_summary` | TEXT | ❌ Technical | Hide |
| `error` | TEXT | ✅ High | Show for failed calls |
| `cumulative_tokens` | INTEGER | ⚠️ Medium | Show daily totals |
| `cumulative_cost_usd` | REAL | ✅ Very High | Show running totals |

**Key Admin Metrics Derivable:**
- 💰 Total daily/weekly/monthly cost
- ⏱️ Average response time
- ✅ Success rate percentage
- 📊 Usage by model (cost comparison)

---

#### Table: `agent_calls` (Agent Execution Tracking)

| Field | Type | Admin Relevance | Recommendation |
|-------|------|-----------------|----------------|
| `id` | INTEGER | ❌ None | Hide |
| `timestamp` | TEXT | ✅ Essential | Show |
| `request_id` | TEXT | ❌ Technical | Hide |
| `conversation_id` | TEXT | ⚠️ Medium | Link to session |
| `agent_name` | TEXT | ✅ Very High | Show as "Service" (Gmail, Calendar, etc.) |
| `tool_name` | TEXT | ✅ High | Translate to friendly action names |
| `step_number` | INTEGER | ⚠️ Medium | Show for multi-step tasks |
| `total_steps` | INTEGER | ⚠️ Medium | Show for multi-step tasks |
| `inputs` | TEXT (JSON) | ⚠️ Low | Hide or show summary only |
| `success` | INTEGER | ✅ Very High | Show as status |
| `duration_ms` | REAL | ✅ High | Show as "Time Taken" |
| `output_summary` | TEXT | ✅ High | Show as "Result" |
| `error` | TEXT | ✅ Very High | Show for failures |

**Agent Names to Friendly Names:**
| Technical | Admin-Friendly |
|-----------|----------------|
| `gmail` | 📧 Email Service |
| `calendar` | 📅 Calendar Service |
| `gdocs` | 📄 Documents Service |
| `sheets` | 📊 Spreadsheets Service |
| `gdrive` | 📁 File Storage Service |

**Tool Names to Actions:**
| Technical Tool | Admin-Friendly Action |
|----------------|----------------------|
| `send_email` | "Sent an email" |
| `create_event` | "Created calendar event" |
| `read_document` | "Read document" |
| `update_sheet` | "Updated spreadsheet" |
| `search_files` | "Searched files" |

---

#### Table: `request_summaries` (Request Aggregations)

| Field | Type | Admin Relevance | Recommendation |
|-------|------|-----------------|----------------|
| `id` | INTEGER | ❌ None | Hide |
| `request_id` | TEXT | ❌ Technical | Hide |
| `conversation_id` | TEXT | ⚠️ Medium | Show as Session |
| `thread_id` | TEXT | ❌ Technical | Hide |
| `started_at` | TEXT | ✅ High | Show |
| `completed_at` | TEXT | ✅ High | Show |
| `total_duration_ms` | REAL | ✅ Very High | Show as "Total Time" |
| `total_input_tokens` | INTEGER | ⚠️ Medium | Show in cost breakdown |
| `total_output_tokens` | INTEGER | ⚠️ Medium | Show in cost breakdown |
| `total_tokens` | INTEGER | ✅ High | Show |
| `total_cost_usd` | REAL | ✅ Very High | Show prominently |
| `llm_call_count` | INTEGER | ⚠️ Medium | Show as "AI Calls Made" |
| `agent_call_count` | INTEGER | ✅ High | Show as "Actions Performed" |
| `success` | INTEGER | ✅ Very High | Show as overall status |
| `error` | TEXT | ✅ Very High | Show for failed requests |

---

#### Table: `pending_actions` (Human-in-the-Loop)

| Field | Type | Admin Relevance | Recommendation |
|-------|------|-----------------|----------------|
| `id` | INTEGER | ❌ None | Hide |
| `action_id` | TEXT | ❌ Technical | Hide |
| `thread_id` | TEXT | ❌ Technical | Hide |
| `conversation_id` | TEXT | ⚠️ Medium | Link to session |
| `request_id` | TEXT | ❌ Technical | Hide |
| `step_number` | INTEGER | ⚠️ Medium | Show in context |
| `agent_name` | TEXT | ✅ Very High | Show as Service |
| `tool_name` | TEXT | ✅ Very High | Show as Action |
| `description` | TEXT | ✅ Very High | Show prominently |
| `inputs` | TEXT (JSON) | ⚠️ Medium | Show key details only |
| `output_variables` | TEXT (JSON) | ❌ Technical | Hide |
| `risk_level` | TEXT | ✅ Very High | Show with color coding |
| `status` | TEXT | ✅ Very High | Show prominently |
| `created_at` | TEXT | ✅ High | Show |
| `expires_at` | TEXT | ✅ High | Show as "Respond by" |
| `decided_at` | TEXT | ⚠️ Medium | Show in history |
| `decided_by` | TEXT | ✅ High | Show who approved |
| `execution_result` | TEXT (JSON) | ⚠️ Medium | Show summary only |
| `error` | TEXT | ✅ Very High | Show if failed |

---

### 1.3 Current API Endpoints

| Endpoint | Purpose | Data Returned |
|----------|---------|---------------|
| `GET /logs` | Fetch logs with filters | Raw log entries |
| `GET /logs/search` | Full-text search | Matching logs |
| `GET /logs/stats` | Token/cost summary | Aggregated statistics |
| `GET /logs/requests/{id}` | Single request details | Logs for one request |
| `GET /agents/metrics` | Agent performance | Accuracy, speed, reliability |

---

## Part 2: Gap Analysis

### 2.1 What's Missing for Admins

| Feature | Current State | Admin Need |
|---------|---------------|------------|
| **Time Period Selector** | ❌ None | Select Last Hour/Day/Week/Month |
| **Alert System** | ❌ None | See errors at a glance |
| **Plain Language** | ❌ Technical terms | Human-readable summaries |
| **Health Status** | ❌ None | Traffic light status (🟢🟡🔴) |
| **Activity Summary** | ❌ Raw logs | "Gmail sent 12 emails today" |
| **Trend Indicators** | ❌ None | ↑↓ compared to yesterday |
| **Recommended Actions** | ❌ None | What to do when issues occur |

### 2.2 What's Too Technical

| Current UI Element | Problem | Solution |
|--------------------|---------|----------|
| Request ID display | Meaningless UUID | Hide it |
| Thread ID display | Meaningless UUID | Hide it |
| JSON data blocks | Overwhelming | Show key-value summary |
| DEBUG/INFO logs | Too verbose | Filter out by default |
| Token counts | Confusing | Show only cost |
| Duration in ms | Non-intuitive | Show as "2.5 seconds" |

---

## Part 3: Implementation Plan

### Phase 1: Alert Banner & Health Status (Priority: HIGH)

**Goal:** Admins see problems immediately on page load.

#### 1.1 New Component: `AlertBanner`
```
Location: Top of LogsPage
Shows:
- 🔴 Critical: "3 failed requests in the last hour"
- 🟡 Warning: "Calendar agent response time increased 50%"
- 🟢 All Good: "All systems operating normally"
```

#### 1.2 New Component: `SystemHealthIndicator`
```
Display: Traffic light with status text
- 🟢 Healthy (>95% success, <5s avg response)
- 🟡 Degraded (>90% success OR <10s avg response)
- 🔴 Issues (>80% success OR >10s avg response)
```

#### 1.3 Backend Changes
- New endpoint: `GET /system/health` - Returns health status
- New endpoint: `GET /alerts/recent` - Returns active alerts

---

### Phase 2: Time Period Selector (Priority: HIGH)

**Goal:** Admins can analyze any time period.

#### 2.1 UI Component: `TimePeriodSelector`
```
Options:
- Last Hour
- Last 24 Hours (default)
- Last 7 Days
- Last 30 Days
- Custom Range (date picker)
```

#### 2.2 State Management
- Store selected period in component state
- Pass start_time/end_time to all API calls
- Persist preference in localStorage

---

### Phase 3: Admin-Friendly Agent Cards (Priority: HIGH)

**Goal:** Replace technical metrics with plain language.

#### 3.1 Redesigned `AgentPerformanceCard`
```
Current:
- Accuracy: 92%
- Speed: 85
- Reliability: 92%
- Efficiency: 75

New:
📧 Email Service
Status: ✅ Working Great

Today's Activity:
- 24 emails sent
- 15 emails read
- 3 drafts created

Performance: Fast (avg 1.2s)
Success Rate: 98% (47/48)

[No issues detected]
```

#### 3.2 Status Labels (Plain Language)
| Score | Label | Color |
|-------|-------|-------|
| 85-100 | "Working Great" | Green |
| 70-84 | "Working Well" | Blue |
| 50-69 | "Needs Attention" | Yellow |
| <50 | "Having Issues" | Red |

---

### Phase 4: Activity Summary Tab (Priority: MEDIUM)

**Goal:** Replace "Live Logs" with readable activity feed.

#### 4.1 New Component: `ActivityFeed`
```
Shows timeline of actions in plain language:

🕐 2 minutes ago
📧 Email Service sent an email to john@example.com
   Subject: "Meeting Tomorrow"
   ✅ Delivered successfully

🕐 5 minutes ago
📅 Calendar Service created an event
   "Team Standup" on Dec 2 at 9:00 AM
   ✅ Event created

🕐 12 minutes ago
📄 Documents Service read a document
   "Q4 Report.docx"
   ✅ Retrieved successfully
```

#### 4.2 Activity Aggregation
```
Daily Summary:
📧 Emails: 24 sent, 15 read, 0 failed
📅 Calendar: 5 events created, 2 modified
📄 Documents: 12 reads, 3 updates
📊 Sheets: 8 updates
📁 Files: 15 searches, 4 downloads
```

#### 4.3 Backend Changes
- New endpoint: `GET /activity/feed` - Returns plain-language activity
- New endpoint: `GET /activity/summary` - Returns aggregated counts

---

### Phase 5: Technical Logs (Hidden by Default) (Priority: LOW)

**Goal:** Keep detailed logs accessible but hidden.

#### 5.1 Changes to "Live Logs" Tab
- Rename to "Technical Logs (Advanced)"
- Add warning: "These logs are for technical troubleshooting"
- Default to showing only ERROR and CRITICAL
- Hide DEBUG and INFO by default
- Collapse JSON data by default

---

## Part 4: New Backend Endpoints Required

### 4.1 System Health Endpoint

```python
GET /system/health

Response:
{
  "status": "healthy" | "degraded" | "unhealthy",
  "score": 95,
  "indicators": {
    "success_rate": 98.5,
    "avg_response_time_ms": 1250,
    "error_count_1h": 2,
    "agents_healthy": 5,
    "agents_degraded": 0
  },
  "last_updated": "2024-12-01T10:30:00Z"
}
```

### 4.2 Active Alerts Endpoint

```python
GET /alerts/recent?hours=1

Response:
{
  "alerts": [
    {
      "type": "error",
      "severity": "high",
      "message": "Gmail agent failed 3 times in the last hour",
      "agent": "gmail",
      "first_occurred": "2024-12-01T09:15:00Z",
      "count": 3,
      "recommendation": "Check Gmail API credentials"
    }
  ],
  "total_errors_1h": 3,
  "total_warnings_1h": 5
}
```

### 4.3 Activity Feed Endpoint

```python
GET /activity/feed?limit=50&start_time=...

Response:
{
  "activities": [
    {
      "timestamp": "2024-12-01T10:25:00Z",
      "agent": "gmail",
      "agent_friendly": "Email Service",
      "action": "send_email",
      "action_friendly": "Sent an email",
      "description": "Sent email to john@example.com",
      "details": {
        "to": "john@example.com",
        "subject": "Meeting Tomorrow"
      },
      "success": true,
      "duration_friendly": "1.2 seconds"
    }
  ]
}
```

### 4.4 Activity Summary Endpoint

```python
GET /activity/summary?period=24h

Response:
{
  "period": "24h",
  "by_agent": {
    "gmail": {
      "friendly_name": "Email Service",
      "total_actions": 42,
      "successful": 41,
      "failed": 1,
      "actions": {
        "send_email": 24,
        "read_email": 15,
        "create_draft": 3
      }
    },
    "calendar": {
      "friendly_name": "Calendar Service",
      "total_actions": 12,
      "successful": 12,
      "failed": 0,
      "actions": {
        "create_event": 5,
        "update_event": 4,
        "list_events": 3
      }
    }
  },
  "totals": {
    "total_actions": 85,
    "successful": 83,
    "failed": 2,
    "success_rate": 97.6
  }
}
```

---

## Part 5: UI Component Structure

### 5.1 Updated LogsPage Component Tree

```
LogsPage
├── AlertBanner (NEW)
│   ├── CriticalAlerts
│   └── WarningAlerts
│
├── SystemHealthIndicator (NEW)
│   ├── TrafficLight
│   └── HealthMetrics
│
├── TimePeriodSelector (NEW)
│   ├── QuickSelects (1h, 24h, 7d, 30d)
│   └── CustomDateRange
│
├── TabNavigation
│   ├── Overview Tab (existing, enhanced)
│   ├── Services Tab (renamed from "Agent Performance")
│   ├── Activity Tab (NEW, replaces Live Logs)
│   └── Technical Logs Tab (existing, hidden by default)
│
├── OverviewTab (existing)
│   ├── StatsCards (simplified)
│   ├── CostSummary
│   └── QuickActions
│
├── ServicesTab (enhanced AgentPerformance)
│   └── ServiceCard (for each agent)
│       ├── StatusBadge
│       ├── ActivitySummary
│       ├── PerformanceBar (simplified)
│       └── RecommendedActions
│
├── ActivityTab (NEW)
│   ├── ActivityFeed
│   │   └── ActivityItem (for each action)
│   └── DailySummary
│
└── TechnicalLogsTab (existing, modified)
    ├── AdvancedWarning
    ├── LogFilters
    └── LogTable
```

---

## Part 6: Implementation Priority & Timeline

### Sprint 1 (Week 1): Foundation
| Task | Priority | Effort |
|------|----------|--------|
| Add `TimePeriodSelector` component | HIGH | 3 hours |
| Create `GET /system/health` endpoint | HIGH | 2 hours |
| Add `AlertBanner` component | HIGH | 3 hours |
| Create `GET /alerts/recent` endpoint | HIGH | 2 hours |

### Sprint 2 (Week 2): Agent Cards
| Task | Priority | Effort |
|------|----------|--------|
| Redesign `AgentPerformanceCard` | HIGH | 4 hours |
| Add plain-language status labels | HIGH | 1 hour |
| Add activity counts to cards | HIGH | 2 hours |
| Create agent name/tool translations | HIGH | 2 hours |

### Sprint 3 (Week 3): Activity Feed
| Task | Priority | Effort |
|------|----------|--------|
| Create `GET /activity/feed` endpoint | MEDIUM | 3 hours |
| Create `GET /activity/summary` endpoint | MEDIUM | 2 hours |
| Build `ActivityFeed` component | MEDIUM | 4 hours |
| Build `DailySummary` component | MEDIUM | 2 hours |

### Sprint 4 (Week 4): Polish
| Task | Priority | Effort |
|------|----------|--------|
| Hide technical logs by default | LOW | 1 hour |
| Add recommended actions | LOW | 3 hours |
| Add localStorage for preferences | LOW | 1 hour |
| Testing and bug fixes | HIGH | 4 hours |

---

## Part 7: Translation Reference

### Agent Names → Friendly Names

```javascript
const AGENT_NAMES = {
  gmail: { name: "Email Service", icon: "📧", color: "#EA4335" },
  calendar: { name: "Calendar Service", icon: "📅", color: "#4285F4" },
  gdocs: { name: "Documents Service", icon: "📄", color: "#4285F4" },
  sheets: { name: "Spreadsheets Service", icon: "📊", color: "#34A853" },
  gdrive: { name: "File Storage Service", icon: "📁", color: "#FBBC04" },
};
```

### Tool Names → Action Descriptions

```javascript
const TOOL_ACTIONS = {
  // Gmail
  send_email: "Sent an email",
  read_email: "Read an email",
  search_emails: "Searched emails",
  create_draft: "Created a draft",
  list_emails: "Listed emails",
  
  // Calendar
  create_event: "Created an event",
  update_event: "Updated an event",
  delete_event: "Deleted an event",
  list_events: "Listed events",
  
  // Docs
  read_document: "Read a document",
  create_document: "Created a document",
  update_document: "Updated a document",
  add_text: "Added text to document",
  
  // Sheets
  read_sheet: "Read spreadsheet data",
  update_sheet: "Updated spreadsheet",
  create_sheet: "Created a spreadsheet",
  
  // Drive
  search_files: "Searched files",
  upload_file: "Uploaded a file",
  download_file: "Downloaded a file",
  list_files: "Listed files",
};
```

### Log Levels → Admin Visibility

```javascript
const LOG_LEVEL_VISIBILITY = {
  DEBUG: { show: false, adminLabel: null },
  INFO: { show: false, adminLabel: null },  // Only major events
  PROGRESS: { show: true, adminLabel: "Activity" },
  WARNING: { show: true, adminLabel: "Warning" },
  ERROR: { show: true, adminLabel: "Error" },
  CRITICAL: { show: true, adminLabel: "Critical Issue" },
};
```

---

## Part 8: Success Criteria

### For Admins

1. ✅ Can see system health in <2 seconds
2. ✅ Can identify problems without scrolling
3. ✅ Understands what each agent is doing
4. ✅ Knows how much the system costs
5. ✅ Gets recommendations when issues occur
6. ✅ Can filter by any time period
7. ✅ Never sees technical IDs or JSON

### For the System

1. ✅ All new endpoints respond in <500ms
2. ✅ Dashboard loads in <3 seconds
3. ✅ Auto-refresh doesn't impact performance
4. ✅ Backwards compatible with existing data

---

## Appendix A: Current vs Proposed UI Comparison

### Overview Tab

**Current:**
```
┌─────────────────────────────────────────────────┐
│ Total Requests: 156    Total Tokens: 245.2K     │
│ Total Cost: $0.0234    Success Rate: N/A        │
└─────────────────────────────────────────────────┘
```

**Proposed:**
```
┌─────────────────────────────────────────────────┐
│ 🟢 System Healthy                               │
│ All 5 services working normally                 │
├─────────────────────────────────────────────────┤
│ Today's Summary:                                │
│ • 85 actions completed successfully             │
│ • 2 errors (both in Email Service)              │
│ • $0.02 spent on AI processing                  │
│ • Average response time: 1.8 seconds            │
└─────────────────────────────────────────────────┘
```

### Agent Performance Tab

**Current:**
```
┌──────────────────────┐
│ gmail                │
│ Accuracy ████░ 92%   │
│ Speed    ███░░ 75    │
│ Reliability ████░ 92%│
│ Efficiency ███░░ 70  │
│ Calls: 156 | 2.5s    │
└──────────────────────┘
```

**Proposed:**
```
┌──────────────────────────────────────────┐
│ 📧 Email Service               ✅ Working│
├──────────────────────────────────────────┤
│ Today's Activity:                        │
│ • 24 emails sent                         │
│ • 15 emails read                         │
│ • 3 drafts created                       │
├──────────────────────────────────────────┤
│ Performance: Fast (avg 1.2s)             │
│ Success: 98% (47 of 48 actions)          │
├──────────────────────────────────────────┤
│ 💡 No issues detected                    │
└──────────────────────────────────────────┘
```

---

## Appendix B: Files to Modify

| File | Changes |
|------|---------|
| `Capstone/src/components/LogsPage.jsx` | Major restructure |
| `Capstone/src/components/LogsPage.css` | New component styles |
| `supervisor-agent/supervisor_agent.py` | Add 4 new endpoints |
| `supervisor-agent/log_storage.py` | Add helper methods |

---

---

## Part 9: 🔐 Privacy & Data Protection (CRITICAL)

### 9.1 Current Privacy State Analysis

**What Exists:**
| Feature | Status | Location |
|---------|--------|----------|
| PII Redaction Function | ⚠️ **DOCUMENTED ONLY** | `log_proposal.md`, `USER_LOG_INTERFACE_GUIDE.md` |
| Input Truncation | ✅ Implemented | `logging_config.py:464` - `{k: str(v)[:50] for k, v in inputs.items()}` |
| Access Control Levels | ⚠️ **DOCUMENTED ONLY** | `log_proposal.md` - `LOG_ACCESS_LEVELS` |

**Critical Finding:** The PII redaction (`PIIRedactor` class) exists only in documentation - **NOT IMPLEMENTED** in actual code!

### 9.2 Privacy Risks in Current System

| Risk | Severity | Current Data Exposed |
|------|----------|---------------------|
| **Email addresses visible** | 🔴 HIGH | `inputs: {"to": "john.doe@company.com"}` |
| **User message content** | 🔴 HIGH | `message: "Send email to my boss about salary..."` |
| **File names/paths** | 🟡 MEDIUM | `inputs: {"file_name": "Q4_Financials_Confidential.xlsx"}` |
| **Calendar event details** | 🟡 MEDIUM | `inputs: {"title": "Doctor Appointment"}` |
| **Phone numbers** | 🔴 HIGH | In message content |
| **API keys partially visible** | 🟡 MEDIUM | Truncated but still 50 chars visible |

### 9.3 What Admins Should See vs. NOT See

| Data Type | Admin Should See | Admin Should NOT See |
|-----------|------------------|---------------------|
| **Request Outcome** | ✅ Success/Failure | ❌ Full error with user data |
| **Agent Used** | ✅ "Gmail Agent" | ❌ Who they emailed |
| **Action Performed** | ✅ "Sent 1 email" | ❌ Email content/subject |
| **Performance Metrics** | ✅ Response time, cost | ❌ Token content |
| **User Identity** | ✅ Hashed user ID | ❌ Real user ID/email |
| **Timestamps** | ✅ When action occurred | ✅ |
| **Error Types** | ✅ "Authentication failed" | ❌ Full stack trace with paths |

### 9.4 Required Privacy Implementation

#### A. Create PII Redactor Utility (NEW FILE)

```python
# File: supervisor-agent/pii_redactor.py

import re
from typing import Dict, Any, Optional
import hashlib

class PIIRedactor:
    """
    Centralized PII redaction for admin-facing logs.
    Applies BEFORE any data is shown to admins.
    """
    
    # PII Detection Patterns
    PATTERNS = {
        'email': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'phone': r'\b(\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
        'ssn': r'\b\d{3}-\d{2}-\d{4}\b',
        'credit_card': r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
        'ip_address': r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
        'api_key': r'\b(sk_live_|sk_test_|api_key_|apikey_)[A-Za-z0-9]{10,}\b',
    }
    
    # Fields that should ALWAYS be redacted for admins
    SENSITIVE_FIELDS = [
        'to', 'from', 'cc', 'bcc',           # Email recipients
        'recipient', 'sender', 'email',       # Email addresses
        'body', 'content', 'message_body',    # Message content
        'subject',                            # Email subjects
        'phone', 'mobile', 'telephone',       # Phone numbers
        'password', 'secret', 'token',        # Credentials
        'api_key', 'access_token',            # API credentials
        'file_path', 'file_name',             # File information
        'query',                              # Search queries
        'attendees', 'participants',          # Meeting participants
    ]
    
    @classmethod
    def redact_text(cls, text: str, level: str = 'admin') -> str:
        """
        Redact PII from text.
        
        Levels:
        - 'admin': Aggressive redaction (default for admin dashboard)
        - 'debug': Minimal redaction (for developers only)
        """
        if not text or not isinstance(text, str):
            return text
            
        result = text
        
        if level == 'admin':
            # Replace all PII patterns
            for pii_type, pattern in cls.PATTERNS.items():
                result = re.sub(pattern, f'[{pii_type.upper()}_REDACTED]', result, flags=re.IGNORECASE)
        
        return result
    
    @classmethod
    def redact_dict(cls, data: Dict[str, Any], level: str = 'admin') -> Dict[str, Any]:
        """Recursively redact PII from dictionary"""
        if not data:
            return data
            
        result = {}
        for key, value in data.items():
            # Check if this field should be completely hidden
            if level == 'admin' and key.lower() in cls.SENSITIVE_FIELDS:
                result[key] = '[REDACTED]'
            elif isinstance(value, dict):
                result[key] = cls.redact_dict(value, level)
            elif isinstance(value, list):
                result[key] = [cls.redact_dict(v, level) if isinstance(v, dict) 
                              else cls.redact_text(str(v), level) if isinstance(v, str) 
                              else v for v in value]
            elif isinstance(value, str):
                result[key] = cls.redact_text(value, level)
            else:
                result[key] = value
                
        return result
    
    @classmethod
    def redact_log_entry(cls, log: Dict[str, Any], level: str = 'admin') -> Dict[str, Any]:
        """Redact an entire log entry for admin viewing"""
        redacted = log.copy()
        
        # Redact message
        if 'message' in redacted:
            redacted['message'] = cls.redact_text(redacted['message'], level)
        
        # Redact data/inputs
        if 'data' in redacted:
            redacted['data'] = cls.redact_dict(redacted['data'], level)
        
        if 'inputs' in redacted:
            redacted['inputs'] = cls.redact_dict(redacted['inputs'], level)
            
        # Hash user identifiers
        if 'conversation_id' in redacted and level == 'admin':
            redacted['conversation_id'] = cls.hash_identifier(redacted['conversation_id'])
            
        # Add redaction flag
        redacted['_pii_redacted'] = True
        redacted['_redaction_level'] = level
        
        return redacted
    
    @classmethod
    def hash_identifier(cls, identifier: str) -> str:
        """Hash an identifier for privacy (one-way)"""
        if not identifier:
            return identifier
        return 'user_' + hashlib.sha256(identifier.encode()).hexdigest()[:8]
    
    @classmethod
    def create_admin_activity_summary(cls, agent_call: Dict[str, Any]) -> str:
        """
        Create a privacy-safe summary of an action for admins.
        
        Instead of: "Sent email to john@example.com with subject 'Salary Discussion'"
        Returns: "Email Service: Sent 1 email"
        """
        agent = agent_call.get('agent_name', 'Unknown')
        tool = agent_call.get('tool_name', 'action')
        success = agent_call.get('success', True)
        
        # Generic action descriptions (NO user data)
        action_summaries = {
            ('gmail', 'send_email'): 'Sent an email',
            ('gmail', 'read_email'): 'Read emails',
            ('gmail', 'search_emails'): 'Searched emails',
            ('calendar', 'create_event'): 'Created a calendar event',
            ('calendar', 'list_events'): 'Listed calendar events',
            ('gdocs', 'read_document'): 'Read a document',
            ('gdocs', 'create_document'): 'Created a document',
            ('sheets', 'read_sheet'): 'Read spreadsheet data',
            ('sheets', 'update_sheet'): 'Updated a spreadsheet',
            ('gdrive', 'search_files'): 'Searched files',
            ('gdrive', 'upload_file'): 'Uploaded a file',
        }
        
        summary = action_summaries.get((agent, tool), f'Performed {tool}')
        status = '✅' if success else '❌'
        
        return f"{status} {summary}"
```

#### B. New Admin-Safe API Endpoints

```python
# Add to supervisor_agent.py

@app.get("/admin/logs")
async def get_admin_logs(...):
    """
    Admin-safe logs endpoint.
    Automatically applies PII redaction before returning.
    """
    from pii_redactor import PIIRedactor
    
    # Get raw logs
    logs, total = storage.get_logs(...)
    
    # Redact EVERY log before returning
    redacted_logs = [PIIRedactor.redact_log_entry(log, level='admin') for log in logs]
    
    return {"logs": redacted_logs, "total": total}


@app.get("/admin/activity")
async def get_admin_activity(...):
    """
    Privacy-safe activity feed for admins.
    Shows WHAT happened, not WHO or WHAT content.
    """
    from pii_redactor import PIIRedactor
    
    agent_calls = storage.get_agent_calls(...)
    
    activities = []
    for call in agent_calls:
        activities.append({
            "timestamp": call['timestamp'],
            "agent": call['agent_name'],
            "summary": PIIRedactor.create_admin_activity_summary(call),
            "success": call['success'],
            "duration_ms": call['duration_ms'],
            # NO inputs, NO outputs, NO user identifiers
        })
    
    return {"activities": activities}
```

### 9.5 Admin Dashboard Data Flow (Privacy-Safe)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DATA FLOW                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   USER ACTION                                                       │
│       ↓                                                             │
│   Raw Log Entry (contains PII)                                      │
│   {                                                                 │
│     "message": "Sent email to john@example.com",                   │
│     "inputs": {"to": "john@example.com", "subject": "Meeting"}     │
│   }                                                                 │
│       ↓                                                             │
│   ┌─────────────────┐                                               │
│   │ STORAGE (SQLite)│ ← Raw data stored (for user's own access)    │
│   └─────────────────┘                                               │
│       ↓                                                             │
│   ┌─────────────────────────────────────────┐                       │
│   │ /admin/* ENDPOINT                       │                       │
│   │   PIIRedactor.redact_log_entry()        │ ← REDACTION LAYER    │
│   └─────────────────────────────────────────┘                       │
│       ↓                                                             │
│   Redacted Log Entry (safe for admin)                               │
│   {                                                                 │
│     "message": "Sent email to [EMAIL_REDACTED]",                   │
│     "inputs": {"to": "[REDACTED]", "subject": "[REDACTED]"}        │
│     "_pii_redacted": true                                          │
│   }                                                                 │
│       ↓                                                             │
│   ADMIN DASHBOARD                                                   │
│       Shows: "Email Service: Sent 1 email ✅"                       │
│       Hides: All user content                                       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 9.6 Privacy Rules Summary

| Rule | Implementation |
|------|----------------|
| **R1: No email addresses** | Regex pattern replacement |
| **R2: No message content** | Field-level redaction |
| **R3: No file names** | Sensitive field list |
| **R4: No search queries** | Sensitive field list |
| **R5: No calendar details** | Sensitive field list |
| **R6: Hashed user IDs** | SHA256 truncated hash |
| **R7: Generic action summaries** | Predefined templates |
| **R8: Redaction flag** | `_pii_redacted: true` |

### 9.7 Updated Implementation Priority

| Task | Priority | Sprint |
|------|----------|--------|
| **Create `pii_redactor.py`** | 🔴 CRITICAL | Sprint 0 (Before all else) |
| **Create `/admin/logs` endpoint** | 🔴 CRITICAL | Sprint 0 |
| **Create `/admin/activity` endpoint** | 🔴 CRITICAL | Sprint 0 |
| **Update LogsPage to use admin endpoints** | 🔴 CRITICAL | Sprint 0 |
| Alert Banner | HIGH | Sprint 1 |
| Time Period Selector | HIGH | Sprint 1 |
| Admin-Friendly Agent Cards | HIGH | Sprint 2 |
| Activity Summary Tab | MEDIUM | Sprint 3 |

---

## Next Steps

Please review this plan and confirm:

1. ✅ Do the proposed changes align with admin needs?
2. ✅ Are the priority rankings correct?
3. ✅ Should any features be added or removed?
4. ✅ Is the timeline acceptable?
5. 🔐 **NEW: Is the privacy/redaction approach sufficient?**

Once approved, I will proceed with implementation starting from **Sprint 0 (Privacy Layer)** first.
