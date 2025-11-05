# Migration Guide: Memory-Only → Thread Management System

Quick guide to migrate from memory-only conversations to persistent thread management.

---

## Overview

This guide helps you migrate from the **memory-only** conversational system to the new **thread management system** with persistent storage.

### What Changed?

| Feature | Before (Memory-Only) | After (Thread System) |
|---------|---------------------|----------------------|
| **State Storage** | In-memory dictionary | SQLite database |
| **Persistence** | Lost on restart | Survives restarts |
| **Thread Discovery** | Not available | List & search threads |
| **Auto-Save** | Manual | Automatic |
| **Multi-User** | Manual isolation | Built-in |

---

## Quick Start

### Step 1: Update ConversationalAgent Initialization

**Before:**
```python
from conversational_agent import ConversationalAgent

agent = ConversationalAgent(
    openai_api_key="your-api-key"
)
```

**After:**
```python
from conversational_agent import ConversationalAgent

agent = ConversationalAgent(
    openai_api_key="your-api-key",
    db_path="threads.db"  # NEW: Add database path
)
```

### Step 2: Replace process_message with Thread Methods

**Before:**
```python
# New conversation
response, state = agent.process_message(
    user_message="Send an email",
    conversation_state=None,
    state_id="user123_conv1"
)

# Continue conversation
response, state = agent.process_message(
    user_message="To john@example.com",
    conversation_state=state,
    state_id="user123_conv1"
)
```

**After:**
```python
# New conversation
thread_id, state = agent.create_new_thread(
    user_id="user123",
    initial_message="Send an email"
)

# Continue conversation
response, state = agent.continue_thread(
    thread_id=thread_id,
    new_message="To john@example.com"
)
```

---

## Code Migration Examples

### Example 1: Simple Chat Bot

**BEFORE (Memory-Only):**
```python
from conversational_agent import ConversationalAgent

agent = ConversationalAgent(openai_api_key="key")

# Store states in memory dictionary
conversation_states = {}

def handle_message(user_id, message):
    # Get or create state
    state_id = f"user_{user_id}"
    state = conversation_states.get(state_id)
    
    # Process message
    response, updated_state = agent.process_message(
        user_message=message,
        conversation_state=state,
        state_id=state_id
    )
    
    # Save state back to dictionary
    conversation_states[state_id] = updated_state
    
    return response
```

**AFTER (Thread System):**
```python
from conversational_agent import ConversationalAgent

agent = ConversationalAgent(
    openai_api_key="key",
    db_path="threads.db"  # NEW
)

def handle_message(user_id, message, thread_id=None):
    if thread_id:
        # Continue existing thread
        response, state = agent.continue_thread(
            thread_id=thread_id,
            new_message=message
        )
    else:
        # Create new thread
        thread_id, state = agent.create_new_thread(
            user_id=user_id,
            initial_message=message
        )
        response = agent.get_thread_messages(thread_id)[-1]['content']
    
    return response, thread_id
```

---

### Example 2: FastAPI Endpoint

**BEFORE (Memory-Only):**
```python
from fastapi import FastAPI
from conversational_agent import ConversationalAgent

app = FastAPI()
agent = ConversationalAgent(openai_api_key="key")

# In-memory storage (lost on restart)
CONVERSATIONS = {}

@app.post("/chat")
async def chat(request: dict):
    user_id = request['user_id']
    message = request['message']
    
    # Get state from memory
    state = CONVERSATIONS.get(user_id)
    
    # Process message
    response, updated_state = agent.process_message(
        user_message=message,
        conversation_state=state,
        state_id=user_id
    )
    
    # Save to memory
    CONVERSATIONS[user_id] = updated_state
    
    return {
        "response": response,
        "ready": updated_state.ready_for_execution
    }
```

**AFTER (Thread System):**
```python
from fastapi import FastAPI
from conversational_agent import ConversationalAgent

app = FastAPI()
agent = ConversationalAgent(
    openai_api_key="key",
    db_path="threads.db"  # NEW: Persistent storage
)

@app.post("/chat")
async def chat(request: dict):
    user_id = request['user_id']
    message = request['message']
    thread_id = request.get('thread_id')  # NEW: Optional thread_id
    
    if thread_id:
        # Continue existing thread
        response, state = agent.continue_thread(
            thread_id=thread_id,
            new_message=message
        )
    else:
        # Create new thread
        thread_id, state = agent.create_new_thread(
            user_id=user_id,
            initial_message=message
        )
        # Get bot's response from messages
        messages = agent.get_thread_messages(thread_id)
        response = messages[-1]['content']
    
    return {
        "thread_id": thread_id,  # NEW: Return thread_id
        "response": response,
        "ready": state.ready_for_execution
    }

# NEW: List threads endpoint
@app.get("/threads")
async def list_threads(user_id: str):
    threads = agent.list_user_threads(user_id=user_id)
    return {"threads": threads}
```

---

### Example 3: Multi-User Support

**BEFORE (Memory-Only):**
```python
# Manual user isolation
CONVERSATIONS = {}

def get_state_key(user_id, conversation_id):
    return f"{user_id}_{conversation_id}"

def handle_message(user_id, conversation_id, message):
    state_key = get_state_key(user_id, conversation_id)
    state = CONVERSATIONS.get(state_key)
    
    response, updated_state = agent.process_message(
        user_message=message,
        conversation_state=state,
        state_id=state_key
    )
    
    CONVERSATIONS[state_key] = updated_state
    return response

# No way to list user's conversations
```

**AFTER (Thread System):**
```python
# Built-in user isolation - no manual tracking needed!

def handle_message(user_id, message, thread_id=None):
    if thread_id:
        response, state = agent.continue_thread(
            thread_id=thread_id,
            new_message=message
        )
    else:
        thread_id, state = agent.create_new_thread(
            user_id=user_id,
            initial_message=message
        )
        messages = agent.get_thread_messages(thread_id)
        response = messages[-1]['content']
    
    return response, thread_id

# NEW: List all threads for a user
def list_user_conversations(user_id):
    threads = agent.list_user_threads(user_id=user_id)
    return [
        {
            "thread_id": t['thread_id'],
            "title": t['title'],
            "message_count": t['message_count'],
            "last_updated": t['updated_at']
        }
        for t in threads
    ]
```

---

## API Migration

### REST API Changes

**Before (Memory-Only):**
```
POST /chat
{
  "user_id": "alice",
  "message": "Send an email"
}

→ Response: {"response": "Who should I send..."}
```

**After (Thread System):**
```
POST /threads
{
  "user_id": "alice",
  "message": "Send an email"
}

→ Response: {
  "thread_id": "abc123",
  "bot_response": "Who should I send...",
  "metadata": {...}
}

POST /threads/abc123/messages
{
  "message": "To john@example.com"
}

→ Response: {
  "thread_id": "abc123",
  "bot_response": "What should the subject be?",
  "metadata": {...}
}
```

### New Endpoints Available

```
GET  /threads?user_id=alice               # List threads
GET  /threads/{thread_id}                 # Get metadata
GET  /threads/{thread_id}/messages        # Get history
POST /threads/{thread_id}/messages        # Send message
PUT  /threads/{thread_id}                 # Update metadata
DELETE /threads/{thread_id}               # Archive/delete
GET  /threads/search?user_id=alice&q=...  # Search threads
```

---

## Benefits of Migration

### ✅ Persistence

**Before:** State lost on server restart
```python
# Server restarts → all conversations lost
CONVERSATIONS = {}  # Empty after restart!
```

**After:** State survives restarts
```python
# Server restarts → all threads intact
agent = ConversationalAgent(db_path="threads.db")  # Loads from disk
```

### ✅ Thread Discovery

**Before:** No way to list user's conversations
```python
# How many conversations does Alice have? → Unknown
# What did Alice talk about yesterday? → Can't find it
```

**After:** Full thread discovery
```python
# List Alice's threads
threads = agent.list_user_threads(user_id="alice")

# Search Alice's threads
email_threads = agent.search_threads(user_id="alice", query="email")
```

### ✅ Auto-Save

**Before:** Manual state persistence
```python
response, state = agent.process_message(...)
CONVERSATIONS[key] = state  # Must remember to save!
save_to_file(CONVERSATIONS)  # Must remember to persist!
```

**After:** Automatic persistence
```python
response, state = agent.continue_thread(...)
# ✅ Automatically saved to database!
```

### ✅ Metadata Tracking

**Before:** No metadata
```python
# When was this conversation created? → Unknown
# How many messages? → Must count manually
# What was it about? → No title
```

**After:** Rich metadata
```python
metadata = agent.get_thread_metadata(thread_id)
# ✅ created_at, updated_at, message_count, title, tags
```

---

## Backward Compatibility

### Option 1: Gradual Migration

Keep both systems running:

```python
# Initialize both systems
agent = ConversationalAgent(
    openai_api_key="key",
    db_path="threads.db"
)

# Old endpoint (memory-only)
@app.post("/chat/legacy")
async def chat_legacy(request: dict):
    state = CONVERSATIONS.get(request['user_id'])
    response, updated_state = agent.process_message(
        user_message=request['message'],
        conversation_state=state,
        state_id=request['user_id']
    )
    CONVERSATIONS[request['user_id']] = updated_state
    return {"response": response}

# New endpoint (thread system)
@app.post("/threads")
async def create_thread(request: dict):
    thread_id, state = agent.create_new_thread(
        user_id=request['user_id'],
        initial_message=request['message']
    )
    return {"thread_id": thread_id, ...}
```

### Option 2: Data Migration Script

Migrate existing in-memory states to threads:

```python
def migrate_to_threads(conversations_dict, agent):
    """
    Migrate in-memory conversations to thread system.
    
    Args:
        conversations_dict: Dict[user_id, ConversationState]
        agent: ConversationalAgent with thread management
    """
    for user_id, state in conversations_dict.items():
        # Create thread from existing state
        thread_id = agent.thread_manager.create_thread(
            user_id=user_id,
            title="Migrated Conversation"
        )
        
        # Save state to database
        agent.thread_manager.save_thread_state(thread_id, state)
        
        # Save memory if exists
        if state.memory_state:
            agent.thread_manager.save_memory_state(thread_id, state.memory_state)
        
        print(f"✅ Migrated {user_id} → thread {thread_id}")

# Usage
agent = ConversationalAgent(openai_api_key="key", db_path="threads.db")
migrate_to_threads(CONVERSATIONS, agent)
```

---

## Testing Your Migration

### Step 1: Run Test Script

```bash
cd supervisor-agent
python test_thread_management.py
```

Expected output:
```
✅ Agent initialized with database: test_threads.db
✅ Thread created: abc123
✅ Thread updated successfully
✅ All tests complete!
```

### Step 2: Verify Database

```python
from thread_manager import ThreadManager

manager = ThreadManager(db_path="threads.db")
threads = manager.list_threads(user_id="test_user")

print(f"Found {len(threads)} threads")
for thread in threads:
    print(f"- {thread.title} ({thread.message_count} messages)")
```

### Step 3: Test API Endpoints

```bash
# Create thread
curl -X POST http://localhost:8000/threads \
  -H "Content-Type: application/json" \
  -d '{"user_id": "alice", "message": "Send an email"}'

# List threads
curl http://localhost:8000/threads?user_id=alice

# Continue thread
curl -X POST http://localhost:8000/threads/abc123/messages \
  -H "Content-Type: application/json" \
  -d '{"message": "To john@example.com"}'
```

---

## Common Issues

### Issue 1: Database Not Found

**Error:** `sqlite3.OperationalError: unable to open database file`

**Solution:** Ensure db_path directory exists
```python
import os
os.makedirs("data", exist_ok=True)
agent = ConversationalAgent(
    openai_api_key="key",
    db_path="data/threads.db"
)
```

### Issue 2: Thread ID Required

**Error:** `ValueError: Thread abc123 not found`

**Solution:** Check if thread exists before continuing
```python
metadata = agent.get_thread_metadata(thread_id)
if not metadata:
    # Thread doesn't exist - create new one
    thread_id, state = agent.create_new_thread(user_id=user_id, initial_message=message)
```

### Issue 3: Old States Not Loading

**Problem:** Migrated threads have no messages

**Solution:** Ensure memory_state is copied during migration
```python
# Include memory state in migration
agent.thread_manager.save_memory_state(thread_id, state.memory_state)
```

---

## Checklist

Before going live with thread system:

- [ ] Update `ConversationalAgent` initialization with `db_path`
- [ ] Replace `process_message` calls with `create_new_thread`/`continue_thread`
- [ ] Update API endpoints to use thread endpoints
- [ ] Test thread creation, continuation, listing
- [ ] Verify database persistence (restart server, check threads still exist)
- [ ] Migrate existing in-memory states (if any)
- [ ] Update frontend to handle `thread_id` in responses
- [ ] Add thread listing UI (optional)
- [ ] Test multi-user isolation
- [ ] Set up database backups

---

## Summary

### Key Changes

1. **Initialization**: Add `db_path` parameter
2. **New Conversations**: Use `create_new_thread()` instead of `process_message()`
3. **Continue Conversations**: Use `continue_thread()` instead of `process_message()`
4. **State Storage**: Automatic (no manual dictionary management)
5. **Thread Discovery**: Use `list_user_threads()` and `search_threads()`

### Migration Effort

- **Small apps** (< 5 API endpoints): ~30 minutes
- **Medium apps** (5-20 endpoints): ~2 hours
- **Large apps** (> 20 endpoints): ~1 day

### Next Steps

1. ✅ Read [THREAD_MANAGEMENT_GUIDE.md](THREAD_MANAGEMENT_GUIDE.md) for full API reference
2. ✅ Run `test_thread_management.py` to verify integration
3. ✅ Update your code using examples above
4. ✅ Test thoroughly before production deployment

---

**Migration Guide Version:** 1.0.0  
**Last Updated:** January 2024
