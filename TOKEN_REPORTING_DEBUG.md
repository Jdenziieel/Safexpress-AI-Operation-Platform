# Token Reporting Debug Analysis

## Issue: Tokens Not Being Reported to Token-Quota-Service

### Flow Analysis

#### 1. Frontend (AIChatNew.jsx)
- User sends message via `/threads/{thread_id}/messages`
- `thread_id` format: `{user_id}_{conv_id}` (e.g., `550e8400_conv123`)

#### 2. Supervisor Agent (/threads/{thread_id}/messages) - LINE 2878
```python
@app.post("/threads/{thread_id}/messages")
async def send_message_to_thread(thread_id: str, request: dict):
    # Extract user_id from thread_id
    user_id = thread_id.split('_')[0] if '_' in thread_id else None  # LINE 2917
    
    # Set request context WITH user_id
    request_id = set_request_context(
        request_id=generate_request_id(),
        conversation_id=conversation_id,
        thread_id=thread_id,
        user_id=user_id  # ← USER_ID IS SET HERE
    )
    
    # Execute workflow
    workflow_result = await execute_workflow(workflow_request)  # LINE 2975
```

#### 3. Workflow Execution → LLM Calls
- Inside workflow, LLM is called
- `logger.llm_call()` is invoked (e.g., line 478)

#### 4. Token Reporting (logging_config.py - LINE 498-600)
```python
def llm_call(self, model, operation, input_tokens, output_tokens, ...):
    # Report to Token Quota Service IF:
    user_id = get_current_user_id()  # LINE 536 - Gets user_id from thread-local context
    
    if user_id and success:  # LINE 537 - ISSUE: Both must be true
        try:
            _report_quota_usage(
                user_id=user_id,
                service="supervisor",
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                operation=operation,
                cost_usd=cost,
                request_id=get_current_request_id(),
                session_id=get_current_conversation_id()  # ← Should be session_id
            )
```

### Potential Issues Found

#### ✅ Issue 1: user_id extraction from thread_id
- **Status**: VERIFIED ✅
- Thread ID format is correct: `{user_id}_{conv_id}`
- Extraction at line 2917 should work

#### ✅ Issue 2: set_request_context being called with user_id
- **Status**: VERIFIED ✅
- Line 2919-2925 sets user_id in request context

#### ⚠️ Issue 3: get_current_user_id() returning None
- **Possible Cause**: Thread-local storage not preserving user_id
- **Debug**: Add print statement to verify user_id is in context
- **Location**: logging_config.py line 536

#### ⚠️ Issue 4: Token reporting only if success=True
- **Issue**: If any exception occurs during workflow, reporting won't happen
- **Location**: logging_config.py line 537
- **Fix**: Report tokens even on partial success

#### ⚠️ Issue 5: session_id parameter mismatch
- **Issue**: Using `get_current_conversation_id()` for session_id
- **Expected**: Should probably use request_id or a proper session_id
- **Location**: logging_config.py line 551

#### ⚠️ Issue 6: QUOTA_ENABLED check
- **Issue**: If `QUOTA_ENABLED` env var is not set or False, reporting is skipped
- **Location**: logging_config.py line 173
- **Check**: Verify env var `QUOTA_ENABLED=true`

### Token-Quota-Service Expected Input
```json
POST /quota/report
{
  "user_id": "550e8400-...",     // UUID format
  "service": "supervisor",
  "model": "gpt-4o",
  "input_tokens": 100,
  "output_tokens": 50,
  "operation": "plan_generation",
  "cost_usd": 0.00275,
  "request_id": "req_...",
  "session_id": "conv_...",
  "metadata": {...}
}
```

### Debugging Steps

1. **Check QUOTA_ENABLED**:
   ```bash
   echo $QUOTA_ENABLED  # Should be "true"
   ```

2. **Add debug to logging_config.py line 536**:
   ```python
   user_id = get_current_user_id()
   print(f"[DEBUG] Token reporting check: user_id={user_id}, success={success}")
   ```

3. **Verify thread_id format being sent from frontend**:
   - Check browser console: `console.log(currentThreadId)`
   - Should see: `550e8400-...e85f_conv_...`

4. **Check token-quota-service logs**:
   - Should see POST /quota/report requests
   - If not, tokens aren't being reported

5. **Verify /quota/admin/logs endpoint**:
   - `curl http://localhost:8011/quota/admin/logs?page=1&page_size=5`
   - Should show records from supervisor service

### Hypothesis: Most Likely Cause
The issue is that `get_current_user_id()` is returning **None** because:
- The thread-local context is not being properly passed through async function calls
- Or the user_id is being cleared before token reporting happens

### Fix Strategy
1. Verify thread-local context preservation across async calls
2. Add explicit user_id parameter to token reporting
3. Add debug logging to confirm user_id at reporting time
4. Ensure QUOTA_ENABLED=true in environment
