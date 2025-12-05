# Comprehensive Logging System Proposal
## Multi-Agent AI System with Supervisor Architecture

**Date:** November 28, 2025  
**System:** Ai-Agents (Supervisor + Gmail + GDrive + GDocs + Calendar + Sheets + Mapping)  
**Version:** 1.0

---

## 📋 Executive Summary

This proposal outlines a comprehensive, production-grade logging system for the entire AI Agents ecosystem. The system consists of:
- **1 Supervisor Agent** (orchestration & conversation management)
- **6 Specialized Agents** (Gmail, GDrive, GDocs, Calendar, Sheets, Mapping)
- **Multi-tier execution flow** (Tier 0 → 0.5 → Full Analysis → Execution)

### Key Objectives
1. **Full traceability** of user requests from entry to completion
2. **Real-time progress tracking** for user feedback
3. **Structured error handling** with context preservation
4. **Performance monitoring** across all agents
5. **Debug capabilities** for development and troubleshooting
6. **Audit trail** for compliance and security
7. **PII protection** with automatic redaction of sensitive data
8. **Cost optimization** through intelligent sampling and retention policies

---

## 🏗️ System Architecture Overview

```
User Request
    ↓
┌───────────────────────────────────────────────────────┐
│ SUPERVISOR AGENT (Port: 8000)                         │
│ ┌─────────────────────────────────────────────────┐   │
│ │ Conversational Agent                            │   │
│ │ - Tier 0: Quick Pattern Checks                  │   │
│ │ - Tier 0.5: Unified LLM Classification          │   │
│ │ - Full Analysis: LLM with capabilities          │   │
│ │ - Conversation Memory Manager                   │   │
│ │ - Thread Manager (SQLite persistence)           │   │
│ └─────────────────────────────────────────────────┘   │
│                                                       │
│ ┌─────────────────────────────────────────────────┐   │
│ │ Supervisor Orchestrator                         │   │
│ │ - Plan Generation (LLM)                         │   │
│ │ - Variable Substitution (Jinja2)                │   │
│ │ - Step-by-step Execution                        │   │
│ │ - Context Management                            │   │
│ │ - Approval System (risk-based)                  │   │
│ └─────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────────────────────┐
│ SPECIALIZED AGENTS (Microservices via HTTP)              │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │
│ │  Gmail   │ │  GDrive  │ │  GDocs   │ │ Calendar │      │
│ │ (5050)   │ │ (5000)   │ │ (5051)   │ │ (5052)   │      │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘      │
│ ┌──────────┐ ┌──────────┐                                │
│ │  Sheets  │ │ Mapping  │                                │
│ │ (5053)   │ │ (5054)   │                                │
│ └──────────┘ └──────────┘                                │
└──────────────────────────────────────────────────────────┘
```

---

## 📊 Logging Architecture

### 1. Centralized Logging Structure

```python
# Logging Levels:
# - DEBUG: Detailed diagnostic information (development only)
# - INFO: General informational messages (always enabled)
# - PROGRESS: User-facing progress updates (NEW - always enabled)
# - WARNING: Warning messages (recoverable issues, always enabled)
# - ERROR: Error messages (operation failures, always enabled)
# - CRITICAL: Critical failures (system-level issues, always enabled + alerts)

# Log Sampling:
# - High-frequency logs (>100/sec) should be sampled to avoid storage overflow
# - Errors and critical logs are NEVER sampled
# - Progress logs are always sent (user-facing)
```

### 2. Log Entry Schema

```json
{
  "timestamp": "2025-11-28T14:23:45.123456Z",
  "level": "INFO|DEBUG|WARNING|ERROR|CRITICAL|PROGRESS",
  "component": "supervisor|gmail|gdrive|gdocs|calendar|sheets|mapping",
  "module": "conversational_agent|supervisor_agent|orchestrator|api|tools",
  "function": "process_message|supervisor_node|orchestrator_node|execute_task",
  "request_id": "req_abc123xyz",
  "conversation_id": "conv_user123_20251128",
  "thread_id": "thread_xyz789",
  "user_id": "user_123",
  "correlation_id": "corr_xyz789abc",  // Links related operations across agents
  "parent_request_id": "req_parent123",  // For multi-step workflows
  
  "message": "Human-readable log message",
  
  "context": {
    "user_input": "Original user request",
    "step_number": 1,
    "total_steps": 3,
    "agent": "gmail_agent",
    "tool": "search_emails",
    "inputs": {...},
    "outputs": {...}
  },
  
  "progress": {
    "status": "started|in_progress|completed|failed|pending_approval",
    "percentage": 33,
    "current_step": "Step 1/3: Searching emails",
    "estimated_time_remaining": "2s"
  },
  
  "performance": {
    "execution_time_ms": 1234,
    "llm_calls": 1,
    "llm_tokens": {"prompt": 500, "completion": 200},
    "agent_calls": 1,
    "retry_count": 0
  },
  
  "error": {
    "error_type": "HttpError|ValidationError|TimeoutError",
    "error_message": "Detailed error message",
    "stack_trace": "Full stack trace",
    "recovery_action": "Retrying with backoff"
  },
  
  "metadata": {
    "tier": "tier_0|tier_0.5|full_analysis|execution",
    "intent": "send_email|search_emails|create_doc",
    "risk_level": "safe|moderate|dangerous|critical",
    "requires_approval": false,
    "action_id": "action_abc123",
    "environment": "development|staging|production",
    "version": "1.0.0",
    "contains_pii": false,  // Flag for logs with personally identifiable information
    "sampling_rate": 1.0  // 1.0 = 100% logged, 0.1 = 10% sampled
  }
}
```

---

## 🔒 Security & Privacy Considerations

### 1. PII Redaction

All logs must automatically redact personally identifiable information:

```python
PII_PATTERNS = {
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
    "ip_address": r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"
}

def redact_pii(text: str) -> str:
    """Redact PII from log messages"""
    for pii_type, pattern in PII_PATTERNS.items():
        text = re.sub(pattern, f"[REDACTED_{pii_type.upper()}]", text)
    return text
```

**Example:**
```json
{
  "message": "Email sent to [REDACTED_EMAIL]",
  "context": {
    "to": "[REDACTED_EMAIL]",
    "subject": "Weekly Report"
  },
  "metadata": {
    "contains_pii": true
  }
}
```

### 2. Sensitive Data Handling

**Never log:**
- OAuth tokens or API keys
- Passwords or credentials
- Full email/document content (log summaries instead)
- Complete file contents (log metadata only)

**Partial logging:**
- Email subjects: First 50 characters only
- File names: Redact user-specific paths
- Document IDs: First 8 characters only (for debugging)

### 3. Access Control

```python
LOG_ACCESS_LEVELS = {
    "DEBUG": ["developer", "admin"],
    "INFO": ["developer", "admin"],
    "PROGRESS": ["all"],  # User-facing
    "WARNING": ["developer", "admin"],
    "ERROR": ["developer", "admin"],
    "CRITICAL": ["all"]  # Alert everyone
}
```

### 4. Compliance Requirements

- **GDPR**: User data retention limited to 30 days
- **HIPAA**: Healthcare-related logs encrypted at rest
- **SOC 2**: Audit trail for all data access
- **CCPA**: User right to request log deletion

---

## 🎯 Component-Specific Logging Requirements

### 1. Supervisor Agent - Conversational Agent

#### A. Tier 0: Quick Pattern Checks
```python
# Log Entry: Greeting Detection
{
  "level": "PROGRESS",
  "component": "supervisor",
  "module": "conversational_agent",
  "function": "_quick_greeting_check",
  "message": "Greeting detected - instant response (0 tokens)",
  "metadata": {
    "tier": "tier_0",
    "tokens_saved": 0,
    "intent": "greeting"
  }
}

# Log Entry: Repeat Request
{
  "level": "PROGRESS",
  "component": "supervisor",
  "module": "conversational_agent",
  "function": "_quick_repeat_check",
  "message": "Repeat request detected - retrieving last response",
  "metadata": {
    "tier": "tier_0",
    "tokens_saved": 0
  }
}

# Log Entry: Capabilities Query
{
  "level": "PROGRESS",
  "component": "supervisor",
  "module": "conversational_agent",
  "function": "_quick_capabilities_check",
  "message": "Capabilities request - returning cached list (0 tokens)",
  "metadata": {
    "tier": "tier_0",
    "query_scope": "general|specific",
    "agents_shown": ["gmail", "docs"]
  }
}
```

#### B. Tier 0.5: Unified LLM Classification
```python
# Log Entry: Quick Classification
{
  "level": "INFO",
  "component": "supervisor",
  "module": "conversational_agent",
  "function": "_unified_quick_check",
  "message": "Unified LLM classification completed",
  "context": {
    "category": "task|confirm|cancel|modify|answer|casual|unclear|template_upload",
    "is_task": true,
    "next_action": "full_analysis|quick_confirm|cancel_request"
  },
  "performance": {
    "execution_time_ms": 250,
    "llm_tokens": {"prompt": 150, "completion": 50}
  },
  "metadata": {
    "tier": "tier_0.5"
  }
}

# Log Entry: Field Modification
{
  "level": "PROGRESS",
  "component": "supervisor",
  "module": "conversational_agent",
  "function": "_unified_quick_check",
  "message": "Field modification detected and applied",
  "context": {
    "modified_field": "subject",
    "old_value": "Meeting",
    "new_value": "Team Sync Meeting"
  },
  "metadata": {
    "tier": "tier_0.5"
  }
}
```

#### C. Full Analysis
```python
# Log Entry: Full Task Analysis Start
{
  "level": "INFO",
  "component": "supervisor",
  "module": "conversational_agent",
  "function": "_full_task_analysis",
  "message": "Starting full task analysis with capabilities",
  "context": {
    "relevant_agents": ["gmail_agent", "docs_agent"],
    "capabilities_filtered": true,
    "query_scope": "specific"
  },
  "metadata": {
    "tier": "full_analysis"
  }
}

# Log Entry: Analysis Result
{
  "level": "PROGRESS",
  "component": "supervisor",
  "module": "conversational_agent",
  "function": "_full_task_analysis",
  "message": "Task analysis completed",
  "context": {
    "intent": "ready_to_execute|needs_clarification|not_feasible",
    "task_type": "send_email",
    "extracted_info": {...},
    "missing_fields": ["recipient"],
    "execution_ready": false
  },
  "performance": {
    "execution_time_ms": 2500,
    "llm_tokens": {"prompt": 1500, "completion": 300}
  },
  "metadata": {
    "tier": "full_analysis"
  }
}
```

#### D. Memory Management
```python
# Log Entry: Memory Summarization
{
  "level": "DEBUG",
  "component": "supervisor",
  "module": "conversation_memory",
  "function": "add_message",
  "message": "Conversation memory summarized - token limit exceeded",
  "context": {
    "messages_summarized": 10,
    "tokens_before": 2500,
    "tokens_after": 800,
    "tokens_saved": 1700
  },
  "performance": {
    "execution_time_ms": 1200,
    "llm_tokens": {"prompt": 2500, "completion": 200}
  }
}

# Log Entry: Entity Extraction
{
  "level": "DEBUG",
  "component": "supervisor",
  "module": "conversation_memory",
  "function": "_extract_entities",
  "message": "Entities extracted from conversation",
  "context": {
    "entities": {
      "people": ["john@example.com", "Sarah"],
      "dates": ["2025-11-28"],
      "tasks": ["send email", "create document"]
    }
  }
}
```

#### E. Thread Management
```python
# Log Entry: Thread Creation
{
  "level": "INFO",
  "component": "supervisor",
  "module": "thread_manager",
  "function": "create_thread",
  "message": "New conversation thread created",
  "context": {
    "thread_id": "thread_xyz789",
    "user_id": "user_123",
    "title": "Send weekly report email"
  }
}

# Log Entry: Thread Load
{
  "level": "INFO",
  "component": "supervisor",
  "module": "thread_manager",
  "function": "get_thread",
  "message": "Thread loaded from database",
  "context": {
    "thread_id": "thread_xyz789",
    "message_count": 5,
    "last_updated": "2025-11-28T14:20:00Z"
  },
  "performance": {
    "execution_time_ms": 50
  }
}
```

---

### 2. Supervisor Agent - Orchestrator

#### A. Plan Generation
```python
# Log Entry: Plan Generation Start
{
  "level": "INFO",
  "component": "supervisor",
  "module": "supervisor_agent",
  "function": "supervisor_node",
  "message": "Generating execution plan",
  "context": {
    "user_input": "Send email to lance with yesterday's data",
    "relevant_agents": ["gmail_agent", "sheets_agent"],
    "context_variables": {
      "today_date": "2025-11-28",
      "yesterday_date": "2025-11-27"
    }
  }
}

# Log Entry: Plan Generated
{
  "level": "PROGRESS",
  "component": "supervisor",
  "module": "supervisor_agent",
  "function": "supervisor_node",
  "message": "Execution plan generated successfully",
  "context": {
    "plan_steps": 3,
    "agents_involved": ["sheets_agent", "gmail_agent"],
    "estimated_duration": "5-10 seconds"
  },
  "progress": {
    "status": "completed",
    "percentage": 20,
    "current_step": "Plan generated"
  },
  "performance": {
    "execution_time_ms": 3000,
    "llm_tokens": {"prompt": 2000, "completion": 500}
  }
}
```

#### B. Orchestrator Execution
```python
# Log Entry: Step Start
{
  "level": "PROGRESS",
  "component": "supervisor",
  "module": "supervisor_agent",
  "function": "orchestrator_node",
  "message": "Executing step",
  "context": {
    "step_number": 1,
    "total_steps": 3,
    "agent": "sheets_agent",
    "tool": "get_sheet_data",
    "description": "Fetch yesterday's data from spreadsheet",
    "inputs": {
      "sheet_id": "abc123",
      "date_filter": "2025-11-27"
    }
  },
  "progress": {
    "status": "in_progress",
    "percentage": 33,
    "current_step": "Step 1/3: Fetching data from spreadsheet"
  }
}

# Log Entry: Variable Substitution
{
  "level": "DEBUG",
  "component": "supervisor",
  "module": "supervisor_agent",
  "function": "orchestrator_node",
  "message": "Variable substitution completed",
  "context": {
    "step_number": 2,
    "original_inputs": {
      "to": "{{ recipient_email }}",
      "date": "{{ yesterday_date }}"
    },
    "substituted_inputs": {
      "to": "lance@example.com",
      "date": "2025-11-27"
    },
    "context_variables_used": ["recipient_email", "yesterday_date"]
  }
}

# Log Entry: Agent Call with Retry
{
  "level": "INFO",
  "component": "supervisor",
  "module": "utils",
  "function": "call_agent_with_retry",
  "message": "Calling agent microservice",
  "context": {
    "agent_url": "http://localhost:5053/execute_task",
    "agent": "sheets_agent",
    "tool": "get_sheet_data",
    "attempt": 1,
    "max_retries": 3,
    "timeout": 320
  }
}

# Log Entry: Retry Attempt
{
  "level": "WARNING",
  "component": "supervisor",
  "module": "utils",
  "function": "call_agent_with_retry",
  "message": "Agent call failed, retrying with backoff",
  "context": {
    "attempt": 2,
    "max_retries": 3,
    "backoff_delay": 4.0,
    "next_retry_at": "2025-11-28T14:24:00Z"
  },
  "error": {
    "error_type": "TimeoutError",
    "error_message": "Request timeout after 320s",
    "retry_strategy": "exponential_backoff",
    "recoverable": true
  }
}

# Log Entry: Step Success
{
  "level": "PROGRESS",
  "component": "supervisor",
  "module": "supervisor_agent",
  "function": "orchestrator_node",
  "message": "Step completed successfully",
  "context": {
    "step_number": 1,
    "total_steps": 3,
    "agent": "sheets_agent",
    "tool": "get_sheet_data",
    "output_variables_extracted": ["sheet_data", "row_count"]
  },
  "progress": {
    "status": "completed",
    "percentage": 53,
    "current_step": "Step 1/3 completed: Data fetched (150 rows)"
  },
  "performance": {
    "execution_time_ms": 2345
  }
}

# Log Entry: No Results (Graceful)
{
  "level": "WARNING",
  "component": "supervisor",
  "module": "supervisor_agent",
  "function": "orchestrator_node",
  "message": "Step returned no results but continuing",
  "context": {
    "step_number": 1,
    "agent": "gmail_agent",
    "tool": "search_emails",
    "inputs": {
      "query": "from:nonexistent@example.com"
    }
  },
  "progress": {
    "status": "completed",
    "percentage": 33,
    "current_step": "Step 1/3: No matching emails found"
  }
}

# Log Entry: Step Error (Stop Execution)
{
  "level": "ERROR",
  "component": "supervisor",
  "module": "supervisor_agent",
  "function": "orchestrator_node",
  "message": "Step failed - stopping workflow",
  "context": {
    "step_number": 2,
    "total_steps": 3,
    "agent": "gmail_agent",
    "tool": "send_email",
    "completed_steps": 1,
    "failed_at_step": 2
  },
  "progress": {
    "status": "failed",
    "percentage": 66,
    "current_step": "Step 2/3 failed: Email send error"
  },
  "error": {
    "error_type": "HttpError",
    "error_message": "Gmail API error: Invalid recipient",
    "recovery_action": "Workflow stopped"
  }
}
```

#### C. Approval System
```python
# Log Entry: Approval Required
{
  "level": "WARNING",
  "component": "supervisor",
  "module": "supervisor_agent",
  "function": "orchestrator_node",
  "message": "Action requires user approval",
  "context": {
    "action_id": "action_abc123",
    "step_number": 2,
    "agent": "gmail_agent",
    "tool": "send_draft_email",
    "inputs": {
      "draft_id": "draft_xyz789"
    }
  },
  "progress": {
    "status": "pending_approval",
    "percentage": 50,
    "current_step": "Awaiting approval to send email"
  },
  "metadata": {
    "risk_level": "moderate",
    "approval_endpoint": "/action/approve/action_abc123"
  }
}

# Log Entry: Approval Granted
{
  "level": "INFO",
  "component": "supervisor",
  "module": "supervisor_agent",
  "function": "approve_action",
  "message": "Action approved by user",
  "context": {
    "action_id": "action_abc123",
    "approved_at": "2025-11-28T14:25:00Z"
  }
}
```

---

### 3. Gmail Agent

```python
# Log Entry: Tool Execution Start
{
  "level": "INFO",
  "component": "gmail",
  "module": "api",
  "function": "execute_task",
  "message": "Gmail agent task execution started",
  "context": {
    "tool": "search_emails",
    "inputs": {
      "query": "from:lance@example.com",
      "max_results": 10
    }
  }
}

# Log Entry: Gmail API Call
{
  "level": "DEBUG",
  "component": "gmail",
  "module": "tools",
  "function": "_search_emails_impl",
  "message": "Calling Gmail API",
  "context": {
    "method": "users().messages().list()",
    "query": "from:lance@example.com",
    "max_results": 10
  }
}

# Log Entry: Success with Results
{
  "level": "INFO",
  "component": "gmail",
  "module": "tools",
  "function": "_search_emails_impl",
  "message": "Emails retrieved successfully",
  "context": {
    "emails_found": 5,
    "emails_returned": 5,
    "query": "from:lance@example.com"
  },
  "performance": {
    "execution_time_ms": 1234,
    "api_calls": 6
  }
}

# Log Entry: No Results Found
{
  "level": "WARNING",
  "component": "gmail",
  "module": "tools",
  "function": "_search_emails_impl",
  "message": "No emails found matching query",
  "context": {
    "query": "from:nonexistent@example.com",
    "no_results": true
  }
}

# Log Entry: Email Sent
{
  "level": "INFO",
  "component": "gmail",
  "module": "tools",
  "function": "_send_email_impl",
  "message": "Email sent successfully",
  "context": {
    "to": "lance@example.com",
    "subject": "Weekly Report",
    "message_id": "msg_abc123",
    "thread_id": "thread_xyz789"
  },
  "performance": {
    "execution_time_ms": 890
  }
}

# Log Entry: Draft Created
{
  "level": "INFO",
  "component": "gmail",
  "module": "tools",
  "function": "_create_draft_email_impl",
  "message": "Email draft created",
  "context": {
    "draft_id": "draft_xyz789",
    "to": "lance@example.com",
    "subject": "Weekly Report"
  }
}

# Log Entry: API Error
{
  "level": "ERROR",
  "component": "gmail",
  "module": "tools",
  "function": "_send_email_impl",
  "message": "Gmail API error",
  "error": {
    "error_type": "HttpError",
    "error_message": "Invalid recipient email address",
    "error_code": 400
  }
}
```

---

### 4. Google Drive Agent

```python
# Log Entry: File Upload Start
{
  "level": "INFO",
  "component": "gdrive",
  "module": "api",
  "function": "execute_task",
  "message": "Drive agent task execution started",
  "context": {
    "tool": "upload_file_to_folder",
    "inputs": {
      "file_path": "/tmp/report.xlsx",
      "folder_path": "SafeExpress/Reports"
    }
  }
}

# Log Entry: Folder Creation
{
  "level": "INFO",
  "component": "gdrive",
  "module": "tools",
  "function": "create_nested_folder_impl",
  "message": "Nested folder structure created",
  "context": {
    "folder_path": "SafeExpress/Reports/2025",
    "folder_id": "folder_abc123",
    "folders_created": 1
  },
  "performance": {
    "execution_time_ms": 567
  }
}

# Log Entry: File Upload Success
{
  "level": "INFO",
  "component": "gdrive",
  "module": "tools",
  "function": "upload_file_to_folder_impl",
  "message": "File uploaded successfully",
  "context": {
    "file_name": "report.xlsx",
    "file_id": "file_xyz789",
    "file_url": "https://drive.google.com/file/d/file_xyz789",
    "folder_path": "SafeExpress/Reports/2025",
    "file_size_bytes": 45678
  },
  "performance": {
    "execution_time_ms": 2345,
    "upload_speed_mbps": 15.6
  }
}

# Log Entry: Search Results
{
  "level": "INFO",
  "component": "gdrive",
  "module": "tools",
  "function": "search_files_in_safeexpress_impl",
  "message": "Files found in search",
  "context": {
    "search_query": "report",
    "files_found": 12,
    "folder_searched": "SafeExpress"
  }
}
```

---

### 5. Google Docs Agent

```python
# Log Entry: Document Creation
{
  "level": "INFO",
  "component": "gdocs",
  "module": "tools",
  "function": "_create_google_doc_impl",
  "message": "Google Doc created",
  "context": {
    "title": "Meeting Minutes - Nov 28",
    "document_id": "doc_abc123",
    "document_url": "https://docs.google.com/document/d/doc_abc123/edit"
  },
  "performance": {
    "execution_time_ms": 789
  }
}

# Log Entry: Template Processing
{
  "level": "INFO",
  "component": "gdocs",
  "module": "tools",
  "function": "_extract_template_structure_impl",
  "message": "Template structure extracted",
  "context": {
    "template_id": "doc_template123",
    "placeholders_found": ["[DATE]", "[ATTENDEES]", "[AGENDA]"],
    "formatting_extracted": true
  },
  "performance": {
    "execution_time_ms": 1234
  }
}

# Log Entry: Document from Template
{
  "level": "INFO",
  "component": "gdocs",
  "module": "tools",
  "function": "_create_from_uploaded_template_impl",
  "message": "Document created from template",
  "context": {
    "template_file_id": "file_template123",
    "new_document_id": "doc_new789",
    "placeholders_replaced": 5,
    "output_format": "google_docs"
  },
  "performance": {
    "execution_time_ms": 3456
  }
}

# Log Entry: Document Shared
{
  "level": "INFO",
  "component": "gdocs",
  "module": "tools",
  "function": "_share_google_docs_impl",
  "message": "Document shared successfully",
  "context": {
    "document_id": "doc_abc123",
    "shared_with": "lance@example.com",
    "permission": "writer"
  }
}
```

---

### 6. Calendar Agent

```python
# Log Entry: Event Creation
{
  "level": "INFO",
  "component": "calendar",
  "module": "tools",
  "function": "create_event_impl",
  "message": "Calendar event created",
  "context": {
    "summary": "Team Sync Meeting",
    "start": "2025-11-29T10:00:00",
    "end": "2025-11-29T11:00:00",
    "event_id": "event_abc123",
    "event_url": "https://calendar.google.com/event?eid=event_abc123",
    "attendees": ["john@example.com", "sarah@example.com"],
    "meet_link": "https://meet.google.com/abc-defg-hij"
  },
  "performance": {
    "execution_time_ms": 1234
  }
}

# Log Entry: Past Date Validation Error
{
  "level": "ERROR",
  "component": "calendar",
  "module": "tools",
  "function": "create_event_impl",
  "message": "Cannot schedule event in the past",
  "context": {
    "requested_date": "2025-11-27T10:00:00",
    "current_date": "2025-11-28T14:30:00"
  },
  "error": {
    "error_type": "past_date",
    "error_message": "Cannot schedule events in the past. 'November 27, 2025 at 10:00 AM' has already passed."
  }
}

# Log Entry: Event Search
{
  "level": "INFO",
  "component": "calendar",
  "module": "tools",
  "function": "search_events_impl",
  "message": "Calendar events retrieved",
  "context": {
    "search_query": "meeting",
    "events_found": 5,
    "time_range": "2025-11-28 to 2025-12-05"
  }
}

# Log Entry: Conflict Detection
{
  "level": "WARNING",
  "component": "calendar",
  "module": "tools",
  "function": "check_conflicts",
  "message": "Scheduling conflict detected",
  "context": {
    "requested_time": "2025-11-29T10:00:00",
    "conflicting_events": [
      {
        "summary": "Existing Meeting",
        "start": "2025-11-29T09:30:00",
        "end": "2025-11-29T10:30:00"
      }
    ]
  }
}
```

---

### 7. Sheets Agent

```python
# Log Entry: Spreadsheet Created
{
  "level": "INFO",
  "component": "sheets",
  "module": "sheets_agent_api",
  "function": "create_sheet",
  "message": "Spreadsheet created",
  "context": {
    "title": "SafeXpress Operations - Nov 2025",
    "spreadsheet_id": "sheet_abc123",
    "spreadsheet_url": "https://docs.google.com/spreadsheets/d/sheet_abc123",
    "sheets": ["Operations", "Summary"]
  },
  "performance": {
    "execution_time_ms": 1567
  }
}

# Log Entry: Data Written
{
  "level": "INFO",
  "component": "sheets",
  "module": "sheets_agent_api",
  "function": "write_data_to_sheet",
  "message": "Data written to spreadsheet",
  "context": {
    "spreadsheet_id": "sheet_abc123",
    "sheet_name": "Operations",
    "range": "A1:Z100",
    "rows_written": 100,
    "columns_written": 26
  },
  "performance": {
    "execution_time_ms": 2345
  }
}

# Log Entry: Data Read
{
  "level": "INFO",
  "component": "sheets",
  "module": "sheets_agent_api",
  "function": "read_sheet_data",
  "message": "Data read from spreadsheet",
  "context": {
    "spreadsheet_id": "sheet_abc123",
    "sheet_name": "Operations",
    "range": "A1:Z100",
    "rows_read": 98,
    "columns_read": 26
  }
}
```

---

### 8. Mapping Agent

```python
# Log Entry: File Parsing
{
  "level": "INFO",
  "component": "mapping",
  "module": "mapping_agent_api",
  "function": "parse_file",
  "message": "File parsed successfully",
  "context": {
    "file_type": "xlsx",
    "rows": 150,
    "columns": 12,
    "column_names": ["Date", "Customer", "Amount", ...]
  },
  "performance": {
    "execution_time_ms": 567
  }
}

# Log Entry: Smart Mapping
{
  "level": "INFO",
  "component": "mapping",
  "module": "mapping_agent_api",
  "function": "smart_map_columns",
  "message": "Smart column mapping completed",
  "context": {
    "source_columns": 12,
    "target_columns": 10,
    "mapped_columns": 10,
    "confidence_scores": {
      "Date": 0.95,
      "Customer Name": 0.87,
      "Amount": 0.92
    },
    "mapping_engine": "SmartMappingEngine"
  },
  "performance": {
    "execution_time_ms": 1234,
    "llm_tokens": {"prompt": 500, "completion": 200}
  }
}

# Log Entry: Date Extraction
{
  "level": "INFO",
  "component": "mapping",
  "module": "mapping_agent_api",
  "function": "extract_date",
  "message": "Date extracted from data",
  "context": {
    "date_found": "2025-11-27",
    "format_detected": "YYYY-MM-DD",
    "source": "filename"
  }
}

# Log Entry: Mapping Fallback
{
  "level": "WARNING",
  "component": "mapping",
  "module": "mapping_agent_api",
  "function": "smart_map_columns",
  "message": "Smart mapping unavailable, using fallback",
  "context": {
    "fallback_method": "string_similarity",
    "reason": "SmartMappingEngine not available"
  }
}
```

---

## 🎨 Progress Tracking for Users

### Real-Time Progress Updates

The system should emit **PROGRESS** level logs that can be consumed by the frontend to show:

1. **Current Status**: What's happening now
2. **Progress Percentage**: 0-100%
3. **Current Step**: Human-readable description
4. **Estimated Time**: When available

#### Progress States

```python
PROGRESS_STATES = {
    "started": "Request received and processing started",
    "analyzing": "Analyzing your request...",
    "planning": "Creating execution plan...",
    "executing": "Executing step {step}/{total}...",
    "pending_approval": "Waiting for your approval...",
    "completed": "Task completed successfully",
    "failed": "Task failed at step {step}"
}
```

#### Example Progress Flow

```json
[
  {
    "timestamp": "2025-11-28T14:23:45.123Z",
    "level": "PROGRESS",
    "progress": {
      "status": "started",
      "percentage": 0,
      "current_step": "Request received: Send email with yesterday's data"
    }
  },
  {
    "timestamp": "2025-11-28T14:23:46.456Z",
    "level": "PROGRESS",
    "progress": {
      "status": "analyzing",
      "percentage": 10,
      "current_step": "Analyzing request..."
    }
  },
  {
    "timestamp": "2025-11-28T14:23:48.789Z",
    "level": "PROGRESS",
    "progress": {
      "status": "planning",
      "percentage": 20,
      "current_step": "Creating 3-step execution plan"
    }
  },
  {
    "timestamp": "2025-11-28T14:23:49.012Z",
    "level": "PROGRESS",
    "progress": {
      "status": "executing",
      "percentage": 33,
      "current_step": "Step 1/3: Fetching data from spreadsheet",
      "estimated_time_remaining": "8s"
    }
  },
  {
    "timestamp": "2025-11-28T14:23:52.345Z",
    "level": "PROGRESS",
    "progress": {
      "status": "executing",
      "percentage": 53,
      "current_step": "Step 1/3 completed: 150 rows fetched"
    }
  },
  {
    "timestamp": "2025-11-28T14:23:52.456Z",
    "level": "PROGRESS",
    "progress": {
      "status": "executing",
      "percentage": 56,
      "current_step": "Step 2/3: Creating email draft",
      "estimated_time_remaining": "4s"
    }
  },
  {
    "timestamp": "2025-11-28T14:23:54.789Z",
    "level": "PROGRESS",
    "progress": {
      "status": "pending_approval",
      "percentage": 80,
      "current_step": "Draft created. Review and approve to send."
    }
  },
  {
    "timestamp": "2025-11-28T14:24:30.123Z",
    "level": "PROGRESS",
    "progress": {
      "status": "executing",
      "percentage": 90,
      "current_step": "Step 3/3: Sending email",
      "estimated_time_remaining": "2s"
    }
  },
  {
    "timestamp": "2025-11-28T14:24:32.456Z",
    "level": "PROGRESS",
    "progress": {
      "status": "completed",
      "percentage": 100,
      "current_step": "Email sent successfully to lance@example.com"
    }
  }
]
```

---

## 📊 Advanced Logging Features

### 1. Log Aggregation & Metrics

```python
class LogAggregator:
    """Aggregate logs for metrics and dashboards"""
    
    def __init__(self):
        self.metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "avg_execution_time_ms": 0,
            "error_types": {},
            "agent_call_counts": {}
        }
    
    def process_log(self, log_entry: dict):
        """Process log entry and update metrics"""
        level = log_entry.get("level")
        
        if level == "PROGRESS":
            progress = log_entry.get("progress", {})
            if progress.get("status") == "started":
                self.metrics["total_requests"] += 1
            elif progress.get("status") == "completed":
                self.metrics["successful_requests"] += 1
            elif progress.get("status") == "failed":
                self.metrics["failed_requests"] += 1
        
        if level == "ERROR":
            error_type = log_entry.get("error", {}).get("error_type", "Unknown")
            self.metrics["error_types"][error_type] = \
                self.metrics["error_types"].get(error_type, 0) + 1
        
        # Update execution time
        performance = log_entry.get("performance", {})
        if "execution_time_ms" in performance:
            current_avg = self.metrics["avg_execution_time_ms"]
            new_time = performance["execution_time_ms"]
            self.metrics["avg_execution_time_ms"] = \
                (current_avg + new_time) / 2 if current_avg > 0 else new_time
    
    def get_metrics(self) -> dict:
        """Get current metrics snapshot"""
        return {
            **self.metrics,
            "success_rate": (
                self.metrics["successful_requests"] / 
                max(self.metrics["total_requests"], 1)
            ) * 100,
            "error_rate": (
                self.metrics["failed_requests"] / 
                max(self.metrics["total_requests"], 1)
            ) * 100
        }
```

### 2. Distributed Tracing

Implement OpenTelemetry-compatible tracing:

```python
from opentelemetry import trace
from opentelemetry.trace import SpanKind

class TracingLogger(StructuredLogger):
    """Logger with distributed tracing support"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tracer = trace.get_tracer(__name__)
    
    def log_with_span(self, span_name: str, level: str, message: str, **kwargs):
        """Log with OpenTelemetry span for distributed tracing"""
        with self.tracer.start_as_current_span(
            span_name,
            kind=SpanKind.INTERNAL
        ) as span:
            # Add trace context to log
            span_context = span.get_span_context()
            kwargs['metadata'] = kwargs.get('metadata', {})
            kwargs['metadata']['trace_id'] = format(span_context.trace_id, '032x')
            kwargs['metadata']['span_id'] = format(span_context.span_id, '016x')
            
            # Log using base logger
            getattr(self, level.lower())(message, **kwargs)
            
            # Add log to span attributes
            span.set_attribute("log.level", level)
            span.set_attribute("log.message", message)
```

### 3. Log Search & Analytics

```python
class LogSearchEngine:
    """Advanced log search with filters and analytics"""
    
    def search_logs(
        self,
        filters: dict,
        time_range: tuple,
        aggregations: list = None
    ) -> dict:
        """
        Search logs with complex filters
        
        Example:
        filters = {
            "level": ["ERROR", "CRITICAL"],
            "component": "gmail",
            "error.error_type": "HttpError"
        }
        time_range = ("2025-11-28T00:00:00Z", "2025-11-28T23:59:59Z")
        aggregations = [
            {"field": "error.error_type", "type": "count"},
            {"field": "performance.execution_time_ms", "type": "avg"}
        ]
        """
        results = {
            "hits": [],
            "total": 0,
            "aggregations": {}
        }
        
        # Implementation would query log storage (file/DB/ES)
        # and apply filters, time range, and aggregations
        
        return results
```

---

## 🛠️ Implementation Strategy

### Phase 1: Core Logging Infrastructure (Week 1)

1. **Create Logging Module** (`logging_config.py`)
   - Centralized logger configuration
   - Custom log formatters (JSON, console)
   - Log level management
   - Request ID generation

2. **Create Log Schema** (`log_schema.py`)
   - Pydantic models for log entries
   - Validation and serialization
   - Helper functions for log creation

3. **Storage Backend**
   - File-based logging (rotating files)
   - Optional: SQLite for structured queries
   - Optional: External services (CloudWatch, Elasticsearch)

### Phase 2: Supervisor Integration (Week 1-2)

1. **Conversational Agent**
   - Add logging to all tiers (0, 0.5, full)
   - Memory manager logging
   - Thread manager logging

2. **Supervisor Orchestrator**
   - Plan generation logging
   - Step execution logging
   - Variable substitution logging
   - Error handling logging

3. **Progress Tracking**
   - Implement PROGRESS level logs
   - Add percentage calculations
   - Add time estimations

### Phase 3: Agent Integration (Week 2)

1. **Gmail Agent**
   - Tool execution logging
   - Gmail API call logging
   - Success/failure logging

2. **GDrive Agent**
   - File operation logging
   - Folder management logging

3. **GDocs Agent**
   - Document creation logging
   - Template processing logging

4. **Calendar Agent**
   - Event management logging
   - Validation logging

5. **Sheets Agent**
   - Data operation logging

6. **Mapping Agent**
   - Parsing logging
   - Mapping logging

### Phase 4: Frontend Integration (Week 3)

1. **WebSocket/SSE for Real-Time Updates**
   - Stream PROGRESS logs to frontend
   - Display progress bar
   - Show current step

2. **Log Viewer Dashboard**
   - Search and filter logs
   - View execution history
   - Debug mode toggle

### Phase 5: Monitoring & Alerts (Week 3-4)

1. **Performance Metrics**
   - Average execution time per tool
   - LLM token usage tracking
   - Agent call success rate

2. **Error Alerting**
   - Critical error notifications
   - Retry failure alerts
   - Timeout alerts

3. **Dashboards**
   - Real-time system health
   - Usage statistics
   - Error rate trends

---

## 📝 Code Examples

### 1. Centralized Logging Configuration

```python
# logging_config.py
import logging
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from enum import Enum

class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    PROGRESS = "PROGRESS"  # Custom level for user-facing progress
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class StructuredLogger:
    """
    Centralized structured logger for the entire AI Agents system.
    Emits JSON-formatted logs with consistent schema.
    """
    
    def __init__(
        self, 
        component: str,
        module: str,
        log_file: str = "logs/agent.log",
        enable_console: bool = True
    ):
        self.component = component
        self.module = module
        self.logger = logging.getLogger(f"{component}.{module}")
        self.logger.setLevel(logging.DEBUG)
        
        # Add custom PROGRESS level
        logging.addLevelName(25, "PROGRESS")  # Between INFO (20) and WARNING (30)
        
        # File handler (JSON format)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(JsonFormatter())
        self.logger.addHandler(file_handler)
        
        # Console handler (human-readable)
        if enable_console:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(ConsoleFormatter())
            self.logger.addHandler(console_handler)
    
    def _build_log_entry(
        self,
        level: LogLevel,
        message: str,
        function: str,
        context: Optional[Dict[str, Any]] = None,
        progress: Optional[Dict[str, Any]] = None,
        performance: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build standardized log entry"""
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": level.value,
            "component": self.component,
            "module": self.module,
            "function": function,
            "request_id": request_id or _get_current_request_id(),
            "conversation_id": conversation_id or _get_current_conversation_id(),
            "thread_id": thread_id,
            "user_id": user_id,
            "message": message,
            "context": context or {},
            "progress": progress,
            "performance": performance,
            "error": error,
            "metadata": metadata or {}
        }
    
    def debug(self, message: str, function: str, **kwargs):
        """Log debug message"""
        entry = self._build_log_entry(LogLevel.DEBUG, message, function, **kwargs)
        self.logger.debug(json.dumps(entry))
    
    def info(self, message: str, function: str, **kwargs):
        """Log info message"""
        entry = self._build_log_entry(LogLevel.INFO, message, function, **kwargs)
        self.logger.info(json.dumps(entry))
    
    def progress(self, message: str, function: str, **kwargs):
        """Log progress update (user-facing)"""
        entry = self._build_log_entry(LogLevel.PROGRESS, message, function, **kwargs)
        self.logger.log(25, json.dumps(entry))  # Custom level
    
    def warning(self, message: str, function: str, **kwargs):
        """Log warning message"""
        entry = self._build_log_entry(LogLevel.WARNING, message, function, **kwargs)
        self.logger.warning(json.dumps(entry))
    
    def error(self, message: str, function: str, **kwargs):
        """Log error message"""
        entry = self._build_log_entry(LogLevel.ERROR, message, function, **kwargs)
        self.logger.error(json.dumps(entry))
    
    def critical(self, message: str, function: str, **kwargs):
        """Log critical message"""
        entry = self._build_log_entry(LogLevel.CRITICAL, message, function, **kwargs)
        self.logger.critical(json.dumps(entry))


class JsonFormatter(logging.Formatter):
    """JSON formatter for file logging"""
    def format(self, record):
        return record.getMessage()


class ConsoleFormatter(logging.Formatter):
    """Human-readable formatter for console"""
    def format(self, record):
        try:
            log_data = json.loads(record.getMessage())
            timestamp = log_data.get("timestamp", "")
            level = log_data.get("level", "")
            component = log_data.get("component", "")
            message = log_data.get("message", "")
            
            # Color codes
            colors = {
                "DEBUG": "\033[36m",     # Cyan
                "INFO": "\033[32m",      # Green
                "PROGRESS": "\033[34m",  # Blue
                "WARNING": "\033[33m",   # Yellow
                "ERROR": "\033[31m",     # Red
                "CRITICAL": "\033[35m",  # Magenta
            }
            reset = "\033[0m"
            
            color = colors.get(level, "")
            
            # Progress bars for PROGRESS level
            if level == "PROGRESS" and "progress" in log_data:
                progress_data = log_data["progress"]
                percentage = progress_data.get("percentage", 0)
                bar_length = 30
                filled = int(bar_length * percentage / 100)
                bar = "█" * filled + "░" * (bar_length - filled)
                return f"{color}[{timestamp[:19]}] [{level}] {component}: {message}{reset}\n{color}  [{bar}] {percentage}%{reset}"
            
            return f"{color}[{timestamp[:19]}] [{level}] {component}: {message}{reset}"
        except:
            return record.getMessage()


# Context managers for request tracking
_current_request_id = None
_current_conversation_id = None

def set_request_context(request_id: str = None, conversation_id: str = None):
    """Set current request context"""
    global _current_request_id, _current_conversation_id
    _current_request_id = request_id or f"req_{uuid.uuid4().hex[:8]}"
    _current_conversation_id = conversation_id

def _get_current_request_id():
    return _current_request_id

def _get_current_conversation_id():
    return _current_conversation_id
```

### 2. Usage in Supervisor Agent

```python
# supervisor_agent.py
from logging_config import StructuredLogger, set_request_context
import time

# Initialize logger
logger = StructuredLogger(
    component="supervisor",
    module="supervisor_agent",
    log_file="logs/supervisor.log"
)

def supervisor_node(state: SharedState) -> SharedState:
    """Generate execution plan"""
    # Set request context
    request_id = f"req_{uuid.uuid4().hex[:8]}"
    conversation_id = state.get("conversation_id")
    set_request_context(request_id, conversation_id)
    
    start_time = time.time()
    
    # Log start
    logger.progress(
        message="Generating execution plan",
        function="supervisor_node",
        context={
            "user_input": state["input"],
            "relevant_agents": identify_relevant_agents(state["input"])
        },
        progress={
            "status": "planning",
            "percentage": 10,
            "current_step": "Analyzing request and identifying agents"
        }
    )
    
    try:
        # Generate plan
        plan = generate_plan(state)
        
        execution_time_ms = (time.time() - start_time) * 1000
        
        # Log success
        logger.progress(
            message="Execution plan generated successfully",
            function="supervisor_node",
            context={
                "plan_steps": len(plan.get("plan", [])),
                "agents_involved": list(set([s["agent"] for s in plan.get("plan", [])]))
            },
            progress={
                "status": "completed",
                "percentage": 20,
                "current_step": f"Plan generated ({len(plan.get('plan', []))} steps)"
            },
            performance={
                "execution_time_ms": execution_time_ms,
                "llm_tokens": {"prompt": 2000, "completion": 500}
            }
        )
        
        return {"plan": plan, "context": state.get("context", {})}
        
    except Exception as e:
        # Log error
        logger.error(
            message="Failed to generate execution plan",
            function="supervisor_node",
            error={
                "error_type": type(e).__name__,
                "error_message": str(e),
                "stack_trace": traceback.format_exc()
            }
        )
        raise


def orchestrator_node(state: SharedState) -> SharedState:
    """Execute plan steps"""
    plan = state["plan"].get("plan", [])
    total_steps = len(plan)
    
    for step_num, step in enumerate(plan, 1):
        step_start_time = time.time()
        
        # Log step start
        logger.progress(
            message=f"Executing step {step_num}/{total_steps}",
            function="orchestrator_node",
            context={
                "step_number": step_num,
                "total_steps": total_steps,
                "agent": step["agent"],
                "tool": step["tool"],
                "description": step.get("description", ""),
                "inputs": step.get("inputs", {})
            },
            progress={
                "status": "executing",
                "percentage": int((step_num - 1) / total_steps * 70) + 20,  # 20-90%
                "current_step": f"Step {step_num}/{total_steps}: {step.get('description', '')}"
            }
        )
        
        try:
            # Execute step
            result = execute_step(step, state)
            
            execution_time_ms = (time.time() - step_start_time) * 1000
            
            # Log success
            logger.progress(
                message=f"Step {step_num}/{total_steps} completed successfully",
                function="orchestrator_node",
                context={
                    "step_number": step_num,
                    "agent": step["agent"],
                    "tool": step["tool"],
                    "output_variables": list(step.get("output_variables", {}).keys())
                },
                progress={
                    "status": "completed",
                    "percentage": int(step_num / total_steps * 70) + 20,
                    "current_step": f"Step {step_num}/{total_steps} completed"
                },
                performance={
                    "execution_time_ms": execution_time_ms
                }
            )
            
        except Exception as e:
            # Log error
            logger.error(
                message=f"Step {step_num}/{total_steps} failed",
                function="orchestrator_node",
                context={
                    "step_number": step_num,
                    "total_steps": total_steps,
                    "agent": step["agent"],
                    "tool": step["tool"]
                },
                progress={
                    "status": "failed",
                    "percentage": int(step_num / total_steps * 70) + 20,
                    "current_step": f"Step {step_num}/{total_steps} failed"
                },
                error={
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                }
            )
            raise
    
    # Final progress
    logger.progress(
        message="All steps completed successfully",
        function="orchestrator_node",
        progress={
            "status": "completed",
            "percentage": 100,
            "current_step": f"Task completed ({total_steps} steps executed)"
        }
    )
    
    return state
```

### 3. Usage in Specialized Agents

```python
# gmail-agent/api.py
from logging_config import StructuredLogger
import time

logger = StructuredLogger(
    component="gmail",
    module="api",
    log_file="logs/gmail.log"
)

@app.post("/execute_task")
async def execute_task(request: AgentTaskRequest):
    """Execute Gmail tool"""
    start_time = time.time()
    
    # Log start
    logger.info(
        message=f"Gmail agent task execution started: {request.tool}",
        function="execute_task",
        context={
            "tool": request.tool,
            "inputs": request.inputs
        }
    )
    
    try:
        # Execute tool
        result = execute_gmail_tool(request.tool, request.inputs, request.credentials_dict)
        
        execution_time_ms = (time.time() - start_time) * 1000
        
        # Log success
        logger.info(
            message=f"Gmail task completed: {request.tool}",
            function="execute_task",
            context={
                "tool": request.tool,
                "success": result.get("success"),
                "result_summary": _summarize_result(result)
            },
            performance={
                "execution_time_ms": execution_time_ms
            }
        )
        
        return result
        
    except Exception as e:
        execution_time_ms = (time.time() - start_time) * 1000
        
        # Log error
        logger.error(
            message=f"Gmail task failed: {request.tool}",
            function="execute_task",
            context={
                "tool": request.tool,
                "inputs": request.inputs
            },
            error={
                "error_type": type(e).__name__,
                "error_message": str(e)
            },
            performance={
                "execution_time_ms": execution_time_ms
            }
        )
        raise
```

---

## 📊 Log Storage & Retrieval

### File Structure

```
logs/
├── supervisor.log          # Supervisor agent logs
├── gmail.log              # Gmail agent logs
├── gdrive.log             # GDrive agent logs
├── gdocs.log              # GDocs agent logs
├── calendar.log           # Calendar agent logs
├── sheets.log             # Sheets agent logs
├── mapping.log            # Mapping agent logs
├── archive/               # Rotated logs
│   ├── supervisor.log.2025-11-27
│   ├── gmail.log.2025-11-27
│   └── ...
└── progress/              # Real-time progress logs (optional)
    └── req_abc123.log
```

### Log Rotation

```python
# Add to logging_config.py
from logging.handlers import RotatingFileHandler

# Replace FileHandler with RotatingFileHandler
file_handler = RotatingFileHandler(
    log_file,
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=30,  # Keep 30 old files
    encoding='utf-8'
)
```

### Log Query API (Optional)

```python
# logs_api.py
from fastapi import FastAPI, Query
from typing import List, Optional
import json
from datetime import datetime

app = FastAPI(title="Logs API")

@app.get("/logs/search")
async def search_logs(
    component: Optional[str] = None,
    level: Optional[str] = None,
    request_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = Query(100, le=1000)
):
    """Search logs with filters"""
    logs = []
    
    # Read log files
    for log_file in ["supervisor.log", "gmail.log", ...]:
        with open(f"logs/{log_file}", "r") as f:
            for line in f:
                try:
                    log_entry = json.loads(line)
                    
                    # Apply filters
                    if component and log_entry.get("component") != component:
                        continue
                    if level and log_entry.get("level") != level:
                        continue
                    if request_id and log_entry.get("request_id") != request_id:
                        continue
                    if conversation_id and log_entry.get("conversation_id") != conversation_id:
                        continue
                    
                    logs.append(log_entry)
                    
                    if len(logs) >= limit:
                        break
                except:
                    continue
    
    return {
        "total": len(logs),
        "logs": logs[:limit]
    }

@app.get("/logs/progress/{request_id}")
async def get_progress(request_id: str):
    """Get real-time progress for a request"""
    progress_logs = []
    
    # Read all log files for this request_id
    for log_file in ["supervisor.log", "gmail.log", ...]:
        with open(f"logs/{log_file}", "r") as f:
            for line in f:
                try:
                    log_entry = json.loads(line)
                    if (log_entry.get("request_id") == request_id and 
                        log_entry.get("level") == "PROGRESS"):
                        progress_logs.append(log_entry)
                except:
                    continue
    
    # Sort by timestamp
    progress_logs.sort(key=lambda x: x.get("timestamp", ""))
    
    return {
        "request_id": request_id,
        "progress_updates": progress_logs
    }
```

---

## 🚀 Deployment Checklist

### Development Environment
- [ ] Add `logging_config.py` to each agent
- [ ] Update all agents to use `StructuredLogger`
- [ ] Add progress logging to supervisor orchestrator
- [ ] Implement PII redaction in all log messages
- [ ] Test log output and formatting
- [ ] Verify log rotation works
- [ ] Set up local log viewer (optional)

### Testing
- [ ] Unit tests for logging functions
- [ ] Unit tests for PII redaction
- [ ] Integration tests with full workflows
- [ ] Load tests to verify performance impact (<5ms per log)
- [ ] Verify progress tracking accuracy
- [ ] Test log sampling under high load (>100 logs/sec)
- [ ] Test log rotation and archiving
- [ ] Verify correlation IDs work across agents

### Staging Environment
- [ ] Deploy logging infrastructure to staging
- [ ] Configure staging-specific log storage
- [ ] Test with production-like data volumes
- [ ] Verify log aggregation pipeline
- [ ] Test alert notifications
- [ ] Conduct security audit of logged data

### Production
- [ ] Configure log storage location (with encryption at rest)
- [ ] Set up log aggregation (CloudWatch, ELK, Datadog, etc.)
- [ ] Configure alerts for critical errors (PagerDuty, Slack)
- [ ] Set up monitoring dashboards (Grafana, CloudWatch)
- [ ] Document logging conventions for team
- [ ] Set up log retention policy (30 days default)
- [ ] Configure backup and disaster recovery for logs
- [ ] Enable RBAC for log access
- [ ] Set up log archiving for compliance (1 year)
- [ ] Configure cost alerts for log storage

### Post-Deployment
- [ ] Monitor log volume and storage costs
- [ ] Review and optimize sampling rates
- [ ] Analyze common errors and create runbooks
- [ ] Train team on log querying and analysis
- [ ] Schedule quarterly log retention reviews
- [ ] Review and update PII patterns regularly

---

## 📈 Benefits

1. **Full Traceability**: Every request tracked from start to finish
2. **Real-Time Feedback**: Users see progress as tasks execute
3. **Debugging**: Detailed context for troubleshooting
4. **Performance Monitoring**: Identify bottlenecks and optimize
5. **Audit Trail**: Compliance and security tracking
6. **Error Recovery**: Better error messages and recovery strategies
7. **User Experience**: Transparent progress reduces perceived wait time

---

## 🎯 Next Steps

1. **Review this proposal** with the team
2. **Prioritize implementation phases** based on urgency
3. **Assign tasks** to team members
4. **Set up development environment** with logging
5. **Implement Phase 1** (Core Infrastructure)
6. **Test and iterate** before moving to next phase

---

## 💰 Cost Estimation

### Storage Costs (Estimated)

**Assumptions:**
- 7 agents running 24/7
- Average 100 requests/hour per agent
- Average 50 log entries per request
- Average log size: 2 KB

**Daily Volume:**
```
7 agents × 100 req/hr × 24 hrs × 50 logs × 2 KB = ~168 GB/day
```

**Monthly Cost (AWS CloudWatch example):**
```
Ingestion: 168 GB/day × 30 days × $0.50/GB = $2,520/month
Storage: 5 TB (30 days) × $0.03/GB = $150/month
Total: ~$2,670/month
```

**Cost Optimization Strategies:**
1. **Sampling**: Reduce DEBUG logs by 90% → Save ~$1,500/month
2. **Compression**: Enable gzip compression → Save 60% storage
3. **Tiered Storage**: Move old logs to S3 Glacier → Save $100/month
4. **Retention**: Reduce to 7 days hot + 23 days cold → Save $1,000/month

**Optimized Cost: ~$800-1,000/month**

---

## 📈 Success Metrics & SLAs

### Key Performance Indicators (KPIs)

1. **Log Availability**: 99.9% uptime for log ingestion
2. **Log Latency**: < 100ms from generation to storage
3. **Search Performance**: < 2s for queries on 1GB dataset
4. **Storage Efficiency**: < 200 GB/day with compression
5. **Cost per Request**: < $0.001 per request logged

### Service Level Agreements (SLAs)

```yaml
Logging SLAs:
  log_ingestion_availability: 99.9%
  log_search_latency_p95: 2000ms
  log_retention_guarantee: 30_days
  alert_delivery_time: 60_seconds
  pii_redaction_accuracy: 99.99%
  
Incident Response:
  critical_logs_lost: 5_minutes
  search_system_down: 15_minutes
  storage_full: 30_minutes
```

### Monthly Review Metrics

```python
MONTHLY_METRICS = {
    "total_logs_generated": 0,
    "total_storage_used_gb": 0,
    "average_log_latency_ms": 0,
    "error_rate_percentage": 0,
    "critical_incidents": 0,
    "cost_total_usd": 0,
    "cost_per_request_usd": 0,
    "pii_redaction_failures": 0,
    "search_queries_executed": 0,
    "average_search_time_ms": 0
}
```

---

## 📞 Support & Maintenance

### Operational Guidelines

- **Log Retention**: 30 days (configurable per environment)
- **Storage Requirements**: ~10 MB per day per agent (uncompressed), ~4 MB (compressed)
- **Performance Impact**: < 5ms per log entry
- **Monitoring**: Daily review of ERROR and CRITICAL logs
- **On-call Rotation**: 24/7 support for CRITICAL log system failures

### Maintenance Schedule

**Daily:**
- Review CRITICAL and ERROR logs
- Check storage capacity (alert if >80%)
- Verify log ingestion rates

**Weekly:**
- Review log sampling rates and adjust if needed
- Analyze top errors and create tickets
- Update PII redaction patterns if needed
- Review cost dashboard

**Monthly:**
- Generate monthly metrics report
- Review and optimize storage costs
- Audit log access patterns
- Update logging documentation
- Conduct log retention cleanup

**Quarterly:**
- Security audit of logging system
- Review compliance requirements
- Update disaster recovery procedures
- Analyze long-term trends
- Team training on logging best practices

### Escalation Procedures

**Level 1 - Developer (5 min response):**
- Individual agent logging failures
- Non-critical log search issues

**Level 2 - DevOps (15 min response):**
- Multiple agents logging failures
- Log storage approaching capacity
- Log aggregation pipeline issues

**Level 3 - Senior DevOps/Architect (30 min response):**
- Complete log system outage
- Data breach involving logs
- Compliance violation detected

---

## 📚 References & Resources

### Documentation
- [Structured Logging Best Practices](https://www.loggly.com/blog/structured-logging-best-practices/)
- [OpenTelemetry Documentation](https://opentelemetry.io/docs/)
- [AWS CloudWatch Logs](https://docs.aws.amazon.com/cloudwatch/)
- [Elasticsearch Logging Guide](https://www.elastic.co/guide/)
- [GDPR Compliance for Logging](https://gdpr.eu/)

### Tools & Libraries
- **Python**: `structlog`, `python-json-logger`, `opentelemetry-api`
- **Log Aggregation**: CloudWatch, ELK Stack, Datadog, Splunk
- **Visualization**: Grafana, Kibana, CloudWatch Dashboards
- **Alerting**: PagerDuty, Opsgenie, Slack, SNS

### Internal Resources
- Logging Configuration Guide: `/docs/logging-config.md`
- Log Query Examples: `/docs/log-queries.md`
- Troubleshooting Guide: `/docs/logging-troubleshooting.md`
- Cost Optimization Guide: `/docs/logging-costs.md`

---

**End of Proposal**

*This comprehensive logging system will provide complete visibility into your multi-agent AI system, enabling better debugging, monitoring, and user experience.*
