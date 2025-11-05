# Simple Cancellation for Multi-Task Scenarios

## Overview
For multi-task scenarios with a supervisor workflow planning layer, cancellation **completely empties** `extracted_info` to ensure clean state management.

## Design Philosophy

### Why Empty Everything?
1. **Supervisor Layer Handles Planning**: Your supervisor workflow planning layer accepts user query + extracted fields and plans execution
2. **Avoid Contamination**: Cancelled task fields could confuse the planner when processing a new task
3. **Simplicity**: Easier to reason about - cancel = clean slate
4. **Ask When Needed**: If user cancels and the new task needs related info, just ask for it

### Example Flow
```
User: "Send email to alice@example.com about Project Update"
Agent: "What should the body be?"
State: {recipient: "alice@example.com", subject: "Project Update"}

User: "Cancel that"
Agent: "Request cancelled. What would you like to do next?"
State: {}  ✅ EMPTY

User: "Search emails from bob@example.com"
Agent: "I'll search emails from bob@example.com"
State: {query: "from:bob@example.com", max_results: 10}  ✅ CLEAN START
```

## Implementation

### 1. Cancellation Detection (in `_quick_intent_check`)
```python
if category == "cancellation":
    print(f"🔍 Quick check: CANCELLATION - user cancelled request")
    # Store what was cancelled for user feedback
    cancelled_task_info = conversation_state.extracted_info.copy()
    
    return ConversationAnalysis(
        intent=ConversationIntent.CANCELLED,
        task_type="cancellation",
        extracted_info={},  # ✅ Clear everything!
        missing_fields=[],
        clarification_question=None,
        reasoning=f"User cancelled request. Previous data: {cancelled_task_info}",
        suggested_alternatives=None,
        execution_ready=False,
        execution_summary=None
    )
```

### 2. State Cleanup (in `process_message`)
```python
# Handle cancellation first - clear everything!
if analysis.intent == ConversationIntent.CANCELLED:
    conversation_state.extracted_info = {}  # ✅ Empty for multi-task scenarios
    conversation_state.missing_fields = []
    conversation_state.clarification_question = None
    conversation_state.ready_for_execution = False
    conversation_state.execution_summary = None
else:
    # Normal merge for other intents
    for key, value in analysis.extracted_info.items():
        if value is not None and value != "":
            conversation_state.extracted_info[key] = value
```

### 3. User Feedback (in response generation)
```python
elif analysis.intent == ConversationIntent.CANCELLED:
    response = "👍 No problem! Request cancelled.\n\n"
    
    # Extract cancelled info from reasoning for user feedback
    # Shows what was cancelled without storing it
    if "Previous data:" in analysis.reasoning:
        # Parse and display cancelled data
        response += "**Cancelled request:**\n- recipient: alice@example.com\n- subject: Project Update\n\n"
    
    response += "What would you like to do next?"
```

## Benefits

### ✅ Clean State Management
- No data accumulation across different tasks
- Each new task starts with empty `extracted_info`
- No risk of old fields confusing supervisor planner

### ✅ Supervisor-Friendly
```python
# Supervisor receives clean data
supervisor_input = {
    "user_query": "Search emails from bob@example.com",
    "extracted_fields": {
        "query": "from:bob@example.com",
        "max_results": 10
    }
}
# No old email recipient/subject/body fields!
```

### ✅ Simple Logic
- No complex task detection
- No field mapping maintenance
- No cleanup heuristics
- Cancel = empty, always

### ✅ User-Friendly
- User sees what was cancelled (from response)
- If they want to continue with similar task, agent asks for missing fields
- Natural conversation flow

## Test Scenarios

### Scenario 1: Cancel Email, Switch to Search
```
User: "Send email to alice@example.com about Meeting"
State: {recipient: "alice@example.com", subject: "Meeting"}

User: "Cancel"
State: {}  ✅ EMPTY

User: "Search my emails from bob@example.com"  
State: {query: "from:bob@example.com", max_results: 10}  ✅ CLEAN
```

### Scenario 2: Cancel Search, Switch to Document
```
User: "Search emails about invoices"
State: {query: "invoices", max_results: 10}

User: "Cancel"
State: {}  ✅ EMPTY

User: "Create doc titled Q4 Report"
State: {title: "Q4 Report"}  ✅ CLEAN
```

### Scenario 3: Related Tasks After Cancel
```
User: "Send email to alice@example.com"
State: {recipient: "alice@example.com"}

User: "Cancel"
State: {}  ✅ EMPTY

User: "Actually send it to bob@example.com instead"
Agent: "I'll need the email details:"
Agent: "- Who should I send to?" 
User: "bob@example.com"
Agent: "- What's the subject?"
User: "Project Update"
... (agent asks for missing fields)
```

## Comparison with Previous Approach

### Old Approach (Preserved + Task Detection)
- ❌ Complex task type detection
- ❌ Field mapping for all task types  
- ❌ Cleanup heuristics needed
- ❌ Risk of incomplete cleanup
- ✅ Preserved data for modification

### New Approach (Simple Empty)
- ✅ No task detection needed
- ✅ No field mapping maintenance
- ✅ Always clean state
- ✅ Supervisor-friendly
- ✅ Agent asks if fields needed

## When to Use This Approach

✅ **Use when:**
- You have a supervisor/planning layer
- Multi-task scenarios are common
- Clean state separation is critical
- You want simple, predictable behavior

❌ **Don't use when:**
- Single-task focused app
- Users frequently cancel and modify (not switch tasks)
- You want to preserve data for quick modifications

## Integration with Supervisor

### Before (with accumulated data)
```python
# ❌ PROBLEM: Old email fields mixed with search data
supervisor_plan = supervisor.plan({
    "query": "Search emails from bob@example.com",
    "fields": {
        "recipient": "alice@example.com",  # ❌ From cancelled email
        "subject": "Meeting",              # ❌ From cancelled email
        "query": "from:bob@example.com",   # ✅ Current task
        "max_results": 10                  # ✅ Current task
    }
})
```

### After (clean state)
```python
# ✅ CLEAN: Only current task data
supervisor_plan = supervisor.plan({
    "query": "Search emails from bob@example.com",
    "fields": {
        "query": "from:bob@example.com",
        "max_results": 10
    }
})
```

## Code Removed

We removed the complex task switching logic:
- `_detect_task_change()` method (~45 lines)
- `_clean_state_for_new_task()` method (~40 lines)
- Task type field mappings
- Cleanup integration in `process_message()`

**Total:** ~100 lines of complex logic removed, replaced with simple empty on cancel.

## Future Enhancements

### Optional: "Restore" Command
If users want to restore cancelled data:
```python
# Store last cancelled state
conversation_state.last_cancelled = cancelled_task_info.copy()

# Restore command
if user_says("restore"):
    conversation_state.extracted_info = conversation_state.last_cancelled.copy()
```

### Optional: Cancellation History
Track what was cancelled for analytics:
```python
conversation_state.cancellation_history.append({
    "timestamp": datetime.now(),
    "task_type": analysis.task_type,
    "data": cancelled_task_info
})
```

## Summary

✅ **Simple**: Cancel = empty everything  
✅ **Clean**: No data accumulation  
✅ **Supervisor-friendly**: Only current task data  
✅ **User-friendly**: Agent asks if fields needed  
✅ **Maintainable**: No complex cleanup logic  

For multi-task scenarios with supervisor planning, **simplicity wins**.
