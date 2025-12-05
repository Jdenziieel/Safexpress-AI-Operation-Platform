# 🧪 Test Mode for Unified LLM

## What Changed?

Added a **test mode** flag to `ConversationalAgent` that stops execution immediately after the Unified LLM call (Tier 0.5) and saves the JSON output.

### Modified Files:
1. **conversational_agent.py**:
   - Added `test_mode` parameter to `__init__` (line 87)
   - Added early return in `_unified_quick_check()` when `test_mode=True` (after line 515)

### New Test Scripts:
1. **test_unified_quick.py** - Single message testing (fast iteration)
2. **test_unified_llm.py** - Full test suite with multiple cases

---

## How to Use

### Option 1: Quick Single Test (Recommended for Development)

**File:** `test_unified_quick.py`

```python
# 1. Edit the USER_MESSAGE variable
USER_MESSAGE = "yes"  # Change this to test different inputs

# 2. Run the script
python test_unified_quick.py

# 3. Check the output
# - Console shows the response
# - Unified_LLM_results.json has full JSON
```

**Example:**
```bash
cd supervisor-agent
python test_unified_quick.py
```

---

### Option 2: Run Full Test Suite

**File:** `test_unified_llm.py`

Tests all categories:
- ✅ Confirmations ("yes", "ok")
- ❌ Cancellations ("cancel", "nevermind")
- ✏️ Modifications ("change subject to X")
- 💬 Followup answers ("john@example.com")
- 🎯 Task requests ("send email")
- 🗣️ Casual conversation ("how are you")
- ❓ Unintelligible ("asdfkj")

```bash
python test_unified_llm.py
```

---

### Option 3: Enable Test Mode in Your Own Code

```python
from conversational_agent import ConversationalAgent

# Enable test mode
agent = ConversationalAgent(
    openai_api_key="your-key",
    test_mode=True  # 👈 Add this
)

# Now all messages will stop after Unified LLM
response, state = agent.process_message("yes")
# ✅ Saves to Unified_LLM_results.json
# ✅ Returns dummy response
# ✅ No full analysis runs
```

---

## What Happens in Test Mode?

### Normal Flow (test_mode=False):
```
User message
  ↓
Tier 0: Pattern checks
  ↓
Tier 0.5: Unified LLM ← Saves JSON
  ↓
Tier 1: Full analysis (if needed)
  ↓
Response to user
```

### Test Mode Flow (test_mode=True):
```
User message
  ↓
Tier 0: Pattern checks
  ↓
Tier 0.5: Unified LLM ← Saves JSON
  ↓
🛑 STOPS HERE
  ↓
Returns test response with JSON data
```

---

## Output Format

### Console Output:
```
🧪 TEST MODE: Saved JSON to Unified_LLM_results.json
📊 Result: {
  "category": "confirmation",
  "confidence": "high",
  "reasoning": "Clear approval",
  ...
}

🤖 Response:
🧪 TEST MODE: Unified LLM returned:
```json
{
  "category": "confirmation",
  "confidence": "high",
  "reasoning": "Clear approval"
}
```

Saved to `Unified_LLM_results.json`
```

### JSON File (Unified_LLM_results.json):
```json
{
    "category": "confirmation",
    "confidence": "high",
    "reasoning": "Clear approval",
    "query_scope": "specific",
    "has_compound_cancel": false,
    "extracted_value": null,
    "field_to_modify": null,
    "new_value": null
}
```

---

## Quick Testing Workflow

1. **Edit** `test_unified_quick.py` → Change `USER_MESSAGE`
2. **Run** `python test_unified_quick.py`
3. **Check** `Unified_LLM_results.json`
4. **Iterate** - Change message, run again

### Example Iteration:
```python
# Test 1: Confirmation
USER_MESSAGE = "yes"
# Run → Check JSON → category: "confirmation"

# Test 2: Cancellation
USER_MESSAGE = "cancel"
# Run → Check JSON → category: "cancellation"

# Test 3: Compound cancel
USER_MESSAGE = "cancel and send email to john"
# Run → Check JSON → has_compound_cancel: true
```

---

## Disable Test Mode for Production

In `supervisor_agent.py` (line 69):

```python
# Production mode (default)
conversational_agent = ConversationalAgent(
    openai_api_key=config.OPENAI_API_KEY
    # test_mode defaults to False
)

# Test mode (only for testing)
conversational_agent = ConversationalAgent(
    openai_api_key=config.OPENAI_API_KEY,
    test_mode=True  # 👈 Only add when testing
)
```

---

## Benefits

✅ **Faster Testing** - No full analysis, only Unified LLM
✅ **JSON Output** - Easy to inspect LLM responses
✅ **No Side Effects** - Doesn't run full conversation flow
✅ **Clean Iteration** - Change message, run, check JSON
✅ **Non-Destructive** - Original code preserved, just add flag

---

## Reverting to Normal Mode

Remove or set `test_mode=False`:

```python
agent = ConversationalAgent(
    openai_api_key="your-key"
    # test_mode removed or set to False
)
```

That's it! Full conversation flow resumes.
