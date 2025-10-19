# Variable Extraction Fix

## Date: October 18, 2025

## Problem Identified

The supervisor agent was unable to extract variables from gmail agent responses because the agent was transforming the field names.

### Symptoms:
```
📦 Variables added to context:
   ⚠️ last_email_message_id = NOT FOUND (looking for first_message_id in result)
   ⚠️ last_email_thread_id = NOT FOUND (looking for first_thread_id in result)
```

### Root Cause:

**Tool Implementation (`tools.py`)** returns:
```python
{
    "success": True,
    "emails": [...],
    "first_message_id": "abc123",  # ✅ Correct field
    "first_thread_id": "xyz789"     # ✅ Correct field
}
```

**Agent Wrapper (`api.py`)** was instructing LLM to transform to:
```python
{
    "success": true,
    "emails": [...],
    "email_1_from": "sender@example.com",     # ❌ Wrong field
    "email_1_subject": "Subject",              # ❌ Wrong field
    "email_1_snippet": "Preview"               # ❌ Wrong field
}
```

**Supervisor** was looking for:
```python
output_variables = {
    "last_email_message_id": "first_message_id",  # ❌ Field didn't exist!
    "last_email_thread_id": "first_thread_id"      # ❌ Field didn't exist!
}
```

---

## Solution Applied

### Modified: `gmail-agent/api.py`

**Change 1:** Updated `tool_specific_instructions` for `search_emails`:
```python
# BEFORE:
"email_1_from": "<sender of first email>",
"email_1_subject": "<subject of first email>",

# AFTER:
"first_message_id": "<message ID of first email or null>",
"first_thread_id": "<thread ID of first email or null>",
```

**Change 2:** Updated agent prompt instructions:
```python
# BEFORE:
2. Parse the tool's output carefully (it may return formatted text)
3. Extract all relevant information from the tool output
4. Return a properly structured JSON object

# AFTER:
2. The tool will return a structured JSON dictionary
3. Return the EXACT JSON output from the tool without any modifications
4. Do NOT add, remove, or rename any fields
5. Do NOT extract or transform the data
```

**Change 3:** Added explicit warning in instructions:
```
CRITICAL: Return the EXACT output from the tool without modification.
```

---

## Expected Behavior After Fix

### Before (Broken):
```
Agent Response:
{
    "success": true,
    "emails": [],
    "email_1_from": null,        # ❌ Wrong field name
    "email_1_subject": null       # ❌ Wrong field name
}

Variable Extraction:
⚠️ last_email_message_id = NOT FOUND (looking for first_message_id)
```

### After (Fixed):
```
Agent Response:
{
    "success": true,
    "emails": [],
    "first_message_id": null,     # ✅ Correct field name
    "first_thread_id": null       # ✅ Correct field name
}

Variable Extraction:
✓ last_email_message_id = None (from first_message_id)
✓ last_email_thread_id = None (from first_thread_id)
```

---

## Additional Issues Found in Your Test

### Issue 1: No Emails Found
```
"count": 0,
"query": "to:jdenziiel"
```
**Cause:** No emails were sent to "jdenziiel" in your Gmail account.

**Solutions:**
- Use `from:jdenziiel` to search emails FROM that person instead
- Or send a test email to jdenziiel first
- Or use a different search query like `from:yourself@gmail.com`

### Issue 2: Invalid Email Address
```
"to": "Jdenziieel",
"error": "Gmail API error: Invalid To header"
```
**Cause:** "Jdenziieel" is not a valid email address (missing `@domain.com`).

**Solution:** Use a valid email address:
- `jdenziiel@gmail.com`
- Or get the email from search results: `{{ emails.0.from }}`

### Issue 3: Empty Body
```
"body": ""
```
**Cause:** `last_email_content` was empty because:
1. No emails were found in step 1
2. Variable extraction failed in step 2

**Will be fixed by:** The variable extraction fix above

---

## Testing Recommendations

### Test 1: Search and Extract Email ID
```bash
curl -X POST http://localhost:8000/workflow \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Search for recent emails from myself and get the first message ID"
  }'
```

**Expected:** Variables `first_message_id` and `first_thread_id` should be extracted successfully.

### Test 2: Full Workflow with Valid Email
```bash
curl -X POST http://localhost:8000/workflow \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Search for my recent sent emails and create a draft reply to the first one"
  }'
```

**Expected:** All variable extractions should work, email address should be valid.

---

## Files Modified

1. **`gmail-agent/api.py`**
   - Updated `tool_specific_instructions` for `search_emails` to use `first_message_id`, `first_thread_id`
   - Updated `tool_specific_instructions` for `read_recent_emails` to use `first_message_id`, `first_thread_id`
   - Modified agent prompt to pass through tool output without modifications
   - Added explicit instructions to NOT transform or extract data

---

## Status: ✅ COMPLETE

The variable extraction issue has been fixed. The agent will now return the exact field names from the tool implementations, allowing the supervisor to properly extract variables for multi-step workflows.

**Next Steps:** 
1. Restart the gmail agent service
2. Test with a valid search query that returns results
3. Use valid email addresses in the workflow
