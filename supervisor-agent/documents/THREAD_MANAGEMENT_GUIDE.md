# Thread Management System Guide

Complete guide to the persistent thread management system for multi-user conversations.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Database Schema](#database-schema)
4. [Thread Lifecycle](#thread-lifecycle)
5. [API Reference](#api-reference)
6. [Integration Guide](#integration-guide)
7. [Usage Examples](#usage-examples)
8. [Migration from Memory-Only](#migration-from-memory-only)

---

## Overview

### What is Thread Management?

The **Thread Management System** provides persistent storage and retrieval of conversation threads for multi-user support. Each thread represents a complete conversation between a user and the agent, including:

- **Conversation State**: Intent, extracted info, execution readiness
- **Memory State**: Full message history, summaries, entities
- **Metadata**: Title, tags, creation time, last activity, message count

### Key Features

✅ **Persistent Storage**: Conversations survive server restarts  
✅ **Multi-User Support**: Isolated threads per user  
✅ **Thread Discovery**: List, search, and filter threads  
✅ **Auto-Save**: Automatic state persistence on each message  
✅ **Memory Management**: Integrated with ConversationMemoryManager  
✅ **Thread Metadata**: Titles, tags, timestamps, message counts  

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Supervisor API Layer                      │
│  POST /threads, GET /threads, GET /threads/{id}/messages    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 ConversationalAgent                          │
│  • create_new_thread()                                       │
│  • continue_thread()                                         │
│  • list_user_threads()                                       │
│  • get_thread_messages()                                     │
└─────────────────────────────────────────────────────────────┘
                              │
                 ┌────────────┴───────────┐
                 ▼                        ▼
┌──────────────────────────┐  ┌──────────────────────────┐
│  ConversationMemoryManager│  │    ThreadManager         │
│  • Message history        │  │  • SQLite persistence    │
│  • Auto-summarization     │  │  • CRUD operations       │
│  • Entity extraction      │  │  • Search & filtering    │
└──────────────────────────┘  └──────────────────────────┘
                 │                        │
                 └────────────┬───────────┘
                              ▼
                    ┌──────────────────┐
                    │   threads.db     │
                    │  (SQLite)        │
                    └──────────────────┘
```

### Thread Identification

- **thread_id**: Unique identifier for each conversation thread
- **state_id**: Used internally by ConversationalAgent (equals thread_id)
- **user_id**: Identifies the owner of the thread

### Data Flow

1. **User sends message** → API endpoint
2. **API creates/loads thread** → ConversationalAgent
3. **Agent processes message** → Updates memory & state
4. **Auto-save triggered** → ThreadManager persists to database
5. **Response returned** → User receives bot reply + metadata

---

## Database Schema

### Tables

#### `threads` - Thread Metadata

```sql
CREATE TABLE threads (
    thread_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    title TEXT,
    message_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',  -- active, archived
    tags TEXT,  -- JSON array
    last_message_preview TEXT
);

CREATE INDEX idx_threads_user_id ON threads(user_id);
CREATE INDEX idx_threads_status ON threads(status);
CREATE INDEX idx_threads_updated_at ON threads(updated_at DESC);
```

#### `thread_states` - Conversation State Storage

```sql
CREATE TABLE thread_states (
    thread_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,  -- JSON serialized ConversationState
    updated_at TIMESTAMP NOT NULL,
    FOREIGN KEY (thread_id) REFERENCES threads(thread_id) ON DELETE CASCADE
);
```

#### `memory_states` - Memory State Storage

```sql
CREATE TABLE memory_states (
    thread_id TEXT PRIMARY KEY,
    memory_json TEXT NOT NULL,  -- JSON serialized ConversationMemory
    updated_at TIMESTAMP NOT NULL,
    FOREIGN KEY (thread_id) REFERENCES threads(thread_id) ON DELETE CASCADE
);
```

### Data Relationships

```
threads (1) ──────── (1) thread_states
   │
   └─────────────── (1) memory_states
```

---

## Thread Lifecycle

### 1. Thread Creation

```python
# User starts a new conversation
thread_id, state = conversational_agent.create_new_thread(
    user_id="user123",
    initial_message="Send an email to john@example.com",
    title="Email to John",  # Optional
    tags=["email", "work"]  # Optional
)
```

**What happens:**
- New thread_id generated (UUID)
- Thread metadata created in database
- Initial message processed (if provided)
- Title auto-generated from message (if not provided)
- State and memory saved to database

### 2. Thread Continuation

```python
# User continues the conversation
response, state = conversational_agent.continue_thread(
    thread_id="abc123",
    new_message="The subject is 'Meeting Notes'"
)
```

**What happens:**
- Thread state loaded from database
- Memory manager reconstructed from stored memory
- New message processed
- Auto-save updates database
- Metadata updated (message count, last message preview, updated_at)

### 3. Thread Discovery

```python
# List user's threads
threads = conversational_agent.list_user_threads(
    user_id="user123",
    status="active",
    limit=50
)

# Search threads
threads = conversational_agent.search_threads(
    user_id="user123",
    query="email",
    limit=20
)
```

### 4. Thread Archival

```python
# Archive (soft delete)
conversational_agent.archive_thread("abc123")

# Permanent delete
conversational_agent.delete_thread("abc123", hard_delete=True)
```

---

## API Reference

### Thread Creation

**Endpoint:** `POST /threads`

**Request:**
```json
{
  "user_id": "user123",
  "message": "Send an email to john@example.com",
  "title": "Email to John",
  "tags": ["email", "work"]
}
```

**Response:**
```json
{
  "thread_id": "abc123",
  "user_id": "user123",
  "metadata": {
    "thread_id": "abc123",
    "user_id": "user123",
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:30:00Z",
    "title": "Email to John",
    "message_count": 2,
    "status": "active",
    "tags": ["email", "work"],
    "last_message_preview": "📋 What should the subject be?..."
  },
  "bot_response": "📋 What should the subject be?",
  "ready_for_execution": false,
  "message": "Thread created successfully"
}
```

---

### List Threads

**Endpoint:** `GET /threads?user_id={user_id}&status={status}&limit={limit}&offset={offset}`

**Parameters:**
- `user_id` (required): User identifier
- `status` (optional): Filter by status - `active`, `archived`, `all` (default: `active`)
- `limit` (optional): Max results (default: 50)
- `offset` (optional): Pagination offset (default: 0)

**Response:**
```json
{
  "user_id": "user123",
  "threads": [
    {
      "thread_id": "abc123",
      "user_id": "user123",
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T10:35:00Z",
      "title": "Email to John",
      "message_count": 4,
      "status": "active",
      "tags": ["email", "work"],
      "last_message_preview": "✅ Ready to execute!..."
    }
  ],
  "count": 1,
  "limit": 50,
  "offset": 0
}
```

---

### Get Thread Messages

**Endpoint:** `GET /threads/{thread_id}/messages`

**Response:**
```json
{
  "thread_id": "abc123",
  "messages": [
    {"role": "user", "content": "Send an email to john@example.com"},
    {"role": "assistant", "content": "📋 What should the subject be?"},
    {"role": "user", "content": "Meeting Notes"},
    {"role": "assistant", "content": "✅ Ready to execute!..."}
  ],
  "count": 4
}
```

---

### Continue Thread

**Endpoint:** `POST /threads/{thread_id}/messages`

**Request:**
```json
{
  "message": "The subject is 'Meeting Notes'"
}
```

**Response:**
```json
{
  "thread_id": "abc123",
  "bot_response": "✅ Ready to execute!...",
  "ready_for_execution": true,
  "metadata": {
    "thread_id": "abc123",
    "message_count": 4,
    "updated_at": "2024-01-15T10:35:00Z",
    ...
  }
}
```

---

### Update Thread Metadata

**Endpoint:** `PUT /threads/{thread_id}`

**Request:**
```json
{
  "title": "Updated Title",
  "tags": ["email", "urgent"],
  "status": "archived"
}
```

**Response:**
```json
{
  "thread_id": "abc123",
  "metadata": {...},
  "message": "Thread updated successfully"
}
```

---

### Delete Thread

**Endpoint:** `DELETE /threads/{thread_id}?hard_delete={true|false}`

**Parameters:**
- `hard_delete` (optional): If `true`, permanently delete. Otherwise, archive (default: `false`)

**Response:**
```json
{
  "thread_id": "abc123",
  "message": "Thread archived successfully",
  "hard_delete": false
}
```

---

### Search Threads

**Endpoint:** `GET /threads/search?user_id={user_id}&q={query}&limit={limit}`

**Parameters:**
- `user_id` (required): User identifier
- `q` (required): Search query (searches in title)
- `limit` (optional): Max results (default: 20)

**Response:**
```json
{
  "user_id": "user123",
  "query": "email",
  "threads": [...],
  "count": 3
}
```

---

## Integration Guide

### Backend Integration

#### 1. Initialize ConversationalAgent with Database Path

```python
from conversational_agent import ConversationalAgent

agent = ConversationalAgent(
    openai_api_key="your-api-key",
    db_path="threads.db"  # SQLite database path
)
```

#### 2. Create New Thread

```python
# New conversation
thread_id, state = agent.create_new_thread(
    user_id="user123",
    initial_message="Send an email"
)
```

#### 3. Continue Existing Thread

```python
# Continue conversation
response, state = agent.continue_thread(
    thread_id=thread_id,
    new_message="To john@example.com"
)
```

#### 4. List User's Threads

```python
threads = agent.list_user_threads(
    user_id="user123",
    status="active",
    limit=50
)
```

---

### Frontend Integration

#### 1. Create New Thread

```javascript
async function createThread(userId, message) {
  const response = await fetch('/threads', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      user_id: userId,
      message: message
    })
  });
  
  const data = await response.json();
  return data.thread_id;
}
```

#### 2. Send Message to Thread

```javascript
async function sendMessage(threadId, message) {
  const response = await fetch(`/threads/${threadId}/messages`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({message})
  });
  
  const data = await response.json();
  return data.bot_response;
}
```

#### 3. Load Thread History

```javascript
async function loadThreadMessages(threadId) {
  const response = await fetch(`/threads/${threadId}/messages`);
  const data = await response.json();
  return data.messages;
}
```

#### 4. List User's Threads

```javascript
async function listThreads(userId) {
  const response = await fetch(`/threads?user_id=${userId}`);
  const data = await response.json();
  return data.threads;
}
```

---

## Usage Examples

### Example 1: Multi-Turn Email Task

```python
# Turn 1: User starts new thread
thread_id, state = agent.create_new_thread(
    user_id="alice",
    initial_message="Send an email"
)
# Bot: "📋 Who should I send the email to?"

# Turn 2: User provides recipient
response, state = agent.continue_thread(
    thread_id=thread_id,
    new_message="john@example.com"
)
# Bot: "📋 What should the subject be?"

# Turn 3: User provides subject
response, state = agent.continue_thread(
    thread_id=thread_id,
    new_message="Meeting Notes"
)
# Bot: "📋 What should I include in the email body?"

# Turn 4: User provides body
response, state = agent.continue_thread(
    thread_id=thread_id,
    new_message="See you tomorrow at 3pm"
)
# Bot: "✅ Ready to execute!"
# state.ready_for_execution = True
```

### Example 2: Thread Discovery

```python
# List all active threads for user
threads = agent.list_user_threads(
    user_id="alice",
    status="active"
)

print(f"Found {len(threads)} active threads")
for thread in threads:
    print(f"- {thread['title']} ({thread['message_count']} messages)")

# Search for specific threads
email_threads = agent.search_threads(
    user_id="alice",
    query="email"
)
```

### Example 3: Thread Archival & Cleanup

```python
# Archive completed thread
agent.archive_thread(thread_id)

# Permanently delete old threads
old_threads = agent.list_user_threads(
    user_id="alice",
    status="archived"
)

for thread in old_threads:
    created_at = datetime.fromisoformat(thread['created_at'])
    if datetime.now() - created_at > timedelta(days=90):
        agent.delete_thread(thread['thread_id'], hard_delete=True)
```

---

## Migration from Memory-Only

### Before: Memory-Only Mode

```python
# Old way (in-memory only)
response, state = agent.process_message(
    user_message="Send an email",
    conversation_state=previous_state,
    state_id="default"
)
# State lost on server restart
```

### After: Thread Mode

```python
# New way (persistent threads)
# First message
thread_id, state = agent.create_new_thread(
    user_id="alice",
    initial_message="Send an email"
)

# Continue thread
response, state = agent.continue_thread(
    thread_id=thread_id,
    new_message="To john@example.com"
)
# State persists across server restarts
```

### Key Differences

| Feature | Memory-Only | Thread Mode |
|---------|-------------|-------------|
| **Persistence** | ❌ Lost on restart | ✅ Survives restarts |
| **Multi-User** | ⚠️ Manual isolation | ✅ Built-in |
| **Thread Discovery** | ❌ No listing | ✅ List & search |
| **Auto-Save** | ⚠️ Manual | ✅ Automatic |
| **Metadata** | ❌ None | ✅ Title, tags, counts |

---

## Best Practices

### 1. Use Meaningful Titles

```python
# Auto-generated title
thread_id, state = agent.create_new_thread(
    user_id="alice",
    initial_message="Send an email to john@example.com about meeting"
)
# Title: "Email about meeting"

# Custom title
thread_id, state = agent.create_new_thread(
    user_id="alice",
    initial_message="Send an email",
    title="Weekly Team Update Email"
)
```

### 2. Use Tags for Organization

```python
thread_id, state = agent.create_new_thread(
    user_id="alice",
    initial_message="Search my emails for invoices",
    tags=["email", "finance", "urgent"]
)

# Later: find all finance-related threads
finance_threads = agent.search_threads(
    user_id="alice",
    query="finance"
)
```

### 3. Archive Completed Threads

```python
# After successful execution
if state.ready_for_execution:
    # Execute task...
    # Archive thread when done
    agent.archive_thread(thread_id)
```

### 4. Cleanup Old Threads

```python
# Periodically delete threads older than 90 days
def cleanup_old_threads(user_id):
    archived = agent.list_user_threads(user_id, status="archived")
    cutoff_date = datetime.now() - timedelta(days=90)
    
    for thread in archived:
        created = datetime.fromisoformat(thread['created_at'])
        if created < cutoff_date:
            agent.delete_thread(thread['thread_id'], hard_delete=True)
```

---

## Troubleshooting

### Thread Not Found

**Error:** `ValueError: Thread abc123 not found`

**Solution:** Ensure thread_id exists and is not deleted
```python
# Check if thread exists
metadata = agent.get_thread_metadata(thread_id)
if not metadata:
    print("Thread does not exist")
```

### Database Locked

**Error:** `sqlite3.OperationalError: database is locked`

**Solution:** Use connection pooling or retry logic
```python
# ThreadManager automatically retries on lock
```

### Memory Not Loading

**Issue:** Thread loads but messages are empty

**Solution:** Check memory_states table
```python
# Verify memory state exists
memory_data = agent.thread_manager.load_memory_state(thread_id)
if not memory_data:
    print("Memory state missing - may need reinitialization")
```

---

## Performance Considerations

### Database Size

- **threads**: ~1 KB per thread
- **thread_states**: ~2 KB per thread
- **memory_states**: ~10-50 KB per thread (depends on message count)

**Example:** 1000 threads ≈ 13-53 MB database size

### Auto-Save Impact

Auto-save triggers on every message:
- **Database write**: ~5-10 ms
- **JSON serialization**: ~1-2 ms

**Total overhead per message:** ~6-12 ms (negligible)

### Indexing

Indexes are created automatically for:
- `user_id` (fast user thread listing)
- `status` (fast filtering)
- `updated_at` (fast sorting by recency)

---

## Summary

✅ **Persistent Storage**: All conversations survive restarts  
✅ **Multi-User Support**: Isolated threads per user  
✅ **Thread Discovery**: List, search, filter threads  
✅ **Auto-Save**: Automatic persistence on every message  
✅ **Memory Integration**: Works seamlessly with ConversationMemoryManager  
✅ **Rich Metadata**: Titles, tags, timestamps, message counts  

**Next Steps:**
1. Initialize ConversationalAgent with `db_path`
2. Use `create_new_thread()` for new conversations
3. Use `continue_thread()` for ongoing conversations
4. List threads with `list_user_threads()`
5. Archive completed threads with `archive_thread()`

---

**Documentation Version:** 1.0.0  
**Last Updated:** January 2024
