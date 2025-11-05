# Conversational Agent - Complete Flow with Example Run

## 🎯 Example Scenario

**User wants to send an email but provides incomplete information across 3 turns**

---

## 📊 Complete Flow Visualization

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                  TURN 1                                         │
│                         User: "Send an email"                                   │
└─────────────────────────────────────────────────────────────────────────────────┘

STEP 1: process_message() - ENTRY POINT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📥 INPUT:
    user_message: "Send an email"
    conversation_state: None
    state_id: "default"

📝 ACTION:
    if conversation_state is None:
        conversation_state = ConversationState()
        # Creates empty state with defaults

📤 NEW STATE CREATED:
    ConversationState(
        conversation_history: [],
        extracted_info: {},
        missing_fields: [],
        intent: None,
        clarification_question: None,
        ready_for_execution: False,
        execution_summary: None,
        execution_history: [],
        executed_count: 0,
        memory_state: None
    )

───────────────────────────────────────────────────────────────────────────────────

STEP 2: _get_memory_manager()
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📥 INPUT:
    conversation_state: ConversationState(...)
    state_id: "default"

📝 ACTION:
    if "default" not in self.memory_managers:
        # Create new memory manager
        memory_manager = ConversationMemoryManager(
            openai_api_key=self.openai_api_key,
            model="gpt-4o",
            temperature=0.3,
            max_tokens_before_summary=2000
        )
        self.memory_managers["default"] = memory_manager

📤 RETURN:
    ConversationMemoryManager(
        memory: ConversationMemory(
            raw_history: [],
            working_context: [],
            entity_memory: {},
            summary: None,
            current_token_count: 0,
            MAX_TOKENS_BEFORE_SUMMARY: 2000
        )
    )

───────────────────────────────────────────────────────────────────────────────────

STEP 3: memory_manager.add_message()
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📥 INPUT:
    role: "user"
    content: "Send an email"

📝 ACTION:
    message = {"role": "user", "content": "Send an email"}
    
    # Add to raw_history
    self.memory.raw_history.append(message)
    
    # Add to working_context
    self.memory.working_context.append(message)
    
    # Count tokens
    message_tokens = _count_tokens("user") + _count_tokens("Send an email") + 4
    message_tokens = 1 + 3 + 4 = 8 tokens
    
    # Update count
    self.memory.current_token_count += 8
    
    # Check threshold
    if 8 > 2000:  # False
        # No summarization needed

📤 UPDATED MEMORY STATE:
    ConversationMemory(
        raw_history: [
            {"role": "user", "content": "Send an email"}
        ],
        working_context: [
            {"role": "user", "content": "Send an email"}
        ],
        entity_memory: {},
        summary: None,
        current_token_count: 8,
        MAX_TOKENS_BEFORE_SUMMARY: 2000
    )

🖥️  CONSOLE OUTPUT:
    📝 Added message: user (8 tokens)
    📊 Current context: 8 / 2000 tokens

───────────────────────────────────────────────────────────────────────────────────

STEP 4: analyze_request()
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📥 INPUT:
    user_message: "Send an email"
    conversation_state: ConversationState(...)
    state_id: "default"

───────────────────────────────────────────────────────────────────────────────────

    STAGE 1: _quick_intent_check()
    ─────────────────────────────────────────────────────────────────────────────

    📥 INPUT:
        user_message: "Send an email"
        conversation_state: ConversationState(...)
        state_id: "default"

    📝 ACTION:
        # Get recent messages
        memory_manager = _get_memory_manager(state, "default")
        recent_messages = memory_manager.get_recent_messages(n=3)
        # Returns: [{"role": "user", "content": "Send an email"}]
        
        # Build minimal history
        history_snippet = "Recent context:\n  user: Send an email\n"
        
        # Build LLM prompt (lightweight, ~200 tokens)
        prompt = """
        You are a fast intent classifier...
        Recent context:
          user: Send an email
        
        Current user message: "Send an email"
        
        Reply with JSON:
        {
            "category": "confirmation" | "cancellation" | "casual_conversation" | 
                       "unintelligible" | "followup_answer" | "task_request",
            "confidence": "high" | "medium" | "low",
            "reasoning": "Brief explanation"
        }
        """
        
        # Call LLM (fast)
        llm_response = self.llm.invoke([{"role": "user", "content": prompt}])
        
    📤 LLM RESPONSE:
        {
            "category": "task_request",
            "confidence": "high",
            "reasoning": "User wants to perform an action (send email)"
        }
    
    📤 RETURN:
        None  # task_request means proceed to full analysis

    🖥️  CONSOLE OUTPUT:
        🔍 Quick check: TASK_REQUEST - proceeding to full analysis

───────────────────────────────────────────────────────────────────────────────────

    STAGE 1.5: _quick_help_check()
    ─────────────────────────────────────────────────────────────────────────────

    📥 INPUT:
        user_message: "Send an email"
        conversation_state: ConversationState(...)

    📝 ACTION:
        help_keywords = ["help", "how", "guide", "tutorial", ...]
        user_lower = "send an email"
        
        # Check if help request
        if not any(keyword in user_lower for keyword in help_keywords):
            return None

    📤 RETURN:
        None  # Not a help request

───────────────────────────────────────────────────────────────────────────────────

    STAGE 1.6: _quick_status_check()
    ─────────────────────────────────────────────────────────────────────────────

    📥 INPUT:
        user_message: "Send an email"
        conversation_state: ConversationState(executed_count=0)

    📝 ACTION:
        status_keywords = ["status", "done", "finished", ...]
        user_lower = "send an email"
        
        if not any(keyword in user_lower for keyword in status_keywords):
            return None

    📤 RETURN:
        None  # Not a status check

───────────────────────────────────────────────────────────────────────────────────

    STAGE 1.7: _quick_modification_check()
    ─────────────────────────────────────────────────────────────────────────────

    📥 INPUT:
        user_message: "Send an email"
        conversation_state: ConversationState(extracted_info={})

    📝 ACTION:
        modification_keywords = ["change", "update", "modify", ...]
        user_lower = "send an email"
        
        if not any(keyword in user_lower for keyword in modification_keywords):
            return None

    📤 RETURN:
        None  # Not a modification

───────────────────────────────────────────────────────────────────────────────────

    STAGE 1.8: _quick_followup_answer_extraction()
    ─────────────────────────────────────────────────────────────────────────────

    📥 INPUT:
        user_message: "Send an email"
        conversation_state: ConversationState(intent=None)

    📝 ACTION:
        if conversation_state.intent != ConversationIntent.NEEDS_CLARIFICATION:
            return None

    📤 RETURN:
        None  # Not in clarification state

───────────────────────────────────────────────────────────────────────────────────

    STAGE 2: FULL TASK ANALYSIS
    ─────────────────────────────────────────────────────────────────────────────

    🖥️  CONSOLE OUTPUT:
        🔍 Performing full task analysis with capabilities...

    📝 ACTION:
        # Get context from memory manager
        memory_manager = _get_memory_manager(state, "default")
        history_text = memory_manager.get_context_for_llm()
        
    📤 MEMORY CONTEXT:
        "RECENT CONVERSATION:\nUSER: Send an email\n"
        # No summary yet (first turn)
        # No entities yet

    📝 ACTION:
        # Add execution context (if any)
        exec_context = ""  # executed_count = 0
        
        # Classify query type
        query_type = classify_query_type("Send an email")
        
    📤 QUERY CLASSIFICATION:
        "specific"  # Task-specific, not general question

    🖥️  CONSOLE OUTPUT:
        🔍 Query classified as SPECIFIC - filtered to agents: ['gmail_agent']

    📝 ACTION:
        # Get relevant agents
        relevant_agents = identify_relevant_agents("Send an email")
        # Returns: ["gmail_agent"]
        
        # Build filtered capabilities
        capabilities_to_show = _build_capabilities_summary(["gmail_agent"])
        
    📤 CAPABILITIES (filtered):
        """
        **GMAIL_AGENT:**
          • send_email: Sends an email
            Required: to, subject, body
          • search_emails: Search inbox
            Required: query
          • reply_to_email: Reply to an email
            Required: message_id, body
        """
        # ~500 tokens (vs 2000 for all agents)

    📝 ACTION:
        # Build system prompt with capabilities
        system_prompt = f"""
        You are a conversational AI assistant that validates and clarifies 
        user requests before executing them.

        AVAILABLE CAPABILITIES:
        {capabilities_to_show}

        YOUR ROLE:
        1. Understand what the user wants to do
        2. Check if we have the tools to do it
        3. Extract all necessary information
        4. Identify required fields from tool definitions
        5. Ask clarification questions if info missing
        ...

        Return JSON:
        {{
            "intent": "needs_clarification | not_feasible | ready_to_execute | ...",
            "task_type": "send_email | ...",
            "extracted_info": {{}},
            "missing_fields": ["to", "subject", "body"],
            "clarification_question": "Who would you like to send this email to?",
            "reasoning": "...",
            "execution_ready": false,
            "execution_summary": "..."
        }}
        """
        
        user_prompt = f"""
        RECENT CONVERSATION:
        USER: Send an email

        CURRENT USER MESSAGE: Send an email

        Analyze this request and determine if we have enough information.
        """
        
        # Call LLM (comprehensive analysis, ~700 tokens input, ~200 tokens output)
        llm_response = self.llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ])
        
    📤 LLM RESPONSE:
        {
            "intent": "needs_clarification",
            "task_type": "send_email",
            "extracted_info": {},
            "missing_fields": ["to", "subject", "body"],
            "clarification_question": "Who would you like to send this email to?",
            "reasoning": "User wants to send an email but hasn't provided recipient, subject, or body",
            "suggested_alternatives": null,
            "execution_ready": false,
            "execution_summary": null
        }
    
    📝 ACTION:
        # Parse JSON response
        analysis_dict = json.loads(response_text)
        analysis = ConversationAnalysis(**analysis_dict)

📤 analyze_request() RETURN:
    ConversationAnalysis(
        intent: NEEDS_CLARIFICATION,
        task_type: "send_email",
        extracted_info: {},
        missing_fields: ["to", "subject", "body"],
        clarification_question: "Who would you like to send this email to?",
        reasoning: "User wants to send an email but hasn't provided recipient, subject, or body",
        suggested_alternatives: None,
        execution_ready: False,
        execution_summary: None
    )

───────────────────────────────────────────────────────────────────────────────────

STEP 5: Update ConversationState
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📥 INPUT:
    analysis: ConversationAnalysis(...)
    conversation_state: ConversationState(...)

📝 ACTION:
    conversation_state.intent = analysis.intent
    # NEEDS_CLARIFICATION
    
    conversation_state.extracted_info = analysis.extracted_info
    # {}
    
    conversation_state.missing_fields = analysis.missing_fields
    # ["to", "subject", "body"]
    
    conversation_state.clarification_question = analysis.clarification_question
    # "Who would you like to send this email to?"
    
    conversation_state.ready_for_execution = analysis.execution_ready
    # False
    
    conversation_state.execution_summary = analysis.execution_summary
    # None

📤 UPDATED STATE:
    ConversationState(
        conversation_history: [],  # Will be updated from memory
        extracted_info: {},
        missing_fields: ["to", "subject", "body"],
        intent: NEEDS_CLARIFICATION,
        clarification_question: "Who would you like to send this email to?",
        ready_for_execution: False,
        execution_summary: None,
        execution_history: [],
        executed_count: 0,
        memory_state: None  # Will be saved
    )

───────────────────────────────────────────────────────────────────────────────────

STEP 6: Generate Response
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📝 ACTION:
    if analysis.intent == ConversationIntent.NEEDS_CLARIFICATION:
        response = f"📋 {analysis.clarification_question}\n\n"
        
        if analysis.extracted_info:
            response += "**So far I have:**\n"
            for key, value in analysis.extracted_info.items():
                response += f"- {key}: {value}\n"

📤 RESPONSE GENERATED:
    "📋 Who would you like to send this email to?"
    # (No extracted_info yet, so no "So far I have" section)

───────────────────────────────────────────────────────────────────────────────────

STEP 7: memory_manager.add_message() - Assistant Response
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📥 INPUT:
    role: "assistant"
    content: "📋 Who would you like to send this email to?"

📝 ACTION:
    message = {"role": "assistant", "content": "📋 Who would you like to send this email to?"}
    self.memory.raw_history.append(message)
    self.memory.working_context.append(message)
    
    message_tokens = 1 + 12 + 4 = 17 tokens
    self.memory.current_token_count += 17
    # Total: 8 + 17 = 25 tokens

📤 UPDATED MEMORY STATE:
    ConversationMemory(
        raw_history: [
            {"role": "user", "content": "Send an email"},
            {"role": "assistant", "content": "📋 Who would you like to send this email to?"}
        ],
        working_context: [
            {"role": "user", "content": "Send an email"},
            {"role": "assistant", "content": "📋 Who would you like to send this email to?"}
        ],
        entity_memory: {},
        summary: None,
        current_token_count: 25,
        MAX_TOKENS_BEFORE_SUMMARY: 2000
    )

🖥️  CONSOLE OUTPUT:
    📝 Added message: assistant (17 tokens)
    📊 Current context: 25 / 2000 tokens

───────────────────────────────────────────────────────────────────────────────────

STEP 8: _save_memory_to_state()
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📥 INPUT:
    conversation_state: ConversationState(...)
    state_id: "default"

📝 ACTION:
    exported = memory_manager.export_memory()
    conversation_state.memory_state = exported
    conversation_state.conversation_history = memory_manager.get_full_history()

📤 SAVED TO STATE:
    conversation_state.memory_state = {
        "raw_history": [
            {"role": "user", "content": "Send an email"},
            {"role": "assistant", "content": "📋 Who would you like to send this email to?"}
        ],
        "working_context": [
            {"role": "user", "content": "Send an email"},
            {"role": "assistant", "content": "📋 Who would you like to send this email to?"}
        ],
        "entity_memory": {},
        "summary": None,
        "current_token_count": 25,
        "MAX_TOKENS_BEFORE_SUMMARY": 2000
    }
    
    conversation_state.conversation_history = [
        {"role": "user", "content": "Send an email"},
        {"role": "assistant", "content": "📋 Who would you like to send this email to?"}
    ]

───────────────────────────────────────────────────────────────────────────────────

STEP 9: process_message() - RETURN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📤 RETURN:
    (
        "📋 Who would you like to send this email to?",
        ConversationState(
            conversation_history: [
                {"role": "user", "content": "Send an email"},
                {"role": "assistant", "content": "📋 Who would you like to send this email to?"}
            ],
            extracted_info: {},
            missing_fields: ["to", "subject", "body"],
            intent: NEEDS_CLARIFICATION,
            clarification_question: "Who would you like to send this email to?",
            ready_for_execution: False,
            execution_summary: None,
            execution_history: [],
            executed_count: 0,
            memory_state: {...}
        )
    )

🖥️  USER SEES:
    Bot: "📋 Who would you like to send this email to?"


┌─────────────────────────────────────────────────────────────────────────────────┐
│                                  TURN 2                                         │
│                    User: "john@example.com"                                     │
└─────────────────────────────────────────────────────────────────────────────────┘

STEP 1: process_message() - ENTRY POINT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📥 INPUT:
    user_message: "john@example.com"
    conversation_state: ConversationState(...)  # From Turn 1
    state_id: "default"

📝 ACTION:
    # State already exists, use it
    # conversation_state is NOT None

───────────────────────────────────────────────────────────────────────────────────

STEP 2: _get_memory_manager()
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📥 INPUT:
    conversation_state: ConversationState(memory_state={...})
    state_id: "default"

📝 ACTION:
    if "default" in self.memory_managers:
        # Already exists from Turn 1
        return self.memory_managers["default"]

📤 RETURN:
    ConversationMemoryManager(
        memory: ConversationMemory(
            raw_history: [2 messages],
            working_context: [2 messages],
            entity_memory: {},
            summary: None,
            current_token_count: 25,
            MAX_TOKENS_BEFORE_SUMMARY: 2000
        )
    )

───────────────────────────────────────────────────────────────────────────────────

STEP 3: memory_manager.add_message()
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📥 INPUT:
    role: "user"
    content: "john@example.com"

📝 ACTION:
    message = {"role": "user", "content": "john@example.com"}
    self.memory.raw_history.append(message)
    self.memory.working_context.append(message)
    
    message_tokens = 1 + 5 + 4 = 10 tokens
    self.memory.current_token_count += 10
    # Total: 25 + 10 = 35 tokens

📤 UPDATED MEMORY STATE:
    ConversationMemory(
        raw_history: [
            {"role": "user", "content": "Send an email"},
            {"role": "assistant", "content": "📋 Who would you like to send this email to?"},
            {"role": "user", "content": "john@example.com"}
        ],
        working_context: [same as raw_history],
        entity_memory: {},
        summary: None,
        current_token_count: 35,
        MAX_TOKENS_BEFORE_SUMMARY: 2000
    )

🖥️  CONSOLE OUTPUT:
    📝 Added message: user (10 tokens)
    📊 Current context: 35 / 2000 tokens

───────────────────────────────────────────────────────────────────────────────────

STEP 4: analyze_request() - STAGE 1: _quick_intent_check()
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📥 INPUT:
    user_message: "john@example.com"
    conversation_state: ConversationState(intent=NEEDS_CLARIFICATION)
    state_id: "default"

📝 ACTION:
    recent_messages = memory_manager.get_recent_messages(n=3)
    # Returns: [
    #     {"role": "user", "content": "Send an email"},
    #     {"role": "assistant", "content": "📋 Who would you like to send this email to?"},
    #     {"role": "user", "content": "john@example.com"}
    # ]
    
    history_snippet = """
    Recent context:
      user: Send an email
      assistant: 📋 Who would you like to send this email to?
      user: john@example.com
    """
    
    # Check context
    is_awaiting_clarification = (
        conversation_state.intent == ConversationIntent.NEEDS_CLARIFICATION and
        conversation_state.clarification_question is not None
    )
    # True
    
    context_note = "⚠️ CONTEXT: Bot asked: 'Who would you like to send this email to?'"
    
    # Build prompt
    prompt = f"""
    ...
    {history_snippet}
    {context_note}
    
    Current user message: "john@example.com"
    
    Reply with JSON...
    """
    
    # Call LLM
    llm_response = self.llm.invoke([{"role": "user", "content": prompt}])

📤 LLM RESPONSE:
    {
        "category": "followup_answer",
        "confidence": "high",
        "reasoning": "Direct answer to clarification question"
    }

📤 RETURN:
    None  # followup_answer means proceed to Stage 1.8

🖥️  CONSOLE OUTPUT:
    🔍 Quick check: FOLLOWUP_ANSWER - proceeding to full analysis for extraction

───────────────────────────────────────────────────────────────────────────────────

STEP 5: analyze_request() - STAGE 1.8: _quick_followup_answer_extraction()
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📥 INPUT:
    user_message: "john@example.com"
    conversation_state: ConversationState(
        intent: NEEDS_CLARIFICATION,
        missing_fields: ["to", "subject", "body"],
        clarification_question: "Who would you like to send this email to?"
    )

📝 ACTION:
    # Check if in clarification state
    if conversation_state.intent == ConversationIntent.NEEDS_CLARIFICATION:
        # Yes!
        
        missing_field = conversation_state.missing_fields[0]
        # "to"
        
        # Build extraction prompt
        prompt = f"""
        Previous question asked: "Who would you like to send this email to?"
        Missing field needed: "to"
        User replied: "john@example.com"
        
        Task: Extract the value for the missing field.
        
        Reply with JSON:
        {{
            "is_simple_answer": true/false,
            "extracted_value": "..." or null,
            "needs_full_analysis": true/false,
            "reasoning": "..."
        }}
        """
        
        # Call LLM
        llm_response = self.llm.invoke([{"role": "user", "content": prompt}])

📤 LLM RESPONSE:
    {
        "is_simple_answer": true,
        "extracted_value": "john@example.com",
        "needs_full_analysis": false,
        "reasoning": "Direct email address answer"
    }

📝 ACTION:
    # Update extracted_info
    updated_info = conversation_state.extracted_info.copy()
    # Currently: {}
    
    updated_info["to"] = "john@example.com"
    # Now: {"to": "john@example.com"}
    
    # Remove "to" from missing_fields
    remaining_missing = ["subject", "body"]
    
    # Still have missing fields, ask for next one
    next_field = "subject"
    
    return ConversationAnalysis(
        intent=NEEDS_CLARIFICATION,
        task_type="send_email",
        extracted_info={"to": "john@example.com"},
        missing_fields=["subject", "body"],
        clarification_question="Great! What should the subject line be?",
        reasoning="Extracted to, still need subject",
        execution_ready=False,
        execution_summary=None
    )

📤 analyze_request() RETURN:
    ConversationAnalysis(
        intent: NEEDS_CLARIFICATION,
        task_type: "send_email",
        extracted_info: {"to": "john@example.com"},
        missing_fields: ["subject", "body"],
        clarification_question: "Great! What should the subject line be?",
        reasoning: "Extracted to, still need subject",
        suggested_alternatives: None,
        execution_ready: False,
        execution_summary: None
    )

🖥️  CONSOLE OUTPUT:
    🔍 Quick followup extraction: to = john@example.com

───────────────────────────────────────────────────────────────────────────────────

STEP 6: Update ConversationState
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📝 ACTION:
    conversation_state.intent = NEEDS_CLARIFICATION
    conversation_state.extracted_info = {"to": "john@example.com"}
    conversation_state.missing_fields = ["subject", "body"]
    conversation_state.clarification_question = "Great! What should the subject line be?"
    conversation_state.ready_for_execution = False
    conversation_state.execution_summary = None

📤 UPDATED STATE:
    ConversationState(
        extracted_info: {"to": "john@example.com"},
        missing_fields: ["subject", "body"],
        intent: NEEDS_CLARIFICATION,
        clarification_question: "Great! What should the subject line be?",
        ready_for_execution: False,
        ...
    )

───────────────────────────────────────────────────────────────────────────────────

STEP 7: Generate Response
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📝 ACTION:
    if analysis.intent == ConversationIntent.NEEDS_CLARIFICATION:
        response = "📋 Great! What should the subject line be?\n\n"
        
        if analysis.extracted_info:
            response += "**So far I have:**\n"
            response += "- to: john@example.com\n"

📤 RESPONSE GENERATED:
    """
    📋 Great! What should the subject line be?
    
    **So far I have:**
    - to: john@example.com
    """

───────────────────────────────────────────────────────────────────────────────────

STEP 8: memory_manager.add_message() - Assistant Response
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📥 INPUT:
    role: "assistant"
    content: "📋 Great! What should the subject line be?\n\n**So far I have:**\n- to: john@example.com"

📝 ACTION:
    message_tokens = 1 + 25 + 4 = 30 tokens
    self.memory.current_token_count += 30
    # Total: 35 + 30 = 65 tokens

📤 UPDATED MEMORY STATE:
    ConversationMemory(
        raw_history: [4 messages],
        working_context: [4 messages],
        entity_memory: {},
        summary: None,
        current_token_count: 65,
        MAX_TOKENS_BEFORE_SUMMARY: 2000
    )

🖥️  CONSOLE OUTPUT:
    📝 Added message: assistant (30 tokens)
    📊 Current context: 65 / 2000 tokens

───────────────────────────────────────────────────────────────────────────────────

STEP 9: process_message() - RETURN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📤 RETURN:
    (
        "📋 Great! What should the subject line be?\n\n**So far I have:**\n- to: john@example.com",
        ConversationState(
            extracted_info: {"to": "john@example.com"},
            missing_fields: ["subject", "body"],
            intent: NEEDS_CLARIFICATION,
            ready_for_execution: False,
            ...
        )
    )

🖥️  USER SEES:
    Bot: "📋 Great! What should the subject line be?
    
    **So far I have:**
    - to: john@example.com"


┌─────────────────────────────────────────────────────────────────────────────────┐
│                                  TURN 3                                         │
│          User: "Meeting Notes - body: See you at 3pm tomorrow"                 │
└─────────────────────────────────────────────────────────────────────────────────┘

STEP 1-3: [Similar to Turn 2 - add message to memory]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📤 MEMORY STATE AFTER add_message():
    current_token_count: 105 tokens (65 + 40)

───────────────────────────────────────────────────────────────────────────────────

STEP 4: analyze_request() - STAGE 2: FULL ANALYSIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📥 INPUT:
    user_message: "Meeting Notes - body: See you at 3pm tomorrow"
    conversation_state: ConversationState(
        extracted_info: {"to": "john@example.com"},
        missing_fields: ["subject", "body"]
    )

📝 ACTION:
    # Stage 1 returns None (task_request)
    # Stage 1.5-1.7 return None
    # Stage 1.8: Not in simple followup (provides both subject AND body)
    
    # Proceed to STAGE 2: Full Analysis
    
    history_text = memory_manager.get_context_for_llm()

📤 CONTEXT FROM MEMORY:
    """
    RECENT CONVERSATION:
    USER: Send an email
    ASSISTANT: 📋 Who would you like to send this email to?
    USER: john@example.com
    ASSISTANT: 📋 Great! What should the subject line be?

    **So far I have:**
    - to: john@example.com
    USER: Meeting Notes - body: See you at 3pm tomorrow
    """

📝 ACTION:
    # Query classification
    query_type = classify_query_type(user_message)
    # Returns: "specific"
    
    # Get relevant agents
    relevant_agents = ["gmail_agent"]
    
    # Build capabilities
    capabilities = _build_capabilities_summary(["gmail_agent"])
    
    # Build system + user prompts
    system_prompt = """
    You are a conversational AI assistant...
    
    AVAILABLE CAPABILITIES:
    **GMAIL_AGENT:**
      • send_email: Sends an email
        Required: to, subject, body
    ...
    """
    
    user_prompt = """
    RECENT CONVERSATION:
    USER: Send an email
    ...
    USER: Meeting Notes - body: See you at 3pm tomorrow
    
    CURRENT USER MESSAGE: Meeting Notes - body: See you at 3pm tomorrow
    
    Analyze this request...
    """
    
    # Call LLM
    llm_response = self.llm.invoke([system, user])

📤 LLM RESPONSE:
    {
        "intent": "ready_to_execute",
        "task_type": "send_email",
        "extracted_info": {
            "to": "john@example.com",
            "subject": "Meeting Notes",
            "body": "See you at 3pm tomorrow"
        },
        "missing_fields": [],
        "clarification_question": null,
        "reasoning": "All required fields collected: to, subject, body",
        "suggested_alternatives": null,
        "execution_ready": true,
        "execution_summary": "Send email to john@example.com with subject 'Meeting Notes'"
    }

📤 analyze_request() RETURN:
    ConversationAnalysis(
        intent: READY_TO_EXECUTE,
        task_type: "send_email",
        extracted_info: {
            "to": "john@example.com",
            "subject": "Meeting Notes",
            "body": "See you at 3pm tomorrow"
        },
        missing_fields: [],
        clarification_question: None,
        reasoning: "All required fields collected",
        execution_ready: True,
        execution_summary: "Send email to john@example.com with subject 'Meeting Notes'"
    )

───────────────────────────────────────────────────────────────────────────────────

STEP 5: Update ConversationState
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📝 ACTION:
    conversation_state.intent = READY_TO_EXECUTE
    conversation_state.extracted_info = {
        "to": "john@example.com",
        "subject": "Meeting Notes",
        "body": "See you at 3pm tomorrow"
    }
    conversation_state.missing_fields = []
    conversation_state.clarification_question = None
    conversation_state.ready_for_execution = True  ✅
    conversation_state.execution_summary = "Send email to john@example.com with subject 'Meeting Notes'"

───────────────────────────────────────────────────────────────────────────────────

STEP 6: Generate Response
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📝 ACTION:
    if analysis.intent == ConversationIntent.READY_TO_EXECUTE:
        response = "✅ **Ready to execute!**\n\n"
        response += "**Task:** Send email to john@example.com with subject 'Meeting Notes'\n\n"
        response += "**Details:**\n"
        response += "- to: john@example.com\n"
        response += "- subject: Meeting Notes\n"
        response += "- body: See you at 3pm tomorrow\n"

📤 RESPONSE GENERATED:
    """
    ✅ **Ready to execute!**
    
    **Task:** Send email to john@example.com with subject 'Meeting Notes'
    
    **Details:**
    - to: john@example.com
    - subject: Meeting Notes
    - body: See you at 3pm tomorrow
    """

───────────────────────────────────────────────────────────────────────────────────

STEP 7-9: Add response to memory, save state, return
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📤 FINAL RETURN:
    (
        "✅ **Ready to execute!**\n\n**Task:** ...",
        ConversationState(
            extracted_info: {
                "to": "john@example.com",
                "subject": "Meeting Notes",
                "body": "See you at 3pm tomorrow"
            },
            missing_fields: [],
            intent: READY_TO_EXECUTE,
            ready_for_execution: True,  ✅
            execution_summary: "Send email to john@example.com with subject 'Meeting Notes'",
            ...
        )
    )

🖥️  USER SEES:
    Bot: "✅ **Ready to execute!**
    
    **Task:** Send email to john@example.com with subject 'Meeting Notes'
    
    **Details:**
    - to: john@example.com
    - subject: Meeting Notes
    - body: See you at 3pm tomorrow"

───────────────────────────────────────────────────────────────────────────────────

STEP 10: Check if Ready to Execute
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📥 CALLER CODE:
    response, state = agent.process_message("Meeting Notes...", state)
    
    if agent.should_execute(state):  ✅ TRUE
        supervisor_input = agent.build_supervisor_input(state)
        # Execute workflow...

📝 should_execute():
    return conversation_state.ready_for_execution
    # Returns: True

📝 build_supervisor_input():
    return conversation_state.execution_summary
    # Returns: "Send email to john@example.com with subject 'Meeting Notes'"

📤 SUPERVISOR RECEIVES:
    "Send email to john@example.com with subject 'Meeting Notes'"
    
    # Supervisor generates plan:
    # 1. Call gmail_agent.send_email(to="john@example.com", subject="...", body="...")


═══════════════════════════════════════════════════════════════════════════════════
                               SUMMARY STATISTICS
═══════════════════════════════════════════════════════════════════════════════════

TURN 1:
  - Messages: 2 (user + assistant)
  - Tokens: 25
  - Intent: NEEDS_CLARIFICATION
  - Missing: ["to", "subject", "body"]
  - LLM Calls: 2 (quick_intent + full_analysis)
  - Cost: ~$0.005

TURN 2:
  - Messages: 4 (cumulative)
  - Tokens: 65
  - Intent: NEEDS_CLARIFICATION
  - Missing: ["subject", "body"]
  - LLM Calls: 2 (quick_intent + quick_followup_extraction)
  - Cost: ~$0.002 (quick path!)

TURN 3:
  - Messages: 6 (cumulative)
  - Tokens: 105
  - Intent: READY_TO_EXECUTE ✅
  - Missing: []
  - LLM Calls: 2 (quick_intent + full_analysis)
  - Cost: ~$0.005

TOTAL:
  - Turns: 3
  - Total Tokens: 105
  - Total LLM Calls: 6
  - Total Cost: ~$0.012
  - Result: Ready to execute! 🚀

═══════════════════════════════════════════════════════════════════════════════════
```

## 🎯 Key Takeaways

### **1. Memory Management**
- Every message stored in both `raw_history` (permanent) and `working_context` (recent)
- Token count tracked continuously
- Summarization triggers at 2000 tokens (not hit in this example)

### **2. Multi-Stage Pipeline**
- **Quick Checks (Stages 1-1.8):** Fast, lightweight analysis for common patterns
- **Full Analysis (Stage 2):** Comprehensive LLM analysis with capabilities

### **3. State Persistence**
- `memory_state` saved after every turn for database storage
- Enables conversation continuation across sessions

### **4. Optimization**
- Turn 2 used quick-path (200 tokens) instead of full analysis (2000 tokens)
- 90% token savings on followup answers!

### **5. Progressive Information Gathering**
- Turn 1: Ask for recipient
- Turn 2: Ask for subject (while showing "So far I have: to")
- Turn 3: Complete task (subject + body extracted together)

This visualization shows **exactly** what happens at each step, with real data structures! 🚀
