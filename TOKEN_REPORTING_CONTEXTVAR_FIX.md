# Token Reporting - Async Context Fix Complete

## What Was Fixed

### Problem
Threading.local() doesn't work with async/await. When supervisor_agent spawned async tasks for LLM calls, the thread-local context (including user_id) was lost.

### Solution  
Switched from `threading.local()` to `contextvars.ContextVar` which:
- ✅ Automatically propagates through async function calls
- ✅ Maintains context across await boundaries  
- ✅ Thread-safe and async-safe

## Testing Token Reporting

### Test Case 1: Greeting (Current Request - NO LLM)
```
User sends: "hello"
→ Tier 0 greeting check (instant, no LLM)
→ [TOKEN REPORTING] user_id=..., success=True, operation=... (0 tokens)
→ No logger.llm_call() because no LLM was used
✅ CORRECT: Greetings use 0 tokens
```

### Test Case 2: Task Request (NEXT - WITH LLM)
```
User sends: "send email to john@example.com"
→ Tier 0-0.5 checks fail
→ Tier 1 full analysis triggered (LLM call)
→ logger.llm_call() is called with tokens
→ [TOKEN REPORTING] user_id=..., success=True, operation=tier_1_full_analysis, tokens=XXX
→ _report_quota_usage() called with user_id
✅ EXPECTED: Tokens are reported
```

### Test Case 3: Workflow Execution (AFTER TASK - MORE TOKENS)
```
User says "yes" to execute
→ execute_workflow() called
→ LLM generates plan
→ logger.llm_call() for plan_generation
→ [TOKEN REPORTING] user_id=..., success=True, operation=plan_generation, tokens=YYY
→ _report_quota_usage() called
✅ EXPECTED: More tokens reported
```

## Debug Output to Look For

### ✅ When context is set correctly:
```
[CONTEXT SET] request_id=req_..., user_id=5ace696a-..., thread_id=...
```

### ✅ When token reporting happens:
```
[TOKEN REPORTING] user_id=5ace696a-..., success=True, operation=tier_1_full_analysis, tokens=150
📊 Reported 150 tokens to quota service for user 5ace696a-...
```

### ❌ When user_id is missing:
```
[TOKEN REPORTING] user_id=None, success=True, operation=tier_1_full_analysis, tokens=150
⚠️ [TOKEN REPORTING SKIPPED] No user_id in context
```

### ❌ When QUOTA_ENABLED is off:
```
No report output at all
```

## What to Check

1. **QUOTA_ENABLED environment variable**:
   ```bash
   echo $QUOTA_ENABLED  # Must be "true"
   ```

2. **Send a real task** (not just greeting):
   - "Send email to john@doe.com saying hello"
   - "Search my emails for meeting notes"
   - "Create a Google Doc called 'Minutes'"

3. **Watch for `[TOKEN REPORTING]` in console**:
   - Greeting → should show 0 tokens (no LLM used)
   - Task → should show actual token count
   - Execution → should show more tokens

4. **Check token-quota-service logs**:
   ```
   POST /quota/report received
   Status: 200 (success) or 404 (user not found)
   ```

5. **Verify frontend displays tokens**:
   - Token Management page → Usage Logs tab
   - Should see entries from "supervisor" service

## Files Modified

- `logging_config.py`:
  - Added `contextvars.ContextVar` imports
  - Updated all getter functions to use contextvars
  - Updated `set_request_context()` to use contextvars
  - Updated `clear_request_context()` to use contextvars
  - Added debug print for token reporting

## Expected Behavior Now

When user sends a task request that triggers LLM calls:

```
Terminal Output:
[CONTEXT SET] request_id=req_20251205_abc123, user_id=5ace696a-1501-46f4-803c-116b9d3bd309, thread_id=5ace696a_conv123
[TOKEN REPORTING] user_id=5ace696a-1501-46f4-803c-116b9d3bd309, success=True, operation=tier_1_full_analysis, tokens=250
📊 Reported 250 tokens to quota service for user 5ace696a-1501-46f4-803c-116b9d3bd309

Frontend (Token Management):
- Usage Logs tab shows: supervisor | tier_1_full_analysis | 250 tokens | Nov 5 | 19:39:25
```

If this doesn't happen, the issue is likely:
1. QUOTA_ENABLED not set to "true"
2. Token-quota-service not running
3. User not created in quota service database
