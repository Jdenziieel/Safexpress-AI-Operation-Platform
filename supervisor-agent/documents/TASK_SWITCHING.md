# 🔄 Task Switching & State Management

## Problem

When users cancel a task and switch to a completely different task, the old task data was **persisting and mixing** with the new task data, creating confusion.

### Example of the Problem (BEFORE):

```
User: "Send email to john@example.com about Q4 Planning"
Bot: [Collects subject, body...]

User: "Cancel that"
Bot: "Cancelled! Data preserved in case you want to modify it."

User: "Search my emails from john@example.com"
Bot: "Ready to execute!"

extracted_info = {
    'recipient': 'john@example.com',  ← From CANCELLED email task
    'subject': 'Q4 Planning',          ← From CANCELLED email task
    'body': "Let's meet tomorrow...",  ← From CANCELLED email task
    'query': 'from:john@example.com',  ← From NEW search task
    'max_results': 10                  ← From NEW search task
}

❌ PROBLEM: Mixed data from 2 different tasks!
```

---

## Solution

Added **Smart Task Detection** that:
1. Detects when user switches to a completely different task type
2. Cleans old task-specific data
3. Preserves only shared/relevant fields

---

## Implementation

### 1. Task Detection Method

```python
def _detect_task_change(self, new_task_type: str, old_extracted_info: Dict) -> bool:
    """Detect if user is switching to a completely different task"""
    
    # Define task-specific field patterns
    task_patterns = {
        'email': ['to', 'recipient', 'subject', 'body', 'cc', 'bcc'],
        'search': ['query', 'max_results', 'label_ids'],
        'document': ['title', 'doc_id', 'document_id', 'content'],
        'calendar': ['event_title', 'start_time', 'end_time', 'attendees']
    }
    
    # Detect what task the old data belongs to
    old_task_types = set()
    for task, fields in task_patterns.items():
        if any(field in old_extracted_info for field in fields):
            old_task_types.add(task)
    
    # Map new task to category
    task_mapping = {
        'send_email': 'email',
        'search_emails': 'search',
        'create_document': 'document',
        # ... etc
    }
    
    new_task_category = task_mapping.get(new_task_type, new_task_type)
    
    # If categories don't match, it's a task switch
    if old_task_types and new_task_category not in old_task_types:
        print(f"🔄 Task switch detected: {old_task_types} → {new_task_category}")
        return True
    
    return False
```

### 2. State Cleaning Method

```python
def _clean_state_for_new_task(
    self,
    new_task_type: str,
    new_extracted_info: Dict,
    old_extracted_info: Dict
) -> Dict:
    """Clean old task data when switching to a new task"""
    
    # Shared fields that can transfer between tasks
    shared_fields = {'date', 'time', 'from_date', 'to_date', 'user_name', 'user_email'}
    
    # Start with new extracted info
    cleaned = new_extracted_info.copy()
    
    # Add back only shared fields from old data
    for key, value in old_extracted_info.items():
        if key in shared_fields and key not in cleaned:
            cleaned[key] = value
    
    return cleaned
```

### 3. Integration in process_message()

```python
# In process_message(), after analyze_request():

# SMART TASK CHANGE DETECTION
if analysis.intent not in [ConversationIntent.SMALL_TALK, ConversationIntent.CANCELLED]:
    if self._detect_task_change(analysis.task_type, conversation_state.extracted_info):
        # User switched tasks - clean old task data
        print(f"🧹 Cleaning old task data for new task: {analysis.task_type}")
        cleaned_info = self._clean_state_for_new_task(
            analysis.task_type,
            analysis.extracted_info,
            conversation_state.extracted_info
        )
        # Replace extracted_info entirely with cleaned version
        conversation_state.extracted_info = cleaned_info
    else:
        # Same task or first task - merge as usual
        for key, value in analysis.extracted_info.items():
            if value is not None and value != "":
                conversation_state.extracted_info[key] = value
```

---

## Behavior Comparison

### BEFORE (Data Accumulation)

```
Step 1: Email Task
User: "Send email to john@example.com"
State: {recipient: "john@example.com", subject: "Q4 Planning"}

Step 2: Cancel
User: "Cancel"
State: {recipient: "john@example.com", subject: "Q4 Planning"}  ← Preserved

Step 3: Switch to Search
User: "Search my emails from john"
State: {
    recipient: "john@example.com",  ← Still there! ❌
    subject: "Q4 Planning",          ← Still there! ❌
    query: "from:john@example.com",  ← New search data
    max_results: 10
}
❌ Mixed data from 2 tasks!

Step 4: Switch to Document
User: "Create a doc titled Overview"
State: {
    recipient: "john@example.com",  ← Still there! ❌
    subject: "Q4 Planning",          ← Still there! ❌
    query: "from:john@example.com",  ← Still there! ❌
    max_results: 10,                 ← Still there! ❌
    title: "Overview"                ← New doc data
}
❌ Mixed data from 3 tasks!
```

### AFTER (Smart Cleanup)

```
Step 1: Email Task
User: "Send email to john@example.com"
State: {recipient: "john@example.com", subject: "Q4 Planning"}

Step 2: Cancel
User: "Cancel"
State: {recipient: "john@example.com", subject: "Q4 Planning"}  ← Preserved
Intent: CANCELLED

Step 3: Switch to Search
User: "Search my emails from john"
🔄 Task switch detected: {'email'} → 'search'
🧹 Cleaning old task data
State: {
    query: "from:john@example.com",  ← Only search data
    max_results: 10
}
✅ Clean state! Old email data removed.

Step 4: Switch to Document
User: "Create a doc titled Overview"
🔄 Task switch detected: {'search'} → 'document'
🧹 Cleaning old task data
State: {
    title: "Overview"  ← Only document data
}
✅ Clean state! Old search data removed.
```

---

## Edge Cases Handled

### Case 1: Modify vs Switch

```
User: "Send email to john@example.com"
State: {recipient: "john@example.com"}

User: "Actually, send it to sarah@example.com"
🔍 Same task type (email) → NO CLEANUP
State: {recipient: "sarah@example.com"}  ← Modified, not switched
✅ Correct behavior
```

### Case 2: Shared Fields Preserved

```
User: "Send email to john@example.com for tomorrow's meeting"
State: {
    recipient: "john@example.com",
    date: "tomorrow"  ← Shared field
}

User: "Search emails from yesterday"
🔄 Task switch detected: {'email'} → 'search'
🧹 Cleaning, but preserving shared fields
State: {
    query: "...",
    date: "tomorrow"  ← Preserved! Might be useful
}
✅ Smart preservation
```

### Case 3: First Task (No Old Data)

```
User: "Search my emails"
🔍 No old data → NO CLEANUP NEEDED
State: {query: "..."}
✅ Normal behavior
```

---

## Task Categories

The system recognizes these task categories:

| Task Type | Field Patterns | Examples |
|-----------|---------------|----------|
| **Email** | `to`, `recipient`, `subject`, `body`, `cc`, `bcc` | send_email, reply_to_email |
| **Search** | `query`, `max_results`, `label_ids` | search_emails |
| **Document** | `title`, `doc_id`, `content` | create_document, edit_document |
| **Calendar** | `event_title`, `start_time`, `end_time`, `attendees` | schedule_event |
| **Draft** | `draft_id`, `to`, `subject`, `body` | create_draft |

---

## Testing

Run the comprehensive test:

```bash
python test_cancellation_task_switch.py
```

**Expected output:**
```
✅ GOOD: Old email data cleared, new search task data present
✅ GOOD: Only current task data present (document)
```

---

## Benefits

1. ✅ **No Data Confusion**: Each task has clean, relevant data only
2. ✅ **Better UX**: Users can switch tasks freely without data pollution
3. ✅ **Preserved Cancellation**: Cancelled tasks still preserve data for modification
4. ✅ **Smart Detection**: Automatically detects task type changes
5. ✅ **Shared Fields**: Dates and common fields can transfer between tasks

---

## Future Enhancements

Possible improvements:

1. **Task History Stack**: Keep a history of cancelled tasks for "undo/redo"
2. **Explicit Task Clearing**: `"Start fresh"` or `"New task"` commands
3. **Task Context Switching**: `"Go back to my email task"`
4. **Multi-Task Mode**: Allow users to work on multiple tasks in parallel with namespacing
5. **Smart Field Transfer**: ML-based detection of which fields are actually relevant to transfer

---

## Configuration

To adjust task detection behavior, modify the `task_patterns` dictionary in `_detect_task_change()`:

```python
task_patterns = {
    'email': ['to', 'recipient', 'subject', 'body', 'cc', 'bcc'],
    'search': ['query', 'max_results', 'label_ids'],
    # Add more patterns...
}
```

To adjust shared fields, modify `shared_fields` in `_clean_state_for_new_task()`:

```python
shared_fields = {'date', 'time', 'from_date', 'to_date', 'user_name', 'user_email'}
# Add more shared fields...
```
