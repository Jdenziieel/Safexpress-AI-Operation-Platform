# 👁️ User Log Interface Guide

> **Designing user-facing logs: What to show, what to hide, and how to display it**

---

## 📋 Table of Contents
- [Understanding the ID System](#understanding-the-id-system)
- [What Users Need vs What We Log](#what-users-need-vs-what-we-log)
- [User Interface Designs](#user-interface-designs)
- [Use Cases & Scenarios](#use-cases--scenarios)
- [Implementation Examples](#implementation-examples)

---

## 🔑 Understanding the ID System

### **The Three IDs Explained**

```mermaid
graph TB
    subgraph "User Session"
        U[User: John Doe]
        
        subgraph "Thread 1: Project Discussion"
            T1[thread_id: thread_def456]
            C1[Conv 1: req_aaa111<br/>Hey, check my emails]
            C2[Conv 2: req_bbb222<br/>Send email to Lance]
            C3[Conv 3: req_ccc333<br/>What did I just send?]
        end
        
        subgraph "Thread 2: Calendar Management"
            T2[thread_id: thread_xyz789]
            C4[Conv 4: req_ddd444<br/>Schedule meeting]
            C5[Conv 5: req_eee555<br/>Cancel tomorrow's meeting]
        end
    end
    
    U --> T1
    U --> T2
    T1 --> C1
    T1 --> C2
    T1 --> C3
    T2 --> C4
    T2 --> C5
    
    style U fill:#e1f5ff
    style T1 fill:#fff3cd
    style T2 fill:#fff3cd
    style C1 fill:#d4edda
    style C2 fill:#d4edda
    style C3 fill:#d4edda
    style C4 fill:#d4edda
    style C5 fill:#d4edda
```

---

### **1. `request_id` - Single Request Tracker**

**Purpose:** Tracks ONE user request from start to finish through ALL steps

**Format:** `req_7x9k2m4n`

**Lifetime:** Created when request arrives → Destroyed when response sent

**Connects:** ✅ YES - Connects ALL logs for a single request flow

**Example Flow:**
```
User sends: "Send email to Lance"
├─ request_id: req_7x9k2m4n (SAME FOR ALL BELOW)
├─ LOG 1:  API receives request
├─ LOG 2:  Conversational agent starts
├─ LOG 3:  Tier 0 check
├─ LOG 4:  Tier 0.5 LLM call
├─ LOG 5:  Full analysis
├─ LOG 6:  Supervisor planning
├─ LOG 7:  Orchestrator execution
├─ LOG 8:  Gmail agent call
├─ LOG 9:  Gmail API execution
├─ LOG 10: Result returned
├─ LOG 11: Final response
└─ ALL 11 LOGS SHARE: req_7x9k2m4n
```

**Query:**
```bash
# Get ALL logs for this one request
grep "req_7x9k2m4n" logs/app.log
```

---

### **2. `conversation_id` - Conversation Session Tracker**

**Purpose:** Groups multiple related requests in a back-and-forth conversation

**Format:** `conv_abc123xyz`

**Lifetime:** Created on first message → Persists until conversation ends (timeout or explicit end)

**Connects:** Multiple `request_id`s within the same conversation

**Example:**
```
Conversation ID: conv_abc123xyz
│
├─ Request 1: "Send email to Lance" 
│  └─ request_id: req_aaa111
│
├─ Request 2: "Also CC Sarah on that email"
│  └─ request_id: req_bbb222
│
└─ Request 3: "Did it go through?"
   └─ request_id: req_ccc333
```

**Why It Matters:**
- Maintains conversation context across multiple user messages
- Enables "follow-up" requests (user says "Also add John" without specifying what)
- Tracks conversation-level metrics (how many turns, total time)

---

### **3. `thread_id` - Persistent Conversation Thread**

**Purpose:** Database identifier for saved conversation threads (persists across sessions)

**Format:** `thread_def456`

**Lifetime:** Created when conversation first saved to DB → Persists forever (or until deleted)

**Connects:** One `conversation_id` to database storage

**Example:**
```
Database: threads.db
│
├─ Thread 1: thread_def456 (Created: Nov 20, 2025)
│  ├─ Title: "Project Email Discussion"
│  ├─ Messages: 12
│  ├─ Last Active: Nov 28, 2025 10:30 AM
│  └─ Conversations:
│     ├─ conv_abc123xyz (Nov 28, 10:00 AM) - 3 messages
│     └─ conv_def456uvw (Nov 28, 10:30 AM) - 2 messages
│
└─ Thread 2: thread_xyz789 (Created: Nov 25, 2025)
   ├─ Title: "Calendar Management"
   ├─ Messages: 8
   └─ Last Active: Nov 28, 2025 09:15 AM
```

**Why It Matters:**
- User can return to conversation days/weeks later
- Preserves conversation history and context
- Enables "continue where we left off" functionality

---

### **🔗 How They Connect**

```
User Session
    │
    └─ thread_id: thread_def456 (DB Record - Persistent)
           │
           ├─ conversation_id: conv_abc123xyz (Session 1 - Nov 28, 10:00 AM)
           │      ├─ request_id: req_aaa111 (Message 1)
           │      ├─ request_id: req_bbb222 (Message 2)
           │      └─ request_id: req_ccc333 (Message 3)
           │
           └─ conversation_id: conv_def456uvw (Session 2 - Nov 28, 10:30 AM)
                  ├─ request_id: req_ddd444 (Message 1)
                  └─ request_id: req_eee555 (Message 2)
```

**In Plain English:**
- **`request_id`** = One message/request (tracks all steps for that request)
- **`conversation_id`** = One conversation session (groups multiple messages)
- **`thread_id`** = Saved conversation thread (persists across sessions)

---

### **Example Scenario: User Returns Days Later**

**Day 1 - User starts conversation:**
```
User: "Send email to Lance about Q4 report"

System creates:
- thread_id: thread_abc (saved to DB)
- conversation_id: conv_001
- request_id: req_001
```

**Day 1 - User continues same session:**
```
User: "Also attach the spreadsheet"

System uses:
- thread_id: thread_abc (SAME - same thread)
- conversation_id: conv_001 (SAME - same session)
- request_id: req_002 (NEW - new message)
```

**Day 5 - User returns to conversation:**
```
User opens thread: "Q4 Report Discussion"

System loads:
- thread_id: thread_abc (from DB)
- conversation_id: conv_002 (NEW session)
- request_id: req_003 (NEW message)

Context: System loads history from thread_abc
User: "Did Lance reply?"

System creates:
- thread_id: thread_abc (SAME thread)
- conversation_id: conv_002 (SAME session)
- request_id: req_004 (NEW message)
```

---

## 🎯 What Users Need vs What We Log

### **Internal Logging (Developer View)**
We log **EVERYTHING** for debugging, analytics, compliance:
- 137,000 logs/day
- All 19 log points per full request
- Performance metrics, LLM tokens, API calls
- Error traces, retry attempts, shared state
- PII-redacted sensitive data

### **User-Facing View (User Dashboard)**
Users need **SELECTIVE** visibility:
- Request status & progress
- High-level steps ("Sending email...", "Email sent!")
- Success/failure outcomes
- Basic timing ("took 3.5 seconds")
- Error messages (user-friendly, not stack traces)

---

## 📊 User Interface Designs

### **Design 1: Request History Dashboard** ⭐ RECOMMENDED

**Purpose:** Show user their request history with filtering and details

**When to Use:** Main dashboard, user wants to see past requests

```
┌─────────────────────────────────────────────────────────────────────┐
│  📊 My Request History                                    [Filters ▼]│
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  Filters:  [All Agents ▼]  [All Status ▼]  [Last 7 Days ▼]  [Search]│
│                                                                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ✅ Send email to Lance about project update                         │
│     Nov 28, 2025 • 10:30:03 AM • 3.6s • Gmail                       │
│     Request ID: req_7x9k2m4n                                         │
│     [View Details]  [View Logs]                                      │
│                                                                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ✅ Forward John's Q4 email to Sarah and schedule meeting            │
│     Nov 28, 2025 • 09:15:42 AM • 6.5s • Gmail, Calendar             │
│     Request ID: req_3m5n7p9q                                         │
│     [View Details]  [View Logs]                                      │
│                                                                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ⏳ Analyzing spreadsheet data... (In Progress - 45%)                │
│     Nov 28, 2025 • 09:10:18 AM • Running... • Sheets, Mapping       │
│     Request ID: req_8k2j4m6n                                         │
│     [View Progress]                                                  │
│                                                                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ❌ Send email to invalid@domain.xyz (Failed)                        │
│     Nov 28, 2025 • 08:45:12 AM • 4.2s • Gmail                       │
│     Error: Recipient address rejected                                │
│     Request ID: req_1a2b3c4d                                         │
│     [View Details]  [View Error Logs]  [Retry]                       │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

**Data Shown:**
- ✅ Status icon (✅ success, ❌ error, ⏳ in progress)
- 📝 Request description (user's original message)
- 🕐 Timestamp
- ⏱️ Duration
- 🤖 Agents used
- 🔑 Request ID (for support/debugging)

---

### **Design 2: Request Detail View with Step-by-Step Logs**

**Purpose:** Detailed view of ONE request showing all steps

**When to Use:** User clicks "View Details" or "View Logs"

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ← Back to History                                                       │
├─────────────────────────────────────────────────────────────────────────┤
│  📧 Send email to Lance about project update                            │
│  ✅ Completed Successfully                                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  📋 Request Details                                                      │
│  ├─ Request ID:        req_7x9k2m4n                                     │
│  ├─ Conversation ID:   conv_abc123xyz                                   │
│  ├─ Thread ID:         thread_def456                                    │
│  ├─ Started:           Nov 28, 2025 10:30:00 AM                         │
│  ├─ Completed:         Nov 28, 2025 10:30:03 AM                         │
│  ├─ Total Duration:    3.56 seconds                                     │
│  ├─ Agents Used:       Gmail (1 call)                                   │
│  └─ LLM Calls:         4 calls                                          │
│                                                                           │
├─────────────────────────────────────────────────────────────────────────┤
│  📊 Execution Timeline                          [Detailed View] [Simple]│
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ✅ Step 1: Request received                           [0.12s] 10:30:00 │
│     └─ User input processed and validated                               │
│                                                                           │
│  ✅ Step 2: Analyzing request                          [0.53s] 10:30:00 │
│     └─ Quick classification: Needs execution                            │
│                                                                           │
│  ✅ Step 3: Full task analysis                         [0.45s] 10:30:01 │
│     └─ Identified: Email to lance@example.com                           │
│                                                                           │
│  ✅ Step 4: Creating execution plan                    [0.67s] 10:30:01 │
│     └─ Generated 3-step plan for Gmail                                  │
│                                                                           │
│  ✅ Step 5: Executing plan                             [1.22s] 10:30:02 │
│     ├─ 🔹 Composing email                                               │
│     ├─ 🔹 Sending via Gmail API                                         │
│     └─ 🔹 Confirming delivery                                           │
│                                                                           │
│  ✅ Step 6: Email sent successfully                    [0.76s] 10:30:03 │
│     └─ Message ID: 18c5a1b2f3d4e5f6                                     │
│     └─ Recipient: lance@example.com                                     │
│                                                                           │
│  ✅ Step 7: Response delivered                         [0.11s] 10:30:03 │
│     └─ User notified of success                                         │
│                                                                           │
├─────────────────────────────────────────────────────────────────────────┤
│  📈 Performance Breakdown                                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ████████░░░░░░░░░░░░ Analysis (46%) - 1.65s                            │
│  ████████░░░░░░░░░░░░ Execution (34%) - 1.22s                           │
│  ████░░░░░░░░░░░░░░░░ Other (20%) - 0.69s                               │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘

[Download Full Logs] [Share with Support] [Export as PDF]
```

---

### **Design 3: Real-Time Progress View** 

**Purpose:** Live progress updates during request execution

**When to Use:** Request in progress, user waiting

```
┌─────────────────────────────────────────────────────────────────────┐
│  ⏳ Processing Your Request...                                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  📧 Send email to Lance about project update                         │
│                                                                       │
│  ████████████████████████████████░░░░░░░░░░ 85% Complete             │
│                                                                       │
│  Current Step: Sending email via Gmail                               │
│  Estimated time remaining: 2 seconds                                 │
│                                                                       │
├─────────────────────────────────────────────────────────────────────┤
│  🔄 Progress Details                                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ✅ Request received and validated                      (0.1s ago)   │
│  ✅ Analyzing your request                              (0.6s ago)   │
│  ✅ Understanding task requirements                     (1.2s ago)   │
│  ✅ Creating execution plan                             (1.8s ago)   │
│  ⏳ Sending email via Gmail...                          (now)        │
│  ⏹️ Confirming delivery                                 (pending)    │
│  ⏹️ Preparing response                                  (pending)    │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘

Request ID: req_7x9k2m4n
Started: 10:30:00 AM • Elapsed: 3.2 seconds
```

**Real-Time Updates via WebSocket:**
```javascript
// Frontend receives progress updates
{
  "request_id": "req_7x9k2m4n",
  "progress": {
    "status": "in_progress",
    "percentage": 85,
    "current_step": "Sending email via Gmail",
    "estimated_time_remaining": "2s"
  }
}
```

---

### **Design 4: Thread/Conversation View**

**Purpose:** Show entire conversation thread with all requests

**When to Use:** User wants to see conversation history, context

```
┌─────────────────────────────────────────────────────────────────────┐
│  💬 Thread: Project Email Discussion                   [Options ▼]   │
│  thread_def456 • Started: Nov 20, 2025 • 12 messages                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  👤 You (10:00 AM):                                                  │
│  "Check my emails from yesterday"                                    │
│                                                                       │
│  🤖 Assistant (10:00 AM):                                            │
│  "I found 12 emails from yesterday. Here are the highlights..."      │
│  📎 Request ID: req_aaa111 • ✅ Success • 2.3s                       │
│                                                                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  👤 You (10:05 AM):                                                  │
│  "Send an email to Lance about the project update"                   │
│                                                                       │
│  🤖 Assistant (10:05 AM):                                            │
│  "✅ Email sent successfully to Lance (lance@example.com) with..."   │
│  📎 Request ID: req_bbb222 • ✅ Success • 3.6s                       │
│     [View Details] [View Logs]                                       │
│                                                                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  👤 You (10:07 AM):                                                  │
│  "Did it go through?"                                                │
│                                                                       │
│  🤖 Assistant (10:07 AM):                                            │
│  "Yes! The email was delivered successfully at 10:05 AM. Message..." │
│  📎 Request ID: req_ccc333 • ✅ Success • 0.8s                       │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘

[Export Thread] [Delete Thread] [New Message]
```

---

### **Design 5: Error Details View**

**Purpose:** User-friendly error display with troubleshooting

**When to Use:** Request failed, user needs to understand why

```
┌─────────────────────────────────────────────────────────────────────┐
│  ❌ Request Failed                                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  📧 Send email to invalid@nonexistent-domain.xyz                     │
│                                                                       │
│  Request ID: req_1a2b3c4d                                            │
│  Failed at: Nov 28, 2025 08:45:12 AM                                 │
│  Duration: 4.2 seconds                                               │
│                                                                       │
├─────────────────────────────────────────────────────────────────────┤
│  ⚠️ What Went Wrong                                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  The email could not be delivered because the recipient address      │
│  was rejected by the email server.                                   │
│                                                                       │
│  Error Code: SMTP_550                                                │
│  Error Message: Recipient address rejected                           │
│                                                                       │
├─────────────────────────────────────────────────────────────────────┤
│  💡 What You Can Do                                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ✓ Check that the email address is correct                          │
│  ✓ Verify the domain name exists                                    │
│  ✓ Try a different email address                                    │
│                                                                       │
│  [Retry with Correct Address] [Contact Support]                      │
│                                                                       │
├─────────────────────────────────────────────────────────────────────┤
│  📊 Execution Timeline (Failed at Step 5)                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ✅ Step 1: Request received                           [0.11s]       │
│  ✅ Step 2: Analyzing request                          [0.54s]       │
│  ✅ Step 3: Full task analysis                         [0.43s]       │
│  ✅ Step 4: Creating execution plan                    [0.68s]       │
│  ❌ Step 5: Sending email via Gmail                    [2.44s]       │
│     └─ Error: Recipient address rejected                             │
│                                                                       │
│  [View Technical Logs] (for debugging)                               │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🎯 Use Cases & Scenarios

### **Scenario 1: User Checks If Email Was Sent**

**User Action:** Goes to Request History dashboard

**What They See:**
```
✅ Send email to Lance about project update
   Nov 28, 2025 • 10:30:03 AM • 3.6s • Gmail
   Request ID: req_7x9k2m4n
```

**User Clicks:** "View Details"

**What They Get:**
- ✅ Success confirmation
- 📧 Recipient: lance@example.com
- 🕐 Sent at: 10:30:03 AM
- 📨 Message ID: 18c5a1b2f3d4e5f6
- 📊 Timeline of 7 steps

**Question Answered:** ✅ Yes, email sent successfully

---

### **Scenario 2: User Troubleshoots Failed Request**

**User Action:** Sees red ❌ icon in history, clicks "View Error Logs"

**What They See:**
```
❌ Request Failed: Send email to invalid@domain.xyz
   Error: Recipient address rejected (SMTP_550)
   
   💡 Suggestion: Check email address is correct
```

**What They DON'T See:**
- ❌ Python stack traces
- ❌ Internal function names
- ❌ Raw API responses
- ❌ Database queries

**Question Answered:** ✅ Why it failed + How to fix it

---

### **Scenario 3: User Tracks Long-Running Request**

**User Action:** Submits complex multi-step request, waits

**What They See:** Real-time progress view
```
⏳ Processing Your Request... 65% Complete

Current Step: Forwarding email
Estimated time remaining: 3 seconds

✅ Request received
✅ Analyzing request
✅ Creating execution plan
⏳ Forwarding email...          ← YOU ARE HERE
⏹️ Creating calendar event
⏹️ Sending confirmation
```

**Updates Every Second via WebSocket**

**Question Answered:** ✅ What's happening right now

---

### **Scenario 4: User Reports Issue to Support**

**User Action:** Clicks "Share with Support" button

**What Gets Generated:**
```
Support Ticket #12345

Request ID: req_7x9k2m4n
Conversation ID: conv_abc123xyz
Thread ID: thread_def456

User: john.doe@company.com
Timestamp: Nov 28, 2025 10:30:00 AM
Duration: 3.56 seconds
Status: Success

Request: "Send email to Lance about project update"
Agents Used: Gmail
LLM Calls: 4

Timeline:
- 10:30:00: Request received
- 10:30:00: Analyzing request (0.53s)
- 10:30:01: Full analysis (0.45s)
- 10:30:01: Plan generation (0.67s)
- 10:30:02: Execution (1.22s)
- 10:30:03: Response sent

[View Full Logs] (Support Access Only)
```

**Support Team Can:**
- Search by `request_id` in internal logs
- See all 19 detailed log entries
- Debug with full context

---

### **Scenario 5: User Reviews Past Conversations**

**User Action:** Opens "My Threads" page

**What They See:**
```
📚 My Conversation Threads

🔹 Project Email Discussion (thread_def456)
   Last active: Nov 28, 2025 • 12 messages • 5 requests
   [Open Thread]

🔹 Calendar Management (thread_xyz789)
   Last active: Nov 28, 2025 • 8 messages • 3 requests
   [Open Thread]

🔹 Spreadsheet Analysis (thread_abc123)
   Last active: Nov 25, 2025 • 15 messages • 7 requests
   [Open Thread]
```

**User Clicks:** "Open Thread" → See full conversation history

**Question Answered:** ✅ What did we discuss before?

---

## 💡 Implementation Examples

### **Frontend: Request History Table Component**

```typescript
interface RequestHistoryItem {
  requestId: string;
  conversationId: string;
  threadId: string;
  userInput: string;
  status: 'success' | 'failed' | 'in_progress';
  timestamp: Date;
  duration: number; // milliseconds
  agentsUsed: string[];
  errorMessage?: string;
}

// Component
function RequestHistoryTable({ items }: { items: RequestHistoryItem[] }) {
  return (
    <table className="request-history">
      <thead>
        <tr>
          <th>Status</th>
          <th>Request</th>
          <th>Time</th>
          <th>Duration</th>
          <th>Agents</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.requestId}>
            <td>
              {item.status === 'success' && '✅'}
              {item.status === 'failed' && '❌'}
              {item.status === 'in_progress' && '⏳'}
            </td>
            <td>
              <div>{item.userInput}</div>
              <small>ID: {item.requestId}</small>
            </td>
            <td>{formatTimestamp(item.timestamp)}</td>
            <td>{formatDuration(item.duration)}</td>
            <td>{item.agentsUsed.join(', ')}</td>
            <td>
              <button onClick={() => viewDetails(item.requestId)}>
                View Details
              </button>
              {item.status === 'failed' && (
                <button onClick={() => retry(item.requestId)}>
                  Retry
                </button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

---

### **Backend: User-Facing Log API Endpoint**

```python
from fastapi import APIRouter, HTTPException
from typing import List, Optional
from datetime import datetime, timedelta

router = APIRouter(prefix="/api/logs")

@router.get("/requests")
async def get_user_requests(
    user_id: str,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    days: int = 7,
    limit: int = 50
) -> List[dict]:
    """
    Get user's request history (USER-FACING)
    
    Returns simplified log data, NOT full internal logs
    """
    
    # Query internal logs (simplified)
    since = datetime.utcnow() - timedelta(days=days)
    
    # Get only relevant fields
    requests = await db.query("""
        SELECT 
            request_id,
            conversation_id,
            thread_id,
            user_input,
            status,
            timestamp,
            duration_ms,
            agents_used,
            error_message
        FROM user_requests
        WHERE user_id = %s 
          AND timestamp > %s
          AND (%s IS NULL OR status = %s)
          AND (%s IS NULL OR %s = ANY(agents_used))
        ORDER BY timestamp DESC
        LIMIT %s
    """, (user_id, since, status, status, agent, agent, limit))
    
    return [
        {
            "request_id": r["request_id"],
            "conversation_id": r["conversation_id"],
            "thread_id": r["thread_id"],
            "user_input": r["user_input"],
            "status": r["status"],
            "timestamp": r["timestamp"].isoformat(),
            "duration": f"{r['duration_ms']/1000:.1f}s",
            "agents_used": r["agents_used"],
            "error_message": r["error_message"]  # User-friendly only
        }
        for r in requests
    ]


@router.get("/requests/{request_id}/details")
async def get_request_details(request_id: str, user_id: str) -> dict:
    """
    Get detailed view of ONE request (USER-FACING)
    
    Shows simplified timeline, NOT full internal logs
    """
    
    # Verify user owns this request
    request = await db.get_request(request_id, user_id)
    if not request:
        raise HTTPException(404, "Request not found")
    
    # Get simplified timeline (PROGRESS logs only)
    timeline = await db.query("""
        SELECT 
            timestamp,
            progress->>'current_step' as step,
            progress->>'percentage' as percentage,
            performance->>'execution_time_ms' as duration
        FROM logs
        WHERE request_id = %s 
          AND level IN ('PROGRESS', 'INFO', 'ERROR')
        ORDER BY timestamp ASC
    """, (request_id,))
    
    return {
        "request_id": request_id,
        "conversation_id": request["conversation_id"],
        "thread_id": request["thread_id"],
        "status": request["status"],
        "started": request["started"].isoformat(),
        "completed": request["completed"].isoformat(),
        "duration": f"{request['duration_ms']/1000:.2f}s",
        "agents_used": request["agents_used"],
        "llm_calls": request["llm_calls"],
        "timeline": [
            {
                "step": t["step"],
                "percentage": t["percentage"],
                "duration": f"{float(t['duration'])/1000:.2f}s" if t["duration"] else None,
                "timestamp": t["timestamp"].isoformat()
            }
            for t in timeline
        ]
    }


@router.get("/requests/{request_id}/full-logs")
async def get_full_logs(
    request_id: str, 
    user_id: str,
    admin: bool = False  # Only for support staff
) -> dict:
    """
    Get FULL internal logs (ADMIN/SUPPORT ONLY)
    
    Regular users should NOT see this
    """
    
    if not admin:
        raise HTTPException(403, "Admin access required")
    
    # Return ALL logs for this request (all 19+ entries)
    logs = await db.query("""
        SELECT *
        FROM logs
        WHERE request_id = %s
        ORDER BY timestamp ASC
    """, (request_id,))
    
    return {
        "request_id": request_id,
        "total_logs": len(logs),
        "logs": logs  # Full detail for debugging
    }
```

---

### **Real-Time Progress via WebSocket**

```python
from fastapi import WebSocket
import asyncio

@router.websocket("/ws/progress/{request_id}")
async def websocket_progress(websocket: WebSocket, request_id: str):
    """
    Stream real-time progress updates to user
    """
    await websocket.accept()
    
    try:
        # Subscribe to progress updates for this request
        async for log in subscribe_to_progress(request_id):
            if log["level"] == "PROGRESS":
                # Send only user-facing progress
                await websocket.send_json({
                    "request_id": request_id,
                    "progress": {
                        "status": log["progress"]["status"],
                        "percentage": log["progress"]["percentage"],
                        "current_step": log["progress"]["current_step"],
                        "estimated_time_remaining": log["progress"].get("estimated_time_remaining")
                    },
                    "timestamp": log["timestamp"]
                })
            
            # Close connection when complete
            if log["progress"]["status"] in ["completed", "failed"]:
                break
                
    except Exception as e:
        await websocket.send_json({"error": str(e)})
    finally:
        await websocket.close()
```

---

## ✅ What to Show vs Hide

### **✅ SHOW to Users:**

| Data | Why |
|------|-----|
| Request ID | For support tickets |
| Status (success/failed/in-progress) | Core outcome |
| User's original input | Context reminder |
| Timestamp | When it happened |
| Duration | How long it took |
| Agents used | What systems were involved |
| High-level steps | "Analyzing...", "Sending..." |
| Progress percentage | Real-time feedback |
| User-friendly error messages | What went wrong |
| Suggested fixes | How to resolve issues |
| Result summary | What was accomplished |

### **❌ HIDE from Users:**

| Data | Why |
|------|-----|
| Python function names | Technical jargon |
| Stack traces | Scary and unhelpful |
| LLM token counts | Internal metric |
| API response codes (raw) | Too technical |
| Database queries | Security risk |
| Internal module names | Confusing |
| Memory addresses | Meaningless to users |
| Retry attempt counts | Implementation detail |
| Variable substitution logs | Too granular |
| PII in raw form | Privacy concern |

---

## 🎨 Design Principles

### **1. Progressive Disclosure**
- **Simple by default:** Show status, time, agents
- **Details on demand:** Click to see timeline
- **Full logs for experts:** Download for debugging

### **2. User-Friendly Language**
- ❌ "Executing orchestrator_node()"
- ✅ "Preparing your request..."

- ❌ "HttpError 550: SMTP rejection"
- ✅ "Email address not found"

### **3. Visual Hierarchy**
- 🔴 Errors: Red, prominent, actionable
- 🟢 Success: Green checkmark, concise
- 🟡 In Progress: Yellow, with percentage

### **4. Actionable Information**
- Show "Retry" button on errors
- Provide "Contact Support" with context
- Suggest fixes ("Check email address")

---

## 🚀 Recommendation Summary

### **For Regular Users:**
1. **Main View:** Request History Dashboard (Design 1)
   - Simple table of past requests
   - Status, time, duration, agents
   - Filter by date/agent/status

2. **Detail View:** Request Details (Design 2)
   - 7-step simplified timeline
   - No technical jargon
   - User-friendly error messages

3. **Live View:** Real-Time Progress (Design 3)
   - WebSocket updates
   - Percentage progress bar
   - Current step description

### **For Power Users:**
- Thread view to see conversation context
- Export logs as PDF/JSON
- Search across all requests

### **For Support/Admin:**
- Access to full internal logs (all 19+ entries)
- Raw log download
- Request ID search across all users

---

## 🎯 Is Detailed Logging Necessary for Users?

### **Short Answer: NO**

**Users need:**
- ✅ Did it work?
- ✅ How long did it take?
- ✅ What went wrong (if failed)?
- ✅ What's happening now (if in progress)?

**Users DON'T need:**
- ❌ All 19 internal log points
- ❌ LLM token counts
- ❌ Function names and modules
- ❌ Tier 0/0.5/Full analysis details

### **When Users DO Need Details:**

1. **Debugging errors** - Show simplified timeline with where it failed
2. **Support tickets** - Give them Request ID to share with support
3. **Audit trail** - For compliance, show "Email sent to X at Y time"

### **The Golden Rule:**

> **Log everything internally for debugging.**  
> **Show only what's useful externally for users.**

---

## 🔐 Privacy, Security & Data Access Control

### **Critical Question: Who Can See What?**

```
┌─────────────────────────────────────────────────────────────────┐
│  Data Access Matrix                                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  👤 Regular User:                                                │
│     ✅ Their own simplified logs (dashboard view)               │
│     ✅ Their own thread history                                 │
│     ❌ Other users' data                                         │
│     ❌ Raw internal logs                                         │
│     ❌ PII from other requests                                   │
│                                                                   │
│  👨‍💼 Admin/Support:                                               │
│     ✅ Full internal logs (with PII redacted)                   │
│     ✅ Cross-user debugging (anonymized)                        │
│     ✅ System metrics and analytics                             │
│     ⚠️  PII access ONLY with explicit approval                  │
│     ❌ Cannot modify/delete logs                                 │
│                                                                   │
│  🔒 System/Audit:                                                │
│     ✅ Complete logs with PII (encrypted at rest)               │
│     ✅ Audit trail of all access                                │
│     ✅ Compliance exports                                        │
│     🔐 Encrypted, access logged, immutable                      │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

### **Storage Strategy: Two-Tier System**

#### **Tier 1: User Dashboard Database (Simplified)**
**Purpose:** Fast queries for user interface  
**Storage:** PostgreSQL `user_requests` table  
**Retention:** 90 days  
**Access:** User can only see their own data

```sql
-- User Dashboard Table (PII Redacted)
CREATE TABLE user_requests (
    request_id VARCHAR(20) PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,  -- Encrypted user identifier
    conversation_id VARCHAR(20),
    thread_id VARCHAR(20),
    user_input TEXT,  -- Original query (visible to user)
    status VARCHAR(20),
    timestamp TIMESTAMP,
    duration_ms INTEGER,
    agents_used TEXT[],
    error_message TEXT,  -- User-friendly message only
    
    -- Access control
    CONSTRAINT user_access CHECK (
        user_id = current_user_id()  -- Row-level security
    )
);

-- Index for fast user queries
CREATE INDEX idx_user_requests_user_id ON user_requests(user_id, timestamp DESC);
```

**What's Stored:**
- ✅ User's original question
- ✅ Request ID for support
- ✅ High-level status and duration
- ✅ Which agents were used
- ❌ NO raw API responses
- ❌ NO detailed execution logs
- ❌ NO other users' data

**Who Can Access:**
- ✅ The user themselves (via dashboard)
- ❌ Other users (isolated by user_id)
- ✅ Admin/Support (with audit logging)

---

#### **Tier 2: Internal Audit Logs (Complete)**
**Purpose:** Debugging, compliance, security audits  
**Storage:** Separate logging database + file storage  
**Retention:** 1-7 years (compliance requirement)  
**Access:** Heavily restricted, audit logged

```sql
-- Internal Audit Logs (Complete Detail)
CREATE TABLE audit_logs (
    log_id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    level VARCHAR(10) NOT NULL,
    component VARCHAR(50) NOT NULL,
    module VARCHAR(100) NOT NULL,
    function VARCHAR(100) NOT NULL,
    request_id VARCHAR(20) NOT NULL,
    conversation_id VARCHAR(20),
    thread_id VARCHAR(20),
    user_id_hash VARCHAR(64),  -- Hashed, not plaintext
    
    -- Full log data (encrypted)
    context JSONB,  -- Encrypted with PII redacted
    progress JSONB,
    performance JSONB,
    error JSONB,
    metadata JSONB,
    
    -- Security
    encryption_key_id VARCHAR(50),
    pii_redacted BOOLEAN DEFAULT true,
    
    -- Audit trail
    accessed_by VARCHAR(100)[] DEFAULT '{}',
    access_log JSONB DEFAULT '{}'::jsonb
);

-- Partition by month for performance
CREATE TABLE audit_logs_2025_11 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');

-- Restrict access
REVOKE ALL ON audit_logs FROM PUBLIC;
GRANT SELECT ON audit_logs TO support_team;  -- Read-only
```

**What's Stored:**
- ✅ ALL 19+ log entries per request
- ✅ Complete execution trace
- ✅ LLM calls, tokens, API responses
- ✅ Error stack traces
- ✅ Performance metrics
- ⚠️ PII is REDACTED automatically
- 🔐 Encrypted at rest

**Who Can Access:**
- ❌ Regular users (never)
- ✅ Support team (read-only, audit logged)
- ✅ System administrators (with justification)
- ✅ Compliance officers (for audits)
- ✅ Automated monitoring systems

---

### **PII Redaction Strategy**

**What is PII (Personally Identifiable Information)?**
- Email addresses
- Phone numbers
- Full names
- Physical addresses
- Credit card numbers
- Social Security Numbers
- IP addresses (in some jurisdictions)
- API keys/tokens

#### **Automatic PII Redaction (Before Storage)**

```python
import re
import hashlib

class PIIRedactor:
    """Automatically redact PII before storing logs"""
    
    # Redaction patterns
    PATTERNS = {
        'email': (
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            lambda m: f"{m.group(0)[:3]}***@{m.group(0).split('@')[1]}"
        ),
        'phone': (
            r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
            lambda m: 'XXX-XXX-' + m.group(0)[-4:]
        ),
        'ssn': (
            r'\b\d{3}-\d{2}-\d{4}\b',
            lambda m: 'XXX-XX-' + m.group(0)[-4:]
        ),
        'credit_card': (
            r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b',
            lambda m: 'XXXX-XXXX-XXXX-' + m.group(0)[-4:]
        ),
        'ip_address': (
            r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
            lambda m: '.'.join(m.group(0).split('.')[:2]) + '.XXX.XXX'
        ),
        'api_key': (
            r'\b[A-Za-z0-9_-]{32,}\b',
            lambda m: m.group(0)[:8] + '***REDACTED***'
        )
    }
    
    @classmethod
    def redact(cls, text: str, redaction_level: str = 'standard') -> str:
        """
        Redact PII from text
        
        Levels:
        - 'standard': Partial redaction (show@domain.com → sho***@domain.com)
        - 'strict': Full redaction (show@domain.com → [EMAIL_REDACTED])
        - 'hash': Replace with hash (show@domain.com → [EMAIL_a1b2c3d4])
        """
        redacted = text
        
        for pii_type, (pattern, redactor) in cls.PATTERNS.items():
            if redaction_level == 'strict':
                redacted = re.sub(pattern, f'[{pii_type.upper()}_REDACTED]', redacted)
            elif redaction_level == 'hash':
                def hash_redactor(match):
                    hash_val = hashlib.sha256(match.group(0).encode()).hexdigest()[:8]
                    return f'[{pii_type.upper()}_{hash_val}]'
                redacted = re.sub(pattern, hash_redactor, redacted)
            else:  # standard
                redacted = re.sub(pattern, redactor, redacted)
        
        return redacted
    
    @classmethod
    def redact_log_entry(cls, log_entry: dict, level: str = 'standard') -> dict:
        """Redact PII from entire log entry"""
        redacted = log_entry.copy()
        
        # Redact specific fields
        if 'context' in redacted and isinstance(redacted['context'], dict):
            for key, value in redacted['context'].items():
                if isinstance(value, str):
                    redacted['context'][key] = cls.redact(value, level)
        
        # Mark as redacted
        redacted['metadata'] = redacted.get('metadata', {})
        redacted['metadata']['pii_redacted'] = True
        redacted['metadata']['redaction_level'] = level
        
        return redacted


# Usage in logging pipeline
def log_entry(logger, level: str, message: str, **kwargs):
    """Log entry with automatic PII redaction"""
    
    # Create log entry
    entry = {
        'timestamp': datetime.utcnow().isoformat(),
        'level': level,
        'message': message,
        **kwargs
    }
    
    # Redact PII before storage
    redacted_entry = PIIRedactor.redact_log_entry(entry, level='standard')
    
    # Store to audit logs
    await store_to_audit_logs(redacted_entry)
    
    # Store simplified version to user dashboard (if user-facing)
    if level in ['PROGRESS', 'ERROR']:
        await store_to_user_dashboard({
            'request_id': entry.get('request_id'),
            'user_id': entry.get('user_id'),
            'status': entry.get('progress', {}).get('status'),
            'message': PIIRedactor.redact(message, level='strict')
        })
```

**Example Redaction:**

```json
// BEFORE Redaction (Never stored like this)
{
  "message": "Sending email to lance.richardson@example.com from user phone 555-123-4567",
  "context": {
    "recipient": "lance.richardson@example.com",
    "phone": "555-123-4567",
    "api_key": "sk_live_51HqJ8FK2eZvKYlo2C9XQJ8xK3zN"
  }
}

// AFTER Redaction (What gets stored)
{
  "message": "Sending email to lan***@example.com from user phone XXX-XXX-4567",
  "context": {
    "recipient": "lan***@example.com",
    "phone": "XXX-XXX-4567",
    "api_key": "sk_live_5***REDACTED***"
  },
  "metadata": {
    "pii_redacted": true,
    "redaction_level": "standard"
  }
}
```

---

### **Access Control & Permissions**

#### **Role-Based Access Control (RBAC)**

```python
from enum import Enum
from typing import List, Optional

class Role(Enum):
    USER = "user"
    SUPPORT = "support"
    ADMIN = "admin"
    COMPLIANCE = "compliance"
    SYSTEM = "system"

class Permission(Enum):
    VIEW_OWN_REQUESTS = "view_own_requests"
    VIEW_OWN_LOGS = "view_own_logs"
    VIEW_ALL_REQUESTS = "view_all_requests"
    VIEW_AUDIT_LOGS = "view_audit_logs"
    VIEW_PII = "view_pii"
    EXPORT_LOGS = "export_logs"
    DELETE_LOGS = "delete_logs"
    ACCESS_ANALYTICS = "access_analytics"

# Permission matrix
ROLE_PERMISSIONS = {
    Role.USER: [
        Permission.VIEW_OWN_REQUESTS,
        Permission.VIEW_OWN_LOGS,
        Permission.EXPORT_LOGS  # Own data only
    ],
    Role.SUPPORT: [
        Permission.VIEW_OWN_REQUESTS,
        Permission.VIEW_OWN_LOGS,
        Permission.VIEW_ALL_REQUESTS,  # All users, redacted
        Permission.VIEW_AUDIT_LOGS,  # Read-only, redacted
        Permission.ACCESS_ANALYTICS
    ],
    Role.ADMIN: [
        Permission.VIEW_OWN_REQUESTS,
        Permission.VIEW_OWN_LOGS,
        Permission.VIEW_ALL_REQUESTS,
        Permission.VIEW_AUDIT_LOGS,
        Permission.ACCESS_ANALYTICS,
        Permission.EXPORT_LOGS  # System-wide
    ],
    Role.COMPLIANCE: [
        Permission.VIEW_ALL_REQUESTS,
        Permission.VIEW_AUDIT_LOGS,
        Permission.VIEW_PII,  # With justification
        Permission.EXPORT_LOGS
    ],
    Role.SYSTEM: [
        # System processes (automated monitoring)
        Permission.VIEW_AUDIT_LOGS,
        Permission.ACCESS_ANALYTICS
    ]
}


class AccessControl:
    """Enforce access control for log viewing"""
    
    @staticmethod
    async def can_access_request(
        user_id: str,
        user_role: Role,
        request_id: str
    ) -> bool:
        """Check if user can access a specific request"""
        
        # Get request details
        request = await db.get_request(request_id)
        
        # Users can always see their own requests
        if request['user_id'] == user_id:
            return True
        
        # Support/Admin can see all requests (with redaction)
        if user_role in [Role.SUPPORT, Role.ADMIN, Role.COMPLIANCE]:
            await audit_log_access(
                accessed_by=user_id,
                accessed_resource=request_id,
                reason="support_debugging"
            )
            return True
        
        return False
    
    @staticmethod
    async def get_logs_for_request(
        user_id: str,
        user_role: Role,
        request_id: str,
        include_pii: bool = False
    ) -> List[dict]:
        """Get logs with appropriate access control"""
        
        # Check permission
        if not await AccessControl.can_access_request(user_id, user_role, request_id):
            raise PermissionError("Access denied")
        
        # Get request owner
        request = await db.get_request(request_id)
        is_own_request = (request['user_id'] == user_id)
        
        if is_own_request:
            # User viewing their own data
            # Return simplified dashboard logs only
            return await db.get_user_dashboard_logs(request_id)
        
        elif user_role in [Role.SUPPORT, Role.ADMIN]:
            # Support viewing other user's data
            # Return full audit logs but PII redacted
            logs = await db.get_audit_logs(request_id)
            
            # Audit the access
            await audit_log_access(
                accessed_by=user_id,
                accessed_resource=request_id,
                accessed_user=request['user_id'],
                reason="support_debugging",
                timestamp=datetime.utcnow()
            )
            
            # Redact PII unless explicitly allowed
            if not include_pii or Permission.VIEW_PII not in ROLE_PERMISSIONS[user_role]:
                logs = [PIIRedactor.redact_log_entry(log, 'strict') for log in logs]
            
            return logs
        
        elif user_role == Role.COMPLIANCE and include_pii:
            # Compliance with PII access (requires justification)
            justification = await require_access_justification(user_id)
            
            if not justification:
                raise PermissionError("PII access requires justification")
            
            # Log PII access
            await audit_pii_access(
                accessed_by=user_id,
                accessed_resource=request_id,
                justification=justification,
                timestamp=datetime.utcnow()
            )
            
            # Return full logs with PII
            return await db.get_audit_logs(request_id, include_pii=True)
        
        raise PermissionError("Insufficient permissions")
```

---

### **Audit Trail: Logging the Loggers**

**Every access to audit logs is itself logged:**

```python
async def audit_log_access(
    accessed_by: str,
    accessed_resource: str,
    accessed_user: Optional[str] = None,
    reason: str = None,
    timestamp: datetime = None
):
    """
    Log every access to audit logs
    
    This creates an immutable audit trail of who accessed what
    """
    await db.execute("""
        INSERT INTO access_audit_log (
            accessed_by,
            accessed_resource,
            accessed_user,
            reason,
            timestamp,
            ip_address,
            user_agent
        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
    """, (
        accessed_by,
        accessed_resource,
        accessed_user,
        reason,
        timestamp or datetime.utcnow(),
        get_client_ip(),
        get_user_agent()
    ))
    
    # Alert if sensitive access
    if accessed_user and accessed_by != accessed_user:
        await alert_security_team(
            f"User {accessed_by} accessed logs for user {accessed_user}",
            severity="info"
        )


async def audit_pii_access(
    accessed_by: str,
    accessed_resource: str,
    justification: str,
    timestamp: datetime
):
    """
    Special audit for PII access (higher scrutiny)
    """
    await db.execute("""
        INSERT INTO pii_access_log (
            accessed_by,
            accessed_resource,
            justification,
            timestamp,
            approved_by
        ) VALUES ($1, $2, $3, $4, $5)
    """, (
        accessed_by,
        accessed_resource,
        justification,
        timestamp,
        await get_approval_chain(accessed_by)
    ))
    
    # Alert security team
    await alert_security_team(
        f"PII ACCESS: {accessed_by} viewed PII for {accessed_resource}",
        severity="high",
        justification=justification
    )
```

**Access Audit Log:**
```sql
CREATE TABLE access_audit_log (
    id BIGSERIAL PRIMARY KEY,
    accessed_by VARCHAR(100) NOT NULL,  -- Who accessed
    accessed_resource VARCHAR(100) NOT NULL,  -- What they accessed
    accessed_user VARCHAR(100),  -- Whose data (if different)
    reason TEXT,  -- Why they accessed it
    timestamp TIMESTAMP NOT NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,
    
    -- Immutable
    CONSTRAINT no_delete CHECK (false)  -- Prevent deletion
);

-- Grant only INSERT permission
GRANT INSERT ON access_audit_log TO support_team;
REVOKE DELETE, UPDATE ON access_audit_log FROM support_team;
```

---

### **Data Retention & Deletion**

#### **User Dashboard (Simplified Logs)**

```python
# Retention policy
USER_DASHBOARD_RETENTION = {
    'active_requests': 30,  # days
    'completed_requests': 90,  # days
    'failed_requests': 90  # days
}

async def cleanup_user_dashboard():
    """Clean up old user dashboard entries"""
    cutoff = datetime.utcnow() - timedelta(days=USER_DASHBOARD_RETENTION['completed_requests'])
    
    # Soft delete (keep for compliance)
    await db.execute("""
        UPDATE user_requests
        SET deleted_at = NOW(),
            user_visible = FALSE
        WHERE timestamp < $1
          AND deleted_at IS NULL
    """, (cutoff,))
```

#### **Audit Logs (Complete Logs)**

```python
# Retention policy (compliance-driven)
AUDIT_LOG_RETENTION = {
    'hot_storage': 30,  # days - Fast access
    'warm_storage': 365,  # days - Compressed
    'cold_storage': 2555,  # days (7 years) - Archived
    'permanent_deletion': 2920  # days (8 years) - Legal minimum
}

async def archive_audit_logs():
    """Move old logs to cold storage"""
    
    # Move to warm storage (compressed)
    warm_cutoff = datetime.utcnow() - timedelta(days=AUDIT_LOG_RETENTION['hot_storage'])
    await compress_and_move_to_warm_storage(warm_cutoff)
    
    # Move to cold storage (encrypted archive)
    cold_cutoff = datetime.utcnow() - timedelta(days=AUDIT_LOG_RETENTION['warm_storage'])
    await encrypt_and_move_to_cold_storage(cold_cutoff)
    
    # Permanent deletion (after legal retention period)
    deletion_cutoff = datetime.utcnow() - timedelta(days=AUDIT_LOG_RETENTION['permanent_deletion'])
    await securely_delete_logs(deletion_cutoff)
```

---

### **User Rights: GDPR & Privacy Compliance**

#### **Right to Access (Subject Access Request)**

```python
@router.post("/privacy/export-my-data")
async def export_user_data(user_id: str):
    """
    GDPR Right to Access: User can export all their data
    """
    
    # Collect all user data
    data_export = {
        'user_id': user_id,
        'export_date': datetime.utcnow().isoformat(),
        'threads': await db.get_user_threads(user_id),
        'requests': await db.get_user_requests(user_id, days=365),
        'conversations': await db.get_user_conversations(user_id)
    }
    
    # Generate export file (JSON)
    export_file = f"user_data_export_{user_id}_{datetime.utcnow().strftime('%Y%m%d')}.json"
    
    # Audit the export
    await audit_log_access(
        accessed_by=user_id,
        accessed_resource=user_id,
        reason="user_data_export",
        timestamp=datetime.utcnow()
    )
    
    return export_file
```

#### **Right to Erasure ("Right to be Forgotten")**

```python
@router.post("/privacy/delete-my-data")
async def delete_user_data(user_id: str, confirmation: str):
    """
    GDPR Right to Erasure: User can request data deletion
    
    Note: Audit logs are retained for compliance but anonymized
    """
    
    if confirmation != "I CONFIRM DELETION":
        raise ValueError("Confirmation required")
    
    # 1. Delete user-facing data immediately
    await db.execute("""
        UPDATE user_requests
        SET deleted_at = NOW(),
            user_visible = FALSE,
            user_input = '[DELETED]',
            error_message = '[DELETED]'
        WHERE user_id = $1
    """, (user_id,))
    
    # 2. Anonymize audit logs (keep for compliance, remove PII)
    await db.execute("""
        UPDATE audit_logs
        SET user_id_hash = 'ANONYMIZED',
            context = jsonb_set(context, '{user_input}', '"[DELETED]"'),
            pii_redacted = TRUE
        WHERE user_id_hash = $1
    """, (hash_user_id(user_id),))
    
    # 3. Delete threads
    await db.execute("""
        DELETE FROM threads WHERE user_id = $1
    """, (user_id,))
    
    # 4. Audit the deletion
    await audit_log_access(
        accessed_by=user_id,
        accessed_resource=user_id,
        reason="user_data_deletion_gdpr",
        timestamp=datetime.utcnow()
    )
    
    return {"status": "deleted", "message": "Your data has been deleted"}
```

---

## 📊 Data Retention & Access

### **Summary Table**

| Data Type | Storage | Retention | User Access | Admin Access | PII |
|-----------|---------|-----------|-------------|--------------|-----|
| **User Dashboard Logs** | PostgreSQL | 90 days | ✅ Own data only | ✅ All users (redacted) | ❌ Redacted |
| **Audit Logs (Hot)** | PostgreSQL | 30 days | ❌ Never | ✅ Full access | ⚠️ Redacted |
| **Audit Logs (Warm)** | Compressed files | 365 days | ❌ Never | ✅ With justification | ⚠️ Redacted |
| **Audit Logs (Cold)** | S3/Archive | 7 years | ❌ Never | ⚠️ Compliance only | ⚠️ Redacted |
| **Access Audit Trail** | PostgreSQL | Permanent | ❌ Never | ✅ Read-only | ❌ None |
| **PII Access Log** | PostgreSQL | Permanent | ❌ Never | ✅ Read-only | ⚠️ Minimal |

---

## 🔒 Security Best Practices

### **1. Encryption**

```python
# At Rest: Encrypt sensitive log data
from cryptography.fernet import Fernet

class LogEncryption:
    """Encrypt sensitive log fields at rest"""
    
    def __init__(self, key_id: str):
        self.key = self._get_encryption_key(key_id)
        self.cipher = Fernet(self.key)
    
    def encrypt_field(self, value: str) -> str:
        """Encrypt a log field"""
        return self.cipher.encrypt(value.encode()).decode()
    
    def decrypt_field(self, encrypted_value: str) -> str:
        """Decrypt a log field (admin only)"""
        return self.cipher.decrypt(encrypted_value.encode()).decode()


# In Transit: Use TLS 1.3 for all API calls
# Database connections: Use SSL/TLS
# File storage: Use AES-256 encryption
```

### **2. Rate Limiting & Abuse Prevention**

```python
from fastapi import HTTPException
from datetime import datetime, timedelta

class RateLimiter:
    """Prevent log access abuse"""
    
    MAX_REQUESTS_PER_MINUTE = 60
    MAX_LOGS_PER_REQUEST = 1000
    
    @staticmethod
    async def check_rate_limit(user_id: str, endpoint: str):
        """Enforce rate limits on log access"""
        
        # Check request count
        count = await redis.get(f"rate_limit:{user_id}:{endpoint}")
        
        if count and int(count) > RateLimiter.MAX_REQUESTS_PER_MINUTE:
            # Alert security team
            await alert_security_team(
                f"Rate limit exceeded: {user_id} on {endpoint}",
                severity="medium"
            )
            raise HTTPException(429, "Rate limit exceeded")
        
        # Increment counter
        await redis.incr(f"rate_limit:{user_id}:{endpoint}")
        await redis.expire(f"rate_limit:{user_id}:{endpoint}", 60)
```

### **3. Anomaly Detection**

```python
async def detect_suspicious_access():
    """Detect suspicious log access patterns"""
    
    # Check for unusual patterns
    suspicious_patterns = await db.query("""
        SELECT accessed_by, COUNT(*) as access_count
        FROM access_audit_log
        WHERE timestamp > NOW() - INTERVAL '1 hour'
        GROUP BY accessed_by
        HAVING COUNT(*) > 100  -- Unusual volume
    """)
    
    for pattern in suspicious_patterns:
        await alert_security_team(
            f"Suspicious access pattern detected: {pattern['accessed_by']}",
            severity="high",
            details=pattern
        )
```

### **4. Principle of Least Privilege**

```yaml
# Example IAM policy (AWS-style)
LogAccessPolicy:
  Statement:
    - Effect: Allow
      Principal: 
        Role: SupportTeam
      Action:
        - logs:Read
        - logs:Search
      Resource: 
        - arn:aws:logs:*:*:log-group:/app/audit-logs/*
      Condition:
        StringEquals:
          logs:PIIRedacted: true
    
    - Effect: Deny
      Principal:
        Role: SupportTeam
      Action:
        - logs:Delete
        - logs:Modify
      Resource: "*"
    
    - Effect: Allow
      Principal:
        Role: ComplianceOfficer
      Action:
        - logs:ReadWithPII
      Resource: "*"
      Condition:
        RequiresMFA: true
        RequiresJustification: true
```

---

## 🎯 Final Recommendation

**Implement this tiered approach:**

### **Tier 1: Basic User (95% of users)**
- Request History Dashboard
- Simple status indicators
- Click for 7-step timeline
- User-friendly errors

### **Tier 2: Power User (4% of users)**
- Thread conversation view
- Export capabilities
- Search and filters
- Performance metrics

### **Tier 3: Admin/Support (1% of users)**
- Full internal logs access
- Request ID search
- Cross-user querying
- Raw log download

This gives users what they need without overwhelming them with technical details. The `request_id` serves as the bridge between user-facing simplicity and internal debugging complexity.
