# Thread Endpoints Testing

Test files for the Thread Management API endpoints.

## 📋 Test Files

### 1. `test_threads.py` - Comprehensive Test Suite
Complete test coverage with 9 test scenarios:

- ✅ Create thread without initial message
- ✅ Create thread with initial message (clarification needed)
- ✅ Create thread with auto-execution
- ✅ Send message to thread (continue conversation)
- ✅ Send message that triggers execution
- ✅ Conflict prevention (409 error when executing)
- ✅ List threads for user
- ✅ Get thread metadata
- ✅ Get thread messages (conversation history)

**Run:**
```bash
python test_threads.py
```

### 2. `test_threads_quick.py` - Quick Test
Simple 3-step test for rapid validation:

1. Create thread with initial message
2. Send follow-up message
3. Retrieve conversation history

**Run:**
```bash
python test_threads_quick.py
```

## 🚀 Prerequisites

1. **Start the server:**
   ```bash
   python supervisor_agent.py
   ```
   Server should be running on `http://localhost:8000`

2. **Install requests library** (if not already installed):
   ```bash
   pip install requests
   ```

## 📊 Test Scenarios Covered

### Scenario 1: Multi-Turn Conversation
```
User: "I want to send an email"
Bot: "Who would you like to send this email to?"
User: "john@example.com"
Bot: "What should the subject be?"
User: "Meeting notes"
...continues until ready...
```

### Scenario 2: Auto-Execution
```
User: "Search my emails from john@example.com from last week"
Bot: [Executes immediately and returns friendly summary]
```

### Scenario 3: Conflict Prevention
```
Thread is executing...
User tries to send new message → HTTP 409 Conflict
"Thread is currently executing. Please wait..."
```

## 🎯 Expected Results

### Successful Thread Creation
```json
{
  "thread_id": "thread_abc123",
  "user_id": "test_user_123",
  "metadata": {...},
  "message": "Thread created successfully",
  "bot_response": "Hello! 👋 I'm here to help...",
  "ready_for_execution": false
}
```

### Execution Summary Response
```json
{
  "thread_id": "thread_abc123",
  "bot_response": "✅ Successfully searched your emails...\n\nFound 5 emails from john@example.com...",
  "ready_for_execution": false,
  "metadata": {...}
}
```

### Conflict Error (409)
```json
{
  "detail": "Thread is currently executing. Please wait until the operation completes."
}
```

## 🔍 Debugging

If tests fail:

1. **Check server logs** - Look for error messages in the terminal running `supervisor_agent.py`
2. **Verify database** - Check that `threads.db` is writable
3. **Check OpenAI API** - Ensure `OPENAI_API_KEY` is set
4. **Verify endpoints** - All endpoints in `supervisor_agent.py` should be registered

## 📝 Notes

- Tests create threads with `test_user_*` user IDs
- Each test run creates new threads (no cleanup by default)
- Some tests have delays (`time.sleep()`) to allow execution to complete
- Conflict test (Test 6) may not always catch execution in progress if it completes too quickly

## 🎨 Output Colors

- 🔵 **Blue** - Test headers and info
- 🟢 **Green** - Success messages
- 🔴 **Red** - Error messages
- 🟡 **Yellow** - Information messages

## 🧹 Cleanup

To clean up test threads from database:

```sql
sqlite3 threads.db
DELETE FROM threads WHERE user_id LIKE 'test_user_%';
DELETE FROM messages WHERE thread_id IN (SELECT thread_id FROM threads WHERE user_id LIKE 'test_user_%');
.quit
```
