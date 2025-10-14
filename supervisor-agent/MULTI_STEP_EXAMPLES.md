# Multi-Step Workflow Examples

## How the Supervisor Creates Data-Dependent Plans

The enhanced supervisor can now create plans where later steps depend on earlier step outputs.

## 🔄 Key Concepts

### 1. **Output Variables**
Each step declares what it produces:
```json
{
  "output_variables": {
    "document_id": "ID of created document",
    "document_url": "URL to access the document"
  }
}
```

### 2. **Variable References**
Later steps reference these outputs using `{{ variable_name }}`:
```json
{
  "inputs": {
    "document_id": "{{ document_id }}",
    "text": "Content to add"
  }
}
```

### 3. **The Orchestrator** 
When executing, the orchestrator:
1. Runs step 1 → Gets `document_id` = "abc123"
2. Replaces `{{ document_id }}` with "abc123" in step 2
3. Runs step 2 with the actual ID

---

## 📧 Example 1: Read Emails and Reply to Each

**User Request:**
```
"Read my 3 most recent emails and send a polite acknowledgment reply to each sender"
```

**Generated Plan:**
```json
{
  "plan": [
    {
      "agent": "gmail_agent",
      "tool": "read_recent_emails",
      "inputs": {
        "max_results": 3
      },
      "output_variables": {
        "emails": "List of 3 recent emails with sender info and content",
        "email_1_sender": "Email address of first sender",
        "email_1_subject": "Subject of first email",
        "email_2_sender": "Email address of second sender",
        "email_2_subject": "Subject of second email",
        "email_3_sender": "Email address of third sender",
        "email_3_subject": "Subject of third email"
      },
      "description": "Read the 3 most recent emails"
    },
    {
      "agent": "gmail_agent",
      "tool": "send_email",
      "inputs": {
        "to": "{{ email_1_sender }}",
        "subject": "Re: {{ email_1_subject }}",
        "body": "Thank you for your email. I have received it and will respond shortly."
      },
      "output_variables": {
        "reply_1_status": "Status of first reply"
      },
      "description": "Send acknowledgment to first sender"
    },
    {
      "agent": "gmail_agent",
      "tool": "send_email",
      "inputs": {
        "to": "{{ email_2_sender }}",
        "subject": "Re: {{ email_2_subject }}",
        "body": "Thank you for your email. I have received it and will respond shortly."
      },
      "output_variables": {
        "reply_2_status": "Status of second reply"
      },
      "description": "Send acknowledgment to second sender"
    },
    {
      "agent": "gmail_agent",
      "tool": "send_email",
      "inputs": {
        "to": "{{ email_3_sender }}",
        "subject": "Re: {{ email_3_subject }}",
        "body": "Thank you for your email. I have received it and will respond shortly."
      },
      "output_variables": {
        "reply_3_status": "Status of third reply"
      },
      "description": "Send acknowledgment to third sender"
    }
  ]
}
```

---

## 📄 Example 2: Create Document and Email Link

**User Request:**
```
"Create a project status document titled 'Q1 Update' with a summary, then email it to team@company.com"
```

**Generated Plan:**
```json
{
  "plan": [
    {
      "agent": "docs_agent",
      "tool": "create_doc",
      "inputs": {
        "title": "Q1 Update"
      },
      "output_variables": {
        "document_id": "ID of the created document",
        "document_url": "URL to access the document"
      },
      "description": "Create a new Google Doc for Q1 updates"
    },
    {
      "agent": "docs_agent",
      "tool": "add_text",
      "inputs": {
        "document_id": "{{ document_id }}",
        "text": "Q1 Project Status Summary\n\nKey Achievements:\n- Completed milestone A\n- Launched feature B\n\nNext Steps:\n- Begin milestone C\n- Review feature B metrics"
      },
      "output_variables": {
        "text_status": "Status of text addition"
      },
      "description": "Add Q1 summary content to the document"
    },
    {
      "agent": "gmail_agent",
      "tool": "send_email",
      "inputs": {
        "to": "team@company.com",
        "subject": "Q1 Update Document Ready",
        "body": "Hi Team,\n\nThe Q1 update document is now ready for review. You can access it here:\n{{ document_url }}\n\nBest regards"
      },
      "output_variables": {
        "email_status": "Status of email sent to team"
      },
      "description": "Email the document link to the team"
    }
  ]
}
```

---

## 🔍 Example 3: Search Emails and Forward Summary

**User Request:**
```
"Search for emails from client@acme.com in the last 7 days and forward a summary to my manager@company.com"
```

**Generated Plan:**
```json
{
  "plan": [
    {
      "agent": "gmail_agent",
      "tool": "search_emails",
      "inputs": {
        "query": "from:client@acme.com newer_than:7d",
        "max_results": 10
      },
      "output_variables": {
        "found_emails": "List of emails from client",
        "email_count": "Number of emails found",
        "emails_summary": "Summary of email subjects and dates"
      },
      "description": "Search for recent emails from ACME client"
    },
    {
      "agent": "gmail_agent",
      "tool": "send_email",
      "inputs": {
        "to": "manager@company.com",
        "subject": "ACME Client Email Summary - Last 7 Days",
        "body": "Hi Manager,\n\nI found {{ email_count }} emails from client@acme.com in the last 7 days.\n\nSummary:\n{{ emails_summary }}\n\nPlease let me know if you need the full email threads forwarded."
      },
      "output_variables": {
        "summary_email_status": "Status of summary email to manager"
      },
      "description": "Forward summary to manager"
    }
  ]
}
```

---

## 🔗 Example 4: Complex Multi-Agent Workflow

**User Request:**
```
"Read my unread emails, create a spreadsheet summarizing them, and email the spreadsheet link to assistant@company.com"
```

**Generated Plan:**
```json
{
  "plan": [
    {
      "agent": "gmail_agent",
      "tool": "search_emails",
      "inputs": {
        "query": "is:unread",
        "max_results": 20
      },
      "output_variables": {
        "unread_emails": "List of unread emails",
        "unread_count": "Number of unread emails",
        "email_data": "Structured data with sender, subject, date for each email"
      },
      "description": "Search for all unread emails"
    },
    {
      "agent": "sheets_agent",
      "tool": "create_sheet",
      "inputs": {
        "title": "Unread Emails Summary",
        "data": "{{ email_data }}"
      },
      "output_variables": {
        "sheet_id": "ID of created spreadsheet",
        "sheet_url": "URL to access spreadsheet"
      },
      "description": "Create spreadsheet with email summary"
    },
    {
      "agent": "gmail_agent",
      "tool": "send_email",
      "inputs": {
        "to": "assistant@company.com",
        "subject": "Unread Emails Summary - {{ unread_count }} emails",
        "body": "Hi,\n\nI've compiled a summary of {{ unread_count }} unread emails into a spreadsheet.\n\nAccess it here: {{ sheet_url }}\n\nBest regards"
      },
      "output_variables": {
        "notification_status": "Status of notification email"
      },
      "description": "Email spreadsheet link to assistant"
    }
  ]
}
```

---

## 🎯 Testing Your Multi-Step Plans

### Test 1: Simple Chain
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/workflow" -Method Post -ContentType "application/json" -Body '{"input": "Create a doc called Test Doc and email the link to me@example.com"}'
```

### Test 2: Email Read and Reply
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/workflow" -Method Post -ContentType "application/json" -Body '{"input": "Read my 5 most recent emails and reply with a thank you message"}'
```

### Test 3: Search and Process
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/workflow" -Method Post -ContentType "application/json" -Body '{"input": "Search for emails with subject meeting and forward them to team@example.com"}'
```

---

## 📊 How It Works

1. **Supervisor** analyzes the request and creates a plan with data dependencies
2. **Orchestrator** executes steps sequentially:
   - Step 1 runs → produces `document_id = "abc123"`
   - Step 2 sees `{{ document_id }}` → replaces with "abc123"
   - Step 2 runs with real ID → produces `document_url`
   - Step 3 sees `{{ document_url }}` → replaces with actual URL
   - Step 3 runs and emails the URL

3. **Context** stores all outputs, making them available to subsequent steps

---

## 🔧 Customizing Plans

The supervisor now understands:
- ✅ Sequential dependencies (read → reply)
- ✅ Variable substitution (`{{ variable }}`)
- ✅ Multi-agent orchestration
- ✅ Complex workflows (read → create → email)

You can test different scenarios and the supervisor will intelligently plan the workflow!
