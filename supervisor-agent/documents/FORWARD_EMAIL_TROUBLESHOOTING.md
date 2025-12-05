# Forward Email Troubleshooting Guide

## Issue
When typing "I want to forward an email" in the chat, you get:
> 📋 I'm having trouble processing that. Could you please rephrase your request?

## Root Cause Analysis

This error message comes from **3 possible failure points** in `conversational_agent.py`:

### 1. **LLM Call Timeout** (Line 215)
```python
except Exception as llm_error:
    return ConversationAnalysis(
        clarification_question="I'm having trouble processing that. Could you please rephrase your request?"
    )
```
**Cause:** OpenAI API timeout, network error, or API key issue

### 2. **JSON Parsing Failure** (Line 253)
```python
except (json.JSONDecodeError, ValueError) as e:
    return ConversationAnalysis(
        clarification_question="I'm not sure I understood that. Could you please rephrase what you'd like me to do?"
    )
```
**Cause:** LLM returned malformed JSON or missing required fields

### 3. **Missing Context**
**Cause:** The conversational agent doesn't understand "forward" as a valid action

## Why This Happens

### Problem 1: Vague Request
❌ **User says:** "I want to forward an email"
- **Missing:** Which email to forward?
- **Missing:** Who to forward it to?

The conversational agent should ask clarifying questions, but if the LLM fails, you get the error message instead.

### Problem 2: Email Not Identified
To forward an email, you need:
1. The **message_id** of the email to forward
2. The **recipient** email address
3. Optional: A message to include

If you haven't searched for emails first, the system doesn't know which email you're referring to.

## Solutions

### ✅ Solution 1: Two-Step Process (Recommended)

**Step 1: Search for the email first**
```
"Search for emails from john@example.com about the meeting"
```

**Step 2: Reference the email when forwarding**
```
"Forward the first email to sarah@company.com"
```

### ✅ Solution 2: Be More Specific

Instead of:
```
❌ "I want to forward an email"
```

Try:
```
✅ "Search for emails from john@example.com and forward the most recent one to sarah@company.com"
```

### ✅ Solution 3: Check Service Logs

The error might be from a backend issue. Check terminal logs:

1. **Supervisor Agent Terminal** - Look for:
   - `⚠️ LLM call failed:`
   - `⚠️ Failed to parse LLM response:`
   - Any OpenAI API errors

2. **Gmail Agent Terminal** - Look for:
   - Connection errors
   - Authentication issues

## Diagnostic Steps

### Test 1: Check if Services are Running
```powershell
# Run this to see all services
.\start-all-services.ps1
```

Look for these terminals:
- ✅ Backend (port 8000)
- ✅ Gmail Agent (port 8001)
- ✅ Supervisor Agent (port 8004)
- ✅ Frontend (port 5173)

### Test 2: Test Forward Email Capability
```powershell
# Test direct API call to gmail-agent
curl http://localhost:8001/execute_tool -Method POST -ContentType "application/json" -Body '{
  "tool_name": "search_emails",
  "args": {
    "query": "from:test@example.com",
    "max_results": 1
  }
}'
```

### Test 3: Check OpenAI API Key
```powershell
# In supervisor-agent terminal, check for:
echo $env:OPENAI_API_KEY
```

If empty, the LLM can't process your request!

### Test 4: Increase Timeout (Temporary Fix)
Edit `supervisor-agent/conversational_agent.py` line 195:
```python
# Change from:
config={"timeout": 320}  # 320 seconds

# To:
config={"timeout": 600}  # 10 minutes
```

## Expected Behavior

### ✅ Correct Flow:

**User:** "Forward the email to sarah@company.com"

**Bot:** "📋 I need more information to forward this email:
- Which email would you like to forward? (Please search for emails first or provide the message ID)"

**User:** "The one from john about the meeting"

**Bot:** "Let me search for that email first..."
[Shows email results]

**User:** "Forward the first one to sarah@company.com"

**Bot:** ⚠️ **Action Requires Approval**
[Shows pending action card]

**User:** [Approves]

**Bot:** [Shows green success card with forward confirmation]

## Common Mistakes

### ❌ Mistake 1: No Email Context
```
User: "Forward an email"
```
**Why it fails:** System doesn't know WHICH email

**Fix:** Search first, then forward

### ❌ Mistake 2: Invalid Email Address
```
User: "Forward email to sarah"
```
**Why it fails:** "sarah" is not a valid email address

**Fix:** Use full email: "sarah@company.com"

### ❌ Mistake 3: Email Doesn't Exist
```
User: "Forward message ID xyz123 to bob@test.com"
```
**Why it fails:** Message ID doesn't exist or you don't have access

**Fix:** Search for emails first to get valid message IDs

## Quick Test Commands

### Test 1: Search + Forward (Easiest)
```
1. "Search for recent emails"
2. Wait for results
3. "Forward the first email to test@example.com"
4. Approve action
5. ✅ See green success card
```

### Test 2: Specific Search + Forward
```
1. "Search for emails from john@company.com about meeting"
2. "Forward the most recent one to team@company.com with message: FYI"
3. Approve
4. ✅ See success
```

### Test 3: Forward Multiple
```
1. "Search for emails from john"
2. "Forward the first and second emails to alice@test.com"
3. Approve both
4. ✅ See two success cards
```

## Backend Debug Mode

### Enable Verbose Logging

**In conversational_agent.py** (line 200):
```python
except Exception as llm_error:
    # Add detailed logging
    print(f"⚠️ LLM call failed: {llm_error}")
    print(f"⚠️ User message: {user_message}")
    print(f"⚠️ System prompt length: {len(system_prompt)}")
    print(f"⚠️ History: {conversation_state.conversation_history}")
    return ConversationAnalysis(...)
```

**In conversational_agent.py** (line 238):
```python
except (json.JSONDecodeError, ValueError) as e:
    # Add response logging
    print(f"⚠️ Failed to parse LLM response: {e}")
    print(f"⚠️ Raw response: {llm_response.content}")  # Full response
    print(f"⚠️ Response type: {type(llm_response.content)}")
    return ConversationAnalysis(...)
```

Restart supervisor agent and try again. Check terminal for detailed error messages.

## API Key Issues

### If you see "LLM call failed":

1. **Check environment variable:**
   ```powershell
   echo $env:OPENAI_API_KEY
   ```

2. **Set it if missing:**
   ```powershell
   $env:OPENAI_API_KEY="sk-your-key-here"
   cd supervisor-agent
   python supervisor_agent.py
   ```

3. **Check API key validity:**
   - Visit https://platform.openai.com/api-keys
   - Verify key is active and has credits

## Still Not Working?

### Collect Diagnostic Info:

1. **Exact phrase you typed:**
   ```
   Example: "I want to forward an email"
   ```

2. **Terminal output from supervisor-agent:**
   ```
   Copy any error messages or warnings
   ```

3. **Browser console output:**
   ```
   F12 → Console tab → Copy any errors
   ```

4. **Network tab in browser:**
   ```
   F12 → Network → Find /chat POST request → Copy response
   ```

### Fallback: Direct API Testing

Test the forward_email tool directly without the conversational layer:

```powershell
# First, search for an email
curl http://localhost:8001/execute_tool -Method POST -ContentType "application/json" -Body '{
  "tool_name": "search_emails",
  "args": {"query": "is:inbox", "max_results": 1}
}'

# Get the message_id from response, then:
curl http://localhost:8001/execute_tool -Method POST -ContentType "application/json" -Body '{
  "tool_name": "forward_email",
  "args": {
    "message_id": "YOUR_MESSAGE_ID_HERE",
    "to": "test@example.com",
    "forward_message": "FYI"
  }
}'
```

If this works, the issue is in the conversational layer, not the forward tool itself.

---

## Summary

**Most Likely Causes:**
1. 🔑 **Missing OpenAI API key** → LLM can't process request
2. 📧 **No email context** → System doesn't know which email to forward
3. ⏱️ **LLM timeout** → Response takes too long
4. 🔧 **Malformed LLM response** → JSON parsing fails

**Best Solution:**
Always search for emails first, then forward by reference:
```
"Search for emails from john"
→ See results
→ "Forward the first one to sarah@company.com"
→ Approve
→ ✅ Success!
```

---

**Last Updated:** October 31, 2025  
**Issue Type:** Error Message - "Having trouble processing that"  
**Status:** Diagnostic guide created