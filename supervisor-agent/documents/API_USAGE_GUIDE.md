# API Usage Guide: Unified Chat & Threads System

## Overview
The system now has **unified chat and threads** with two ways to work:

1. **Legacy `/chat` endpoint**: In-memory conversations OR persistent threads
2. **New `/threads` endpoints**: Always persistent with messages table

Both systems use the same underlying messages table for persistence.

---

## Quick Start Examples

### Option 1: Legacy Chat (In-Memory)
```bash
# Start a conversation (in-memory, no database)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Send an email to john@example.com"
  }'

# Continue conversation (still in-memory)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "The subject is Meeting Notes",
    "conversation_id": "conv_abc12345"
  }'

# Convert to persistent thread (saves to database)
curl -X POST http://localhost:8000/chat/conv_abc12345/persist \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_123",
    "title": "Email Draft",
    "tags": ["email", "work"]
  }'
```

### Option 2: Persistent Chat (Auto-Save)
```bash
# Start persistent conversation (saves to database immediately)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Send an email to john@example.com",
    "user_id": "user_123",
    "persist": true
  }'

# Continue (automatically saves each message)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "The subject is Meeting Notes",
    "conversation_id": "user_123_abc12345"
  }'
```

### Option 3: Threads API (Always Persistent)
```bash
# Create thread with first message
curl -X POST http://localhost:8000/threads \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_123",
    "message": "Send an email to john@example.com",
    "title": "Email Draft",
    "tags": ["email", "work"]
  }'

# Continue thread
curl -X POST http://localhost:8000/threads/user_123_abc12345/messages \
  -H "Content-Type: application/json" \
  -d '{
    "message": "The subject is Meeting Notes"
  }'

# Get all messages in thread (with pagination)
curl -X GET "http://localhost:8000/threads/user_123_abc12345/messages?limit=50&offset=0"

# List all threads for user
curl -X GET "http://localhost:8000/threads?user_id=user_123&status=active&limit=50&offset=0"

# Get thread metadata
curl -X GET http://localhost:8000/threads/user_123_abc12345
```

---

## API Endpoints

### Chat Endpoints (Legacy + Enhanced)

#### `POST /chat`
**Start or continue a conversation**

Request:
```json
{
  "message": "string (required)",
  "conversation_id": "string (optional - for continuing)",
  "user_id": "string (optional - for persistent threads)",
  "persist": false,
  "auto_execute": false
}
```

Response:
```json
{
  "response": "Bot's response",
  "conversation_id": "conv_abc12345",
  "ready_for_execution": false,
  "intent": "needs_clarification",
  "extracted_info": {},
  "execution_summary": null
}
```

#### `POST /chat/{conversation_id}/persist`
**Convert in-memory conversation to persistent thread**

Request:
```json
{
  "user_id": "string (required)",
  "title": "string (optional)",
  "tags": ["string"] (optional)
}
```

#### `GET /chat/{conversation_id}`
**Get conversation details**

#### `DELETE /chat/{conversation_id}`
**Delete conversation from memory**

#### `GET /conversations`
**List all active in-memory conversations**

---

### Thread Endpoints (Always Persistent)

#### `POST /threads`
**Create new persistent thread**

Request:
```json
{
  "user_id": "string (required)",
  "message": "string (optional - first message)",
  "title": "string (optional - auto-generated if not provided)",
  "tags": ["string"] (optional)
}
```

Response:
```json
{
  "thread_id": "user_123_abc12345",
  "user_id": "user_123",
  "metadata": {
    "thread_id": "user_123_abc12345",
    "user_id": "user_123",
    "created_at": "2025-11-05T12:00:00",
    "updated_at": "2025-11-05T12:00:00",
    "title": "Email Draft",
    "message_count": 2,
    "status": "active",
    "last_message_preview": "The subject is Meeting Notes",
    "tags": ["email", "work"]
  },
  "bot_response": "Bot's response to first message",
  "ready_for_execution": false
}
```

#### `GET /threads`
**List threads for user**

Query Parameters:
- `user_id`: string (required)
- `status`: "active" | "archived" | "all" (default: "active")
- `limit`: number (default: 50)
- `offset`: number (default: 0)

#### `GET /threads/{thread_id}`
**Get thread metadata**

#### `GET /threads/{thread_id}/messages`
**Get messages from thread (from messages table)**

Query Parameters:
- `limit`: number (default: 50)
- `offset`: number (default: 0)

Response:
```json
{
  "thread_id": "user_123_abc12345",
  "messages": [
    {
      "message_id": 1,
      "thread_id": "user_123_abc12345",
      "role": "user",
      "content": "Send an email to john@example.com",
      "created_at": "2025-11-05T12:00:00"
    },
    {
      "message_id": 2,
      "thread_id": "user_123_abc12345",
      "role": "assistant",
      "content": "What should the subject be?",
      "created_at": "2025-11-05T12:00:05"
    }
  ],
  "count": 2,
  "limit": 50,
  "offset": 0
}
```

#### `POST /threads/{thread_id}/messages`
**Send message to thread**

Request:
```json
{
  "message": "string (required)"
}
```

#### `PUT /threads/{thread_id}`
**Update thread metadata** (title, tags, status)

---

## Key Features

### ✅ Messages Table Integration
- All persistent conversations store messages in relational database
- Individual message records with role, content, and timestamp
- Supports pagination for long conversations
- CASCADE delete ensures data integrity

### ✅ Unified System
- `/chat` can work in-memory OR persistent (your choice)
- `/threads` always persistent
- Both use same messages table
- Easy migration from in-memory to persistent

### ✅ Backward Compatible
- Legacy `/chat` endpoint still works exactly as before
- No breaking changes to existing API contracts
- Gradual migration path available

### ✅ Foreign Key Constraints
- `messages` table has foreign key to `threads`
- CASCADE delete removes all messages when thread deleted
- Data integrity enforced at database level

---

## Database Schema

```sql
-- Threads table
CREATE TABLE threads (
    thread_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    title TEXT,
    message_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    last_message_preview TEXT,
    tags TEXT
);

-- Messages table (NEW!)
CREATE TABLE messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (thread_id) REFERENCES threads(thread_id) ON DELETE CASCADE
);

-- Thread states (conversation context)
CREATE TABLE thread_states (
    thread_id TEXT PRIMARY KEY,
    conversation_state TEXT,
    FOREIGN KEY (thread_id) REFERENCES threads(thread_id) ON DELETE CASCADE
);

-- Memory states (summarized history)
CREATE TABLE memory_states (
    thread_id TEXT PRIMARY KEY,
    memory_state TEXT,
    FOREIGN KEY (thread_id) REFERENCES threads(thread_id) ON DELETE CASCADE
);
```

---

## Migration Guide

### From In-Memory Chat → Persistent Thread

```python
# User has been using /chat endpoint
conversation_id = "conv_abc12345"

# Convert to persistent thread
response = requests.post(
    f"http://localhost:8000/chat/{conversation_id}/persist",
    json={
        "user_id": "user_123",
        "title": "My Conversation",
        "tags": ["important"]
    }
)

# Now use either conversation_id OR new thread_id
thread_id = response.json()["thread_id"]
```

### From Legacy to New Pattern

```python
# OLD WAY (still works!)
requests.post("/chat", json={"message": "Hello"})

# NEW WAY (persistent from start)
requests.post("/chat", json={
    "message": "Hello",
    "user_id": "user_123",
    "persist": True
})

# OR use threads directly
requests.post("/threads", json={
    "user_id": "user_123",
    "message": "Hello"
})
```

---

## Best Practices

1. **Use `/threads` for production**: Always persistent, better for long-term storage
2. **Use `/chat` with `persist=true`**: For gradual migration from legacy code
3. **Use in-memory `/chat`**: Only for testing or temporary conversations
4. **Paginate messages**: Don't fetch all messages at once for long threads
5. **Set meaningful titles**: Auto-generated titles are OK but custom is better

---

## Testing

Run the integration test:
```bash
cd supervisor-agent
python test_threads_integration.py
```

This verifies:
- Messages table creation
- Message CRUD operations
- Pagination
- CASCADE delete
- Thread metadata updates
