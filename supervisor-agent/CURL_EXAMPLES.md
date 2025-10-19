# Supervisor Agent - Curl Request Examples

This document contains various curl examples for testing the supervisor agent with both simple and multi-step workflows.

## 🔧 Setup

Base URL: `http://localhost:8000`
Endpoint: `/workflow`

---

## 📧 SIMPLE GMAIL EXAMPLES

### 1. Check Recent Emails
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Check on the emails that was sent to me today\"}"
```

### 2. Read Last 5 Emails
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Show me my last 5 emails\"}"
```

### 3. Search for Specific Sender
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Find all emails from example.com\"}"
```

### 4. Search Unread Emails
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Show me all my unread emails\"}"
```

### 5. Search by Subject
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Find emails about the quarterly report\"}"
```

### 6. Create a Draft Email
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Create a draft email to sarah@company.com with subject 'Meeting Follow-up' and body 'Thanks for the productive meeting today'\"}"
```

### 7. Send an Email
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Send an email to team@company.com about tomorrow's standup meeting at 9 AM\"}"
```

---

## 📄 SIMPLE GOOGLE DOCS EXAMPLES

### 8. Create a New Document
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Create a new Google Doc titled 'Project Proposal 2025'\"}"
```

### 9. List Recent Documents
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Show me my recent Google Docs\"}"
```

### 10. Search for Document
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Find my document about budget planning\"}"
```

---

## 🔄 MULTI-STEP: EMAIL WORKFLOWS

### 11. Read Email and Reply
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Read my most recent email and send a reply saying I'll get back to them tomorrow\"}"
```

### 12. Search Email and Reply to Thread
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Find the email from alice@company.com about the budget and reply that I approve the request\"}"
```

### 13. Read Multiple Emails and Reply to Each
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Read my 3 most recent emails and send a polite acknowledgment to each sender\"}"
```

### 14. Search with Filter and Reply
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Find unread emails from today and reply to all of them with 'Thanks for reaching out, I'll review this shortly'\"}"
```

---

## 📧📄 MULTI-STEP: EMAIL + DOCS WORKFLOWS

### 15. Create Doc and Email Link
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Create a new Google Doc called 'Q4 Report' and email the link to manager@company.com\"}"
```

### 16. Create Doc and Draft Email with Link
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Create a document titled 'Meeting Notes' and draft an email to the team with the document link\"}"
```

### 17. Read Email, Create Doc, Reply with Link
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Read the latest email from boss@company.com, create a new document called 'Action Items', and reply to the email with the document link\"}"
```

### 18. Search Email, Create Response Doc, Reply
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Find the email about project requirements, create a Google Doc with initial thoughts, and reply to the sender with the doc link\"}"
```

---

## 📄✍️ MULTI-STEP: DOCUMENT WORKFLOWS

### 19. Create Doc and Add Content
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Create a document called 'Weekly Summary' and add the text 'This week we completed 5 tasks and started 3 new projects'\"}"
```

### 20. Create Doc, Add Content, Email Link
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Create a new doc titled 'Product Roadmap', add some introduction text, and email it to product-team@company.com\"}"
```

---

## 🔍 MULTI-STEP: SEARCH AND ACTION WORKFLOWS

### 21. Search and Forward
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Find the most recent email from client@external.com and forward it to my-team@company.com\"}"
```

### 22. Search, Get Thread, Reply
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Search for emails about 'invoice payment', get the conversation thread, and reply with payment confirmation\"}"
```

### 23. Read Email, Label, Reply
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Read the latest email from support@vendor.com, add the 'Important' label, and reply with acknowledgment\"}"
```

---

## 🎯 COMPLEX MULTI-STEP WORKFLOWS

### 24. Email Summary to Document
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Read my last 10 emails, create a Google Doc summarizing them, and draft an email to myself with the doc link\"}"
```

### 25. Conditional Email Reply
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Search for emails from today. If there are unread emails from high-priority senders, reply to them immediately\"}"
```

### 26. Create Multiple Drafts
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Create three draft emails: one to sales@company.com about Q4 goals, one to hr@company.com about team updates, and one to engineering@company.com about technical review\"}"
```

### 27. Document Creation and Distribution
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Create a document titled 'Company Updates', add some placeholder text, and send the link to three different team leads\"}"
```

---

## 📊 MULTI-STEP: DATA GATHERING WORKFLOWS

### 28. Email Audit
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Search for all emails from the last 7 days and create a summary document listing the senders and subjects\"}"
```

### 29. Attachment Processing
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Find emails with attachments from this week and reply to each sender confirming receipt\"}"
```

### 30. Thread Analysis
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Get the conversation thread for the email about 'project deadline' and reply to all participants with a status update\"}"
```

---

## 🔄 MULTI-STEP: WORKFLOW WITH CONDITIONS

### 31. Smart Email Response
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Check my recent emails. If I have any from my manager, reply immediately. Otherwise, create a draft response for later\"}"
```

### 32. Priority-Based Handling
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Search for urgent emails from today. For each urgent email, create a response draft and add a follow-up label\"}"
```

---

## 💡 CREATIVE MULTI-STEP WORKFLOWS

### 33. Meeting Preparation
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Find emails about tomorrow's meeting, create a Google Doc with agenda items, and send the doc to all meeting participants\"}"
```

### 34. Weekly Digest
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Search for all emails from this week, create a summary document, and email it to myself for review\"}"
```

### 35. Client Communication Chain
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Find the latest email from our biggest client, create a response document with talking points, and draft a professional reply using those points\"}"
```

---

## 🧪 TESTING EDGE CASES

### 36. Empty Results Handling
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Search for emails from randomnonexistent@fake.com and reply if found\"}"
```

### 37. Multiple Agent Coordination
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Check my emails, create a doc for each important email summarizing the content, and send links back to each sender\"}"
```

### 38. Cascading Dependencies
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Read my most recent email, extract the sender's email address, create a document addressed to them, add a thank you message, and reply to the email with the doc link\"}"
```

---

## 🎭 CREATIVE USE CASES

### 39. Onboarding New Team Member
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Create a welcome document for new team member, add introduction text, and send it to hr@company.com and newmember@company.com\"}"
```

### 40. Project Status Update
```bash
curl -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d "{\"input\": \"Create a document titled 'Project Status Update', add current progress details, and email it to all stakeholders\"}"
```

---

## 📝 NOTES

- Replace example email addresses with real ones for testing
- Ensure all required agent microservices are running
- The supervisor agent is at `http://localhost:8000`
- Gmail agent typically runs on port 8001
- Docs agent typically runs on port 8002

## 🚀 PowerShell Multi-line Examples

If you need to format these better in PowerShell, use:

```powershell
$body = @{
    input = "Check on the emails that was sent to me today"
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://localhost:8000/workflow" -Body $body -ContentType "application/json"
```

Or with proper escaping:

```powershell
curl.exe -X POST http://localhost:8000/workflow -H "Content-Type: application/json" -d '{\"input\": \"Check on the emails that was sent to me today\"}'
```
