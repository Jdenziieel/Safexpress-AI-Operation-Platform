# Email Safety Updates - Draft-First Policy

## 🎯 Changes Made

### 1. Updated `identify_relevant_agents` Function

**Location:** `supervisor-agent/supervisor_agent.py` (Line ~329)

**Changes:**
- ✅ Added clearer descriptions of what each agent does
- ✅ Noted that `gmail_agent` and `docs_agent` are fully implemented
- ✅ Indicated that `sheets_agent`, `calendar_agent`, and `drive_agent` are defined but may not be fully implemented

**Updated Prompt:**
```python
"""
Based on this user request, which agents are needed? 

Available agents:
- gmail_agent: Read, search, draft, send, reply to emails, manage labels, download attachments
- docs_agent: Create, edit, and read Google Docs documents

Note: sheets_agent, calendar_agent, and drive_agent are defined but may not be implemented yet.

User request: {user_input}

Return ONLY a JSON array of agent names needed. Example: ["gmail_agent", "docs_agent"]
"""
```

**Benefits:**
- 🎯 More accurate agent selection
- 📝 Clearer capabilities for LLM to understand
- ⚠️ Warns about unimplemented agents

---

### 2. Added Draft-First Email Safety Policy

**Location:** `supervisor-agent/supervisor_agent.py` (Line ~483)

**Critical Addition:**
Added a **mandatory safety rule** that enforces creating email drafts before sending.

**Updated System Prompt:**
```python
CRITICAL EMAIL SAFETY RULE:
⚠️ NEVER use send_draft_email, reply_to_email, or send_email_with_attachment as the first step.
✅ ALWAYS create drafts first using create_draft_email before any sending action.
✅ This allows human review before emails are actually sent.

Example CORRECT workflow for sending email:
Step 1: create_draft_email (creates draft for review)
Step 2: send_draft_email (sends after approval) - OPTIONAL, only if user explicitly requests sending

Example WRONG workflow:
❌ Step 1: send_email_with_attachment (NO! Create draft first!)
❌ Step 1: reply_to_email (NO! Create draft first!)
```

**Benefits:**
- 🛡️ **Safety Layer:** No emails sent without drafts first
- 👁️ **Human Review:** User can review content before sending
- ✅ **Prevents Mistakes:** Catches errors before they're sent
- 📋 **Clear Guidelines:** LLM knows exactly what to do

---

### 3. Added Missing Import

**Location:** `supervisor-agent/supervisor_agent.py` (Line ~8)

**Change:**
```python
import time  # Added for retry sleep functionality
```

This was needed for the `call_agent_with_retry` function's exponential backoff.

---

## 🎯 How It Works Now

### Example: User Request to Send Email

**User Input:**
```
"Send an email to boss@company.com saying the project is complete"
```

**OLD Behavior (Without Policy):**
```json
{
  "plan": [
    {
      "agent": "gmail_agent",
      "tool": "send_email_with_attachment",  // ❌ Sends immediately!
      "inputs": {
        "to": "boss@company.com",
        "subject": "Project Update",
        "body": "The project is complete!"
      }
    }
  ]
}
```

**NEW Behavior (With Draft-First Policy):**
```json
{
  "plan": [
    {
      "agent": "gmail_agent",
      "tool": "create_draft_email",  // ✅ Creates draft first!
      "inputs": {
        "to": "boss@company.com",
        "subject": "Project Update",
        "body": "The project is complete!"
      },
      "output_variables": {
        "draft_id": "draft_id"
      },
      "description": "Create draft email for review"
    }
  ]
}
```

**User Can Then:**
1. ✅ Review the draft in Gmail
2. ✅ Edit if needed
3. ✅ Manually send when ready
4. ✅ Or use the draft_id with another request to send

---

## 🔄 Workflow Examples

### Example 1: Simple Email Send

**Request:** `"Email john@example.com about tomorrow's meeting"`

**Generated Plan:**
```json
{
  "plan": [
    {
      "step": 1,
      "agent": "gmail_agent",
      "tool": "create_draft_email",
      "inputs": {
        "to": "john@example.com",
        "subject": "Tomorrow's Meeting",
        "body": "Hi John, Looking forward to our meeting tomorrow. Best regards."
      },
      "description": "Create draft email about meeting"
    }
  ]
}
```

**Result:** ✅ Draft created, no email sent automatically

---

### Example 2: Reply to Email

**Request:** `"Find the email from Sarah and reply with a thank you"`

**Generated Plan:**
```json
{
  "plan": [
    {
      "step": 1,
      "agent": "gmail_agent",
      "tool": "search_emails",
      "inputs": {
        "query": "from:sarah",
        "max_results": 1
      },
      "output_variables": {
        "message_id": "first_message_id"
      },
      "description": "Find email from Sarah"
    },
    {
      "step": 2,
      "agent": "gmail_agent",
      "tool": "create_draft_email",  // ✅ Draft first, not reply_to_email!
      "inputs": {
        "to": "sarah@example.com",
        "subject": "Re: {{ subject }}",
        "body": "Thank you for your email!"
      },
      "description": "Create draft reply to Sarah"
    }
  ]
}
```

**Result:** ✅ Draft reply created, user can review before sending

---

### Example 3: Explicit Send Request

**Request:** `"Create and SEND an email to team@company.com about the update"`

**Generated Plan:**
```json
{
  "plan": [
    {
      "step": 1,
      "agent": "gmail_agent",
      "tool": "create_draft_email",
      "inputs": {
        "to": "team@company.com",
        "subject": "Update",
        "body": "Here is the latest update..."
      },
      "output_variables": {
        "draft_id": "draft_id"
      },
      "description": "Create draft email"
    },
    {
      "step": 2,
      "agent": "gmail_agent",
      "tool": "send_draft_email",  // Only includes send if user explicitly requests
      "inputs": {
        "draft_id": "{{ draft_id }}"
      },
      "description": "Send the draft email"
    }
  ]
}
```

**Result:** ✅ Draft created AND sent (because user said "SEND")

---

## ⚙️ Configuration

The policy is **hardcoded** in the supervisor's system prompt. To modify:

### To Disable Draft-First Policy (Not Recommended):
Remove the "CRITICAL EMAIL SAFETY RULE" section from the system prompt in `supervisor_node()`.

### To Make It More Strict:
Add additional checks in the `orchestrator_node()` to reject plans that violate the policy:

```python
def validate_email_safety(plan: dict) -> bool:
    """Validate that email plans follow draft-first policy"""
    plan_steps = plan.get("plan", [])
    
    dangerous_tools = ["send_draft_email", "reply_to_email", "send_email_with_attachment"]
    
    for i, step in enumerate(plan_steps):
        tool = step.get("tool")
        
        # Check if using dangerous tool
        if tool in dangerous_tools:
            # Check if a draft was created in previous steps
            has_prior_draft = any(
                s.get("tool") == "create_draft_email" 
                for s in plan_steps[:i]
            )
            
            if not has_prior_draft:
                return False
    
    return True

# In orchestrator_node, before executing:
if not validate_email_safety(state["plan"]):
    raise ValueError("Email safety violation: Must create draft before sending")
```

---

## 🧪 Testing

### Test 1: Verify Draft-First Behavior
```bash
curl -X POST http://localhost:8000/workflow \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Send an email to test@example.com saying hello"
  }'

# Expected: Plan should use create_draft_email, NOT send_email_with_attachment
```

### Test 2: Verify Reply Behavior
```bash
curl -X POST http://localhost:8000/workflow \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Find the latest email from John and reply with thanks"
  }'

# Expected: 
# Step 1: search_emails
# Step 2: create_draft_email (not reply_to_email)
```

### Test 3: Explicit Send Request
```bash
curl -X POST http://localhost:8000/workflow \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Create and immediately SEND an email to urgent@example.com"
  }'

# Expected:
# Step 1: create_draft_email
# Step 2: send_draft_email (included because user said "SEND")
```

---

## 📊 Benefits Summary

| Benefit | Description |
|---------|-------------|
| 🛡️ **Safety** | Prevents accidental email sending |
| 👁️ **Review** | User can review content before sending |
| ✅ **Control** | User decides when to actually send |
| 🐛 **Error Prevention** | Catches mistakes before they're sent |
| 📝 **Audit Trail** | Drafts saved in Gmail for reference |
| 🔄 **Flexibility** | Can still send if explicitly requested |

---

## 🎯 Summary

### Changes:
1. ✅ Updated agent identification prompt with clearer descriptions
2. ✅ Added mandatory draft-first policy for all email sending
3. ✅ Fixed missing `time` import

### Impact:
- **No emails sent automatically** - All go through draft stage first
- **User maintains control** - Review before sending
- **Safer workflow** - Prevents accidental sends
- **Backwards compatible** - Explicit "send" requests still work

### Files Modified:
- `supervisor-agent/supervisor_agent.py` (3 changes)

This provides a **safety layer** while maintaining flexibility for users who explicitly want to send emails immediately! 🚀
