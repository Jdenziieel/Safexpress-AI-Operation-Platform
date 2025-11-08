# Thread Management System Architecture

Visual diagrams showing the complete thread management system architecture.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          USER INTERFACE                                  │
│  (Web App / Mobile App / API Client)                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                 │
                                 │ HTTP/REST
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        FASTAPI SERVER                                    │
│  supervisor_agent.py                                                     │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  THREAD ENDPOINTS                                                  │ │
│  │  • POST   /threads              → Create thread                   │ │
│  │  • GET    /threads              → List threads                    │ │
│  │  • GET    /threads/{id}         → Get metadata                    │ │
│  │  • GET    /threads/{id}/messages → Get messages                   │ │
│  │  • POST   /threads/{id}/messages → Send message                   │ │
│  │  • PUT    /threads/{id}         → Update metadata                 │ │
│  │  • DELETE /threads/{id}         → Archive/delete                  │ │
│  │  • GET    /threads/search       → Search threads                  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    CONVERSATIONAL AGENT                                  │
│  conversational_agent.py                                                 │
│                                                                          │
│  ┌─────────────────────────┐      ┌──────────────────────────────────┐ │
│  │  THREAD OPERATIONS      │      │  CONVERSATION PROCESSING         │ │
│  │  • create_new_thread()  │      │  • process_message()             │ │
│  │  • continue_thread()    │      │  • analyze_request()             │ │
│  │  • list_user_threads()  │      │  • build_supervisor_input()      │ │
│  │  • get_thread_metadata()│      │  • summarize_execution()         │ │
│  │  • get_thread_messages()│      └──────────────────────────────────┘ │
│  │  • update_thread()      │                                            │
│  │  • archive_thread()     │                                            │
│  │  • delete_thread()      │                                            │
│  │  • search_threads()     │                                            │
│  └─────────────────────────┘                                            │
└─────────────────────────────────────────────────────────────────────────┘
                │                                     │
                │                                     │
                ▼                                     ▼
┌──────────────────────────────┐    ┌───────────────────────────────────┐
│    THREAD MANAGER            │    │  CONVERSATION MEMORY MANAGER       │
│  thread_manager.py           │    │  conversation_memory.py            │
│                              │    │                                    │
│  • ThreadMetadata model      │    │  • ConversationMemory model       │
│  • ThreadManager class       │    │  • Auto-summarization             │
│  • Database operations       │    │  • Entity extraction              │
│  • CRUD operations           │    │  • Token counting                 │
│  • Search & filtering        │    │  • Export/Load                    │
│  • Auto-title generation     │    │  • Context building               │
└──────────────────────────────┘    └───────────────────────────────────┘
                │                                     │
                │                                     │
                └──────────────┬──────────────────────┘
                               │
                               ▼
                ┌──────────────────────────────┐
                │     SQLITE DATABASE          │
                │  threads.db                  │
                │                              │
                │  ┌────────────────────────┐  │
                │  │  threads               │  │
                │  │  - thread_id (PK)      │  │
                │  │  - user_id             │  │
                │  │  - created_at          │  │
                │  │  - updated_at          │  │
                │  │  - title               │  │
                │  │  - message_count       │  │
                │  │  - status              │  │
                │  │  - tags                │  │
                │  │  - last_message_preview│  │
                │  └────────────────────────┘  │
                │                              │
                │  ┌────────────────────────┐  │
                │  │  thread_states         │  │
                │  │  - thread_id (PK, FK)  │  │
                │  │  - state_json          │  │
                │  │  - updated_at          │  │
                │  └────────────────────────┘  │
                │                              │
                │  ┌────────────────────────┐  │
                │  │  memory_states         │  │
                │  │  - thread_id (PK, FK)  │  │
                │  │  - memory_json         │  │
                │  │  - updated_at          │  │
                │  └────────────────────────┘  │
                └──────────────────────────────┘
```

---

## Thread Lifecycle Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        THREAD LIFECYCLE                                  │
└─────────────────────────────────────────────────────────────────────────┘

1. CREATION
   ┌─────────────────────────────────────────────────────────────────┐
   │ User: "Send an email to john@example.com"                       │
   └─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
          ┌────────────────────────────────────────┐
          │ POST /threads                          │
          │ {                                      │
          │   "user_id": "alice",                  │
          │   "message": "Send an email to..."     │
          │ }                                      │
          └────────────────────────────────────────┘
                              │
                              ▼
          ┌────────────────────────────────────────┐
          │ ConversationalAgent.create_new_thread()│
          └────────────────────────────────────────┘
                              │
                              ├───────────────────────────┐
                              ▼                           ▼
          ┌──────────────────────────┐   ┌─────────────────────────┐
          │ ThreadManager            │   │ Process initial message  │
          │ .create_thread()         │   │ with memory manager      │
          │                          │   └─────────────────────────┘
          │ • Generate thread_id     │                 │
          │ • Insert into DB         │                 │
          │ • Auto-generate title    │                 ▼
          └──────────────────────────┘   ┌─────────────────────────┐
                              │           │ Auto-save to database:  │
                              │           │ • thread_states         │
                              │           │ • memory_states         │
                              │           │ • Update metadata       │
                              │           └─────────────────────────┘
                              ▼
          ┌────────────────────────────────────────┐
          │ Response:                              │
          │ {                                      │
          │   "thread_id": "abc123",               │
          │   "bot_response": "What should...",    │
          │   "ready_for_execution": false         │
          │ }                                      │
          └────────────────────────────────────────┘

2. CONTINUATION
   ┌─────────────────────────────────────────────────────────────────┐
   │ User: "The subject is 'Meeting Notes'"                          │
   └─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
          ┌────────────────────────────────────────┐
          │ POST /threads/abc123/messages          │
          │ {                                      │
          │   "message": "The subject is..."       │
          │ }                                      │
          └────────────────────────────────────────┘
                              │
                              ▼
          ┌────────────────────────────────────────┐
          │ ConversationalAgent.continue_thread()  │
          └────────────────────────────────────────┘
                              │
                              ├───────────────────────────┐
                              ▼                           ▼
          ┌──────────────────────────┐   ┌─────────────────────────┐
          │ ThreadManager            │   │ Process new message      │
          │ .load_thread_state()     │   │ with loaded memory       │
          │ .load_memory_state()     │   └─────────────────────────┘
          │                          │                 │
          │ • Read from DB           │                 │
          │ • Reconstruct state      │                 ▼
          │ • Reconstruct memory     │   ┌─────────────────────────┐
          └──────────────────────────┘   │ Auto-save to database:  │
                              │           │ • Update thread_states  │
                              │           │ • Update memory_states  │
                              │           │ • Update metadata       │
                              │           └─────────────────────────┘
                              ▼
          ┌────────────────────────────────────────┐
          │ Response:                              │
          │ {                                      │
          │   "thread_id": "abc123",               │
          │   "bot_response": "What should...",    │
          │   "ready_for_execution": false,        │
          │   "metadata": {...}                    │
          │ }                                      │
          └────────────────────────────────────────┘

3. DISCOVERY
   ┌─────────────────────────────────────────────────────────────────┐
   │ User wants to see their conversation history                    │
   └─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
          ┌────────────────────────────────────────┐
          │ GET /threads?user_id=alice             │
          └────────────────────────────────────────┘
                              │
                              ▼
          ┌────────────────────────────────────────┐
          │ ConversationalAgent.list_user_threads()│
          └────────────────────────────────────────┘
                              │
                              ▼
          ┌────────────────────────────────────────┐
          │ ThreadManager.list_threads()           │
          │ • Query DB with filters                │
          │ • Apply sorting                        │
          │ • Return metadata list                 │
          └────────────────────────────────────────┘
                              │
                              ▼
          ┌────────────────────────────────────────┐
          │ Response:                              │
          │ {                                      │
          │   "threads": [                         │
          │     {                                  │
          │       "thread_id": "abc123",           │
          │       "title": "Email to John",        │
          │       "message_count": 4,              │
          │       "status": "active",              │
          │       "updated_at": "2024-01-15..."    │
          │     }                                  │
          │   ]                                    │
          │ }                                      │
          └────────────────────────────────────────┘

4. ARCHIVAL
   ┌─────────────────────────────────────────────────────────────────┐
   │ Task completed - archive the thread                             │
   └─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
          ┌────────────────────────────────────────┐
          │ DELETE /threads/abc123                 │
          └────────────────────────────────────────┘
                              │
                              ▼
          ┌────────────────────────────────────────┐
          │ ConversationalAgent.archive_thread()   │
          └────────────────────────────────────────┘
                              │
                              ▼
          ┌────────────────────────────────────────┐
          │ ThreadManager.archive_thread()         │
          │ • UPDATE threads SET status='archived' │
          └────────────────────────────────────────┘
                              │
                              ▼
          ┌────────────────────────────────────────┐
          │ Response:                              │
          │ {                                      │
          │   "message": "Thread archived",        │
          │   "thread_id": "abc123"                │
          │ }                                      │
          └────────────────────────────────────────┘
```

---

## Data Flow - Create New Thread

```
USER REQUEST
    │
    │  POST /threads
    │  {user_id: "alice", message: "Send email"}
    ▼
┌─────────────────────────┐
│   supervisor_agent.py   │
│   create_thread()       │
└─────────────────────────┘
    │
    ▼
┌─────────────────────────┐
│  conversational_agent   │
│  .create_new_thread()   │
└─────────────────────────┘
    │
    ├─────────────────────────────────────┐
    │                                     │
    ▼                                     ▼
┌──────────────────┐          ┌──────────────────────┐
│ thread_manager   │          │  Process Message     │
│ .create_thread() │          │  with Memory         │
└──────────────────┘          └──────────────────────┘
    │                                     │
    │  INSERT INTO threads                │
    │  VALUES (thread_id, user_id, ...)   │
    │                                     │
    ▼                                     ▼
┌──────────────────┐          ┌──────────────────────┐
│   threads.db     │          │  memory_manager      │
│   [threads]      │          │  .add_message()      │
└──────────────────┘          │  • User message      │
                              │  • Bot response      │
                              └──────────────────────┘
                                        │
                                        │  export_memory()
                                        ▼
                              ┌──────────────────────┐
                              │  Auto-save           │
                              │  .save_thread_state()│
                              │  .save_memory_state()│
                              └──────────────────────┘
                                        │
                                        │  INSERT INTO thread_states
                                        │  INSERT INTO memory_states
                                        ▼
                              ┌──────────────────────┐
                              │   threads.db         │
                              │   [thread_states]    │
                              │   [memory_states]    │
                              └──────────────────────┘
                                        │
                                        ▼
RESPONSE
{
  thread_id: "abc123",
  bot_response: "What should the subject be?",
  metadata: {...}
}
```

---

## Data Flow - Continue Thread

```
USER REQUEST
    │
    │  POST /threads/abc123/messages
    │  {message: "The subject is 'Meeting Notes'"}
    ▼
┌─────────────────────────┐
│   supervisor_agent.py   │
│   send_message_to_      │
│   thread()              │
└─────────────────────────┘
    │
    ▼
┌─────────────────────────┐
│  conversational_agent   │
│  .continue_thread()     │
└─────────────────────────┘
    │
    ├─────────────────────────────────────┐
    │  LOAD FROM DATABASE                 │
    ▼                                     │
┌──────────────────┐                     │
│ thread_manager   │                     │
│ .load_thread_    │                     │
│  state()         │                     │
│ .load_memory_    │                     │
│  state()         │                     │
└──────────────────┘                     │
    │                                     │
    │  SELECT * FROM thread_states        │
    │  SELECT * FROM memory_states        │
    │                                     │
    ▼                                     │
┌──────────────────┐                     │
│   threads.db     │                     │
│   Returns JSON   │                     │
└──────────────────┘                     │
    │                                     │
    │  state_json, memory_json            │
    ▼                                     │
┌──────────────────┐                     │
│  Reconstruct     │                     │
│  • Conversation  │                     │
│    State         │                     │
│  • Memory        │                     │
│    Manager       │                     │
└──────────────────┘                     │
    │                                     │
    ├─────────────────────────────────────┘
    │
    ▼
┌──────────────────────┐
│  Process Message     │
│  .process_message()  │
│  (auto_save=True)    │
└──────────────────────┘
    │
    │  • Add user message to memory
    │  • Analyze request
    │  • Generate response
    │  • Add bot response to memory
    │
    ▼
┌──────────────────────┐
│  Auto-save           │
│  Triggered           │
└──────────────────────┘
    │
    ├─────────────────────────────────────┐
    │                                     │
    ▼                                     ▼
┌──────────────────┐          ┌──────────────────────┐
│  .save_thread_   │          │  .save_memory_       │
│   state()        │          │   state()            │
└──────────────────┘          └──────────────────────┘
    │                                     │
    │  UPDATE thread_states               │  UPDATE memory_states
    │  SET state_json = ...               │  SET memory_json = ...
    │                                     │
    └─────────────────┬───────────────────┘
                      │
                      │  UPDATE threads
                      │  SET message_count++,
                      │      updated_at = now(),
                      │      last_message_preview = ...
                      ▼
                ┌──────────────┐
                │  threads.db  │
                │  Updated     │
                └──────────────┘
                      │
                      ▼
RESPONSE
{
  thread_id: "abc123",
  bot_response: "What should I include in the body?",
  ready_for_execution: false,
  metadata: {message_count: 4, ...}
}
```

---

## Database Schema Relationships

```
┌──────────────────────────────────────────────────────────────────┐
│                          threads                                 │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ thread_id (PK)          TEXT                               │  │
│  │ user_id                 TEXT                               │  │
│  │ created_at              TIMESTAMP                          │  │
│  │ updated_at              TIMESTAMP                          │  │
│  │ title                   TEXT                               │  │
│  │ message_count           INTEGER                            │  │
│  │ status                  TEXT (active/archived)             │  │
│  │ tags                    TEXT (JSON array)                  │  │
│  │ last_message_preview    TEXT                               │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
         │                              │
         │  1:1                         │  1:1
         │                              │
         ▼                              ▼
┌─────────────────────────┐   ┌─────────────────────────────┐
│    thread_states        │   │     memory_states           │
│  ┌───────────────────┐  │   │  ┌───────────────────────┐  │
│  │ thread_id (PK,FK) │  │   │  │ thread_id (PK,FK)     │  │
│  │ state_json        │  │   │  │ memory_json           │  │
│  │ updated_at        │  │   │  │ updated_at            │  │
│  └───────────────────┘  │   │  └───────────────────────┘  │
│                         │   │                             │
│  state_json contains:   │   │  memory_json contains:      │
│  {                      │   │  {                          │
│    "intent": "...",     │   │    "raw_history": [...],    │
│    "extracted_info": {} │   │    "working_context": "..." │
│    "missing_fields": [] │   │    "entity_memory": {...},  │
│    "ready": false       │   │    "summary": "..."         │
│  }                      │   │  }                          │
└─────────────────────────┘   └─────────────────────────────┘

Indexes:
- idx_threads_user_id       ON threads(user_id)
- idx_threads_status        ON threads(status)
- idx_threads_updated_at    ON threads(updated_at DESC)
```

---

## Multi-User Thread Isolation

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MULTI-USER SYSTEM                             │
└─────────────────────────────────────────────────────────────────────┘

USER: alice
  │
  ├── Thread 1: "abc123"
  │     ├── Status: active
  │     ├── Title: "Email to John"
  │     ├── Messages: 4
  │     └── State: Ready for execution
  │
  ├── Thread 2: "def456"
  │     ├── Status: active
  │     ├── Title: "Search emails for invoices"
  │     ├── Messages: 2
  │     └── State: Needs clarification
  │
  └── Thread 3: "ghi789"
        ├── Status: archived
        ├── Title: "Create document"
        ├── Messages: 6
        └── State: Completed

USER: bob
  │
  ├── Thread 1: "jkl012"
  │     ├── Status: active
  │     ├── Title: "Schedule meeting"
  │     ├── Messages: 3
  │     └── State: Needs clarification
  │
  └── Thread 2: "mno345"
        ├── Status: active
        ├── Title: "Search calendar"
        ├── Messages: 2
        └── State: Ready for execution

DATABASE QUERY ISOLATION:
┌─────────────────────────────────────────────────────────────────┐
│ SELECT * FROM threads WHERE user_id = 'alice'                   │
│ → Returns only alice's threads                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ SELECT * FROM threads WHERE user_id = 'bob'                     │
│ → Returns only bob's threads                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Component Integration Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                    COMPONENT INTEGRATION                             │
└─────────────────────────────────────────────────────────────────────┘

supervisor_agent.py
  │
  ├─[uses]─> conversational_agent.py
  │             │
  │             ├─[uses]─> thread_manager.py
  │             │             │
  │             │             └─[writes/reads]─> threads.db
  │             │
  │             └─[uses]─> conversation_memory.py
  │                           │
  │                           └─[persisted via]─> thread_manager.py
  │
  └─[imports]─> models.py
                agent_capabilities.py
                utils.py
                config.py

FILE DEPENDENCIES:

thread_manager.py
  • Depends on: pydantic, sqlite3, json, datetime, uuid
  • Used by: conversational_agent.py
  • Database: threads.db (3 tables)

conversation_memory.py
  • Depends on: pydantic, langchain_openai, tiktoken
  • Used by: conversational_agent.py
  • Exports: ConversationMemory dict → stored in memory_states

conversational_agent.py
  • Depends on: thread_manager, conversation_memory, agent_capabilities, utils
  • Used by: supervisor_agent.py
  • Provides: Thread operations + conversation processing

supervisor_agent.py
  • Depends on: conversational_agent, models, config, utils
  • Provides: REST API endpoints
  • Entry point: FastAPI server
```

---

## Performance & Scalability

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PERFORMANCE PROFILE                               │
└─────────────────────────────────────────────────────────────────────┘

REQUEST LATENCY:
┌──────────────────────────┬─────────────┬──────────────────────┐
│ Operation                │ Latency     │ Notes                │
├──────────────────────────┼─────────────┼──────────────────────┤
│ Create thread            │ 10-20 ms    │ DB insert + process  │
│ Continue thread          │ 15-30 ms    │ Load + process + save│
│ List threads (50)        │ 10-20 ms    │ Indexed SELECT       │
│ Get thread messages      │ 5-10 ms     │ Single SELECT        │
│ Search threads           │ 20-40 ms    │ LIKE query           │
│ Update metadata          │ 5-10 ms     │ Single UPDATE        │
│ Archive thread           │ 5-10 ms     │ Single UPDATE        │
└──────────────────────────┴─────────────┴──────────────────────┘

STORAGE EFFICIENCY:
┌──────────────────────────┬─────────────┬──────────────────────┐
│ Data Type                │ Size        │ Per Thread           │
├──────────────────────────┼─────────────┼──────────────────────┤
│ Thread metadata          │ ~1 KB       │ threads table        │
│ Conversation state       │ ~2 KB       │ thread_states table  │
│ Memory (10 messages)     │ ~10 KB      │ memory_states table  │
│ Memory (50 messages)     │ ~30 KB      │ With summarization   │
│ Memory (100 messages)    │ ~40 KB      │ With summarization   │
└──────────────────────────┴─────────────┴──────────────────────┘

SCALABILITY:
┌──────────────────────────┬─────────────┬──────────────────────┐
│ Threads                  │ DB Size     │ Query Time           │
├──────────────────────────┼─────────────┼──────────────────────┤
│ 100 threads              │ ~1-5 MB     │ <10 ms               │
│ 1,000 threads            │ ~10-50 MB   │ <15 ms               │
│ 10,000 threads           │ ~100-500 MB │ <20 ms               │
│ 100,000 threads          │ ~1-5 GB     │ <50 ms               │
└──────────────────────────┴─────────────┴──────────────────────┘

OPTIMIZATION STRATEGIES:
• SQLite indexes on user_id, status, updated_at
• Auto-summarization reduces memory size
• Soft delete (archive) keeps DB clean
• Connection pooling for concurrent requests
• Pagination for large thread lists
```

---

## Security Considerations

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SECURITY MODEL                                    │
└─────────────────────────────────────────────────────────────────────┘

USER ISOLATION:
┌──────────────────────────────────────────────────────────────────┐
│ • Each thread belongs to exactly one user (user_id)              │
│ • All queries filter by user_id                                  │
│ • Cross-user access prevented at database level                  │
│ • No shared threads between users                                │
└──────────────────────────────────────────────────────────────────┘

RECOMMENDED ADDITIONS (Not Yet Implemented):
┌──────────────────────────────────────────────────────────────────┐
│ 1. AUTHENTICATION                                                │
│    • Add JWT token verification to API endpoints                 │
│    • Extract user_id from authenticated token                    │
│    • Reject requests without valid authentication                │
│                                                                  │
│ 2. AUTHORIZATION                                                 │
│    • Verify user owns thread before operations                   │
│    • Check permissions for thread access                         │
│    • Rate limiting per user                                      │
│                                                                  │
│ 3. DATA ENCRYPTION                                               │
│    • Encrypt sensitive data in database                          │
│    • Use HTTPS for all API requests                              │
│    • Secure database file permissions                            │
│                                                                  │
│ 4. INPUT VALIDATION                                              │
│    • Validate all user inputs                                    │
│    • Sanitize thread titles and tags                             │
│    • Prevent SQL injection (using parameterized queries)         │
└──────────────────────────────────────────────────────────────────┘

EXAMPLE AUTHENTICATION:
@app.post("/threads")
async def create_thread(request: dict, token: str = Header(...)):
    # Verify JWT token
    user_id = verify_token(token)
    
    # Ensure request user_id matches authenticated user
    if request.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    # Proceed with thread creation...
```

---

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    DEPLOYMENT OPTIONS                                │
└─────────────────────────────────────────────────────────────────────┘

OPTION 1: Single Server
┌──────────────────────────────────────────────────────────────────┐
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                    SERVER (Docker/VM)                      │  │
│  │                                                            │  │
│  │  ┌──────────────┐         ┌──────────────────────────┐   │  │
│  │  │  FastAPI     │         │     SQLite Database      │   │  │
│  │  │  (Port 8000) │────────>│     threads.db           │   │  │
│  │  └──────────────┘         └──────────────────────────┘   │  │
│  │        │                                                  │  │
│  │        ▼                                                  │  │
│  │  ┌──────────────┐                                        │  │
│  │  │ Conversational│                                       │  │
│  │  │ Agent + Thread│                                       │  │
│  │  │ Manager       │                                       │  │
│  │  └──────────────┘                                        │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
    • Simple deployment
    • SQLite co-located with app
    • Backup: Copy threads.db file

OPTION 2: Cloud Deployment
┌──────────────────────────────────────────────────────────────────┐
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              LOAD BALANCER (Optional)                      │  │
│  └────────────────────────────────────────────────────────────┘  │
│                              │                                   │
│         ┌────────────────────┼────────────────────┐             │
│         │                    │                    │             │
│         ▼                    ▼                    ▼             │
│  ┌─────────────┐      ┌─────────────┐     ┌─────────────┐     │
│  │ App Server 1│      │ App Server 2│     │ App Server N│     │
│  │ (FastAPI)   │      │ (FastAPI)   │     │ (FastAPI)   │     │
│  └─────────────┘      └─────────────┘     └─────────────┘     │
│         │                    │                    │             │
│         └────────────────────┼────────────────────┘             │
│                              │                                   │
│                              ▼                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │         Shared Database (PostgreSQL/MySQL)                 │  │
│  │         OR                                                 │  │
│  │         Network-attached SQLite (e.g., S3 + Litestream)   │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
    • Horizontal scaling
    • Shared database
    • Consider PostgreSQL for multi-server

OPTION 3: Serverless
┌──────────────────────────────────────────────────────────────────┐
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                   API Gateway                              │  │
│  └────────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              ▼                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │         AWS Lambda / Google Cloud Functions                │  │
│  │         (FastAPI via Mangum)                               │  │
│  └────────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              ▼                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │         Cloud Database (RDS / Cloud SQL)                   │  │
│  │         OR                                                 │  │
│  │         DynamoDB / Firestore                               │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
    • Auto-scaling
    • Pay-per-use
    • Requires database adapter changes for NoSQL
```

---

**Architecture Documentation Version:** 1.0.0  
**Last Updated:** January 2024
