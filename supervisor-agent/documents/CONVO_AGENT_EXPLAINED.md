# Conversational Agent Architecture Explained

## 📋 Table of Contents
1. [Overview](#overview)
2. [Core Components](#core-components)
3. [Data Models](#data-models)
4. [Three-Tier Analysis Pipeline](#three-tier-analysis-pipeline)
5. [Key Methods Reference](#key-methods-reference)
6. [Execution Flow](#execution-flow)
7. [Memory Management](#memory-management)
8. [Thread Management](#thread-management)
9. [Token Optimization Strategy](#token-optimization-strategy)

---

## Overview

The **Conversational Agent** is a pre-supervisor validation and clarification layer that sits **BEFORE** the supervisor agent. It's responsible for:

- ✅ Validating if user requests have all necessary information
- 🤔 Asking clarification questions for incomplete requests
- 🔍 Checking if tasks are feasible with available tools
- 💬 Managing multi-turn conversations with memory
- 🔄 Suggesting alternatives for complex tasks
- 🚀 Optimizing token usage through intelligent tier-based analysis

**File:** `conversational_agent.py` (1753 lines)

**Key Design Principle:** Progressive complexity - only use expensive LLM calls when simpler methods fail.

---

## Core Components

### 1. **ConversationalAgent Class**

```python
class ConversationalAgent:
    def __init__(
        self, 
        openai_api_key: str, 
        model: str = "gpt-4o", 
        temperature: float = 0.3, 
        db_path: str = "threads.db"
    )
```

**Initialization Components:**
- **LLM Instance:** ChatOpenAI from LangChain
- **Full Capabilities Summary:** Pre-built cache of all agent capabilities
- **Memory Managers:** Dictionary of `ConversationMemoryManager` instances (one per conversation)
- **Thread Manager:** SQLite-backed persistent storage for conversation threads

**Dependencies:**
- `langchain_openai.ChatOpenAI` - LLM interface
- `agent_capabilities` - Tool definitions and capabilities
- `ConversationMemoryManager` - Smart memory with auto-summarization
- `ThreadManager` - Persistent thread storage

---

## Data Models

### ConversationIntent (Enum)

Classification categories for user intent:

```python
class ConversationIntent(str, Enum):
    NEEDS_CLARIFICATION = "needs_clarification"  # Missing info
    NOT_FEASIBLE = "not_feasible"                # Can't do with tools
    TOO_COMPLEX = "too_complex"                  # Needs breaking down
    READY_TO_EXECUTE = "ready_to_execute"        # All info present
    SMALL_TALK = "small_talk"                    # Not a task
    CANCELLED = "cancelled"                      # User cancelled
```

### ConversationState (BaseModel)

Tracks conversation progress across messages:

```python
class ConversationState(BaseModel):
    # Core data
    extracted_info: Dict[str, Any]              # Extracted task parameters
    missing_fields: List[str]                   # What's still needed
    intent: Optional[ConversationIntent]        # Current intent
    clarification_question: Optional[str]       # What to ask user
    
    # Execution tracking
    ready_for_execution: bool                   # Ready to proceed?
    execution_summary: Optional[str]            # Human-readable summary
    execution_history: List[Dict[str, Any]]     # Past executions
    executed_count: int                         # Number of executions
    last_plan_hash: Optional[str]               # Dedupe detection
    last_executed_at: Optional[str]             # Timestamp
    executing: bool                             # Currently executing?
    
    # Memory persistence
    memory_state: Optional[Dict[str, Any]]      # Serialized memory
    
    # DEPRECATED
    conversation_history: List[Dict[str, str]]  # Use memory_manager instead
```

**Key State Fields:**
- `extracted_info`: Dictionary of task parameters (e.g., `{"recipient": "john@example.com", "subject": "Meeting"}`)
- `missing_fields`: List of required fields not yet provided
- `ready_for_execution`: Boolean flag indicating if supervisor can execute
- `memory_state`: Serialized memory manager state for persistence

### ConversationAnalysis (BaseModel)

LLM's analysis output after processing a message:

```python
class ConversationAnalysis(BaseModel):
    intent: ConversationIntent                  # What user wants
    task_type: str                              # e.g., "send_email"
    extracted_info: Dict[str, Any]              # Extracted parameters
    missing_fields: List[str]                   # What's still needed
    clarification_question: Optional[str]       # What to ask
    reasoning: str                              # Why this analysis
    suggested_alternatives: Optional[List[str]] # Alternative approaches
    execution_ready: bool                       # Ready to execute?
    execution_summary: Optional[str]            # Human summary for user
```

**Purpose:** Returned by `analyze_request()` to inform how to respond to the user.

---

## Three-Tier Analysis Pipeline

The agent uses a **progressive complexity approach** to minimize token usage:

### ⚡ Tier 0: Pattern-Based Quick Checks (0 tokens, instant)

**No LLM calls** - pure pattern matching for common scenarios.

| Method | Detects | Response Time | Token Cost |
|--------|---------|---------------|------------|
| `_quick_greeting_check()` | Greetings ("hello", "hi") | Instant | 0 |
| `_quick_capability_list_check()` | "What can you do?" | Instant | 0 |
| `_quick_repeat_check()` | "Repeat that", "Say again" | Instant | 0 |
| `_quick_examples_check()` | "Show me examples" | Instant | 0 |
| `_quick_help_check()` | "Help", "How does this work" | Instant | 0 |
| `_quick_status_check()` | "Status?", "Did it work?" | Instant | 0 |

**Logic:**
```python
def _quick_greeting_check(self, user_message: str) -> Optional[ConversationAnalysis]:
    greetings = ["hello", "hi", "hey", "good morning", ...]
    user_lower = user_message.lower().strip()
    
    is_greeting = any(user_lower.startswith(g) for g in greetings) and len(user_message) < 30
    
    if is_greeting:
        return ConversationAnalysis(
            intent=ConversationIntent.SMALL_TALK,
            task_type="greeting",
            execution_ready=False,
            ...
        )
```

**Benefits:**
- Zero token cost
- Instant response (<1ms)
- Handles ~30% of user messages (greetings, help, status checks)

---

### ⚡ Tier 0.5: Unified Lightweight LLM Check (~100-250 tokens)

**Single unified LLM call** for non-task intents. This tier was recently optimized from 3 separate calls to 1 unified call.

**Method:** `_unified_quick_check()`

**Detects 7 Categories:**

| Category | Description | Example | Output |
|----------|-------------|---------|--------|
| `confirmation` | User approves action | "yes", "go ahead" | Execute with current data |
| `cancellation` | User wants to stop | "cancel", "never mind" | Clear state, possibly new task |
| `modification` | Change one field | "change subject to X" | Update field, check completeness |
| `followup_answer` | Simple answer to question | "john@example.com" | Extract value, check completeness |
| `casual_conversation` | Chitchat | "how are you?" | Small talk response |
| `unintelligible` | Gibberish | "asdfkj3489" | Ask for clarification |
| `task_request` | New task or complex request | "send email to..." | **Fall through to Tier 1** |

**Unified Prompt Structure:**

```python
unified_prompt = f"""You are a fast, unified intent classifier and data extractor.

CATEGORIES:
1. confirmation - User approves/confirms
2. cancellation - User wants to cancel (check for compound cancel+task)
3. modification - Change ONE field in existing request
4. followup_answer - Simple answer to clarification question
5. casual_conversation - Chitchat, off-topic
6. unintelligible - Gibberish, unclear
7. task_request - New task or complex multi-step request

{history_snippet}{context_note}

Current user message: "{user_message}"

Reply with JSON:
{{
    "category": "...",
    "confidence": "high|medium|low",
    "reasoning": "...",
    
    // Context-specific fields:
    "has_compound_cancel": false,
    "extracted_value": null,
    "field_to_modify": null,
    "new_value": null
}}
"""
```

**Special Handling:**

1. **Compound Cancellation:** Detects "cancel that AND search for..." → Falls through to Tier 1 for new task
2. **Context-Aware:** Uses conversation state to determine if awaiting confirmation/clarification
3. **Data Extraction:** Extracts values for followup answers and modifications directly

**Token Savings:**
- **Before:** 3 separate LLM calls (~50-450 tokens total)
  - `_quick_intent_check()` (confirmation, cancellation, casual, unintelligible, followup)
  - `_quick_modification_check()` (field modifications)
  - `_quick_followup_answer_extraction()` (followup answer extraction)
- **After:** 1 unified call (~100-250 tokens)
- **Savings:** 40-55% token reduction, 2-3x faster response time

---

### 🔍 Tier 1: Full Task Analysis (~500-1500 tokens)

**Comprehensive LLM analysis** for task requests that need full context.

**Method:** `analyze_request()` → Full LLM prompt with capabilities

**When Used:**
- New task requests ("send email to...", "search for...", "create document...")
- Complex multi-step requests
- Compound cancel+task scenarios
- When Tier 0 and 0.5 don't match

**System Prompt Features:**

1. **Capabilities Context:**
   ```python
   # Smart filtering based on query type
   query_type = classify_query_type(user_message)  # "general" or "specific"
   
   if query_type == "general":
       capabilities_to_show = self.full_capabilities_summary  # All agents
   else:
       relevant_agents = identify_relevant_agents(user_message)  # Filter
       capabilities_to_show = self._build_capabilities_summary(relevant_agents)
   ```

2. **Conversation Context:**
   - Memory manager provides summarized history
   - Recent messages (last N turns)
   - Extracted entities and key info
   - Execution history (if any)

3. **Analysis Instructions:**
   ```
   1. Classify intent (needs_clarification | ready_to_execute | cancelled | ...)
   2. Extract all information mentioned (combine current + history)
   3. List missing required fields
   4. Generate clarification question if needed
   5. Suggest alternatives for complex/infeasible tasks
   6. Provide execution summary if ready
   ```

**Output Example:**

```json
{
    "intent": "needs_clarification",
    "task_type": "send_email",
    "extracted_info": {
        "recipient": "john@example.com",
        "task_type": "send_email"
    },
    "missing_fields": ["subject", "body"],
    "clarification_question": "What should the subject of the email be?",
    "reasoning": "User wants to send email but didn't specify subject or body",
    "execution_ready": false,
    "execution_summary": null
}
```

---

## Key Methods Reference

### 1. `analyze_request()`

**The core analysis pipeline orchestrator.**

```python
def analyze_request(
    self, 
    user_message: str, 
    conversation_state: ConversationState,
    state_id: str = "default"
) -> ConversationAnalysis
```

**Args:**
- `user_message` (str): Current user input
- `conversation_state` (ConversationState): Previous conversation context
- `state_id` (str): Conversation identifier for memory manager

**Returns:**
- `ConversationAnalysis`: Analysis result with intent, extracted info, missing fields, etc.

**Flow:**
```
1. Try Tier 0 checks (greeting, capabilities, repeat, examples, help, status)
   ↓ If matched → Return ConversationAnalysis
   
2. Try Tier 0.5 unified check (confirmation, cancellation, modification, etc.)
   ↓ If matched → Return ConversationAnalysis
   ↓ If task_request → Continue to Tier 1
   
3. Perform Tier 1 full analysis
   - Get memory context
   - Classify query type (general vs specific)
   - Filter capabilities (all vs relevant agents)
   - Build system prompt with capabilities
   - Call LLM with 320s timeout
   - Parse JSON response
   - Return ConversationAnalysis
```

**Error Handling:**
- LLM timeout → Fallback to "needs clarification"
- JSON parse error → Fallback to "needs clarification"
- Missing required fields → Validation error with fallback

---

### 2. `process_message()`

**High-level message processor that updates state and returns response.**

```python
def process_message(
    self, 
    user_message: str, 
    conversation_state: Optional[ConversationState] = None,
    state_id: str = "default",
    auto_save: bool = False
) -> tuple[str, ConversationState]
```

**Args:**
- `user_message` (str): User's input
- `conversation_state` (ConversationState | None): Previous state (None = new conversation)
- `state_id` (str): Unique conversation identifier (thread_id)
- `auto_save` (bool): If True, automatically save to database (for thread mode)

**Returns:**
- `(response_text, updated_conversation_state)`: Tuple of bot response and updated state

**Flow:**
```
1. Get/create memory manager for this conversation
2. Add user message to memory (auto-summarizes if needed)
3. Call analyze_request() to get ConversationAnalysis
4. Detect compound "cancel + new task" scenario
5. Update conversation_state based on analysis:
   - If CANCELLED: Clear extracted_info
   - Else: Merge new extracted_info with existing
   - Update missing_fields, clarification_question, ready_for_execution
6. Generate response based on intent:
   - SMALL_TALK: Casual response
   - CANCELLED: "Request cancelled" + show what was cancelled
   - NOT_FEASIBLE: Explain why + suggest alternatives
   - TOO_COMPLEX: Suggest breaking it down
   - NEEDS_CLARIFICATION: Ask clarification question
   - READY_TO_EXECUTE: Show summary + details
7. Add assistant response to memory
8. Save memory state to conversation_state
9. Auto-save to database if enabled
10. Return (response, conversation_state)
```

**Special Handling:**

**Compound Cancel Detection:**
```python
cancel_keywords = ["cancel", "nevermind", "forget", "stop"]
task_keywords = ["send", "search", "create", "schedule", ...]

has_cancel = any(keyword in user_lower for keyword in cancel_keywords)
has_task = any(keyword in user_lower for keyword in task_keywords)
is_compound_cancel = has_cancel and has_task and analysis.intent != CANCELLED

if is_compound_cancel:
    # Clear old state, use ONLY new task data from analysis
    conversation_state.extracted_info = {}
```

---

### 3. `should_execute()`

**Simple check if conversation is ready for supervisor execution.**

```python
def should_execute(self, conversation_state: ConversationState) -> bool
```

**Args:**
- `conversation_state` (ConversationState): Current state

**Returns:**
- `bool`: True if `ready_for_execution` is True

**Usage:**
```python
if agent.should_execute(state):
    supervisor_input = agent.build_supervisor_input(state)
    # Pass to supervisor...
```

---

### 4. `build_supervisor_input()`

**Converts conversation state to clean input string for supervisor.**

```python
def build_supervisor_input(self, conversation_state: ConversationState) -> str
```

**Args:**
- `conversation_state` (ConversationState): Current state

**Returns:**
- `str`: Clean input string for supervisor (e.g., "Send email to john@example.com with subject 'Meeting notes'")

**Logic:**
- Prefers `execution_summary` if available
- Fallback: Reconstructs from `extracted_info` dictionary

**Example:**
```python
# Input state:
{
    "execution_summary": "Send email to john@example.com with subject 'Meeting'",
    "extracted_info": {"recipient": "john@example.com", "subject": "Meeting"}
}

# Output:
"Send email to john@example.com with subject 'Meeting'"
```

---

### 5. `summarize_execution()`

**Generates human-friendly summary of execution results using LLM.**

```python
def summarize_execution(
    self,
    conversation_state: ConversationState,
    final_context: Dict[str, Any],
    execution_status: str,
    execution_message: str
) -> str
```

**Args:**
- `conversation_state` (ConversationState): Current state
- `final_context` (Dict[str, Any]): All variables from orchestrator (email data, document IDs, etc.)
- `execution_status` (str): Status of execution ("success", "error", etc.)
- `execution_message` (str): Raw execution message from supervisor

**Returns:**
- `str`: Human-friendly summary (under 200 words)

**Key Feature - Context Filtering:**

Uses `_filter_context_for_user()` to remove technical fields:

**Excluded Fields:**
- IDs: `message_id`, `thread_id`, `draft_id`, `document_id`
- Timestamps: `created_at`, `updated_at`, `timestamp`
- System fields: `success`, `error`, `status_code`, `api_version`
- Date context: `today_date`, `yesterday_date`, `current_year`
- HTML content: `body_html`, `body_clean`, `raw_content`
- Flags: `is_draft`, `is_sent`, `is_read`, `has_attachments`

**Meaningful Fields (kept):**
- Communication: `subject`, `body`, `from`, `to`, `cc`, `bcc`
- Documents: `title`, `filename`, `document_url`
- Lists: `emails`, `documents`, `files` (limited to first 5 items)
- Counts: `count`, `total`, `found`, `created`
- Links: `body_links`, `attachments`

**Example:**

Before filtering:
```json
{
  "message_id": "18f4b...",
  "thread_id": "18f4a...",
  "subject": "Q4 Report",
  "from": "alice@company.com",
  "body": "Please review...",
  "created_at": "2025-01-15T10:30:00Z",
  "internal_date": 1705315800,
  "success": true,
  "status_code": 200
}
```

After filtering:
```json
{
  "subject": "Q4 Report",
  "from": "alice@company.com",
  "body": "Please review..."
}
```

**Token Savings:** ~60-80% reduction in context size for summary generation.

---

### 6. `get_memory_stats()`

**Returns memory statistics for debugging and monitoring.**

```python
def get_memory_stats(
    self, 
    conversation_state: ConversationState, 
    state_id: str = "default"
) -> Dict[str, Any]
```

**Args:**
- `conversation_state` (ConversationState): Current state
- `state_id` (str): Conversation identifier

**Returns:**
- `Dict[str, Any]`: Memory statistics dictionary

**Example Output:**
```json
{
  "total_messages": 15,
  "total_tokens": 2500,
  "summary_count": 1,
  "entity_count": 3,
  "last_summary_at": "2025-01-15 10:30:00"
}
```

---

## Execution Flow

### Complete Conversation Flow Diagram

```
User Input
    ↓
┌─────────────────────────────────────────────────────────┐
│ process_message()                                        │
├─────────────────────────────────────────────────────────┤
│ 1. Get/create memory manager                            │
│ 2. Add user message to memory                           │
└─────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────┐
│ analyze_request() - THREE-TIER PIPELINE                 │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ ⚡ TIER 0: Pattern Checks (0 tokens, instant)           │
│   ├─ Greeting? → Return greeting response               │
│   ├─ Capabilities? → Return cached list                 │
│   ├─ Repeat? → Return last message                      │
│   ├─ Examples? → Return examples                        │
│   ├─ Help? → Return help                                │
│   └─ Status? → Return execution status                  │
│        ↓ (none matched)                                  │
│                                                          │
│ ⚡ TIER 0.5: Unified Quick Check (~100-250 tokens)      │
│   Unified LLM call detects:                             │
│   ├─ confirmation → Execute with current data           │
│   ├─ cancellation (pure) → Clear state                  │
│   ├─ cancellation (compound) → Fall through to Tier 1   │
│   ├─ modification → Update field, check completeness    │
│   ├─ followup_answer → Extract value, check complete    │
│   ├─ casual_conversation → Small talk response          │
│   ├─ unintelligible → Ask for clarification             │
│   └─ task_request → Fall through to Tier 1              │
│        ↓ (task_request or complex)                       │
│                                                          │
│ 🔍 TIER 1: Full Task Analysis (~500-1500 tokens)       │
│   ├─ Get memory context (summary + recent messages)     │
│   ├─ Classify query type (general vs specific)          │
│   ├─ Filter capabilities (all vs relevant agents)       │
│   ├─ Build system prompt with capabilities              │
│   ├─ Call LLM with full context                         │
│   └─ Parse JSON response → ConversationAnalysis         │
│                                                          │
└─────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────┐
│ Update conversation_state                                │
├─────────────────────────────────────────────────────────┤
│ - Detect compound cancel+task                           │
│ - Merge extracted_info (or clear if cancelled)          │
│ - Update missing_fields, clarification_question         │
│ - Set ready_for_execution flag                          │
│ - Update intent                                          │
└─────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────┐
│ Generate response based on intent                        │
├─────────────────────────────────────────────────────────┤
│ - SMALL_TALK: Casual response                           │
│ - CANCELLED: "Request cancelled" message                │
│ - NOT_FEASIBLE: Explain why + alternatives              │
│ - TOO_COMPLEX: Suggest breaking down                    │
│ - NEEDS_CLARIFICATION: Ask question + show progress     │
│ - READY_TO_EXECUTE: Show summary + details              │
└─────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────┐
│ Finalization                                             │
├─────────────────────────────────────────────────────────┤
│ 1. Add assistant response to memory                     │
│ 2. Save memory state to conversation_state              │
│ 3. Auto-save to database (if enabled)                   │
│ 4. Return (response, conversation_state)                │
└─────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────┐
│ should_execute() check                                   │
├─────────────────────────────────────────────────────────┤
│ If ready_for_execution == True:                         │
│   → build_supervisor_input()                            │
│   → Pass to supervisor agent                            │
│   → Execute task                                         │
│   → summarize_execution() (with context filtering)      │
└─────────────────────────────────────────────────────────┘
    ↓
Bot Response to User
```

---

## Memory Management

The conversational agent uses `ConversationMemoryManager` for intelligent memory handling.

### Memory Manager Features

1. **Automatic Summarization:**
   - Triggers when token count exceeds `max_tokens_before_summary` (default: 2000)
   - LLM creates concise summary of conversation so far
   - Preserves extracted entities (emails, names, dates, etc.)
   - Keeps recent messages (last N turns) for context

2. **Efficient Context Retrieval:**
   - `get_context_for_llm()` returns: summary + entities + recent messages
   - Format optimized for LLM consumption
   - Reduces token usage by ~70% for long conversations

3. **Export/Import:**
   - `export_memory()` serializes to dict
   - `load_memory()` restores from dict
   - Used for thread persistence

### Memory Manager Methods Used

```python
# Get or create memory manager
memory_manager = self._get_memory_manager(state_id, memory_state)

# Add messages (auto-summarizes if needed)
memory_manager.add_message("user", user_message)
memory_manager.add_message("assistant", response)

# Get context for LLM
context = memory_manager.get_context_for_llm()

# Get recent messages
recent = memory_manager.get_recent_messages(n=5)

# Export/import for persistence
memory_data = memory_manager.export_memory()
memory_manager.load_memory(memory_data)

# Statistics
stats = memory_manager.get_stats()
```

### Memory in ConversationState

```python
class ConversationState(BaseModel):
    memory_state: Optional[Dict[str, Any]]  # Serialized memory manager state
```

**Persistence Flow:**
```
1. process_message() → Add messages to memory manager
2. _save_memory_to_state() → Export memory to conversation_state.memory_state
3. Auto-save to database (if enabled)

On load:
1. Load thread from database → Get conversation_state
2. _get_memory_manager() → Restore from conversation_state.memory_state
3. Memory manager ready with full history
```

---

## Thread Management

The conversational agent supports **persistent multi-turn conversations** using SQLite storage.

### Thread Database Schema

**Tables:**
1. `threads` - Thread metadata
   - `thread_id` (PK): UUID
   - `user_id`: User identifier
   - `title`: Thread title (auto-generated or custom)
   - `status`: "active" | "archived"
   - `tags`: JSON array
   - `message_count`: Number of messages
   - `last_message_preview`: First 100 chars of last message
   - `created_at`, `updated_at`: Timestamps

2. `conversation_states` - Conversation state snapshots
   - `thread_id` (FK): Links to threads
   - `state_data`: JSON blob (ConversationState)
   - `updated_at`: Timestamp

3. `memory_states` - Memory manager snapshots
   - `thread_id` (FK): Links to threads
   - `memory_data`: JSON blob (memory manager export)
   - `updated_at`: Timestamp

4. `messages` - Full message history
   - `id` (PK): Auto-increment
   - `thread_id` (FK): Links to threads
   - `role`: "user" | "assistant"
   - `content`: Message text
   - `created_at`: Timestamp

### Thread Management Methods

#### Create New Thread

```python
def create_new_thread(
    self, 
    user_id: str, 
    initial_message: Optional[str] = None,
    title: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> tuple[str, ConversationState, Optional[str]]
```

**Args:**
- `user_id` (str): Unique identifier for the user
- `initial_message` (str | None): Optional first message to process
- `title` (str | None): Optional custom title (auto-generated if not provided)
- `tags` (List[str] | None): Optional tags for categorization

**Returns:**
- `(thread_id, initial_conversation_state, bot_response)`
- `bot_response` is None if no initial_message provided

**Example:**
```python
thread_id, state, response = agent.create_new_thread(
    user_id="user123",
    initial_message="Send an email to john@example.com",
    tags=["email", "work"]
)
# thread_id: "uuid-1234-5678-..."
# response: "Who would you like to send this email to?"
```

#### Continue Existing Thread

```python
def continue_thread(
    self,
    thread_id: str,
    new_message: str
) -> tuple[str, ConversationState]
```

**Args:**
- `thread_id` (str): Thread identifier
- `new_message` (str): New user message to process

**Returns:**
- `(response, updated_conversation_state)`

**Example:**
```python
response, state = agent.continue_thread(
    thread_id="uuid-1234-5678-...",
    new_message="The subject should be 'Meeting Notes'"
)
```

#### List User Threads

```python
def list_user_threads(
    self,
    user_id: str,
    status: Optional[str] = "active",
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]
```

**Args:**
- `user_id` (str): User identifier
- `status` (str | None): Filter by status ("active", "archived", "all")
- `limit` (int): Maximum threads to return
- `offset` (int): Offset for pagination

**Returns:**
- `List[Dict]`: List of thread metadata dictionaries

**Example:**
```python
threads = agent.list_user_threads(
    user_id="user123",
    status="active",
    limit=10
)
# Returns:
# [
#   {"thread_id": "...", "title": "Email to John", "message_count": 5, ...},
#   {"thread_id": "...", "title": "Document creation", "message_count": 3, ...}
# ]
```

#### Get Thread Messages

```python
def get_thread_messages(
    self,
    thread_id: str,
    limit: int = 50,
    offset: int = 0
) -> Optional[List[Dict[str, Any]]]
```

**Args:**
- `thread_id` (str): Thread identifier
- `limit` (int): Maximum messages to return
- `offset` (int): Pagination offset

**Returns:**
- `List[Dict]`: List of messages with `role`, `content`, `created_at`

**Example:**
```python
messages = agent.get_thread_messages("uuid-1234-5678-...")
# Returns:
# [
#   {"role": "user", "content": "Send email...", "created_at": "2025-01-15 10:30:00"},
#   {"role": "assistant", "content": "Who would you like...", "created_at": "2025-01-15 10:30:01"}
# ]
```

#### Update Thread Metadata

```python
def update_thread_metadata(
    self,
    thread_id: str,
    title: Optional[str] = None,
    tags: Optional[List[str]] = None,
    status: Optional[str] = None
) -> bool
```

**Args:**
- `thread_id` (str): Thread identifier
- `title` (str | None): New title
- `tags` (List[str] | None): New tags
- `status` (str | None): New status

**Returns:**
- `bool`: True if successful

#### Archive/Delete Thread

```python
def archive_thread(self, thread_id: str) -> bool
def delete_thread(self, thread_id: str, hard_delete: bool = False) -> bool
```

**Args:**
- `thread_id` (str): Thread identifier
- `hard_delete` (bool): If True, permanently delete. If False, archive only.

**Returns:**
- `bool`: True if successful

#### Search Threads

```python
def search_threads(
    self,
    user_id: str,
    query: str,
    limit: int = 20
) -> List[Dict[str, Any]]
```

**Args:**
- `user_id` (str): User identifier
- `query` (str): Search query (searches thread titles)
- `limit` (int): Maximum results

**Returns:**
- `List[Dict]`: Matching thread metadata

---

## Token Optimization Strategy

### Overall Approach

The conversational agent uses **progressive complexity** to minimize token usage:

```
TIER 0 (0 tokens)
    ↓ (if no match)
TIER 0.5 (~100-250 tokens)
    ↓ (if task_request or complex)
TIER 1 (~500-1500 tokens)
```

### Token Breakdown by Tier

| Tier | Token Range | Use Cases | Success Rate |
|------|-------------|-----------|--------------|
| Tier 0 | 0 | Greetings, help, status, capabilities | ~30% of messages |
| Tier 0.5 | 100-250 | Confirmation, cancellation, modifications, followup | ~50% of messages |
| Tier 1 | 500-1500 | New task requests, complex analysis | ~20% of messages |

### Tier 0.5 Optimization (Recent Improvement)

**Before:**
- 3 separate LLM calls: `_quick_intent_check()`, `_quick_modification_check()`, `_quick_followup_answer_extraction()`
- Combined token usage: 50-450 tokens
- Sequential processing: ~3-6 seconds

**After:**
- 1 unified LLM call: `_unified_quick_check()`
- Token usage: 100-250 tokens
- Single call: ~1-2 seconds
- **Savings:** 40-55% token reduction, 2-3x faster

### Memory Optimization

**Automatic Summarization:**
- Raw conversation: ~100-200 tokens per turn
- After 10 turns: ~1000-2000 tokens (triggers summarization)
- Summarized: ~200-400 tokens (summary + entities + recent 3 turns)
- **Savings:** ~70% token reduction for long conversations

**Context Filtering (for execution summaries):**
- Raw `final_context`: ~500-1000 tokens (all technical fields)
- Filtered context: ~200-400 tokens (user-relevant fields only)
- **Savings:** ~60-80% token reduction

### Capability Filtering

**Smart Context Injection:**
```python
query_type = classify_query_type(user_message)

if query_type == "general":
    capabilities = full_capabilities_summary  # All agents (~800 tokens)
else:
    relevant_agents = identify_relevant_agents(user_message)
    capabilities = filtered_capabilities  # Specific agents (~200-400 tokens)
```

**Savings:** ~50-75% for task-specific queries

### Combined Impact

**Example Conversation (5 turns):**

| Step | Without Optimization | With Optimization | Savings |
|------|---------------------|-------------------|---------|
| Turn 1: Greeting | 500 tokens (full analysis) | 0 tokens (Tier 0) | 100% |
| Turn 2: "Send email..." | 1200 tokens | 1200 tokens | 0% |
| Turn 3: "john@example.com" | 450 tokens (3 calls) | 180 tokens (unified) | 60% |
| Turn 4: "Change subject to X" | 450 tokens (3 calls) | 180 tokens (unified) | 60% |
| Turn 5: "yes, proceed" | 150 tokens | 100 tokens (unified) | 33% |
| **Total** | **2750 tokens** | **1660 tokens** | **~40%** |

---

## Summary

### Key Takeaways

1. **Three-Tier Architecture:** Progressive complexity reduces token usage by 40-70%
2. **Unified Tier 0.5:** Single LLM call handles 7 categories (confirmation, cancellation, modification, followup, casual, unintelligible, task_request)
3. **Smart Context Management:** Memory summarization, capability filtering, context filtering
4. **Persistent Conversations:** Thread management with SQLite for multi-turn support
5. **Error Handling:** Robust fallbacks at every level (LLM timeout, JSON parse errors, validation errors)

### When to Use Each Method

| Task | Method | Tier |
|------|--------|------|
| Greeting detection | `_quick_greeting_check()` | 0 |
| Capabilities list | `_quick_capability_list_check()` | 0 |
| Confirmation/cancellation | `_unified_quick_check()` | 0.5 |
| Field modification | `_unified_quick_check()` | 0.5 |
| Followup answer | `_unified_quick_check()` | 0.5 |
| New task request | Full `analyze_request()` | 1 |
| Complex multi-step | Full `analyze_request()` | 1 |

### Integration with Supervisor

```python
# 1. Create agent
agent = ConversationalAgent(openai_api_key="...", db_path="threads.db")

# 2. Create or continue thread
thread_id, state, response = agent.create_new_thread(
    user_id="user123",
    initial_message="Send email to john@example.com"
)

# 3. Continue conversation
while not agent.should_execute(state):
    user_input = input("You: ")
    response, state = agent.continue_thread(thread_id, user_input)
    print(f"Bot: {response}")

# 4. Execute when ready
if agent.should_execute(state):
    supervisor_input = agent.build_supervisor_input(state)
    # Pass to supervisor agent...
    # final_context = supervisor.execute(supervisor_input)
    
    # 5. Summarize results
    summary = agent.summarize_execution(
        state, 
        final_context, 
        "success", 
        "Email sent successfully"
    )
    print(f"Summary: {summary}")
```

---

## Additional Resources

- **Memory Management:** See `conversation_memory.py` for `ConversationMemoryManager` details
- **Thread Storage:** See `thread_manager.py` for database schema and persistence
- **Agent Capabilities:** See `agent_capabilities.py` for tool definitions
- **Utility Functions:** See `utils.py` for `identify_relevant_agents()`, `classify_query_type()`

---

**Document Version:** 1.0  
**Last Updated:** November 6, 2025  
**Agent Version:** Unified Tier 0.5 (optimized)
