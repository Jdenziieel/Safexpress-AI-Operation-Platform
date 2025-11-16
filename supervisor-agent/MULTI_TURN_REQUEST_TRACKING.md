# Multi-Turn Request Tracking Solution

## Problem Analysis

### Current State Issues

Your system has a **critical gap** in tracking the original user intent across multi-turn conversations:

```python
# ConversationState (Current)
class ConversationState(BaseModel):
    extracted_info: Dict[str, Any]        # ✅ Tracks extracted parameters
    missing_fields: List[str]             # ✅ Tracks what's still needed
    execution_summary: Optional[str]      # ⚠️ Only set when READY_TO_EXECUTE
    # ❌ NO field for original user request!
```

### The Problem Scenario

**Turn 1:**
```
User: "forward email from john@example.com to jane@example.com"
System: extracted_info = {"query": "john@example.com", "to": "jane@example.com"}
         missing_fields = ["message_id"]
         execution_summary = None  ❌ Not set yet!
         
Bot: "Which email from john@example.com should I forward? Can you be more specific?"
```

**Turn 2:**
```
User: "the one about the project update"
System: extracted_info = {"query": "john@example.com project update", "to": "jane@example.com"}
         missing_fields = ["message_id"]
         execution_summary = None  ❌ Still not set!
```

**Turn 3:**
```
User: "yes proceed"
System: execution_summary = "Forward email from john@example.com to jane@example.com"  ✅ FINALLY set!
```

**The Gap:**
- When you call `build_supervisor_input()` in Turn 2, `execution_summary` is `None`
- Fallback reconstructs: `"forward_email with query: john@example.com, to: jane@example.com"`
- **Missing context:** What is the user ACTUALLY trying to do? Forward? Search? Reply?

### Root Cause

1. **`execution_summary` is only set when `execution_ready=True`**
   - Multi-turn conversations never reach `READY_TO_EXECUTE` until the final turn
   - Intermediate turns have no record of the original task intent

2. **`extracted_info` loses semantic meaning**
   - `{"query": "john@example.com", "to": "jane@example.com"}` could be:
     - Forward email from john to jane
     - Search emails from john, then compose to jane
     - Reply to john's email, CC jane
   - The `task_type` field helps, but it's buried in `extracted_info`

3. **Supervisor receives incomplete context**
   - `build_supervisor_input()` falls back to reconstructing from `extracted_info`
   - Result: `"forward_email with query: john@example.com, to: jane@example.com"`
   - Better: `"User wants to forward an email from john@example.com to jane@example.com. We're currently clarifying which specific email."`

---

## Solution: Add Original Request Tracking

### Approach 1: Add `original_user_request` Field (Recommended)

**Best for:** Preserving the exact user intent from the first turn

```python
class ConversationState(BaseModel):
    """Tracks conversation history and extracted information"""
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    extracted_info: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    intent: Optional[ConversationIntent] = None
    clarification_question: Optional[str] = None
    ready_for_execution: bool = False
    execution_summary: Optional[str] = None
    
    # ✅ NEW: Track original user request
    original_user_request: Optional[str] = None  # First task-related message
    task_initiated_at: Optional[str] = None       # Timestamp when task started
    conversation_turn_count: int = 0              # Number of turns in this task
    
    # Execution metadata
    execution_history: List[Dict[str, Any]] = Field(default_factory=list)
    executed_count: int = 0
    last_plan_hash: Optional[str] = None
    last_executed_at: Optional[str] = None
    executing: bool = False
    memory_state: Optional[Dict[str, Any]] = None
```

**Logic to populate:**

```python
def process_message(self, user_message: str, conversation_state: ConversationState, ...):
    # ... existing code ...
    
    analysis = self.analyze_request(user_message, conversation_state, state_id)
    
    # ✅ Track original request when task starts
    if analysis.intent not in [ConversationIntent.SMALL_TALK, ConversationIntent.CANCELLED]:
        # If this is the first task-related message, store it
        if not conversation_state.original_user_request:
            conversation_state.original_user_request = user_message
            conversation_state.task_initiated_at = datetime.now().isoformat()
            conversation_state.conversation_turn_count = 1
        else:
            # Increment turn count for ongoing task
            conversation_state.conversation_turn_count += 1
    
    # Handle cancellation - clear original request too
    if analysis.intent == ConversationIntent.CANCELLED:
        conversation_state.original_user_request = None
        conversation_state.task_initiated_at = None
        conversation_state.conversation_turn_count = 0
        # ... rest of cancellation logic ...
```

**Updated `build_supervisor_input()`:**

```python
def build_supervisor_input(self, conversation_state: ConversationState) -> str:
    """
    Build a complete, well-formed input for the supervisor agent.
    Priority:
    1. execution_summary (human-friendly, set when ready)
    2. original_user_request (user's exact words from first turn)
    3. Reconstructed from extracted_info (fallback)
    """
    # Priority 1: Use execution_summary if available (most reliable)
    if conversation_state.execution_summary:
        return conversation_state.execution_summary
    
    # Priority 2: Use original user request if this is a multi-turn conversation
    if conversation_state.original_user_request:
        task_type = conversation_state.extracted_info.get("task_type", "task")
        
        # Add context about what's been collected
        context_parts = []
        for key, value in conversation_state.extracted_info.items():
            if key != "task_type" and value:
                context_parts.append(f"{key}={value}")
        
        if context_parts:
            context_str = ", ".join(context_parts)
            return f"{conversation_state.original_user_request} [Clarifying: {context_str}]"
        else:
            return conversation_state.original_user_request
    
    # Priority 3: Fallback reconstruction (least reliable)
    info = conversation_state.extracted_info
    task_type = info.get("task_type", "task")
    parts = [f"{k}: {v}" for k, v in info.items() if k != "task_type"]
    return f"{task_type} with " + ", ".join(parts) if parts else task_type
```

---

### Approach 2: Enhance `execution_summary` Early (Alternative)

**Best for:** If you want to avoid adding new fields

```python
def analyze_request(self, user_message: str, conversation_state: ConversationState, ...):
    # ... existing Tier 1 analysis ...
    
    analysis_result = ConversationAnalysis(**analysis_dict)
    
    # ✅ ALWAYS set execution_summary, even if not ready
    if not analysis_result.execution_summary and analysis_result.extracted_info:
        # Generate preliminary summary even for NEEDS_CLARIFICATION
        task_type = analysis_result.extracted_info.get("task_type", "task")
        summary_parts = []
        for key, value in analysis_result.extracted_info.items():
            if key != "task_type" and value:
                summary_parts.append(f"{key}: {value}")
        
        if summary_parts:
            analysis_result.execution_summary = f"{task_type} - " + ", ".join(summary_parts)
    
    return analysis_result
```

**Updated System Prompt for Tier 1:**

```python
system_prompt = f"""...

JSON OUTPUT:
{{
    "intent": "needs_clarification|not_feasible|too_complex|ready_to_execute|small_talk",
    "task_type": "send_email|search_emails|reply_to_email|etc",
    "extracted_info": {{"to": "john@example.com", "subject": "Meeting"}},
    "missing_fields": ["to", "subject"],
    "clarification_question": "Who should I send this to?",
    "reasoning": "1 sentence explanation",
    "suggested_alternatives": ["Alternative 1", "Alternative 2"],
    "execution_ready": false,
    "execution_summary": "Send email to john@example.com about Meeting"  // ✅ ALWAYS provide, even if not ready
}}

IMPORTANT: Always provide execution_summary - a human-readable description of what the user wants to do.
This helps track the conversation context across multiple turns.
"""
```

---

### Approach 3: Add `task_context` Object (Most Comprehensive)

**Best for:** Complex multi-turn tracking with rich metadata

```python
class TaskContext(BaseModel):
    """Tracks the full context of the current task being clarified"""
    original_request: str                    # User's exact first message
    task_type: str                           # e.g., "forward_email", "search_emails"
    task_description: str                    # Human-readable summary
    initiated_at: str                        # ISO timestamp
    turn_count: int = 1                      # Number of clarification turns
    clarification_history: List[Dict[str, str]] = Field(default_factory=list)  # Track what was asked/answered
    partial_extractions: List[Dict[str, Any]] = Field(default_factory=list)    # Evolution of extracted_info

class ConversationState(BaseModel):
    """Tracks conversation history and extracted information"""
    extracted_info: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    intent: Optional[ConversationIntent] = None
    clarification_question: Optional[str] = None
    ready_for_execution: bool = False
    execution_summary: Optional[str] = None
    
    # ✅ NEW: Rich task context
    task_context: Optional[TaskContext] = None
    
    # Execution metadata
    execution_history: List[Dict[str, Any]] = Field(default_factory=list)
    executed_count: int = 0
    memory_state: Optional[Dict[str, Any]] = None
```

**Benefits:**
- Full audit trail of clarification process
- Can regenerate execution_summary at any point
- Helpful for debugging multi-turn failures
- Rich context for supervisor planning

---

## Implementation Recommendation

### **Go with Approach 1** (Add `original_user_request`)

**Why:**
1. ✅ **Simplest implementation** - minimal code changes
2. ✅ **Preserves user intent** - exact words matter for supervisor planning
3. ✅ **Backward compatible** - doesn't break existing logic
4. ✅ **Low overhead** - just one string field
5. ✅ **Solves the core problem** - supervisor gets meaningful context

**Implementation Steps:**

1. **Update `ConversationState` model** (Add 3 new fields)
2. **Update `process_message()`** (Track original request on first task turn)
3. **Update `build_supervisor_input()`** (Use original request as fallback)
4. **Update cancellation logic** (Clear original request when task cancelled)
5. **Update compound cancel logic** (Reset original request for new task)

---

## Comparison Table

| Approach | Complexity | Context Quality | Backward Compat | Debugging | Recommended |
|----------|-----------|----------------|-----------------|-----------|-------------|
| **1. original_user_request** | Low | High | ✅ Yes | Good | **⭐ YES** |
| **2. Enhanced execution_summary** | Medium | Medium | ⚠️ Changes LLM output | Limited | Maybe |
| **3. TaskContext object** | High | Very High | ✅ Yes | Excellent | For v2.0 |

---

## Example Flow with Solution

### With `original_user_request` field:

**Turn 1:**
```python
User: "forward email from john@example.com to jane@example.com"

# State after Turn 1:
conversation_state.original_user_request = "forward email from john@example.com to jane@example.com"
conversation_state.task_initiated_at = "2025-11-12T10:30:00"
conversation_state.conversation_turn_count = 1
conversation_state.extracted_info = {"task_type": "forward_email", "query": "john@example.com", "to": "jane@example.com"}
conversation_state.missing_fields = ["message_id"]
conversation_state.execution_summary = None  # Not ready yet

# Supervisor receives:
build_supervisor_input() → "forward email from john@example.com to jane@example.com [Clarifying: query=john@example.com, to=jane@example.com]"
```

**Turn 2:**
```python
User: "the one about the project update"

# State after Turn 2:
conversation_state.original_user_request = "forward email from john@example.com to jane@example.com"  # Preserved!
conversation_state.conversation_turn_count = 2
conversation_state.extracted_info = {"task_type": "forward_email", "query": "john@example.com project update", "to": "jane@example.com"}
conversation_state.missing_fields = ["message_id"]

# Supervisor receives:
build_supervisor_input() → "forward email from john@example.com to jane@example.com [Clarifying: query=john@example.com project update, to=jane@example.com]"
```

**Turn 3:**
```python
User: "yes proceed"

# State after Turn 3:
conversation_state.original_user_request = "forward email from john@example.com to jane@example.com"
conversation_state.conversation_turn_count = 3
conversation_state.extracted_info = {"task_type": "forward_email", "query": "john@example.com project update", "to": "jane@example.com", "message_id": "msg_12345"}
conversation_state.missing_fields = []
conversation_state.execution_summary = "Forward email from john@example.com about project update to jane@example.com"  # ✅ Finally set!

# Supervisor receives:
build_supervisor_input() → "Forward email from john@example.com about project update to jane@example.com"  # Uses execution_summary
```

---

## Migration Plan

### Phase 1: Add Fields (Non-Breaking)
```python
# In ConversationState
original_user_request: Optional[str] = None
task_initiated_at: Optional[str] = None
conversation_turn_count: int = 0
```

### Phase 2: Update Logic
- ✅ `process_message()` - Track original request
- ✅ `build_supervisor_input()` - Use original request
- ✅ Cancellation handlers - Clear original request

### Phase 3: Test Scenarios
- ✅ Single-turn task (no clarifications)
- ✅ Multi-turn task (2-3 clarifications)
- ✅ Cancel mid-clarification
- ✅ Compound cancel + new task
- ✅ Multiple sequential tasks

### Phase 4: Monitor & Iterate
- Check supervisor planning accuracy
- Compare `original_user_request` vs `execution_summary` usage
- Collect metrics on multi-turn success rate

---

## Additional Benefits

### 1. Better Error Messages
```python
# Before:
"Failed to execute: forward_email with query: john@example.com, to: jane@example.com"

# After:
"Failed to execute: forward email from john@example.com to jane@example.com
Original request (3 turns ago): 'forward email from john@example.com to jane@example.com'
Clarifications provided: query refined, recipient confirmed"
```

### 2. Conversation Analytics
```python
# Track multi-turn patterns
{
    "original_request": "forward email from john to jane",
    "turns_required": 3,
    "missing_fields_resolved": ["message_id", "subject"],
    "time_to_resolution": "45 seconds"
}
```

### 3. Better Resumption After Interruption
```python
User: "actually wait, let me check something first"
[5 minutes later]
User: "ok proceed with that email"

# System knows:
conversation_state.original_user_request = "forward email from john@example.com to jane@example.com"
# Can resume context correctly
```

---

## Code Example: Complete Implementation

```python
# models.py
class ConversationState(BaseModel):
    """Tracks conversation history and extracted information"""
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    extracted_info: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    intent: Optional[ConversationIntent] = None
    clarification_question: Optional[str] = None
    ready_for_execution: bool = False
    execution_summary: Optional[str] = None
    
    # ✅ NEW: Original request tracking
    original_user_request: Optional[str] = None
    task_initiated_at: Optional[str] = None
    conversation_turn_count: int = 0
    
    # Execution metadata
    execution_history: List[Dict[str, Any]] = Field(default_factory=list)
    executed_count: int = 0
    last_plan_hash: Optional[str] = None
    last_executed_at: Optional[str] = None
    executing: bool = False
    memory_state: Optional[Dict[str, Any]] = None


# conversational_agent.py
def process_message(self, user_message: str, conversation_state: ConversationState, ...):
    memory_manager.add_message("user", user_message)
    
    analysis = self.analyze_request(user_message, conversation_state, state_id)
    
    # ✅ Track original request on first task turn
    is_task_related = analysis.intent not in [
        ConversationIntent.SMALL_TALK, 
        ConversationIntent.CANCELLED
    ]
    
    if is_task_related:
        if not conversation_state.original_user_request:
            # First turn of a new task
            conversation_state.original_user_request = user_message
            conversation_state.task_initiated_at = datetime.now().isoformat()
            conversation_state.conversation_turn_count = 1
            print(f"📝 New task started: {user_message}")
        else:
            # Subsequent turn of ongoing task
            conversation_state.conversation_turn_count += 1
            print(f"🔄 Task turn {conversation_state.conversation_turn_count}: {user_message}")
    
    # Handle cancellation - clear original request
    if analysis.intent == ConversationIntent.CANCELLED:
        print(f"❌ Task cancelled after {conversation_state.conversation_turn_count} turns")
        conversation_state.original_user_request = None
        conversation_state.task_initiated_at = None
        conversation_state.conversation_turn_count = 0
        conversation_state.extracted_info = {}
        conversation_state.missing_fields = []
        # ... rest of cancellation logic ...
    
    # Handle compound cancel - reset for new task
    if is_compound_cancel:
        print(f"🔄 Compound cancel: resetting task tracking")
        conversation_state.original_user_request = None  # Will be set to new task in next iteration
        conversation_state.task_initiated_at = None
        conversation_state.conversation_turn_count = 0
        conversation_state.extracted_info = {}
    
    # ... rest of process_message logic ...


def build_supervisor_input(self, conversation_state: ConversationState) -> str:
    """
    Build supervisor input with proper context from multi-turn conversations.
    
    Priority:
    1. execution_summary (when ready to execute)
    2. original_user_request (for multi-turn clarifications)
    3. Reconstructed from extracted_info (fallback)
    """
    # Priority 1: Use execution_summary (most reliable)
    if conversation_state.execution_summary:
        return conversation_state.execution_summary
    
    # Priority 2: Use original request with clarification context
    if conversation_state.original_user_request:
        base_request = conversation_state.original_user_request
        
        # Add clarification context if we have extracted info
        if conversation_state.extracted_info:
            context_parts = []
            for key, value in conversation_state.extracted_info.items():
                if key != "task_type" and value:
                    context_parts.append(f"{key}={value}")
            
            if context_parts:
                clarification_context = ", ".join(context_parts)
                return f"{base_request} [Context: {clarification_context}]"
        
        return base_request
    
    # Priority 3: Fallback reconstruction
    info = conversation_state.extracted_info
    task_type = info.get("task_type", "task")
    parts = [f"{k}: {v}" for k, v in info.items() if k != "task_type"]
    return f"{task_type} with " + ", ".join(parts) if parts else task_type
```

---

## Summary

**Problem:** Multi-turn conversations lose the original user intent, causing supervisor planning to fail.

**Solution:** Add `original_user_request` field to `ConversationState` to preserve the user's exact words from the first turn.

**Impact:**
- ✅ Supervisor gets meaningful context even during clarifications
- ✅ Better error messages and debugging
- ✅ Improved conversation analytics
- ✅ Minimal code changes (3 new fields + 3 function updates)

**Next Step:** Implement Approach 1 with the code examples provided above.
