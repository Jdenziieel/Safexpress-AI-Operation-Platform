# Quick Reference - Forward Email Feature

## 🎯 How to Forward Emails

### Simple Commands:

```
✅ "Forward the email from john@example.com to mary@example.com"
✅ "Send that email to bob@company.com"  
✅ "Forward the most recent email to alice@example.com"
✅ "Share the message from client@example.com with team@company.com"
```

---

## 📊 Visual Flow

```
┌─────────────────────────────────────────────────────────────┐
│  User: "Forward email from john@ex.com to mary@ex.com"     │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────┐
│  Supervisor Agent: Creates 2-Step Plan                      │
│  • Step 1: search_emails (query: "from:john@ex.com")       │
│  • Step 2: forward_email (message_id: X, to: mary@ex.com)  │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 1: Search Executes (SAFE - Auto)                     │
│  Gmail Agent returns email list                             │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────┐
│  UI: Shows Search Results in Chat                          │
│  "Found 1 email from john@ex.com:                          │
│   Subject: Project Update - Jan 15"                         │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 2: Forward → PENDING ACTIONS (DANGEROUS)             │
│  ⏰ Pending Actions Widget Shows:                           │
│     Agent: gmail_agent                                      │
│     Tool: forward_email                                     │
│     To: mary@ex.com                                         │
│     [✅ Approve] [❌ Reject]                                │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
          ┌────────────┴────────────┐
          ↓                         ↓
┌──────────────────┐    ┌──────────────────┐
│  User Approves   │    │  User Rejects    │
└────────┬─────────┘    └────────┬─────────┘
         ↓                       ↓
┌──────────────────┐    ┌──────────────────┐
│  Gmail Agent     │    │  Action Skipped  │
│  Forwards Email  │    │  No email sent   │
└────────┬─────────┘    └──────────────────┘
         ↓
┌──────────────────────────────────────────┐
│  UI: Success Message                     │
│  "✅ Action approved and executed        │
│   Email forwarded to mary@ex.com"       │
└──────────────────────────────────────────┘
```

---

## 🎨 What the Forward Looks Like

```
From: your.email@gmail.com
To: mary@example.com
Subject: Fwd: Project Update

[Optional: Your added message here]

---------- Forwarded message ---------
From: john@example.com
Date: Thu, Jan 15, 2025 at 2:30 PM
Subject: Project Update

[Original email body content]

---
This is written by Assistant Agent
```

---

## 🛡️ Safety Features

| Feature | Status |
|---------|--------|
| Requires Approval | ✅ Yes (DANGEROUS level) |
| Shows Full Details | ✅ Before approval |
| Can Be Rejected | ✅ User choice |
| Automatic Signature | ✅ Added to all forwards |
| Error Handling | ✅ Complete |

---

## 📋 Backend Components

```
┌─────────────────────────────────────────────┐
│  tools.py                                   │
│  • _forward_email_impl()                    │
│    - Fetches original email                 │
│    - Extracts headers (From, Subject, Date) │
│    - Builds forward body                    │
│    - Sends via Gmail API                    │
└─────────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────┐
│  agent.py                                   │
│  • forward_email tool                       │
│  • Added to tools list                      │
└─────────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────┐
│  api.py                                     │
│  • TOOL_MAP["forward_email"]                │
│  • Signature transformation                 │
└─────────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────┐
│  agent_capabilities.py                      │
│  • forward_email documentation              │
│  • Args and return types                    │
└─────────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────┐
│  models.py                                  │
│  • Risk level: DANGEROUS                    │
│  • Requires approval                        │
└─────────────────────────────────────────────┘
```

---

## 🧪 Test Examples

### Test 1: Basic Forward
```
Input:  "Forward email from lance@example.com to test@example.com"
Step 1: Search emails from lance@example.com ✅
Step 2: Forward to test@example.com ⏳ (needs approval)
Result: Email forwarded after approval ✅
```

### Test 2: With Custom Message
```
Input:  "Forward latest email to bob@ex.com with message 'FYI'"
Step 1: Search recent emails ✅
Step 2: Forward with message "FYI" ⏳ (needs approval)
Result: Email forwarded with custom message ✅
```

### Test 3: Conversational
```
User: "Show me emails from client@example.com"
AI:   "Found 3 emails: [shows list]"
User: "Forward the first one to manager@company.com"
AI:   [Pending action appears]
User: [Clicks Approve]
AI:   "✅ Email forwarded successfully"
```

---

## 💡 Pro Tips

1. **Be Specific:** "Forward the email about 'Budget' to finance@company.com"
2. **Add Context:** "Forward with message 'Please review ASAP'"
3. **Use Natural Language:** The AI understands variations like:
   - "Send that email to..."
   - "Share this with..."
   - "Forward the message to..."

---

## 🚀 Ready to Test!

Start services and try:
```
Search my emails and forward the most recent one to test@example.com
```

Watch the magic happen! 🎉
