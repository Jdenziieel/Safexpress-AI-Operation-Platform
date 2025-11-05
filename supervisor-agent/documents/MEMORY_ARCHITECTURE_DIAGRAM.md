# Conversation Memory System - Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                        │
│                        CONVERSATIONAL AGENT WITH MEMORY MANAGER                        │
│                                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                    USER INTERACTION                                     │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  User sends message                                                                     │
│       ↓                                                                                 │
│  ConversationalAgent.process_message(message, state, state_id="user_123")              │
│       ↓                                                                                 │
│  ┌────────────────────────────────────────────────────────────────────────┐            │
│  │ STEP 1: Get or Create Memory Manager                                   │            │
│  │                                                                         │            │
│  │  memory_manager = _get_memory_manager(state, "user_123")               │            │
│  │                                                                         │            │
│  │  If new:                                                                │            │
│  │    • Create ConversationMemoryManager                                  │            │
│  │    • Check if state.memory_state exists (persistence)                  │            │
│  │    • If yes: Load from persisted state                                 │            │
│  │    • If no + old conversation_history exists: Migrate                  │            │
│  └────────────────────────────────────────────────────────────────────────┘            │
│       ↓                                                                                 │
│  ┌────────────────────────────────────────────────────────────────────────┐            │
│  │ STEP 2: Add User Message to Memory                                     │            │
│  │                                                                         │            │
│  │  memory_manager.add_message("user", message)                           │            │
│  │       ↓                                                                 │            │
│  │  ┌──────────────────────────────────────────────────────────┐          │            │
│  │  │ Memory Manager Internal Flow:                            │          │            │
│  │  │                                                           │          │            │
│  │  │  1. Append to raw_history (permanent record)             │          │            │
│  │  │  2. Append to working_context (recent messages)          │          │            │
│  │  │  3. Count tokens: current_token_count += tokens          │          │            │
│  │  │  4. Check: current_token_count > MAX_TOKENS?             │          │            │
│  │  │      ↓                                                    │          │            │
│  │  │      YES → TRIGGER SUMMARIZATION                         │          │            │
│  │  │      ↓                                                    │          │            │
│  │  │  ┌──────────────────────────────────────────────┐        │          │            │
│  │  │  │ _summarize_conversation()                    │        │          │            │
│  │  │  │                                              │        │          │            │
│  │  │  │  A. Split working_context:                  │        │          │            │
│  │  │  │     old_msgs = first_half                   │        │          │            │
│  │  │  │     recent_msgs = second_half               │        │          │            │
│  │  │  │                                              │        │          │            │
│  │  │  │  B. Call LLM:                                │        │          │            │
│  │  │  │     Prompt: "Summarize old_msgs"            │        │          │            │
│  │  │  │     Response: {                              │        │          │            │
│  │  │  │       "summary": "condensed history",       │        │          │            │
│  │  │  │       "entities": {                          │        │          │            │
│  │  │  │         "people": [...],                     │        │          │            │
│  │  │  │         "tasks": [...],                      │        │          │            │
│  │  │  │         "dates": [...]                       │        │          │            │
│  │  │  │       }                                       │        │          │            │
│  │  │  │     }                                         │        │          │            │
│  │  │  │                                              │        │          │            │
│  │  │  │  C. Update memory:                           │        │          │            │
│  │  │  │     summary = new_summary                    │        │          │            │
│  │  │  │     entity_memory += new_entities            │        │          │            │
│  │  │  │     working_context = recent_msgs            │        │          │            │
│  │  │  │     current_token_count = recalculate()      │        │          │            │
│  │  │  └──────────────────────────────────────────────┘        │          │            │
│  │  └──────────────────────────────────────────────────────────┘          │            │
│  └────────────────────────────────────────────────────────────────────────┘            │
│       ↓                                                                                 │
│  ┌────────────────────────────────────────────────────────────────────────┐            │
│  │ STEP 3: Analyze Request (7-Stage Pipeline)                             │            │
│  │                                                                         │            │
│  │  analysis = analyze_request(message, state, "user_123")                │            │
│  │       ↓                                                                 │            │
│  │  Stage 1: _quick_intent_check()                                        │            │
│  │    • Uses memory_manager.get_recent_messages(n=3)                      │            │
│  │    • Fast classification (200 tokens)                                  │            │
│  │       ↓                                                                 │            │
│  │  Stage 1.5-1.8: Quick checks (help, status, modification, followup)    │            │
│  │       ↓                                                                 │            │
│  │  Stage 2: Full Analysis                                                │            │
│  │    • Uses memory_manager.get_context_for_llm()                         │            │
│  │    • Returns: summary + entities + recent messages                     │            │
│  │    • Comprehensive analysis (2000+ tokens)                             │            │
│  └────────────────────────────────────────────────────────────────────────┘            │
│       ↓                                                                                 │
│  ┌────────────────────────────────────────────────────────────────────────┐            │
│  │ STEP 4: Generate Response                                              │            │
│  │                                                                         │            │
│  │  Based on analysis.intent:                                             │            │
│  │    • NEEDS_CLARIFICATION → Ask question                                │            │
│  │    • READY_TO_EXECUTE → Confirm execution                              │            │
│  │    • NOT_FEASIBLE → Explain limitations                                │            │
│  │    • SMALL_TALK → Friendly response                                    │            │
│  └────────────────────────────────────────────────────────────────────────┘            │
│       ↓                                                                                 │
│  ┌────────────────────────────────────────────────────────────────────────┐            │
│  │ STEP 5: Add Assistant Response to Memory                               │            │
│  │                                                                         │            │
│  │  memory_manager.add_message("assistant", response)                     │            │
│  │    • Same flow as Step 2 (may trigger summarization again)             │            │
│  └────────────────────────────────────────────────────────────────────────┘            │
│       ↓                                                                                 │
│  ┌────────────────────────────────────────────────────────────────────────┐            │
│  │ STEP 6: Save Memory State for Persistence                              │            │
│  │                                                                         │            │
│  │  _save_memory_to_state(state, "user_123")                              │            │
│  │    • Exports memory_manager state                                      │            │
│  │    • Saves to state.memory_state                                       │            │
│  │    • Also updates state.conversation_history (backward compat)         │            │
│  └────────────────────────────────────────────────────────────────────────┘            │
│       ↓                                                                                 │
│  Return (response, updated_state)                                                      │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              MEMORY MANAGER STATE                                       │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐              │
│  │ 📚 raw_history (NEVER TRUNCATED)                                     │              │
│  │                                                                       │              │
│  │  [                                                                    │              │
│  │    {"role": "user", "content": "Send email to john@example.com"},    │              │
│  │    {"role": "assistant", "content": "What's the subject?"},          │              │
│  │    {"role": "user", "content": "Q4 Planning Meeting"},               │              │
│  │    ... (all 50 messages)                                              │              │
│  │  ]                                                                    │              │
│  │                                                                       │              │
│  │  Purpose: Complete audit trail, never modified                       │              │
│  └──────────────────────────────────────────────────────────────────────┘              │
│                                                                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐              │
│  │ 🔄 working_context (RECENT MESSAGES)                                 │              │
│  │                                                                       │              │
│  │  [                                                                    │              │
│  │    {"role": "user", "content": "Create doc about invoices"},         │              │
│  │    {"role": "assistant", "content": "What's the title?"},            │              │
│  │    {"role": "user", "content": "October Invoices"},                  │              │
│  │    {"role": "assistant", "content": "✅ Doc created"},               │              │
│  │    {"role": "user", "content": "Search emails from Sarah"},          │              │
│  │    {"role": "assistant", "content": "Found 3 emails"}                │              │
│  │  ]                                                                    │              │
│  │                                                                       │              │
│  │  Purpose: Recent context for LLM (auto-trimmed when threshold)       │              │
│  │  Size: ~850 tokens                                                   │              │
│  └──────────────────────────────────────────────────────────────────────┘              │
│                                                                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐              │
│  │ 📝 summary (CONDENSED HISTORY)                                       │              │
│  │                                                                       │              │
│  │  "User sent email to john@example.com about Q4 planning meeting.     │              │
│  │   Then searched for invoices from last month and created a document  │              │
│  │   summarizing them. Multiple back-and-forth clarifications occurred. │              │
│  │   User then searched for emails from Sarah and replied to them."     │              │
│  │                                                                       │              │
│  │  Purpose: Preserve old context in compressed form                    │              │
│  │  Size: ~200 tokens (vs 1200 tokens for full history)                │              │
│  └──────────────────────────────────────────────────────────────────────┘              │
│                                                                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐              │
│  │ 🏷️ entity_memory (EXTRACTED ENTITIES)                                │              │
│  │                                                                       │              │
│  │  {                                                                    │              │
│  │    "people": [                                                        │              │
│  │      "john@example.com",                                              │              │
│  │      "Sarah",                                                         │              │
│  │      "sarah@example.com"                                              │              │
│  │    ],                                                                 │              │
│  │    "tasks": [                                                         │              │
│  │      "send email",                                                    │              │
│  │      "search invoices",                                               │              │
│  │      "create document",                                               │              │
│  │      "reply to email"                                                 │              │
│  │    ],                                                                 │              │
│  │    "dates": [                                                         │              │
│  │      "tomorrow at 3pm",                                               │              │
│  │      "last month",                                                    │              │
│  │      "Friday"                                                         │              │
│  │    ],                                                                 │              │
│  │    "documents": [                                                     │              │
│  │      "Q4 Planning Meeting",                                           │              │
│  │      "October Invoices"                                               │              │
│  │    ]                                                                  │              │
│  │  }                                                                    │              │
│  │                                                                       │              │
│  │  Purpose: Track important entities across entire conversation        │              │
│  │  Size: ~150 tokens                                                   │              │
│  └──────────────────────────────────────────────────────────────────────┘              │
│                                                                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐              │
│  │ 📊 STATISTICS                                                         │              │
│  │                                                                       │              │
│  │  current_token_count: 1850                                            │              │
│  │  MAX_TOKENS_BEFORE_SUMMARY: 2000                                     │              │
│  │  token_utilization: 92.5%                                            │              │
│  │  total_messages: 50                                                  │              │
│  │  working_context_messages: 6                                         │              │
│  │  has_summary: true                                                   │              │
│  │  entity_types: 4                                                     │              │
│  │  total_entities: 15                                                  │              │
│  └──────────────────────────────────────────────────────────────────────┘              │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                          CONTEXT BUILDING FOR LLM                                       │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  get_context_for_llm() combines:                                                       │
│                                                                                         │
│  ┌────────────────────────────────────────────────────────┐                            │
│  │ CONVERSATION SUMMARY: (200 tokens)                     │                            │
│  │ User sent email to john@example.com about Q4 planning  │                            │
│  │ meeting. Then searched for invoices from last month... │                            │
│  └────────────────────────────────────────────────────────┘                            │
│                          +                                                              │
│  ┌────────────────────────────────────────────────────────┐                            │
│  │ KNOWN ENTITIES: (150 tokens)                           │                            │
│  │   PEOPLE: john@example.com, Sarah                      │                            │
│  │   TASKS: send email, search invoices                   │                            │
│  │   DATES: tomorrow at 3pm, last month                   │                            │
│  │   DOCUMENTS: Q4 Planning, October Invoices            │                            │
│  └────────────────────────────────────────────────────────┘                            │
│                          +                                                              │
│  ┌────────────────────────────────────────────────────────┐                            │
│  │ RECENT CONVERSATION: (850 tokens)                      │                            │
│  │ USER: Create doc about invoices                        │                            │
│  │ ASSISTANT: What's the title?                           │                            │
│  │ USER: October Invoices                                 │                            │
│  │ ASSISTANT: ✅ Doc created                              │                            │
│  │ USER: Search emails from Sarah                         │                            │
│  │ ASSISTANT: Found 3 emails                              │                            │
│  └────────────────────────────────────────────────────────┘                            │
│                          ↓                                                              │
│                    Total: ~1200 tokens                                                  │
│                                                                                         │
│  vs WITHOUT memory manager:                                                            │
│    • Full history: 50 messages × 100 tokens = 5000 tokens 💥 OVERFLOW                  │
│                                                                                         │
│  Savings: 76% token reduction! (1200 vs 5000)                                          │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              PERSISTENCE FLOW                                           │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  After processing message:                                                              │
│       ↓                                                                                 │
│  _save_memory_to_state(state, "user_123")                                              │
│       ↓                                                                                 │
│  memory_manager.export_memory()                                                         │
│       ↓                                                                                 │
│  {                                                                                      │
│    "raw_history": [...],         ← All 50 messages                                     │
│    "working_context": [...],     ← Recent 6 messages                                   │
│    "entity_memory": {...},       ← 15 entities                                         │
│    "summary": "...",              ← Condensed history                                  │
│    "current_token_count": 1850,                                                        │
│    "MAX_TOKENS_BEFORE_SUMMARY": 2000                                                   │
│  }                                                                                      │
│       ↓                                                                                 │
│  state.memory_state = exported_dict                                                    │
│  state.conversation_history = raw_history  ← Backward compatibility                    │
│       ↓                                                                                 │
│  Database.save(conversation_id, state.dict())                                          │
│                                                                                         │
│  ─────────────────────────────────────────────────                                     │
│                                                                                         │
│  On next request (same conversation):                                                  │
│       ↓                                                                                 │
│  state = Database.load(conversation_id)                                                │
│       ↓                                                                                 │
│  memory_manager = _get_memory_manager(state, "user_123")                               │
│       ↓                                                                                 │
│  Check: state.memory_state exists?                                                     │
│    YES → memory_manager.load_memory(state.memory_state)                                │
│           ↓                                                                             │
│           Restored: All 50 messages, summary, entities ✅                               │
│                                                                                         │
│    NO (old format) → Migrate from state.conversation_history                           │
│           ↓                                                                             │
│           for msg in state.conversation_history:                                       │
│               memory_manager.add_message(msg['role'], msg['content'])                  │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                          TOKEN FLOW VISUALIZATION                                       │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  Turn 1:    100 tokens   ███                                                           │
│  Turn 2:    250 tokens   ███████                                                       │
│  Turn 3:    400 tokens   ████████████                                                  │
│  Turn 4:    550 tokens   ████████████████                                              │
│  Turn 5:    700 tokens   █████████████████████                                         │
│  Turn 6:    850 tokens   █████████████████████████                                     │
│  Turn 7:   1000 tokens   ██████████████████████████████                                │
│  Turn 8:   1150 tokens   ██████████████████████████████████                            │
│  Turn 9:   1300 tokens   ████████████████████████████████████                          │
│  Turn 10:  1450 tokens   ███████████████████████████████████████                       │
│  Turn 11:  1600 tokens   ████████████████████████████████████████                      │
│  Turn 12:  1750 tokens   █████████████████████████████████████████                     │
│  Turn 13:  1900 tokens   ██████████████████████████████████████████                    │
│  Turn 14:  2050 tokens   ███████████████████████████████████████████ 🔥 THRESHOLD!    │
│              ↓                                                                          │
│         SUMMARIZE!                                                                      │
│              ↓                                                                          │
│  Turn 15:   850 tokens   █████████████████████████                                     │
│  Turn 16:  1000 tokens   ██████████████████████████████                                │
│  ...                                                                                    │
│  Turn 50:  1850 tokens   █████████████████████████████████████████ ✅                  │
│                                                                                         │
│  Without memory manager: Turn 20 would be 2000 tokens → OVERFLOW! 💥                   │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```
