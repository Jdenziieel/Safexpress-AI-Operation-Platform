# Compound "Cancel + New Task" Handling

## Overview
Gracefully handles when users say **"cancel X and do Y"** in a single message, providing a smooth UX without requiring two separate messages.

## The Problem

Before this feature, users had to cancel and then start a new task separately:
```
User: "Cancel that email"
Bot: "Request cancelled. What would you like to do next?"
User: "Search my emails from bob@example.com"
Bot: "I'll search..."
```

This felt clunky for compound requests like:
- "Cancel that email and search for invoices instead"
- "Forget that and create a doc titled Report"
- "Nevermind, send it to alice@example.com instead"

## The Solution

### Three-Stage Detection

#### Stage 1: Quick Intent Check
```python
# In _quick_intent_check()
if category == "cancellation":
    # Detect compound pattern
    task_keywords = ["send", "search", "create", "schedule", ...]
    has_new_task = any(keyword in user_message.lower() for keyword in task_keywords)
    
    if has_new_task:
        # Compound: "cancel X and do Y"
        print("🔍 CANCEL+NEW_TASK detected - proceeding to full analysis")
        return None  # Let full analysis handle both
    else:
        # Pure cancellation
        return ConversationAnalysis(intent=CANCELLED, extracted_info={}, ...)
```

#### Stage 2: Full Analysis with LLM
```python
# Enhanced system prompt in analyze_request()
"""
SPECIAL HANDLING FOR COMPOUND "CANCEL + NEW TASK" REQUESTS:
- If user says "cancel X and do Y" in ONE message:
  1. IGNORE all previous context completely
  2. Extract ONLY the NEW task (the Y part)
  3. Set intent based on NEW task (not "cancelled")
  4. Example: "Cancel email and search invoices" → Extract search, ignore email
"""
```

The LLM naturally understands this pattern and extracts only the new task.

#### Stage 3: State Cleanup
```python
# In process_message()
# Detect compound cancel pattern
has_cancel = any(keyword in user_lower for keyword in ["cancel", "forget", "nevermind"])
has_task = any(keyword in user_lower for keyword in ["send", "search", "create", ...])
is_compound = has_cancel and has_task and intent != CANCELLED

if is_compound:
    # Clear old state, use only new task data
    conversation_state.extracted_info = {}
```

## How It Works

### Example Flow: "Cancel email and search"

```
1. User Input:
   "Cancel that email and search my emails from bob@example.com"
   
   State Before: {recipient: "alice@example.com", subject: "Meeting", body: "..."}

2. Quick Intent Check:
   - Detects "cancel" keyword ✓
   - Detects "search" keyword ✓
   - Returns None → Fall through to full analysis

3. Full Analysis (LLM):
   - Sees: "User wants to cancel email AND start new search"
   - Ignores old email context per instructions
   - Extracts: {query: "from:bob@example.com", max_results: 10}
   - Returns: ConversationIntent.READY_TO_EXECUTE (NOT CANCELLED!)

4. Process Message:
   - Detects compound pattern (has "cancel" + has "search")
   - Clears state: conversation_state.extracted_info = {}
   - Merges new data: {query: "from:bob@example.com", max_results: 10}
   
   State After: {query: "from:bob@example.com", max_results: 10}
   Intent: READY_TO_EXECUTE ✅

5. User Response:
   "I'll search your emails from bob@example.com. I found 5 results..."
```

## Supported Patterns

### ✅ Works With

**Direct compound:**
- "Cancel that email and search for invoices"
- "Forget that and create a doc titled Report"
- "Nevermind, send it to alice@example.com instead"

**With connectors:**
- "Cancel that and search emails instead"
- "Actually cancel that, I want to create a document"
- "No wait, cancel and search for bob@example.com"

**Different cancel words:**
- "Forget that and..." (forget)
- "Nevermind, create..." (nevermind)
- "Stop that and..." (stop)

### ❌ Still Requires Two Messages

**Pure cancellation:**
- "Cancel that" → Returns CANCELLED intent
- "Nevermind" → Returns CANCELLED intent
- "Forget it" → Returns CANCELLED intent

*These don't have new task keywords, so they return CANCELLED as expected.*

## Implementation Details

### Detection Keywords

**Cancel Keywords:**
```python
["cancel", "nevermind", "forget", "stop"]
```

**Task Keywords:**
```python
["send", "search", "create", "schedule", "find", 
 "draft", "reply", "add", "edit", "delete", "update"]
```

### LLM Instructions
The full analysis prompt includes special handling:
```
SPECIAL HANDLING FOR COMPOUND "CANCEL + NEW TASK" REQUESTS:
- If user says "cancel X and do Y" in ONE message:
  1. IGNORE all previous context and extracted_info completely
  2. Extract ONLY the NEW task information (the Y part)
  3. Set intent based on the NEW task (ready_to_execute, needs_clarification, etc.)
  4. Do NOT set intent to "cancelled" - treat it as a fresh new task
```

This leverages the LLM's natural language understanding rather than complex pattern matching.

## Benefits

### ✅ Better UX
- One message instead of two
- Natural conversation flow
- Matches how humans naturally speak

### ✅ Clean State
- Old task data completely cleared
- Only new task data in `extracted_info`
- No contamination for supervisor planner

### ✅ Simple Implementation
- Minimal code (~30 lines across 3 locations)
- Leverages LLM intelligence
- No complex field mappings

### ✅ Backwards Compatible
- Pure cancellation still works (returns CANCELLED)
- Pure new tasks still work (no cancel keyword)
- Existing tests still pass

## Test Coverage

```python
# Test 1: Compound cancel + new task
"Cancel that email and search my emails from bob@example.com"
✅ Old email data cleared
✅ New search data extracted
✅ Intent = READY_TO_EXECUTE (not CANCELLED)

# Test 2: Multiple compound cancels
"Cancel that and create a Google doc titled Meeting Notes"
✅ Old data cleared
✅ New doc data extracted

# Test 3: Pure cancellation still works
"Cancel that document"
✅ Intent = CANCELLED
✅ State = {} (empty)

# Test 4: Different phrasings
"Actually cancel that and search for invoices instead"
✅ Compound pattern detected
✅ New search extracted
```

## Architecture Comparison

### Before (Two Messages Required)
```
User: "Cancel that email"
  ↓
Quick Check: CANCELLATION
  ↓
State: {} (empty)
Response: "Request cancelled. What would you like to do?"
  ↓
User: "Search emails from bob"
  ↓
Quick Check: TASK_REQUEST
  ↓
Full Analysis: Extract search
  ↓
State: {query: "from:bob", max_results: 10}
```

### After (One Message)
```
User: "Cancel that email and search from bob"
  ↓
Quick Check: CANCEL+NEW_TASK → return None
  ↓
Full Analysis: LLM ignores email, extracts search
  ↓
Compound Detection: Clear old state
  ↓
State: {query: "from:bob", max_results: 10}
Response: "I'll search your emails from bob..."
```

**50% fewer messages, cleaner UX!**

## Edge Cases

### ✅ Handled Correctly

**Cancel with modification to same task:**
```
User: "Cancel and send to alice@example.com instead"
→ Clears old recipient, extracts new one
```

**Cancel with completely different task:**
```
User: "Cancel that email and create a document"
→ Clears email fields, extracts document fields
```

**Multiple task keywords:**
```
User: "Cancel and search for invoices then create a report"
→ LLM handles, extracts primary task (search)
→ User can start new task for report creation
```

### ❌ Not Supported (By Design)

**No task keyword after cancel:**
```
User: "Cancel that"
→ Returns CANCELLED (no new task to extract)
```

**Cancel word in non-cancel context:**
```
User: "Search for cancelled orders"
→ No actual cancellation, just contains word "cancel"
→ Handled correctly by LLM context understanding
```

## Supervisor Integration

### Clean Data to Planner

**Before (with contamination):**
```python
# ❌ Old approach mixed old and new data
supervisor.plan({
    "query": "Search from bob",
    "fields": {
        "recipient": "alice@example.com",  # ❌ From cancelled email
        "subject": "Meeting",              # ❌ From cancelled email
        "query": "from:bob",               # ✅ Current task
        "max_results": 10                  # ✅ Current task
    }
})
```

**After (clean):**
```python
# ✅ New approach: only current task data
supervisor.plan({
    "query": "Search from bob",
    "fields": {
        "query": "from:bob",
        "max_results": 10
    }
})
```

## Summary

**What it does:**
- Detects "cancel X and do Y" in one message
- Clears old task data automatically
- Extracts only the new task
- Sets intent to new task (not CANCELLED)

**Why it's better:**
- One message instead of two
- Natural conversation flow
- Clean state for supervisor
- Simple implementation

**How it works:**
1. Quick check detects compound pattern
2. LLM extracts new task (ignoring old context)
3. State cleanup ensures no contamination

**Result:**
✅ Graceful UX + Clean State + Simple Code = Happy Users & Happy Supervisor! 🎉
