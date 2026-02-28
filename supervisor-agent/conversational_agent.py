"""
Conversational Agent - Pre-Supervisor Validation & Clarification Layer

This agent sits BEFORE the supervisor and handles:
1. Validating if user request has all necessary information
2. Asking clarification questions
3. Checking if task is feasible with available tools
4. Managing multi-turn conversations
5. Suggesting alternatives for complex tasks
"""

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from typing import Optional, List, Dict, Any
from enum import Enum
import json
import os
import re
import time
import httpx

# Import agent capabilities for feasibility checking
from agent_capabilities_v2 import agent_capabilities

# Import utility functions for agent filtering
from utils import identify_relevant_agents, get_filtered_capabilities

# Import LLM error handler for unified error handling
from llm_error_handler import handle_llm_error, LLMServiceException, is_llm_error

# Import conversation memory manager
from conversation_memory import ConversationMemoryManager

# Import thread manager for persistent storage
from thread_manager import ThreadManager

# Import logging module
from logging_config import (
    conversational_logger as logger,
    get_current_request_id,
    get_token_summary
)


class ConversationIntent(str, Enum):
    """Intent classification for conversation state"""
    NEEDS_CLARIFICATION = "needs_clarification"  # Missing info, ask user
    NOT_FEASIBLE = "not_feasible"  # Can't do with current tools
    TOO_COMPLEX = "too_complex"  # Task needs breaking down
    READY_TO_EXECUTE = "ready_to_execute"  # All info present, proceed
    SMALL_TALK = "small_talk"  # Not a task request
    CANCELLED = "cancelled"  # User cancelled the request but data preserved
    TEMPLATE_UPLOAD = "template_upload" 


class ConversationState(BaseModel):
    """Tracks conversation history and extracted information"""
    # Note: conversation_history removed - use memory_manager instead
    extracted_info: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    intent: Optional[ConversationIntent] = None
    clarification_question: Optional[str] = None
    ready_for_execution: bool = False
    execution_summary: Optional[str] = None  # Human-readable summary
    # Execution metadata (added to support supervisor execution history)
    execution_history: List[Dict[str, Any]] = Field(default_factory=list)
    executed_count: int = 0
    last_plan_hash: Optional[str] = None
    last_executed_at: Optional[str] = None
    executing: bool = False
    
    # NEW: Memory manager state (for persistence)
    memory_state: Optional[Dict[str, Any]] = None


class ConversationAnalysis(BaseModel):
    """LLM's analysis of the user request"""
    intent: ConversationIntent
    task_type: str  # e.g., "send_email", "search_emails", "manage_calendar"
    extracted_info: Dict[str, Any]
    missing_fields: List[str]
    clarification_question: Optional[str] = None
    reasoning: str
    suggested_alternatives: Optional[List[str]] = None
    execution_ready: bool
    execution_summary: Optional[str] = None


class ConversationalAgent:
    """
    Manages conversation flow before passing to supervisor.
    Uses LLM to understand intent and gather complete information.
    """
    
    def __init__(
        self, 
        openai_api_key: str, 
        model: str = "gpt-4o", 
        temperature: float = 0.2, 
        db_path: str = "threads.db",
        test_mode: bool = False,  # Enable to only test Unified LLM
        test_n_responses: int = 5  # Number of responses to generate in test mode
    ):
        self.llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            openai_api_key=openai_api_key
        )
        self.openai_api_key = openai_api_key
        self.model = model
        self.temperature = temperature
        self.test_mode = test_mode  # Store test mode flag
        self.test_n_responses = test_n_responses  # Store n parameter for testing
        
        # Build FULL capabilities summary once (for "what can you do?" questions)
        self.full_capabilities_summary = self._build_capabilities_summary()
        
        # Memory managers (one per conversation, keyed by conversation_id or state)
        self.memory_managers: Dict[str, ConversationMemoryManager] = {}
        
        # Thread manager for persistent storage with SQLite
        self.thread_manager = ThreadManager(db_path=db_path)
    
    def _build_capabilities_summary(self, agent_names: Optional[List[str]] = None) -> str:
        """
        Build comprehensive summary of available tools with their required arguments.
        NOW INCLUDES workflow documentation for multi-step operations.
    
        Args:
            agent_names: Optional list of agent names to include. If None, includes all agents.
    
        Returns:
            Formatted string with capabilities
        """
    # Use filtered agents if provided, otherwise use all
        agents_to_include = agent_capabilities if agent_names is None else get_filtered_capabilities(agent_names)
    
        capabilities = []
        for agent_name, agent_info in agents_to_include.items():
            capabilities.append(f"\n**{agent_name.upper()}:**")
        
            # Add tools
            tools = agent_info.get("tools", {})
            for tool_name, tool_info in tools.items():
            # Extract required and optional args
                args = tool_info.get("args", {})
                required_args = [k for k, v in args.items() if "(required)" in str(v)]
                optional_args = [k for k, v in args.items() if "(optional)" in str(v)]
            
            # Check for can_be_derived_from metadata
                derivation_info = tool_info.get("can_be_derived_from", {})
            
            # Build compact format with derivation hints
                arg_parts = []
                for req_arg in required_args:
                    if req_arg in derivation_info:
                    # Add derivation hint inline
                        deriv = derivation_info[req_arg]
                        source = deriv.get("source_tool", "")
                        criteria = ", ".join(deriv.get("search_criteria", []))
                        arg_parts.append(f'{req_arg} [via {source}: {criteria}]')
                    else:
                        arg_parts.append(req_arg)
            
            # Build final argument string
                arg_list = []
                if arg_parts:
                    arg_list.append(', '.join(arg_parts))
                if optional_args:
                    arg_list.append(f"[{', '.join(optional_args)}]")
            
                args_str = f"({', '.join(arg_list)})" if arg_list else "()"
            capabilities.append(f"  • {tool_name}{args_str}")
        
        # ✅ FIX: Add workflow documentation ONCE per agent (not per tool)
        if "template_with_data_workflow" in agent_info:
            workflow = agent_info["template_with_data_workflow"]
            capabilities.append(f"\n  📋 TEMPLATE+DATA WORKFLOW:")
            capabilities.append(f"     When to use: {workflow.get('when_to_use', '')}")
            
            if "workflow_steps" in workflow:
                capabilities.append(f"     Required steps:")
                for step_name, step_info in workflow["workflow_steps"].items():
                    step_agent = step_info.get("agent", "")
                    step_tool = step_info.get("tool", "")
                    step_purpose = step_info.get("purpose", "")
                    capabilities.append(f"       {step_name}. {step_agent}.{step_tool} - {step_purpose}")
            
            if "extraction_rules" in workflow:
                rules = workflow["extraction_rules"]
                capabilities.append(f"     Extract from user:")
                for field, rule in rules.items():
                    capabilities.append(f"       - {field}: {rule}")
    
        return "\n".join(capabilities)
    
    def _get_memory_manager(self, state_id: str = "default", memory_state: Optional[Dict[str, Any]] = None, ) -> ConversationMemoryManager:
        """
        Get or create a memory manager for the given conversation.
        
        Args:
            state_id: Unique identifier for this conversation (for multi-conversation support)
            memory_state: Optional persisted memory state to restore from
            
        Returns:
            ConversationMemoryManager instance
        """
        # Check if memory manager already exists
        if state_id not in self.memory_managers:
            # Create new memory manager
            self.memory_managers[state_id] = ConversationMemoryManager(
                openai_api_key=self.openai_api_key,
                model=self.model,
                temperature=self.temperature,
                max_tokens_before_summary=2000  # 2000 tokens before summarization
            )
            
            # Load from persisted state if available
            if memory_state:
                self.memory_managers[state_id].load_memory(memory_state)
                print(f"📥 Loaded memory from state: {len(memory_state.get('raw_history', []))} messages")
        
        return self.memory_managers[state_id]
    
    def _save_memory_to_state(self, conversation_state: ConversationState, state_id: str = "default") -> None:
        """
        Save memory manager state to conversation state for persistence.
        
        Args:
            conversation_state: Conversation state to update
            state_id: Unique identifier for this conversation
        """
        if state_id in self.memory_managers:
            conversation_state.memory_state = self.memory_managers[state_id].export_memory()
            # # Also update conversation_history for backward compatibility
            # conversation_state.conversation_history = self.memory_managers[state_id].get_full_history()

    # =============================================================================
    # TIER 0: PATTERN-BASED QUICK CHECKS (NO LLM - INSTANT RESPONSE)
    # =============================================================================
    
    def _quick_greeting_check(self, user_message: str) -> Optional[ConversationAnalysis]:
        """
        Instant response to greetings without LLM call.
        Pattern-based recognition for common greetings.
        
        Args:
            user_message: Current user input
            
        Returns:
            ConversationAnalysis with greeting response, or None if not a greeting
        """
        greetings = [
            "hello", "hi", "hey", "good morning", "good afternoon", 
            "good evening", "greetings", "howdy", "what's up", "sup", "yo"
        ]
        
        user_lower = user_message.lower().strip()
        
        # Check if it's JUST a greeting (no task request)
        # Must start with greeting and be short
        is_greeting = any(user_lower.startswith(g) for g in greetings) and len(user_message) < 30
        
        if is_greeting:
            # Make sure it's not "hi, send email to..." (greeting + task)
            task_indicators = ["send", "search", "create", "find", "schedule", "draft", "reply", "make", "write"]
            if not any(task in user_lower for task in task_indicators):
                print(f"⚡ Tier 0: Greeting detected - instant response (0 tokens)")
                
                greeting_response = """Hello! 👋 I'm here to help you with:

📧 **Emails** - Send, search, reply, draft
📄 **Documents** - Create and edit Google Docs
📅 **Calendar** - Schedule meetings (coming soon)

What would you like to do today?"""
                
                return ConversationAnalysis(
                    intent=ConversationIntent.SMALL_TALK,
                    task_type="greeting",
                    extracted_info={},
                    missing_fields=[],
                    clarification_question=greeting_response,
                    reasoning="Simple greeting - instant response",
                    execution_ready=False,
                    execution_summary=None
                )
        
        return None
    
    def _quick_repeat_check(self, user_message: str, conversation_state: ConversationState, state_id: str = "default") -> Optional[ConversationAnalysis]:
        """
        Detect requests to repeat last response.
        Uses memory manager to retrieve last assistant message.
        
        Args:
            user_message: Current user input
            conversation_state: Previous conversation context
            state_id: Conversation identifier for memory manager
            
        Returns:
            ConversationAnalysis with repeated message, or None if not a repeat request
        """
        repeat_keywords = [
            "repeat", "say that again", "what did you say", 
            "come again", "pardon", "didn't catch that", "what was that"
        ]
        
        user_lower = user_message.lower().strip()
        
        if any(keyword in user_lower for keyword in repeat_keywords):
            print(f"⚡ Tier 0: Repeat request - retrieving last response (0 tokens)")
            
            # Get memory manager to retrieve last assistant message
            memory_manager = self._get_memory_manager(state_id, conversation_state.memory_state)
            recent = memory_manager.get_recent_messages(n=5)
            
            last_assistant = None
            for msg in reversed(recent):
                if msg['role'] == 'assistant':
                    last_assistant = msg['content']
                    break
            
            if last_assistant:
                return ConversationAnalysis(
                    intent=ConversationIntent.SMALL_TALK,
                    task_type="repeat_request",
                    extracted_info={},
                    missing_fields=[],
                    clarification_question=f"Sure, here's what I said:\n\n{last_assistant}",
                    reasoning="User requested repeat of last message",
                    execution_ready=False,
                    execution_summary=None
                )
        
        return None
    
    def _quick_capability_list_check(self, user_message: str) -> Optional[ConversationAnalysis]:
        """
        Instant list of capabilities for specific questions.
        Uses cached capabilities summary built in __init__.
        
        Args:
            user_message: Current user input
            
        Returns:
            ConversationAnalysis with capabilities list, or None if not a capability question
        """
        capability_questions = [
            "what can you do", "what are you capable of", "capabilities",
            "what do you do", "what tasks", "features", "functions",
            "what can i ask", "what are your features"
        ]
        
        user_lower = user_message.lower().strip()
        
        if any(q in user_lower for q in capability_questions):
            print(f"⚡ Tier 0: Capabilities request - returning cached list (0 tokens)")
            
            # Use cached full_capabilities_summary (already built in __init__)
            capabilities_response = f"""Here's what I can help you with:

{self.full_capabilities_summary}

**To get started, try saying:**
- "Send an email to john@example.com"
- "Search my emails for invoices from last week"
- "Create a document about project planning"

What would you like to try?"""
            
            return ConversationAnalysis(
                intent=ConversationIntent.SMALL_TALK,
                task_type="capabilities_inquiry",
                extracted_info={},
                missing_fields=[],
                clarification_question=capabilities_response,
                reasoning="User asking about capabilities - used cached summary",
                execution_ready=False,
                execution_summary=None
            )
        
        return None
    
    def _quick_examples_check(self, user_message: str) -> Optional[ConversationAnalysis]:
        """
        Provide examples when requested.
        Pattern-based detection for example requests.
        
        Args:
            user_message: Current user input
            
        Returns:
            ConversationAnalysis with examples, or None if not an example request
        """
        example_keywords = ["example", "show me", "demonstrate", "sample", "give me an example"]
        
        user_lower = user_message.lower().strip()
        
        if any(keyword in user_lower for keyword in example_keywords):
            print(f"⚡ Tier 0: Examples request - returning samples (0 tokens)")
            
            examples = """Here are some examples of what you can ask me:

📧 **Email Examples:**
- "Send an email to john@example.com about the Q4 report"
- "Search my emails from alice@company.com from last week"
- "Draft an email to the team about project updates"
- "Reply to the last email from bob@example.com"

📄 **Document Examples:**
- "Create a Google doc titled Meeting Notes"
- "Add this text to my document: [your content]"
- "Edit my document with id abc123"

📅 **Calendar Examples (coming soon):**
- "Schedule a meeting with Sarah tomorrow at 3pm"
- "Check my availability for next week"

Try one of these or tell me what you'd like to do!"""
            
            return ConversationAnalysis(
                intent=ConversationIntent.SMALL_TALK,
                task_type="examples_request",
                extracted_info={},
                missing_fields=[],
                clarification_question=examples,
                reasoning="User requested examples",
                execution_ready=False,
                execution_summary=None
            )
        
        return None

    # =============================================================================
    # TIER 0.5: UNIFIED LIGHTWEIGHT LLM CHECK (~100-250 TOKENS)
    # =============================================================================
    
    def _unified_quick_check(self, user_message: str, conversation_state: ConversationState, state_id: str = "default", uploaded_file: Optional[Dict[str, Any]] = None ) -> Optional[ConversationAnalysis]:
        """
        UNIFIED Tier 0.5 LLM check - detects ALL non-task intents in ONE call.
        Handles: confirmation, cancellation, casual conversation, unintelligible input,
        followup answers, and simple modifications.
        
        Args:
            user_message: Current user input
            conversation_state: Previous conversation context
            state_id: Conversation identifier for memory manager
            
        Returns:
            ConversationAnalysis if handled by quick check, None if needs full analysis
        """
        
        # Get memory manager
        memory_manager = self._get_memory_manager(state_id, conversation_state.memory_state)
        
        # Build context for LLM
        history_snippet = ""
        last_bot_message = ""
        recent_messages = memory_manager.get_recent_messages(n=3)
        
        if recent_messages:
            history_snippet = "Recent context:\n"
            for turn in recent_messages:
                content_preview = turn['content']
                history_snippet += f"  {turn['role']}: {content_preview}\n"
            
            assistant_turns = [t for t in recent_messages if t['role'] == 'assistant']
            if assistant_turns:
                last_bot_message = assistant_turns[-1]['content']

        file_context = ""
        if uploaded_file:
            file_context = f"\n\n📎 USER UPLOADED FILE:\n"
            file_context += f"- Filename: {uploaded_file.get('filename', 'unknown')}\n"
            file_context += f"- Size: {uploaded_file.get('size', 0)} bytes\n"
            file_context += f"- Type: {uploaded_file.get('mime_type', 'unknown')}\n"
            file_context += f"- Temp path: {uploaded_file.get('temp_path', 'unknown')}\n"
            file_context += f"\n🔍 FILE CONTEXT: The user has uploaded a file. Any document/template name mentioned likely refers to what they want to CREATE, not the uploaded file itself.\n"
    
        
        # Build state context
        is_awaiting_confirmation = (
            conversation_state.ready_for_execution or 
            conversation_state.intent == ConversationIntent.READY_TO_EXECUTE or
            "ready to execute" in last_bot_message.lower() or
            "should i proceed" in last_bot_message.lower()
        )
        
        is_awaiting_clarification = (
            conversation_state.intent == ConversationIntent.NEEDS_CLARIFICATION and
            conversation_state.clarification_question is not None
        )
        
        has_extracted_info = bool(conversation_state.extracted_info)
        missing_field = conversation_state.missing_fields[0] if conversation_state.missing_fields else None
        
        # Display current state for debugging
        print(f"  → Current extracted_info: {json.dumps(conversation_state.extracted_info, indent=2)}")
        print(f"  → Current missing_fields: {conversation_state.missing_fields}")
        print(f"  → First missing_field: {missing_field}")
        
        # Build unified prompt
        context_note = ""
        if is_awaiting_confirmation:
            context_note = "\n⚠️ CONTEXT: Bot asked for confirmation to proceed."
        elif is_awaiting_clarification and missing_field:
            context_note = f"\n⚠️ CONTEXT: Bot asked about missing '{missing_field}': '{conversation_state.clarification_question}'"
        elif has_extracted_info:
            context_note = f"\n⚠️ CONTEXT: Current request data: {json.dumps(conversation_state.extracted_info)}"
        
        # Add extracted_info and missing_fields to context for LLM
        state_context = ""
        if has_extracted_info or conversation_state.missing_fields or conversation_state.execution_summary:
            state_context = f"\n\n📋 CURRENT STATE:\n"
            if has_extracted_info:
                state_context += f"- Extracted so far: {json.dumps(conversation_state.extracted_info)}\n"
            if conversation_state.missing_fields:
                state_context += f"- Still missing: {conversation_state.missing_fields}\n"
                if missing_field:
                    state_context += f"- Next to collect: {missing_field}\n"
            if conversation_state.execution_summary:
                state_context += f"- Current task description: {conversation_state.execution_summary}\n"
        
        # UNIFIED prompt that handles ALL Tier 0.5 categories
        unified_prompt = f"""Classify user intent and extract data. Return JSON only.

CATEGORIES (pick ONE):
1. confirmation - Approval to proceed ("yes", "ok", "proceed")
2. cancellation - Stop current task ("cancel", "no", "forget it")
3. modification - Change single field ("change X to Y")
4. followup_answer - Direct answer to question ("john@example.com")
5. casual_conversation - Chitchat ("how are you")
6. unintelligible - Unclear input   
7. template_upload - User uploaded file + wants document/save ("use this template", "create MOM", "save to drive")
8. task_request - Action request

QUERY SCOPE (for task_request only):
- general: User asking about capabilities/features ("what can you do?", "show me features")
- specific: User wants to perform a task ("send email", "search for invoices")

- Use exact field names from tool criteria and capabilities_to_show when extracting fields and naming them.

TEMPLATE_UPLOAD EXTRACTION RULES (category=template_upload only):
⚠️ CRITICAL NAMING LOGIC:
- The UPLOADED FILE is the template (source)
- Any document name mentioned is for the NEW document to CREATE
- Example: "Upload this template, document name will be Sigma" → document_title="Sigma", template_name=<from filename or explicit>
- Example: "Create Board Meeting from this" → document_title="Board Meeting", template_name=<from filename>
- If user says "name the template X" → template_name="X"
- If user says "document name is Y" or "create Y" → document_title="Y"
- DEFAULT: template_name = filename without extension if not specified

FIELDS TO EXTRACT:
- save_to_drive: Did user ask to save/upload template? (default: true if file uploaded)
- template_name: Explicit name for the template itself (e.g., "name the template X", "save as X_Template")
  → If NOT specified, use uploaded filename without extension
- document_title: Name for the NEW document to create (e.g., "create document Y", "document name is Y")
  → This is what the user wants to call the NEW document, NOT the template

{history_snippet}{context_note}{state_context}
User: "{user_message}"

OUTPUT (JSON only):
{{
    "category": "confirmation|cancellation|modification|followup_answer|casual_conversation|unintelligible|task_request",
    "confidence": "high|medium|low",
    "reasoning": "1 sentence",
    "query_scope": "general|specific",  // only for task_request, default "specific"
    "has_compound_cancel": false,  // only for cancellation with new task
    "extracted_value": null,       // only for followup_answer
    "field_to_modify": null,       // only for modification
    "new_value": null,             // only for modification
    "execution_summary": null      // only for followup_answer - human-readable task description
    "save_to_drive": false,      // only for template_upload
    "template_name": null,        // only for template_upload
    "document_title": null,       // only for template_upload
    "extracted_value": null,      // only for followup_answer
    "field_to_modify": null,      // only for modification
    "new_value": null,            // only for modification
    "execution_summary": null     // for followup_answer/template_upload
    "template_name": null,        // Name for template (or use filename if null)
    "document_title": null,       // Name for NEW document to create
}}

"""

        try:
            # === TOKEN TRACKING: Tier 0.5 Unified Check ===
            start_time = time.time()
            llm_response = self.llm.invoke(
                [{"role": "user", "content": unified_prompt}],
                config={"timeout": 30, "max_tokens": 1000}
            )
            duration_ms = (time.time() - start_time) * 1000
            
            # Extract token usage from response
            input_tokens = 0
            output_tokens = 0
            if hasattr(llm_response, 'response_metadata'):
                token_usage = llm_response.response_metadata.get('token_usage', {})
                input_tokens = token_usage.get('prompt_tokens', len(unified_prompt) // 4)
                output_tokens = token_usage.get('completion_tokens', len(llm_response.content) // 4)
            else:
                input_tokens = len(unified_prompt) // 4
                output_tokens = len(llm_response.content) // 4
            
            # Log the LLM call with token tracking
            logger.llm_call(
                model=self.llm.model_name if hasattr(self.llm, 'model_name') else "gpt-4o",
                operation="tier_0.5_unified_check",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
                tier="0.5",
                prompt_summary=f"Classifying: {user_message[:50]}...",
                success=True
            )
            
            response_text = llm_response.content.strip()
            
            # Remove markdown code blocks if present
            if response_text.startswith("```json"):
                response_text = response_text[7:-3].strip()
            elif response_text.startswith("```"):
                response_text = response_text[3:-3].strip()
            
            # Validate response_text is not empty
            if not response_text:
                print("⚠️ Empty response from LLM, falling back to full analysis")
                return None, "specific"
            
            # Parse JSON with better error handling
            try:
                result = json.loads(response_text)
            except json.JSONDecodeError as json_err:
                print(f"⚠️ JSON parse error: {json_err}")
                print(f"   Response text: {response_text[:200]}")
                return None, "specific"

            category = result.get("category")
            
            print(f"⚡ Tier 0.5 Unified: {category.upper()} detected")
            
            # === HANDLE EACH CATEGORY ===
            
            # 1. TASK REQUEST - needs full analysis
            if category == "task_request":
                query_scope = result.get("query_scope", "specific")
                print(f"  → Proceeding to full analysis (query_scope: {query_scope})")
                return None, query_scope  # Pass query_scope to Tier 1
            
            # 2. CONFIRMATION
            if category == "confirmation":
                print(f"  → User confirmed action")
                return ConversationAnalysis(
                        intent=ConversationIntent.READY_TO_EXECUTE,
                        task_type=conversation_state.extracted_info.get("task_type", "task"),
                        extracted_info=conversation_state.extracted_info,
                        missing_fields=[],
                        clarification_question=None,
                        reasoning="User confirmed execution",
                        execution_ready=True,
                        execution_summary=conversation_state.execution_summary
                    ), None  # No query_scope for non-task_request            # 3. CANCELLATION
            if category == "cancellation":
                has_compound = result.get("has_compound_cancel", False)
                if has_compound:
                    print(f"  → Compound cancel+task, proceeding to full analysis")
                    return None, "specific"  # Compound cancel → default to specific
                else:
                    print(f"  → Pure cancellation")
                    cancelled_task_info = conversation_state.extracted_info.copy()
                    return ConversationAnalysis(
                        intent=ConversationIntent.CANCELLED,
                        task_type="cancellation",
                        extracted_info={},
                        missing_fields=[],
                        clarification_question=None,
                        reasoning=f"User cancelled request. Previous data: {cancelled_task_info}",
                        execution_ready=False,
                        execution_summary=None
                    ), None  # No query_scope for non-task_request
            
            # 4. MODIFICATION
            if category == "modification":
                field = result.get("field_to_modify")
                new_value = result.get("new_value")
                
                if field and new_value:
                    print(f"  → Modified {field} to {new_value}")
                    updated_info = conversation_state.extracted_info.copy()
                    updated_info[field] = new_value
                    
                    if not conversation_state.missing_fields:
                        return ConversationAnalysis(
                            intent=ConversationIntent.READY_TO_EXECUTE,
                            task_type=updated_info.get("task_type", "task"),
                            extracted_info=updated_info,
                            missing_fields=[],
                            clarification_question=None,
                            reasoning=f"Modified {field} to {new_value}",
                            execution_ready=True,
                            execution_summary=conversation_state.execution_summary
                        ), None  # No query_scope for non-task_request
                    else:
                        return ConversationAnalysis(
                            intent=ConversationIntent.NEEDS_CLARIFICATION,
                            task_type=updated_info.get("task_type", "task"),
                            extracted_info=updated_info,
                            missing_fields=conversation_state.missing_fields,
                            clarification_question=conversation_state.clarification_question,
                            reasoning=f"Modified {field}, still need clarification",
                            execution_ready=False,
                            execution_summary=None
                        ), None  # No query_scope for non-task_request
                else:
                    # Complex modification, needs full analysis
                    print(f"  → Complex modification, proceeding to full analysis")
                    return None, "specific"  # Complex modification → default to specific
            
            # 5. FOLLOWUP ANSWER
            if category == "followup_answer":
                extracted_value = result.get("extracted_value")
                execution_summary_from_llm = result.get("execution_summary")  # ✅ Get execution_summary from LLM
                
                if extracted_value and missing_field:
                    print(f"  → Extracted {missing_field} = {extracted_value}")
                    print(f"  → Current extracted_info: {conversation_state.extracted_info}")
                    print(f"  → Current missing_fields: {conversation_state.missing_fields}")
                    updated_info = conversation_state.extracted_info.copy()
                    
                    # Check if extracted_value is a dict with multiple fields
                    if isinstance(extracted_value, dict):
                        # User provided multiple pieces of info - merge all fields
                        print(f"  → Multi-field answer detected, merging all fields")
                        for key, val in extracted_value.items():
                            updated_info[key] = val
                        
                        # Remove all fields that were provided from missing_fields
                        remaining_missing = [f for f in conversation_state.missing_fields if f not in extracted_value]
                    else:
                        # Single field answer - assign to missing_field
                        updated_info[missing_field] = extracted_value
                        remaining_missing = [f for f in conversation_state.missing_fields if f != missing_field]
                    
                    print(f"  → Updated extracted_info: {updated_info}")
                    print(f"  → Remaining missing_fields: {remaining_missing}")
                    
                    if not remaining_missing:
                        # ✅ All fields complete - use execution_summary from LLM or generate fallback
                        final_execution_summary = execution_summary_from_llm or conversation_state.execution_summary
                        
                        # If still no execution_summary, generate from extracted_info
                        if not final_execution_summary:
                            task_type = updated_info.get("task_type", "task")
                            summary_parts = []
                            for key, value in updated_info.items():
                                if key != "task_type" and value:
                                    summary_parts.append(f"{key}: {value}")
                            final_execution_summary = f"{task_type} - " + ", ".join(summary_parts) if summary_parts else task_type
                        
                        print(f"  → Execution summary: {final_execution_summary}")
                        
                        return ConversationAnalysis(
                            intent=ConversationIntent.READY_TO_EXECUTE,
                            task_type=updated_info.get("task_type", "task"),
                            extracted_info=updated_info,
                            missing_fields=[],
                            clarification_question=None,
                            reasoning="All required fields collected",
                            execution_ready=True,
                            execution_summary=final_execution_summary  # ✅ Use generated summary
                        ), None  # No query_scope for non-task_request
                    else:
                        next_field = remaining_missing[0]
                        return ConversationAnalysis(
                            intent=ConversationIntent.NEEDS_CLARIFICATION,
                            task_type=updated_info.get("task_type", "task"),
                            extracted_info=updated_info,
                            missing_fields=remaining_missing,
                            clarification_question=f"Great! What should the {next_field} be?",
                            reasoning=f"Extracted {list(extracted_value.keys()) if isinstance(extracted_value, dict) else missing_field}, still need {next_field}",
                            execution_ready=False,
                            execution_summary=None
                        ), None  # No query_scope for non-task_request
                else:
                    # Complex answer, needs full analysis
                    print(f"  → Complex answer, proceeding to full analysis")
                    return None, "specific"  # Complex answer → default to specific
            
            # 6. CASUAL CONVERSATION
            if category == "casual_conversation":
                print(f"  → Casual conversation")
                return ConversationAnalysis(
                    intent=ConversationIntent.SMALL_TALK,
                    task_type="conversation",
                    extracted_info={},
                    missing_fields=[],
                    clarification_question=None,
                    reasoning="User is engaging in casual conversation",
                    execution_ready=False,
                    execution_summary=None
                ), None  # No query_scope for non-task_request
            
            # 7. UNINTELLIGIBLE
            if category == "unintelligible":
                print(f"  → Unintelligible input")
                return ConversationAnalysis(
                    intent=ConversationIntent.NEEDS_CLARIFICATION,
                    task_type="unknown",
                    extracted_info={},
                    missing_fields=["all"],
                    clarification_question="I didn't quite catch that. Could you rephrase what you'd like me to help with?",
                    reasoning="User input is not intelligible",
                    execution_ready=False,
                    execution_summary=None
                ), None  # No query_scope for non-task_request
            
            if category == "template_upload":
                if not uploaded_file:
                    print(f"  → Template upload detected but no file provided")
                    return ConversationAnalysis(
                        intent=ConversationIntent.NEEDS_CLARIFICATION,
                        task_type="template_upload",
                        extracted_info={},
                        missing_fields=["file_upload"],
                        clarification_question="Please upload a template file to continue.",
                        reasoning="Template upload requested but no file attached",
                        execution_ready=False,
                        execution_summary=None
                ), None
            
            save_to_drive = result.get("save_to_drive", True)
            template_name = result.get("template_name")
            document_title = result.get("document_title")
            execution_summary = result.get("execution_summary")
            
            print(f"  → File uploaded: {uploaded_file.get('filename')}")
            print(f"  → Save to drive: {save_to_drive}")
            print(f"  → Template name: {template_name}")
            print(f"  → Document title: {document_title}")
            
            # Build extracted_info
            extracted_info = {
                "task_type": "template_upload",
                "uploaded_file": uploaded_file,
                "save_to_drive": save_to_drive,
                "template_name": template_name
            }
            if document_title:
                extracted_info["document_title"] = document_title
            
            missing_fields = []
            if not document_title:
                missing_fields.append("document_title")

            if missing_fields:
                clarification_q = f"Great! I'll save this as '{template_name}' template.\n\n"
                clarification_q += f"What should I title the new document I create from it?"
            else:
                clarification_q = None
            
            if template_name:
                extracted_info["template_name"] = template_name
            if document_title:
                extracted_info["document_title"] = document_title
            
            # Determine missing fields
            missing_fields = []
            if save_to_drive and not template_name:
                missing_fields.append("template_name")
            if not document_title:
                missing_fields.append("document_title")
            
            # Build clarification question
            if missing_fields:
                if "template_name" in missing_fields and "document_title" in missing_fields:
                    clarification_q = f"Great! I'll save this as a template and create a document from it.\n\n"
                    clarification_q += f"What should I name:\n"
                    clarification_q += f"1. The template (for future use)?\n"
                    clarification_q += f"2. The new document?"
                elif "template_name" in missing_fields:
                    clarification_q = f"What should I name this template for future use?"
                else:  # document_title missing
                    clarification_q = f"What should I title the new document?"
            else:
                clarification_q = None
            
            # Generate execution summary if not provided
            if not execution_summary:
                if save_to_drive and document_title:
                    execution_summary = f"Upload template '{template_name}' to Drive and create document '{document_title}'"
                elif document_title:
                    execution_summary = f"Create document '{document_title}' from uploaded template"
                else:
                    execution_summary = f"Process uploaded template '{template_name}'"
            
            return ConversationAnalysis(
                intent=ConversationIntent.TEMPLATE_UPLOAD if not missing_fields else ConversationIntent.NEEDS_CLARIFICATION,
                task_type="template_upload",
                extracted_info=extracted_info,
                missing_fields=missing_fields,
                clarification_question=clarification_q,
                reasoning=f"Template upload: template='{template_name}', document='{document_title}', missing={missing_fields}",
                execution_ready=len(missing_fields) == 0,
                execution_summary=execution_summary if not missing_fields else None
            ), None
            
        except Exception as e:
            # Check if this is an LLM service error (rate limit, quota, etc.)
            if is_llm_error(e):
                print(f"❌ LLM service error in unified quick check: {e}")
                raise handle_llm_error(e)
            
            print(f"⚠️ Unified quick check failed: {e}, falling back to full analysis")
            return None, "specific"  # Fallback: default to specific
        
        # Default: proceed to full analysis
        return None, "specific"  # Fallback: default to specific
    
    
    def _quick_help_check(self, user_message: str, conversation_state: ConversationState) -> Optional[ConversationAnalysis]:
        """
        Detect help/tutorial requests and provide structured guidance.
        Uses pattern matching for instant response without LLM call.
        
        Args:
            user_message: Current user input
            conversation_state: Previous conversation context
            
        Returns:
            ConversationAnalysis with help response, or None if not a help request
        """
        help_keywords = ["help", "how", "guide", "tutorial", "teach me", "explain", "instructions", "show me how"]
        user_lower = user_message.lower().strip()
        
        # Check if this is a help request
        if not any(keyword in user_lower for keyword in help_keywords):
            return None
        
        # Check if it's a general help request (not task-specific like "how do I send email")
        task_indicators = ["send", "search", "find", "create", "delete", "schedule", "reply"]
        is_general_help = not any(task in user_lower for task in task_indicators)
        
        if is_general_help:
            print(f"🔍 Quick help: General help request detected")
            
            help_response = """I can help you with several tasks:

📧 **Email Management:**
- Send emails to anyone
- Search your inbox
- Reply to emails
- Draft emails for later

📄 **Document Creation:**
- Create Google Docs
- Edit existing documents
- Add content to documents

📅 **Calendar (coming soon):**
- Schedule meetings
- Check availability

**To get started, try saying:**
- "Send an email to john@example.com"
- "Search my emails for invoices from last week"
- "Create a document about project planning"

What would you like to do?"""
            
            return ConversationAnalysis(
                intent=ConversationIntent.SMALL_TALK,
                task_type="help_request",
                extracted_info={},
                missing_fields=[],
                clarification_question=help_response,
                reasoning="User requested general help",
                execution_ready=False,
                execution_summary=None
            )
        
        # Task-specific help, let full analysis handle it
        return None
    
    def _quick_status_check(self, user_message: str, conversation_state: ConversationState) -> Optional[ConversationAnalysis]:
        """
        Detect status check requests after execution and provide quick update.
        Uses pattern matching + execution history lookup.
        
        Args:
            user_message: Current user input
            conversation_state: Previous conversation context
            
        Returns:
            ConversationAnalysis with status response, or None if not a status check
        """
        status_keywords = ["status", "done", "finished", "complete", "did it work", "success", "result", "what happened"]
        user_lower = user_message.lower().strip()
        
        # Check if this is a status request
        if not any(keyword in user_lower for keyword in status_keywords):
            return None
        
        # Only respond if we have execution history
        if conversation_state.executed_count == 0:
            return None
        
        print(f"🔍 Quick status: Status check request detected")
        
        last_exec = conversation_state.execution_history[-1] if conversation_state.execution_history else {}
        status = last_exec.get('status', 'unknown')
        message = last_exec.get('message', 'No details available')
        task = last_exec.get('task', 'the task')
        
        if status == "success":
            status_response = f"✅ **Last execution: Successful**\n\n{message}\n\nAnything else you'd like to do?"
        elif status == "error":
            status_response = f"❌ **Last execution: Failed**\n\n**Error:** {message}\n\nWould you like to try again or do something else?"
        else:
            status_response = f"📊 **Last execution status:** {status}\n\n{message}"
        
        return ConversationAnalysis(
            intent=ConversationIntent.SMALL_TALK,
            task_type="status_check",
            extracted_info={},
            missing_fields=[],
            clarification_question=status_response,
            reasoning="User checking execution status",
            execution_ready=False,
            execution_summary=None
        )
    
    def analyze_request(
        self, 
        user_message: str, 
        conversation_state: ConversationState,
        state_id: str = "default",
        uploaded_file: Optional[Dict[str, Any]] = None
    ) -> ConversationAnalysis:
        """
        Analyze user message to determine intent and completeness.
        
        Args:
            user_message: Current user input
            conversation_state: Previous conversation context
            state_id: Conversation identifier for memory manager
            
        Returns:
            ConversationAnalysis with intent, missing fields, and questions
        """
        
        # === TIER 0: PATTERN-BASED QUICK CHECKS (NO LLM - INSTANT) ===
        
        # Check for greetings first (most common)
        greeting_result = self._quick_greeting_check(user_message)
        if greeting_result is not None:
            return greeting_result
        
        # Check for capability questions (uses cached summary)
        capability_result = self._quick_capability_list_check(user_message)
        if capability_result is not None:
            return capability_result
        
        # Check for repeat requests
        repeat_result = self._quick_repeat_check(user_message, conversation_state, state_id)
        if repeat_result is not None:
            return repeat_result
        
        # Check for example requests
        examples_result = self._quick_examples_check(user_message)
        if examples_result is not None:
            return examples_result
        
        # Quick help check (pattern-based, instant response)
        help_result = self._quick_help_check(user_message, conversation_state)
        if help_result is not None:
            return help_result
        
        # Quick status check (pattern-based + history lookup)
        status_result = self._quick_status_check(user_message, conversation_state)
        if status_result is not None:
            return status_result
        
        # === TIER 0.5: UNIFIED LIGHTWEIGHT LLM CHECK (~100-250 TOKENS) ===
        
        # Single unified LLM call handles: confirmation, cancellation, modification,
        # followup answers, casual conversation, unintelligible input
        # Also classifies query_scope for task_request (general vs specific)
        unified_result, query_scope_hint = self._unified_quick_check(user_message, conversation_state, state_id, uploaded_file=uploaded_file)
        if unified_result is not None:
            return unified_result
        
        # === TIER 1: FULL TASK ANALYSIS (~500-1500 TOKENS) ===
        print(f"🔍 Performing full task analysis with capabilities...")
        
        # Get memory manager and build context using it
        memory_manager = self._get_memory_manager(state_id, conversation_state.memory_state)
        
        # Get context from memory manager (includes summary, entities, recent messages)
        history_text = memory_manager.get_context_for_llm()
        if history_text:
            history_text = f"{history_text}\n\n"
        
        # Add execution context if available (helps LLM understand post-execution modifications)
        exec_context = ""
        if conversation_state.executed_count > 0:
            last_exec = conversation_state.execution_history[-1] if conversation_state.execution_history else {}
            exec_context = (
                f"\nEXECUTION CONTEXT:\n"
                f"- Executed {conversation_state.executed_count} task(s) | "
                f"Last: {conversation_state.last_executed_at or 'unknown'} | "
                f"Status: {last_exec.get('status', 'unknown')} | "
                f"Result: {last_exec.get('message', 'N/A')}\n"
                f"- User may be modifying/redoing previous execution\n\n"
            )
            
        # Use query_scope from Tier 0.5 if available (for task_request fallthrough)
        # Otherwise use pattern-based fallback
        if query_scope_hint is None:
            # Fallback: Pattern-based check for general capability questions
            general_patterns = ["what can you do", "capabilities", "features", "what tasks", "show me everything"]
            query_scope = "general" if any(pattern in user_message.lower() for pattern in general_patterns) else "specific"
        else:
            # Use query_scope from Tier 0.5 LLM classification
            query_scope = query_scope_hint
            print(f"🎯 Using query_scope from Tier 0.5: {query_scope}")
        
        # Choose capabilities based on query scope
        if query_scope == "general":
            # Show ALL capabilities for general questions
            capabilities_to_show = self.full_capabilities_summary 
            print(f"🔍 Query classified as GENERAL - showing all capabilities")
        else:
            # Filter capabilities to relevant agents for specific tasks
            relevant_agents = identify_relevant_agents(user_message)
            capabilities_to_show = self._build_capabilities_summary(relevant_agents)
            print(f"🔍 Query classified as SPECIFIC - filtered to agents: {relevant_agents}")
            print(f"🔍 Capabilities are: {capabilities_to_show}")
            
        # Build system prompt with capabilities
        system_prompt = """Validate and clarify user requests before execution. Check feasibility against available agents and tools, extract required fields, ask specific questions for missing info.

Available agents and tools:
{capabilities}

🚨 TEMPLATE+DATA WORKFLOW DETECTION:
Pattern: User mentions creating document using BOTH a template file AND a data file
Examples:
  - "Create January Reports using MOMtemplate template and TestData123 data"
  - "Make document X with template Y and data Z"
  - "Use template ABC and data DEF to create document GHI"

Required Fields (extract from user message):
  1. template_name: Name of template file in Drive (e.g., "MOMtemplate")
  2. data_name: Name of data file in Drive (e.g., "TestData123")
  3. new_title: Title for new document to create (e.g., "January Reports")

How it works:
  Step 1: drive_agent searches Drive for both files → returns template_file_id, data_file_id
  Step 2: docs_agent creates document using those IDs

Classification:
  - If ALL 3 fields present → intent: "ready_to_execute", task_type: "create_from_template_and_data"
  - If missing fields → intent: "needs_clarification"
  - execution_summary: "Create [new_title] from [template_name] using [data_name] data"

CONTEXT RULES:
- Post-execution: Conversation continues. Treat modification requests as NEW tasks
- Compound cancel ("cancel X and do Y"): Extract ONLY new task (Y), ignore old context

DERIVABLE FIELDS [via tool: criteria]:
Fields marked [via tool: criteria] are derived by calling that tool. Extract the tool criteria instead of asking for the field directly.

Example: forward_email(message_id [via search_emails: query], to)
- User: "forward email from john@example.com to jane@example.com"
- extracted_info: {{"query": "john@example.com", "to": "jane@example.com"}}
- missing_fields: [] (message_id derived from query)

INTENT CLASSIFICATION:
- needs_clarification: Missing required fields
- not_feasible: No matching capability
- too_complex: Multi-step/unclear
- ready_to_execute: All fields present
- small_talk: Non-task conversation

JSON OUTPUT:
{{
    "intent": "ready_to_execute",
    "task_type": "create_from_template_and_data",
    "extracted_info": {{"template_name": "X", "data_name": "Y", "new_title": "Z"}},
    "missing_fields": [],
    "clarification_question": null,
    "reasoning": "All fields extracted for template+data workflow",
    "execution_ready": true,
    "execution_summary": "Create Z from template X using data Y"
}}

IMPORTANT: Always provide execution_summary - human-readable task description.

CLARIFICATION QUESTIONS - Be specific and reference what's already known.

ROLE DISAMBIGUATION RULE:
When user mentions multiple entities, infer roles from explicit cues ("from", "to", "template", "data"). If unclear, ask.
""".format(capabilities=capabilities_to_show)

        user_prompt = f"""{history_text}{exec_context}CURRENT USER MESSAGE: {user_message}"""

        # Call LLM with timeout and retry
        try:
            # === TOKEN TRACKING: Tier 1 Full Analysis ===
            start_time = time.time()
            llm_response = self.llm.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                config={"timeout": 320, "max_tokens": 2000}  # 320 second timeout
            )
            duration_ms = (time.time() - start_time) * 1000
            
            # Extract token usage from response
            input_tokens = 0
            output_tokens = 0
            if hasattr(llm_response, 'response_metadata'):
                token_usage = llm_response.response_metadata.get('token_usage', {})
                input_tokens = token_usage.get('prompt_tokens', (len(system_prompt) + len(user_prompt)) // 4)
                output_tokens = token_usage.get('completion_tokens', len(llm_response.content) // 4)
            else:
                input_tokens = (len(system_prompt) + len(user_prompt)) // 4
                output_tokens = len(llm_response.content) // 4
            
            # Log the LLM call with token tracking
            logger.llm_call(
                model=self.llm.model_name if hasattr(self.llm, 'model_name') else "gpt-4o",
                operation="tier_1_full_analysis",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
                tier="1",
                prompt_summary=f"Analyzing: {user_message[:50]}...",
                success=True
            )
        except Exception as llm_error:
            # Check if this is an LLM service error (rate limit, quota, etc.)
            if is_llm_error(llm_error):
                print(f"❌ LLM service error in full analysis: {llm_error}")
                # Log the failed LLM call
                logger.llm_call(
                    model=self.llm.model_name if hasattr(self.llm, 'model_name') else "gpt-4o",
                    operation="tier_1_full_analysis",
                    input_tokens=(len(system_prompt) + len(user_prompt)) // 4,
                    output_tokens=0,
                    duration_ms=0,
                    tier="1",
                    prompt_summary=f"Analyzing: {user_message[:50]}...",
                    success=False,
                    error=str(llm_error)
                )
                raise handle_llm_error(llm_error)
            
            # Log the failed LLM call
            logger.llm_call(
                model=self.llm.model_name if hasattr(self.llm, 'model_name') else "gpt-4o",
                operation="tier_1_full_analysis",
                input_tokens=(len(system_prompt) + len(user_prompt)) // 4,
                output_tokens=0,
                duration_ms=0,
                tier="1",
                prompt_summary=f"Analyzing: {user_message[:50]}...",
                success=False,
                error=str(llm_error)
            )
            # LLM call failed - return safe fallback
            print(f"⚠️ LLM call failed: {llm_error}")
            return ConversationAnalysis(
                intent=ConversationIntent.NEEDS_CLARIFICATION,
                task_type="unknown",
                extracted_info={},
                missing_fields=["all"],
                clarification_question="I'm having trouble processing that. Could you please rephrase your request?",
                reasoning=f"LLM invocation failed: {str(llm_error)}",
                execution_ready=False,
                execution_summary=None
            )
        
        # Parse response
        try:
            response_text = llm_response.content.strip()
            
            # Handle code blocks - LLM may include text before JSON
            if "```json" in response_text:
                # Extract content between ```json and ```
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                if end > start:
                    response_text = response_text[start:end].strip()
            elif "```" in response_text:
                # Extract content between ``` and ```
                start = response_text.find("```") + 3
                end = response_text.find("```", start)
                if end > start:
                    response_text = response_text[start:end].strip()
            
            # If still not valid JSON, try to find JSON object directly
            if not response_text.startswith("{"):
                json_start = response_text.find("{")
                if json_start != -1:
                    # Find matching closing brace
                    brace_count = 0
                    json_end = json_start
                    for i, char in enumerate(response_text[json_start:], json_start):
                        if char == "{":
                            brace_count += 1
                        elif char == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                json_end = i + 1
                                break
                    response_text = response_text[json_start:json_end]
            
            # Parse JSON
            analysis_dict = json.loads(response_text)
            
            # Save for comparison
            with open("tier1_llm_comparison.json", "w") as f:
                json.dump({"response": response_text, "parsed": analysis_dict}, f, indent=2)
            
            # Validate required fields exist
            required_fields = ["intent", "task_type", "extracted_info", "missing_fields", "execution_ready"]
            for field in required_fields:
                if field not in analysis_dict:
                    raise ValueError(f"Missing required field: {field}")
            
            analysis_result = ConversationAnalysis(**analysis_dict)
            
            # Print analysis result for debugging
            print(f"\n{'='*60}")
            print(f"📊 CONVERSATION ANALYSIS RESULT:")
            print(f"{'='*60}")
            print(f"Intent: {analysis_result.intent}")
            print(f"Task Type: {analysis_result.task_type}")
            print(f"Extracted Info: {json.dumps(analysis_result.extracted_info, indent=2)}")
            print(f"Missing Fields: {analysis_result.missing_fields}")
            print(f"Clarification Question: {analysis_result.clarification_question}")
            print(f"Execution Ready: {analysis_result.execution_ready}")
            print(f"Reasoning: {analysis_result.reasoning}")
            print(f"{'='*60}\n")
            
            return analysis_result
            
        except (json.JSONDecodeError, ValueError) as e:
            # JSON parsing or validation failed
            print(f"⚠️ Failed to parse LLM response: {e}")
            print(f"Raw response: {llm_response.content[:500]}")  # Log first 500 chars
            
            # Fallback: treat as needing clarification
            return ConversationAnalysis(
                intent=ConversationIntent.NEEDS_CLARIFICATION,
                task_type="unknown",
                extracted_info={},
                missing_fields=["all"],
                clarification_question=llm_response.content,
                reasoning=f"Failed to parse LLM response: {str(e)}",
                execution_ready=False,
                execution_summary=None
            )
        except Exception as e:
            # Unexpected error creating ConversationAnalysis
            print(f"⚠️ Unexpected error in analyze_request: {e}")
            return ConversationAnalysis(
                intent=ConversationIntent.NEEDS_CLARIFICATION,
                task_type="unknown",
                extracted_info={},
                missing_fields=["all"],
                clarification_question="Something went wrong. Could you try rephrasing your request?",
                reasoning=f"Unexpected error: {str(e)}",
                execution_ready=False,
                execution_summary=None
            )
    
    def _is_delivery_order_request(self, user_message: str) -> bool:
        """
        Quick pattern check to detect if user is asking about delivery orders.
        
        Args:
            user_message: User message to check
            
        Returns:
            True if message appears to be a delivery order request
        """
        delivery_keywords = [
            "delivery order", "delivery orders", "purchase order", "purchase orders",
            "po ", "pos ", "orders from", "search for", "find orders", "find delivery",
            "orders to", "batangas", "supplier", "vendor order"
        ]
        
        user_lower = user_message.lower()
        return any(keyword in user_lower for keyword in delivery_keywords)
    
    def _handle_delivery_order_preview(
        self,
        query: str,
        credentials_dict: Dict[str, Any],
        gmail_agent_url: str = None
    ) -> Dict[str, Any]:
        """
        Stage 1: Search for delivery orders without downloading (preview only).
        
        Args:
            query: Gmail search query (e.g., "from:supplier delivery")
            credentials_dict: User OAuth credentials
            gmail_agent_url: URL of Gmail agent (default from env)
            
        Returns:
            Dictionary with preview results or error
        """
        
        if gmail_agent_url is None:
            gmail_agent_url = os.getenv("GMAIL_AGENT_URL", "http://localhost:8000")
        
        try:
            payload = {
                "tool": "search_emails_with_delivery_order_attachments",
                "inputs": {
                    "query": query,
                    "max_results": 5,
                    "download_attachments": False  # Preview only - don't download yet
                },
                "credentials_dict": credentials_dict or {}
            }
            
            response = httpx.post(
                f"{gmail_agent_url}/execute_task",
                json=payload,
                timeout=30.0
            )
            
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Gmail agent error: {response.status_code}",
                    "preview": []
                }
            
            result = response.json()
            
            if not result.get("success"):
                return {
                    "success": False,
                    "error": result.get("error", "Search failed"),
                    "preview": []
                }
            
            # Extract preview information
            emails = result.get("emails_with_attachments", [])
            preview = []
            
            for email in emails:
                email_preview = {
                    "id": email.get("id"),
                    "from": email.get("from"),
                    "subject": email.get("subject"),
                    "date": email.get("date"),
                    "attachment_count": len(email.get("attachments", [])),
                    "attachments": [
                        {
                            "filename": att.get("filename"),
                            "size_kb": att.get("size", 0) // 1024,
                            "mime_type": att.get("mime_type")
                        }
                        for att in email.get("attachments", [])
                    ]
                }
                preview.append(email_preview)
            
            return {
                "success": True,
                "error": None,
                "preview": preview,
                "total_found": result.get("total_emails_found", 0),
                "total_attachments": result.get("total_attachments_downloaded", 0)
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": f"Preview failed: {str(e)}",
                "preview": []
            }
    
    def _build_delivery_order_preview_response(
        self,
        preview_result: Dict[str, Any],
        conversation_state: ConversationState
    ) -> str:
        """
        Build a user-friendly preview response showing found orders.
        
        Args:
            preview_result: Result from _handle_delivery_order_preview
            conversation_state: Conversation state to update
            
        Returns:
            Formatted response string
        """
        if not preview_result["success"]:
            return f"❌ Search failed: {preview_result['error']}"
        
        preview = preview_result["preview"]
        
        if not preview:
            return "📭 No delivery orders found matching your search. Try a different query."
        
        # Store preview results in conversation state for later execution
        conversation_state.extracted_info["delivery_order_preview"] = preview
        conversation_state.extracted_info["delivery_order_total_found"] = preview_result.get("total_found", 0)
        
        # Build formatted response
        response = f"📦 **Found {len(preview)} delivery order(s):**\n\n"
        
        for i, email in enumerate(preview, 1):
            response += f"**{i}. {email['subject']}**\n"
            response += f"   From: {email['from']}\n"
            response += f"   Date: {email['date']}\n"
            response += f"   Attachments: {email['attachment_count']}\n"
            
            if email['attachments']:
                for att in email['attachments']:
                    response += f"     • {att['filename']} ({att['size_kb']} KB)\n"
            
            response += "\n"
        
        # Ask for confirmation
        response += "**Ready to process?**\n\n"
        response += "I can:\n"
        response += "1. Parse and extract the order data\n"
        response += "2. Upload results to a Google Sheet\n"
        response += "3. Create a summary document in Google Docs\n"
        response += "4. Save metadata to database\n\n"
        response += "**Which sheet should I upload to?** (Provide sheet ID or name)"
        
        # Mark that we're awaiting sheet confirmation
        conversation_state.extracted_info["delivery_order_stage"] = "awaiting_sheet_confirmation"
        conversation_state.clarification_question = response
        conversation_state.missing_fields = ["sheets_sheet_id"]
        conversation_state.ready_for_execution = False
        
        return response
    
    def _handle_delivery_order_execution(
        self,
        user_message: str,
        conversation_state: ConversationState,
        credentials_dict: Dict[str, Any],
        gmail_agent_url: str = None,
        destination_type: str = "both",
        sheet_id: str = None,
        create_summary_doc: bool = True,
        summary_doc_title: str = None
    ) -> Dict[str, Any]:
        """
        Stage 5+: Execute full workflow (download, parse, transform, upload, save).
        
        Args:
            user_message: User's response (not used in new flow)
            conversation_state: Conversation state with all setup data
            credentials_dict: User OAuth credentials
            gmail_agent_url: URL of Gmail agent
            destination_type: "sheets", "docs", or "both"
            sheet_id: Google Sheets ID (if applicable)
            create_summary_doc: Whether to create summary document
            summary_doc_title: Title for summary document
            
        Returns:
            Dictionary with execution result
        """
        
        if gmail_agent_url is None:
            gmail_agent_url = os.getenv("GMAIL_AGENT_URL", "http://localhost:8000")
        
        try:
            # Get original query from conversation state
            original_query = conversation_state.extracted_info.get("delivery_order_query")
            if not original_query:
                return {
                    "success": False,
                    "error": "Lost original search query. Please start over.",
                    "processed": []
                }
            
            # Determine what to upload/create
            upload_to_sheets = destination_type in ["sheets", "both"]
            create_doc = create_summary_doc and destination_type in ["docs", "both"]
            
            # Call the full workflow tool
            payload = {
                "tool": "process_delivery_order_workflow",
                "inputs": {
                    "query": original_query,
                    "max_results": 5,
                    "download_attachments": True,
                    "save_to_db": True,
                    "upload_to_sheets": upload_to_sheets,
                    "sheets_sheet_id": sheet_id if upload_to_sheets else None,
                    "create_summary_doc": create_doc,
                    "summary_doc_title": summary_doc_title if create_doc else None,
                },
                "credentials_dict": credentials_dict or {}
            }
            
            response = httpx.post(
                f"{gmail_agent_url}/execute_task",
                json=payload,
                timeout=120.0
            )
            
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Workflow error: {response.status_code}",
                    "processed": []
                }
            
            result = response.json()
            return result
        
        except Exception as e:
            return {
                "success": False,
                "error": f"Execution failed: {str(e)}",
                "processed": []
            }
    
    def _build_delivery_order_execution_response(
        self,
        execution_result: Dict[str, Any],
        conversation_state: ConversationState
    ) -> str:
        """
        Build a user-friendly response showing execution results.
        
        Args:
            execution_result: Result from _handle_delivery_order_execution
            conversation_state: Conversation state to update
            
        Returns:
            Formatted response string
        """
        if not execution_result["success"]:
            return f"❌ Processing failed: {execution_result.get('error', 'Unknown error')}"
        
        processed = execution_result.get("processed", [])
        errors = execution_result.get("errors", [])
        document_url = execution_result.get("document_url")
        
        response = "✅ **Delivery order processing complete!**\n\n"
        
        if processed:
            response += f"**Successfully processed: {len(processed)} order(s)**\n\n"
            for item in processed:
                response += f"📄 {item.get('file_name', 'Unknown')}\n"
                response += f"   From: {item.get('email_from', 'Unknown')}\n"
                response += f"   Subject: {item.get('email_subject', 'N/A')}\n"
                response += f"   ✓ Parsed ✓ Transformed ✓ Uploaded\n\n"
        
        if errors:
            response += f"⚠️ **{len(errors)} error(s) occurred:**\n\n"
            for error in errors[:3]:  # Show first 3 errors
                response += f"   • {error}\n"
            if len(errors) > 3:
                response += f"   ... and {len(errors) - 3} more\n\n"
        
        summary = execution_result.get("search_summary", {})
        response += f"**Summary:** {summary.get('total_emails_found', 0)} emails processed\n\n"
        
        # Add document link if created
        if document_url:
            response += f"📋 **Summary Document Created:** [View in Google Docs]({document_url})\n\n"
        
        # Clean up conversation state
        conversation_state.extracted_info["delivery_order_stage"] = "completed"
        conversation_state.ready_for_execution = False
        conversation_state.clarification_question = None
        conversation_state.missing_fields = []
        
        return response
    
    def _show_email_content_and_ask_destination(
        self,
        email_preview: Dict[str, Any],
        conversation_state: ConversationState
    ) -> str:
        """
        Stage 1.5: Show actual email content and ask where to put the data.
        
        Args:
            email_preview: Email metadata from preview
            conversation_state: Conversation state to update
            
        Returns:
            Formatted response showing email content
        """
        response = f"📧 **Email Found!**\n\n"
        response += f"**From:** {email_preview.get('from', 'Unknown')}\n"
        response += f"**Subject:** {email_preview.get('subject', 'N/A')}\n"
        response += f"**Date:** {email_preview.get('date', 'Unknown')}\n\n"
        
        # Show attachments
        attachments = email_preview.get('attachments', [])
        if attachments:
            response += "**Attachments:**\n"
            for att in attachments:
                response += f"  • {att.get('filename', 'Unknown')} ({att.get('size_kb', 0)} KB)\n"
            response += "\n"
        
        # AI must understand content message
        response += "✅ I understand the email content and found the attachment.\n\n"
        
        # Ask for destination
        response += "**Where would you like me to put the extracted data?**\n\n"
        response += "1. **Google Sheets** - Upload to an existing sheet\n"
        response += "2. **Google Docs** - Create a summary document\n"
        response += "3. **Both** - Upload to sheets AND create a doc\n\n"
        response += "Just reply with your choice (1, 2, or 3):"
        
        # Update state
        conversation_state.extracted_info["delivery_order_stage"] = "awaiting_destination_choice"
        conversation_state.extracted_info["email_preview"] = email_preview
        conversation_state.clarification_question = response
        conversation_state.missing_fields = ["destination_choice"]
        conversation_state.ready_for_execution = False
        
        return response
    
    def _format_extracted_data_for_review(
        self,
        parsed_data: Dict[str, Any],
        filename: str
    ) -> str:
        """
        Format extracted data in human-readable format (not JSON).
        
        Args:
            parsed_data: Parsed data from mapping agent
            filename: Name of the file that was extracted
            
        Returns:
            Formatted string for user review
        """
        response = f"📊 **Extracted Data from {filename}:**\n\n"
        
        # If it's structured data with rows
        if isinstance(parsed_data, dict):
            if "rows" in parsed_data:
                rows = parsed_data["rows"]
                if rows and isinstance(rows, list):
                    # Show as a formatted table
                    headers = list(rows[0].keys()) if rows else []
                    response += "| " + " | ".join(headers) + " |\n"
                    response += "|" + "|".join(["---"] * len(headers)) + "|\n"
                    
                    for row in rows[:5]:  # Show first 5 rows
                        values = [str(row.get(h, "")) for h in headers]
                        response += "| " + " | ".join(values) + " |\n"
                    
                    if len(rows) > 5:
                        response += f"\n... and {len(rows) - 5} more rows\n"
                    
                    response += f"\n**Total rows:** {len(rows)}\n"
            else:
                # Show as key-value pairs
                for key, value in parsed_data.items():
                    if key not in ["rows", "metadata"]:
                        response += f"**{key}:** {value}\n"
        
        response += "\n✅ Does this look correct?\n\n"
        response += "Please type **'Yes'** to confirm or **'No'** to cancel."
        
        return response
    
    def _confirm_full_plan(
        self,
        conversation_state: ConversationState,
        destination_choice: str,
        sheet_id: str = None,
        summary_doc_title: str = None
    ) -> str:
        """
        Show the full plan before execution.
        
        Args:
            conversation_state: Current conversation state
            destination_choice: User's choice (1=sheets, 2=docs, 3=both)
            sheet_id: Google Sheets ID if applicable
            summary_doc_title: Doc title if applicable
            
        Returns:
            Formatted confirmation message
        """
        response = "✅ **Let me confirm your request:**\n\n"
        response += "**Plan:**\n"
        response += "1. ✓ Read the document\n"
        response += "2. ✓ Extract its contents\n"
        response += "3. ✓ Save the data to the database\n"
        
        # Based on destination choice
        if destination_choice == "1" or destination_choice == "3":
            response += f"4. ✓ Put the data in **{sheet_id}** Sheets\n"
        if destination_choice == "2" or destination_choice == "3":
            doc_title = summary_doc_title or "Delivery Order Summary"
            response += f"4. ✓ Create a Google Doc: **{doc_title}**\n"
        
        response += "\n**Is this correct?** (Reply: **Yes** to proceed or **No** to cancel)"
        
        return response
    
    def _handle_destination_choice(
        self,
        user_message: str,
        conversation_state: ConversationState
    ) -> Dict[str, Any]:
        """
        Parse user's destination choice.
        
        Args:
            user_message: User's choice message
            conversation_state: Conversation state
            
        Returns:
            Dictionary with destination info
        """
        user_lower = user_message.lower().strip()
        
        # Determine destination choice
        if user_lower in ["1", "sheets", "sheet"]:
            destination_type = "sheets"
        elif user_lower in ["2", "docs", "doc"]:
            destination_type = "docs"
        elif user_lower in ["3", "both"]:
            destination_type = "both"
        else:
            return {
                "success": False,
                "error": f"Invalid choice. Please reply with 1, 2, or 3."
            }
        
        return {
            "success": True,
            "destination_type": destination_type,
            "requires_sheet_id": destination_type in ["sheets", "both"],
            "requires_doc_title": destination_type in ["docs", "both"]
        }

    def process_message(
        self, 
        user_message: str, 
        conversation_state: Optional[ConversationState] = None,
        state_id: str = "default",
        auto_save: bool = False,
        uploaded_file: Optional[Dict[str, Any]] = None
    ) -> tuple[str, ConversationState]:
        """
        Process a user message and return response + updated state + file upload.
        
        Args:
            user_message: User's input
            conversation_state: Previous conversation state (None for new conversation)
            state_id: Unique conversation identifier for memory management (thread_id)
            auto_save: If True, automatically save to database (for thread mode)
            
        Returns:
            Tuple of (response_text, updated_conversation_state)
        """
        # Initialize state if new conversation
        # if conversation_state is None:
        #     conversation_state = ConversationState()
        
        # Get or create memory manager for this conversation
        memory_manager = self._get_memory_manager(state_id, conversation_state.memory_state if conversation_state else None)
        
        # Add user message to memory manager (automatically handles summarization)
        memory_manager.add_message("user", user_message)
        
        # Also store in messages table if this is a persistent thread
        if auto_save and state_id != "default":
            self.thread_manager.add_message(state_id, "user", user_message)
        
        # Initialize conversation state if new
        if conversation_state is None:
            conversation_state = ConversationState()
        
        # === DELIVERY ORDER ADAPTER: Handle multi-stage delivery order workflow ===
        delivery_stage = conversation_state.extracted_info.get("delivery_order_stage")
        
        # STAGE 0: Initial delivery order search
        if self._is_delivery_order_request(user_message) and not delivery_stage:
            print(f"🚚 DELIVERY ORDER SEARCH: User is searching for delivery orders")
            
            query = user_message
            if "from:" not in query.lower():
                if "batangas" in query.lower():
                    query = f"from:supplier delivery has:attachment to:batangas"
                elif "po" in query.lower() or "purchase order" in query.lower():
                    query = f"subject:PO has:attachment"
                else:
                    query = f"{query} has:attachment"
            
            conversation_state.extracted_info["delivery_order_query"] = query
            credentials_dict = {}  # TODO: Get from session/auth context
            
            preview_result = self._handle_delivery_order_preview(query=query, credentials_dict=credentials_dict)
            
            if not preview_result["success"]:
                response = f"❌ Search failed: {preview_result['error']}"
            else:
                # Get first email for content display
                emails = preview_result["preview"]
                if emails:
                    # Show email content and ask for destination
                    first_email = emails[0]
                    response = self._show_email_content_and_ask_destination(first_email, conversation_state)
                else:
                    response = "📭 No delivery orders found. Try a different search."
                    conversation_state.extracted_info["delivery_order_stage"] = "completed"
            
            memory_manager.add_message("assistant", response)
            if auto_save and state_id != "default":
                self.thread_manager.add_message(state_id, "assistant", response)
            self._save_memory_to_state(conversation_state, state_id)
            if auto_save and state_id != "default":
                self._save_thread_to_db(state_id, conversation_state)
            return response, conversation_state
        
        # STAGE 1: Awaiting destination choice (sheets/docs/both)
        elif delivery_stage == "awaiting_destination_choice":
            print(f"🚚 DELIVERY ORDER DESTINATION: User choosing where to put data")
            
            dest_result = self._handle_destination_choice(user_message, conversation_state)
            if not dest_result["success"]:
                response = dest_result["error"]
            else:
                destination_type = dest_result["destination_type"]
                conversation_state.extracted_info["destination_type"] = destination_type
                
                # Determine next step
                if dest_result["requires_sheet_id"]:
                    conversation_state.extracted_info["delivery_order_stage"] = "awaiting_sheet_id"
                    response = "📊 **Which Google Sheet should I upload the data to?**\n\n"
                    response += "Provide the sheet ID or name (e.g., 'Order-123' or '1a2b3c4d5e6f')"
                    conversation_state.missing_fields = ["sheets_sheet_id"]
                elif dest_result["requires_doc_title"]:
                    conversation_state.extracted_info["delivery_order_stage"] = "awaiting_doc_title"
                    response = "📝 **What should I name the document?**\n\n"
                    response += "E.g., 'Delivery Orders Summary' or 'Order Report Jan 2024'"
                    conversation_state.missing_fields = ["summary_doc_title"]
                else:
                    # Docs only, no sheet needed - show plan
                    response = self._confirm_full_plan(conversation_state, destination_type)
                    conversation_state.extracted_info["delivery_order_stage"] = "confirming_plan"
            
            memory_manager.add_message("assistant", response)
            if auto_save and state_id != "default":
                self.thread_manager.add_message(state_id, "assistant", response)
            self._save_memory_to_state(conversation_state, state_id)
            if auto_save and state_id != "default":
                self._save_thread_to_db(state_id, conversation_state)
            return response, conversation_state
        
        # STAGE 2: Awaiting sheet ID
        elif delivery_stage == "awaiting_sheet_id":
            print(f"🚚 DELIVERY ORDER SHEET_ID: User provided sheet ID")
            
            sheet_id = user_message.strip()
            conversation_state.extracted_info["sheets_sheet_id"] = sheet_id
            
            # Check if also needs doc title
            destination_type = conversation_state.extracted_info.get("destination_type", "sheets")
            if destination_type == "both":
                conversation_state.extracted_info["delivery_order_stage"] = "awaiting_doc_title"
                response = "📝 **What should I name the summary document?**\n\n"
                response += "E.g., 'Delivery Orders Summary' or 'Order Report Jan 2024'"
                conversation_state.missing_fields = ["summary_doc_title"]
            else:
                # Ready to confirm plan
                response = self._confirm_full_plan(conversation_state, destination_type, sheet_id)
                conversation_state.extracted_info["delivery_order_stage"] = "confirming_plan"
            
            memory_manager.add_message("assistant", response)
            if auto_save and state_id != "default":
                self.thread_manager.add_message(state_id, "assistant", response)
            self._save_memory_to_state(conversation_state, state_id)
            if auto_save and state_id != "default":
                self._save_thread_to_db(state_id, conversation_state)
            return response, conversation_state
        
        # STAGE 2.5: Awaiting doc title
        elif delivery_stage == "awaiting_doc_title":
            print(f"🚚 DELIVERY ORDER DOC_TITLE: User provided doc title")
            
            doc_title = user_message.strip()
            conversation_state.extracted_info["summary_doc_title"] = doc_title
            
            destination_type = conversation_state.extracted_info.get("destination_type", "both")
            sheet_id = conversation_state.extracted_info.get("sheets_sheet_id")
            
            # Ready to confirm plan
            response = self._confirm_full_plan(conversation_state, destination_type, sheet_id, doc_title)
            conversation_state.extracted_info["delivery_order_stage"] = "confirming_plan"
            
            memory_manager.add_message("assistant", response)
            if auto_save and state_id != "default":
                self.thread_manager.add_message(state_id, "assistant", response)
            self._save_memory_to_state(conversation_state, state_id)
            if auto_save and state_id != "default":
                self._save_thread_to_db(state_id, conversation_state)
            return response, conversation_state
        
        # STAGE 3: Confirming the full plan
        elif delivery_stage == "confirming_plan":
            print(f"🚚 DELIVERY ORDER CONFIRM: User confirming the plan")
            
            user_lower = user_message.lower().strip()
            if user_lower not in ["yes", "y", "confirm", "proceed"]:
                response = "❌ Plan cancelled. Let me know if you want to try again."
                conversation_state.extracted_info["delivery_order_stage"] = "completed"
            else:
                response = "🔄 Great! Let me extract the contents and show them to you first...\n\n"
                
                # Simulate extraction (in real scenario, would call mapping agent)
                extracted_data = {
                    "rows": [
                        {"Product": "Item 1", "Quantity": "10", "Price": "$100"},
                        {"Product": "Item 2", "Quantity": "5", "Price": "$200"},
                    ]
                }
                
                conversation_state.extracted_info["extracted_data"] = extracted_data
                conversation_state.extracted_info["delivery_order_stage"] = "awaiting_data_confirmation"
                conversation_state.missing_fields = ["data_confirmation"]
                
                response += self._format_extracted_data_for_review(extracted_data, "order.pdf")
            
            memory_manager.add_message("assistant", response)
            if auto_save and state_id != "default":
                self.thread_manager.add_message(state_id, "assistant", response)
            self._save_memory_to_state(conversation_state, state_id)
            if auto_save and state_id != "default":
                self._save_thread_to_db(state_id, conversation_state)
            return response, conversation_state
        
        # STAGE 4: Awaiting data confirmation
        elif delivery_stage == "awaiting_data_confirmation":
            print(f"🚚 DELIVERY ORDER DATA_CHECK: User verifying extracted data")
            
            user_lower = user_message.lower().strip()
            if user_lower not in ["yes", "y", "correct", "looks good"]:
                response = "❌ Data verification refused. Request cancelled."
                conversation_state.extracted_info["delivery_order_stage"] = "completed"
            else:
                response = "✅ **Executing the workflow...**\n\n"
                
                conversation_state.extracted_info["delivery_order_stage"] = "executing"
                destination_type = conversation_state.extracted_info.get("destination_type", "both")
                sheet_id = conversation_state.extracted_info.get("sheets_sheet_id")
                doc_title = conversation_state.extracted_info.get("summary_doc_title")
                
                # Execute the full workflow
                credentials_dict = {}
                execution_result = self._handle_delivery_order_execution(
                    user_message="",  # Not used in this context
                    conversation_state=conversation_state,
                    credentials_dict=credentials_dict,
                    destination_type=destination_type,
                    sheet_id=sheet_id,
                    create_summary_doc=destination_type in ["docs", "both"],
                    summary_doc_title=doc_title
                )
                
                response += self._build_delivery_order_execution_response(execution_result, conversation_state)
            
            memory_manager.add_message("assistant", response)
            if auto_save and state_id != "default":
                self.thread_manager.add_message(state_id, "assistant", response)
            self._save_memory_to_state(conversation_state, state_id)
            if auto_save and state_id != "default":
                self._save_thread_to_db(state_id, conversation_state)
            return response, conversation_state
        
        # === END DELIVERY ORDER ADAPTER ===            # Also store in messages table if this is a persistent thread
            if auto_save and state_id != "default":
                self.thread_manager.add_message(state_id, "assistant", response)
            
            # Save memory state back to conversation_state for persistence
            self._save_memory_to_state(conversation_state, state_id)
            
            # Auto-save to database if requested
            if auto_save and state_id != "default":
                self._save_thread_to_db(state_id, conversation_state)
            
            return response, conversation_state
        
        elif delivery_stage == "awaiting_sheet_confirmation":
            # Stage 2: User provided sheet ID - execute full workflow
            print(f"🚚 DELIVERY ORDER EXECUTION: User confirmed, executing full workflow")
            
            # Get credentials from request context (if available from session)
            credentials_dict = {}  # TODO: Get from session/auth context
            
            # Execute the full workflow
            execution_result = self._handle_delivery_order_execution(
                user_message=user_message,
                conversation_state=conversation_state,
                credentials_dict=credentials_dict
            )
            
            response = self._build_delivery_order_execution_response(execution_result, conversation_state)
            
            # Add response to memory manager
            memory_manager.add_message("assistant", response)
            
            # Also store in messages table if this is a persistent thread
            if auto_save and state_id != "default":
                self.thread_manager.add_message(state_id, "assistant", response)
            
            # Save memory state back to conversation_state for persistence
            self._save_memory_to_state(conversation_state, state_id)
            
            # Auto-save to database if requested
            if auto_save and state_id != "default":
                self._save_thread_to_db(state_id, conversation_state)
            
            return response, conversation_state
        
        # === END DELIVERY ORDER ADAPTER ===
        
        # Continue with standard message analysis for non-delivery-order requests
        analysis = self.analyze_request(user_message, conversation_state, state_id, uploaded_file=uploaded_file)
        
        # Detect compound "cancel + new task" scenario
        # Check if user message has both cancel words AND task keywords
        cancel_keywords = ["cancel", "nevermind", "forget", "stop"]
        task_keywords = ["send", "search", "create", "schedule", "find", "draft", "reply", "add", "edit", "delete", "update"]
        user_lower = user_message.lower()
        
        has_cancel = any(keyword in user_lower for keyword in cancel_keywords)
        has_task = any(keyword in user_lower for keyword in task_keywords)
        is_compound_cancel = has_cancel and has_task and analysis.intent != ConversationIntent.CANCELLED
        
        if is_compound_cancel:
            # User said "cancel X and do Y" in one message
            # Clear old state and ONLY use the new task data from analysis
            print(f"🔄 Compound cancel+task detected - clearing old state, using only new task data")
            conversation_state.extracted_info = {}  # Clear everything first
        
        # Handle cancellation first - clear everything!
        if analysis.intent == ConversationIntent.CANCELLED:
            conversation_state.extracted_info = {}  # ✅ Empty for multi-task scenarios
            conversation_state.missing_fields = []
            conversation_state.clarification_question = None
            conversation_state.ready_for_execution = False
            conversation_state.execution_summary = None
        else:
            # Update extracted information (merge new with existing)
            for key, value in analysis.extracted_info.items():
                if value is not None and value != "":
                    conversation_state.extracted_info[key] = value
            
            # Update other state fields
            conversation_state.missing_fields = analysis.missing_fields
            conversation_state.clarification_question = analysis.clarification_question
            conversation_state.ready_for_execution = analysis.execution_ready
            conversation_state.execution_summary = analysis.execution_summary
        
        # Update state with analysis intent
        conversation_state.intent = analysis.intent
        
        # Print updated conversation state for debugging
        print(f"\n{'='*60}")
        print(f"💬 UPDATED CONVERSATION STATE:")
        print(f"{'='*60}")
        print(f"Intent: {conversation_state.intent}")
        print(f"Task Type: {conversation_state.extracted_info.get('task_type', 'N/A')}")
        print(f"Extracted Info: {json.dumps(conversation_state.extracted_info, indent=2)}")
        print(f"Missing Fields: {conversation_state.missing_fields}")
        print(f"Clarification Question: {conversation_state.clarification_question}")
        print(f"Ready for Execution: {conversation_state.ready_for_execution}")
        print(f"Execution Summary: {conversation_state.execution_summary}")
        print(f"{'='*60}\n")
    # In case of compound cancel detected, we should proceed with the task and if cancel only just return response that cancelle just fine.
        if analysis.intent == ConversationIntent.TEMPLATE_UPLOAD:
            if analysis.execution_ready:
                response = f"✅ **Ready to process template!**\n\n"
                response += f"**File:** {analysis.extracted_info.get('uploaded_file', {}).get('filename')}\n"
                if analysis.extracted_info.get('save_to_drive'):
                    response += f"**Template name:** {analysis.extracted_info.get('template_name')}\n"
                response += f"**Document title:** {analysis.extracted_info.get('document_title')}\n\n"
                response += f"I'll upload the template to your Drive and create the document now."
        else:
            response = analysis.clarification_question or "Please provide more details."
    
        # Generate response based on intent
        if analysis.intent == ConversationIntent.SMALL_TALK:
            # Check if this is a cancellation
            if analysis.task_type == "cancellation":
                response = "👍 No problem! Request cancelled. Let me know if you need anything else."
            else:
                response = "I'm here to help you manage your emails, calendar, and documents. What would you like me to do?"
            # ------- Can improve small_talk response into not being static later -------

        elif analysis.intent == ConversationIntent.CANCELLED:
            response = "👍 No problem! Request cancelled.\n\n"
            
            # Extract cancelled info from reasoning field for user feedback
            # reasoning format: "User cancelled request. Previous data: {...}"
            #  ----  CHECK THIS ONE AS WELL. I DON'T UNDERSTAND BUT I THINK THIS WILL CAUSE BUGS ----
            if "Previous data:" in analysis.reasoning:
                try:
                    # Extract the dict from reasoning string
                    match = re.search(r"Previous data: ({.*})", analysis.reasoning)
                    if match:
                        cancelled_info = eval(match.group(1))  # Safe here since we created it
                        if cancelled_info:
                            response += "**Cancelled request:**\n"
                            for key, value in cancelled_info.items():
                                if key != "task_type":  # Don't show internal task_type
                                    response += f"- {key}: {value}\n"
                            response += "\n"
                except:
                    pass  # If parsing fails, just show generic message
            
            response += "What would you like to do next?"
        
        elif analysis.intent == ConversationIntent.NOT_FEASIBLE:
            response = f"❌ I'm unable to help with that request.\n\n"
            response += f"**Reason:** {analysis.reasoning}\n\n"
            if analysis.suggested_alternatives:
                response += "**What I can do instead:**\n"
                for alt in analysis.suggested_alternatives:
                    response += f"- {alt}\n"
            response += f"\n**Available capabilities:**\n{self.capabilities_summary}"
        
        elif analysis.intent == ConversationIntent.TOO_COMPLEX:
            response = f"⚠️ This task seems quite complex.\n\n"
            response += f"**Analysis:** {analysis.reasoning}\n\n"
            if analysis.suggested_alternatives:
                response += "**I suggest breaking it down:**\n"
                for i, alt in enumerate(analysis.suggested_alternatives, 1):
                    response += f"{i}. {alt}\n"
            response += f"\nWould you like to proceed with one of these approaches?"

        # IMPROVE CLARIFICATION RESPONSE  OR TO BE MORE DYNAMIC LATER
        elif analysis.intent == ConversationIntent.NEEDS_CLARIFICATION:
            response = f"📋 {analysis.clarification_question}\n\n"
            if analysis.extracted_info:
                response += "**So far I have:**\n"
                for key, value in analysis.extracted_info.items():
                    response += f"- {key}: {value}\n"
        
        elif analysis.intent == ConversationIntent.READY_TO_EXECUTE:
            response = f"✅ **Ready to execute!**\n\n"
            response += f"**Task:** {analysis.execution_summary}\n\n"
            response += "**Details:**\n"
            for key, value in analysis.extracted_info.items():
                response += f"- {key}: {value}\n"

        else:
            response = "I'm processing your request..."
        
        # Add assistant response to memory manager
        memory_manager.add_message("assistant", response)
        
        # Also store in messages table if this is a persistent thread
        if auto_save and state_id != "default":
            self.thread_manager.add_message(state_id, "assistant", response)
        
        # Save memory state back to conversation_state for persistence
        self._save_memory_to_state(conversation_state, state_id)
        
        # Auto-save to database if requested (for thread mode)
        if auto_save and state_id != "default":
            self._save_thread_to_db(state_id, conversation_state)
        
        return response, conversation_state
    
    def should_execute(self, conversation_state: ConversationState) -> bool:
        """Check if conversation is ready for execution"""
        return conversation_state.ready_for_execution
    
    def get_memory_stats(self, conversation_state: ConversationState, state_id: str = "default") -> Dict[str, Any]:
        """
        Get memory statistics for debugging and monitoring.
        
        Args:
            conversation_state: Current conversation state
            state_id: Conversation identifier
            
        Returns:
            Dictionary with memory stats
        """
        memory_manager = self._get_memory_manager(state_id, conversation_state.memory_state)
        return memory_manager.get_stats()
    
    def build_supervisor_input(self, conversation_state: ConversationState) -> str:
        """
        Build a complete, well-formed input for the supervisor agent.
        Includes both execution_summary and extracted_info for comprehensive planning.
    
        Args:
            conversation_state: Current conversation state
        
        Returns:
            Clean input string for supervisor with task description and parameters
        """
    # Get execution summary (with fallback)
        if not conversation_state.execution_summary:
        # Fallback: reconstruct from extracted info
            info = conversation_state.extracted_info
            task_type = info.get("task_type", "task")
        
        # Handle template upload
            if task_type == "template_upload":
                uploaded_file = info.get("uploaded_file", {})
                filename = uploaded_file.get("filename", "template")
            
                if info.get("save_to_drive"):
                    execution_summary = f"Upload template '{info.get('template_name', filename)}' to Google Drive Templates folder and create document '{info.get('document_title')}' from it"
                else:
                    execution_summary = f"Create document '{info.get('document_title')}' from uploaded template '{filename}'"
            else:
            # Build sentence from extracted info for other task types
                parts = []
                for key, value in info.items():
                    if key != "task_type":
                        parts.append(f"{key}: {value}")
            
                execution_summary = f"{task_type} with " + ", ".join(parts)
        else:
        # Use existing execution summary
            execution_summary = conversation_state.execution_summary
    
    # Build comprehensive input with both summary and detailed parameters
        supervisor_input = execution_summary
    
    # Add extracted_info as structured parameters if available
        if conversation_state.extracted_info:
            supervisor_input += "\n\nParameters:\n"
            for key, value in conversation_state.extracted_info.items():
            # ✅ FIX: Special handling for uploaded_file
                if key == "uploaded_file" and isinstance(value, dict):
                    supervisor_input += f"- uploaded_file:\n"
                    supervisor_input += f"  - filename: {value.get('filename')}\n"
                    supervisor_input += f"  - temp_path: {value.get('temp_path')}\n"
                    supervisor_input += f"  - size: {value.get('size')} bytes\n"
                    supervisor_input += f"  - mime_type: {value.get('mime_type')}\n"
                elif isinstance(value, (list, dict)):
                    value_str = json.dumps(value, indent=2)
                    supervisor_input += f"- {key}: {value_str}\n"
                else:
                    supervisor_input += f"- {key}: {value}\n"
                    
        return supervisor_input
    
    def _filter_context_for_user(self, final_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Filter final_context to remove technical/internal fields that users don't care about.
        Keeps only user-relevant information for cleaner, faster summarization.
        
        Args:
            final_context: Raw final_context from orchestrator
            
        Returns:
            Filtered context with only user-relevant fields
        """
        # Fields to ALWAYS exclude (technical IDs, internal metadata)
        EXCLUDED_FIELDS = {
            # IDs and technical identifiers
            "message_id", "thread_id", "draft_id", "attachment_id", "document_id",
            "conversation_id", "session_id", "request_id", "transaction_id",
            
            # Timestamps and internal dates
            "internal_date", "created_at", "updated_at", "timestamp", "last_modified",
            
            # System/API fields
            "success", "error", "status_code", "api_version", "request_time",
            
            # Date context (already known by user)
            "today_date", "yesterday_date", "current_year", "current_month", "current_day",
            
            # HTML/technical content
            "body_html", "body_clean", "raw_content", "encoded_data", "body",  # Full body is too verbose
            
            # Internal flags
            "is_draft", "is_sent", "is_read", "has_attachments", "body_has_tables",
            
            # Duplicate data
            "latest_email", "first_email",  # Redundant if emails array exists
            
            # Query details (user already knows what they asked)
            "query",
        }
        
        # Fields to KEEP if they contain meaningful data (whitelist approach)
        MEANINGFUL_FIELDS = {
            # Communication content
            "subject", "body", "from", "to", "cc", "bcc", "reply_to",
            
            # Document/file info
            "title", "filename", "file_size", "document_url", "file_path",
            
            # Lists of items (but will be summarized)
            "emails", "documents", "files", "events", "drafts",
            
            # Counts and summaries
            "count", "total", "found", "created", "sent",
            
            # Action results
            "label_added", "label_removed", "action_taken",
            
            # Links (useful for user)
            "body_links", "attachments",
            
            # Extracted metadata
            "action_items", "placeholders", "template_info",
        }
        
        filtered = {}
        
        for key, value in final_context.items():
            # Skip if in excluded list
            if key in EXCLUDED_FIELDS:
                continue
            
            # Handle list values (like emails, documents)
            if isinstance(value, list):
                if key in MEANINGFUL_FIELDS:
                    # For email/document arrays, keep only essential fields from each item
                    if len(value) > 0 and isinstance(value[0], dict):
                        filtered_items = []
                        for item in value:
                            filtered_item = self._filter_context_for_user(item)  # Recursive
                            if filtered_item:  # Only add if non-empty
                                filtered_items.append(filtered_item)
                        
                        if filtered_items:
                            # Limit to first 5 items to prevent overwhelming summary
                            filtered[key] = filtered_items[:5]
                            if len(value) > 5:
                                filtered[f"{key}_total_count"] = len(value)
                    else:
                        # Simple list (not objects), keep as-is if meaningful
                        filtered[key] = value
            
            # Handle dict values (nested objects)
            elif isinstance(value, dict):
                filtered_nested = self._filter_context_for_user(value)  # Recursive
                if filtered_nested:
                    filtered[key] = filtered_nested
            
            # Handle primitive values (strings, numbers, booleans)
            else:
                if key in MEANINGFUL_FIELDS:
                    filtered[key] = value
                # Also keep any custom fields not in excluded list
                elif key not in EXCLUDED_FIELDS:
                    # Only keep if value is meaningful (not empty string, not None)
                    if value is not None and value != "":
                        filtered[key] = value
        
        return filtered
    
    def summarize_execution(
        self,
        conversation_state: ConversationState,
        final_context: Dict[str, Any],
        execution_status: str,
        execution_message: str
    ) -> str:
        """
        Generate a human-friendly summary of the execution results.
        
        For SUCCESS: Uses LLM to generate natural summary with actual data.
        For ERRORS: Uses structured templates (no LLM needed - saves tokens).
        
        Args:
            conversation_state: Current conversation state
            final_context: The final_context from orchestrator (all variables)
            execution_status: Status of execution (success, error, no_results, etc.)
            execution_message: Raw execution message
            
        Returns:
            Human-friendly summary for the user
        """
        
        # Get original request for context
        original_request = conversation_state.extracted_info.get("original_message", "your request")
        if not original_request or original_request == "your request":
            original_request = conversation_state.execution_summary or "your request"
        
        # =====================================================================
        # FAST PATH: Handle errors WITHOUT LLM (saves tokens, faster response)
        # =====================================================================
        
        # Check for error conditions in final_context
        stopped_at_step = final_context.get("stopped_at_step")
        error_in_context = final_context.get("error")
        results = final_context.get("results", [])
        
        # Determine if this is an error case
        is_error = (
            execution_status == "error" or 
            stopped_at_step is not None or 
            error_in_context is not None
        )
        
        # Check for no_results (valid operation but empty data)
        has_no_results = any(
            r.get("status") == "no_results" for r in results if isinstance(r, dict)
        )
        
        if is_error:
            return self._format_error_response(
                original_request=original_request,
                execution_message=execution_message,
                final_context=final_context,
                results=results,
                stopped_at_step=stopped_at_step
            )
        
        # Check if all steps were no_results (nothing found but not an error)
        if has_no_results and not any(r.get("status") == "success" for r in results if isinstance(r, dict)):
            return self._format_no_results_response(
                original_request=original_request,
                results=results
            )
        
        # =====================================================================
        # SUCCESS PATH: Use LLM for rich summary
        # =====================================================================
        
        # FILTER: Remove technical fields user doesn't care about
        user_relevant_context = self._filter_context_for_user(final_context)
        
        print(f"📊 Context filtering:")
        print(f"   Before: {len(final_context)} fields, {len(json.dumps(final_context))} chars")
        print(f"   After: {len(user_relevant_context)} fields, {len(json.dumps(user_relevant_context))} chars")
        
        # Build READABLE context with actual content
        context_text = self._build_readable_context(user_relevant_context)
        
        print(f"\n📝 Generating user-friendly summary...")
        print(f"📊 Context for LLM ({len(context_text)} chars):\n{context_text[:500]}...\n")
        
        system_prompt = f"""You are a concise AI assistant summarizing task results.

RULES:
1. Start with outcome: ✅ success or ❌ failed
2. Use ACTUAL DATA from context (names, subjects, dates - NOT "email data")
3. NEVER say: "variables", "fields available", "data includes"
4. Be SPECIFIC: "Found email from Mike about Rovo AI sent yesterday"

Use the ACTUAL content below, not generic descriptions."""

        user_prompt = f"""Task: {original_request}
Status: {execution_status}
Message: {execution_message}

Context (use ACTUAL values below):
{context_text}

Summarize the results using specific data"""

        try:
            # === TOKEN TRACKING: Result Summarization ===
            start_time = time.time()
            llm_response = self.llm.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                config={"timeout": 30}
            )
            duration_ms = (time.time() - start_time) * 1000
            
            # Extract token usage from response
            input_tokens = 0
            output_tokens = 0
            if hasattr(llm_response, 'response_metadata'):
                token_usage = llm_response.response_metadata.get('token_usage', {})
                input_tokens = token_usage.get('prompt_tokens', (len(system_prompt) + len(user_prompt)) // 4)
                output_tokens = token_usage.get('completion_tokens', len(llm_response.content) // 4)
            else:
                input_tokens = (len(system_prompt) + len(user_prompt)) // 4
                output_tokens = len(llm_response.content) // 4
            
            # Log the LLM call with token tracking
            logger.llm_call(
                model=self.llm.model_name if hasattr(self.llm, 'model_name') else "gpt-4o",
                operation="result_summarization",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
                tier="post",
                prompt_summary=f"Summarizing: {original_request[:50]}...",
                success=True
            )
            
            summary = llm_response.content.strip()
            return summary
            
        except Exception as e:
            # Check if this is an LLM service error (rate limit, quota, etc.)
            if is_llm_error(e):
                print(f"❌ LLM service error in result summarization: {e}")
                # Log the failed LLM call
                logger.llm_call(
                    model=self.llm.model_name if hasattr(self.llm, 'model_name') else "gpt-4o",
                    operation="result_summarization",
                    input_tokens=(len(system_prompt) + len(user_prompt)) // 4,
                    output_tokens=0,
                    duration_ms=0,
                    tier="post",
                    prompt_summary=f"Summarizing: {original_request[:50]}...",
                    success=False,
                    error=str(e)
                )
                raise handle_llm_error(e)
            
            # Log the failed LLM call
            logger.llm_call(
                model=self.llm.model_name if hasattr(self.llm, 'model_name') else "gpt-4o",
                operation="result_summarization",
                input_tokens=(len(system_prompt) + len(user_prompt)) // 4,
                output_tokens=0,
                duration_ms=0,
                tier="post",
                prompt_summary=f"Summarizing: {original_request[:50]}...",
                success=False,
                error=str(e)
            )
            # Fallback to simple summary if LLM fails
            print(f"⚠️ Failed to generate LLM summary: {e}")
            return f"✅ Successfully completed: {original_request}\n\nResults:\n{context_text}"
    
    def _build_readable_context(self, user_relevant_context: Dict[str, Any]) -> str:
        """Build readable context text from filtered context."""
        context_lines = []
        
        for key, value in user_relevant_context.items():
            # For arrays of objects (emails, documents, etc.)
            if isinstance(value, list) and len(value) > 0:
                if isinstance(value[0], dict):
                    # Show FIRST ITEM with actual content
                    first_item = value[0]
                    context_lines.append(f"\n{key} (found {len(value)}):")
                    
                    # Extract key user-facing fields with actual values
                    for item_key, item_value in first_item.items():
                        # Truncate long values
                        if isinstance(item_value, str) and len(item_value) > 150:
                            item_value = item_value[:150] + "..."
                        context_lines.append(f"  • {item_key}: {item_value}")
                    
                    # If multiple items, show count
                    if len(value) > 1:
                        context_lines.append(f"  (+ {len(value) - 1} more)")
                else:
                    # Simple array (strings, numbers)
                    context_lines.append(f"{key}: {value}")
            
            # For single objects
            elif isinstance(value, dict):
                context_lines.append(f"\n{key}:")
                for sub_key, sub_value in value.items():
                    if isinstance(sub_value, str) and len(sub_value) > 150:
                        sub_value = sub_value[:150] + "..."
                    context_lines.append(f"  • {sub_key}: {sub_value}")
            
            # For primitives (count, total, etc.)
            else:
                context_lines.append(f"{key}: {value}")
        
        return "\n".join(context_lines) if context_lines else "No data returned"
    
    def _format_error_response(
        self,
        original_request: str,
        execution_message: str,
        final_context: Dict[str, Any],
        results: List[Dict],
        stopped_at_step: Optional[int]
    ) -> str:
        """
        Format a user-friendly error response WITHOUT using LLM.
        This saves tokens and provides faster, more consistent error messages.
        """
        lines = ["❌ **Unable to complete your request**\n"]
        
        # Identify the error type and provide specific message
        error_msg = final_context.get("error", execution_message)
        
        # Categorize the error for better user messaging
        error_category = self._categorize_error(error_msg)
        
        # Add error explanation based on category
        if error_category == "auth":
            lines.append("**Issue:** Authentication failed with the service.")
            lines.append("**Suggestion:** Your access may have expired. Please try reconnecting your account.\n")
        elif error_category == "not_found":
            lines.append("**Issue:** The requested resource could not be found.")
            lines.append("**Suggestion:** Please verify the ID or name and try again.\n")
        elif error_category == "timeout":
            lines.append("**Issue:** The operation took too long to complete.")
            lines.append("**Suggestion:** The service may be busy. Please try again in a moment.\n")
        elif error_category == "connection":
            lines.append("**Issue:** Could not connect to the required service.")
            lines.append("**Suggestion:** Please check if all services are running and try again.\n")
        elif error_category == "permission":
            lines.append("**Issue:** You don't have permission to perform this action.")
            lines.append("**Suggestion:** Please verify your access rights or contact your administrator.\n")
        elif error_category == "rate_limit":
            lines.append("**Issue:** Too many requests were made in a short time.")
            lines.append("**Suggestion:** Please wait a moment and try again.\n")
        else:
            lines.append(f"**Issue:** {error_msg}\n")
        
        # Show what was completed (if any steps succeeded)
        successful_steps = [r for r in results if isinstance(r, dict) and r.get("status") == "success"]
        if successful_steps:
            lines.append("---")
            lines.append("**What was completed before the error:**")
            for step in successful_steps:
                desc = step.get("description", step.get("tool", "Unknown step"))
                lines.append(f"  ✅ {desc}")
            lines.append("")
        
        # Show where it failed
        if stopped_at_step:
            failed_step = next((r for r in results if isinstance(r, dict) and r.get("step") == stopped_at_step), None)
            if failed_step:
                lines.append(f"**Failed at step {stopped_at_step}:** {failed_step.get('description', failed_step.get('tool', 'Unknown'))}")
        
        # Add helpful context if available
        lines.append("\n---")
        lines.append(f"*Original request: \"{original_request[:100]}{'...' if len(original_request) > 100 else ''}\"*")
        
        return "\n".join(lines)
    
    def _format_no_results_response(
        self,
        original_request: str,
        results: List[Dict]
    ) -> str:
        """
        Format a user-friendly response when operations succeeded but found no data.
        Does NOT use LLM - provides consistent, fast response.
        """
        lines = ["ℹ️ **Search completed - No results found**\n"]
        
        # Extract what was searched for from the results
        for result in results:
            if isinstance(result, dict) and result.get("status") == "no_results":
                tool = result.get("tool", "")
                inputs = result.get("inputs", {})
                message = result.get("message", "")
                
                # Provide context-aware suggestions
                if "email" in tool.lower() or "gmail" in tool.lower():
                    query = inputs.get("query", inputs.get("search_query", ""))
                    lines.append(f"No emails were found matching your search criteria.")
                    if query:
                        lines.append(f"  • Search query: `{query}`")
                    lines.append("\n**Suggestions:**")
                    lines.append("  • Try broadening your search terms")
                    lines.append("  • Check the date range if specified")
                    lines.append("  • Verify the sender's email address spelling")
                
                elif "calendar" in tool.lower() or "event" in tool.lower():
                    lines.append(f"No calendar events were found matching your criteria.")
                    lines.append("\n**Suggestions:**")
                    lines.append("  • Try expanding the date range")
                    lines.append("  • Check if the calendar is shared with you")
                
                elif "doc" in tool.lower() or "drive" in tool.lower():
                    lines.append(f"No documents were found matching your search.")
                    lines.append("\n**Suggestions:**")
                    lines.append("  • Try different keywords")
                    lines.append("  • Check the folder location")
                    lines.append("  • Verify you have access to the files")
                
                else:
                    lines.append(f"The operation completed but returned no data.")
                    if message:
                        lines.append(f"  • Details: {message}")
        
        lines.append("\n---")
        lines.append(f"*Original request: \"{original_request[:100]}{'...' if len(original_request) > 100 else ''}\"*")
        
        return "\n".join(lines)
    
    def _categorize_error(self, error_msg: str) -> str:
        """Categorize error message for appropriate user response."""
        error_lower = error_msg.lower()
        
        if any(term in error_lower for term in ["auth", "token", "credential", "unauthorized", "401", "403"]):
            return "auth"
        elif any(term in error_lower for term in ["not found", "404", "does not exist", "invalid id"]):
            return "not_found"
        elif any(term in error_lower for term in ["timeout", "timed out", "too long"]):
            return "timeout"
        elif any(term in error_lower for term in ["connection", "refused", "unreachable", "network", "503"]):
            return "connection"
        elif any(term in error_lower for term in ["permission", "denied", "forbidden", "access"]):
            return "permission"
        elif any(term in error_lower for term in ["rate limit", "429", "too many requests", "quota"]):
            return "rate_limit"
        else:
            return "unknown"
    
    # =============================================================================
    # THREAD MANAGEMENT METHODS
    # =============================================================================
    
    def create_new_thread(
        self, 
        user_id: str, 
        initial_message: Optional[str] = None,
        title: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> tuple[str, ConversationState, Optional[str]]:
        """
        Create a new conversation thread with persistent storage.
        
        Args:
            user_id: Unique identifier for the user
            initial_message: Optional first message to process
            title: Optional custom title (will be auto-generated if not provided)
            tags: Optional tags for categorization
            
        Returns:
            Tuple of (thread_id, initial_conversation_state, bot_response)
            bot_response is None if no initial_message provided
        """
        # Create thread in database
        thread_metadata = self.thread_manager.create_thread(
            user_id=user_id,
            title=title,  # Will be auto-generated if None
            tags=tags or []
        )
        thread_id = thread_metadata.thread_id
        
        # Initialize conversation state
        conversation_state = ConversationState()
        bot_response = None
        
        # Process initial message if provided
        if initial_message:
            bot_response, conversation_state = self.process_message(
                user_message=initial_message,
                conversation_state=conversation_state,
                state_id=thread_id,  # Use thread_id as state_id for consistency
                auto_save=True  # Auto-save to database
            )
            
            # Auto-generate title from first message if not provided
            if not title:
                new_title = self.thread_manager.auto_generate_title(initial_message)
                self.thread_manager.update_thread(thread_id, title=new_title)
        else:
            # Save initial empty state
            self._save_thread_to_db(thread_id, conversation_state)
        
        print(f"✅ Created new thread: {thread_id} for user: {user_id}")
        
        return thread_id, conversation_state, bot_response
    
    def continue_thread(
        self,
        thread_id: str,
        new_message: str
    ) -> tuple[str, ConversationState]:
        """
        Continue an existing conversation thread.
        
        Args:
            thread_id: Thread identifier
            new_message: New user message to process
            
        Returns:
            Tuple of (response, updated_conversation_state)
        """
        # Load thread state from database
        conversation_state = self._load_thread_from_db(thread_id)
        
        if conversation_state is None:
            raise ValueError(f"Thread {thread_id} not found")
        
        # Process the new message with auto-save enabled
        response, conversation_state = self.process_message(
            user_message=new_message,
            conversation_state=conversation_state,
            state_id=thread_id,  # Use thread_id as state_id
            auto_save=True  # Auto-save to database
        )
        
        return response, conversation_state
    
    def list_user_threads(
        self,
        user_id: str,
        status: Optional[str] = "active",
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        List all threads for a user.
        
        Args:
            user_id: User identifier
            status: Filter by status (active, archived, all)
            limit: Maximum number of threads to return
            offset: Offset for pagination
            
        Returns:
            List of thread metadata dictionaries
        """
        threads = self.thread_manager.list_threads(
            user_id=user_id,
            status=status,
            limit=limit,
            offset=offset
        )
        
        # Pydantic v2
        return [thread.model_dump() for thread in threads]
    
    def get_thread_metadata(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a specific thread.
        
        Args:
            thread_id: Thread identifier
            
        Returns:
            Thread metadata dictionary or None if not found
        """
        thread = self.thread_manager.get_thread(thread_id)
        if not thread:
            return None
        
        # Pydantic v2
        return thread.model_dump()
    
    def get_thread_messages(
        self,
        thread_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get full conversation history from messages table.
        
        Args:
            thread_id: Thread identifier
            limit: Maximum messages to return (default: 50)
            offset: Pagination offset (default: 0)
            
        Returns:
            List of message dictionaries with role, content, and created_at
        """
        # Get messages from database table (not memory_states)
        messages = self.thread_manager.get_messages(thread_id, limit=limit, offset=offset)
        
        if messages is None:
            return None
        
        return messages
    
    def update_thread_metadata(
        self,
        thread_id: str,
        title: Optional[str] = None,
        tags: Optional[List[str]] = None,
        status: Optional[str] = None
    ) -> bool:
        """
        Update thread metadata.
        
        Args:
            thread_id: Thread identifier
            title: New title (optional)
            tags: New tags (optional)
            status: New status (optional)
            
        Returns:
            True if successful, False otherwise
        """
        return self.thread_manager.update_thread(
            thread_id=thread_id,
            title=title,
            tags=tags,
            status=status
        )
    
    def archive_thread(self, thread_id: str) -> bool:
        """
        Archive a thread (soft delete).
        
        Args:
            thread_id: Thread identifier
            
        Returns:
            True if successful, False otherwise
        """
        return self.thread_manager.archive_thread(thread_id)
    
    def delete_thread(self, thread_id: str, hard_delete: bool = False) -> bool:
        """
        Delete a thread.
        
        Args:
            thread_id: Thread identifier
            hard_delete: If True, permanently delete. If False, archive only.
            
        Returns:
            True if successful, False otherwise
        """
        if hard_delete:
            return self.thread_manager.delete_thread(thread_id, hard_delete=True)
        else:
            return self.archive_thread(thread_id)
    
    def search_threads(
        self,
        user_id: str,
        query: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Search user's threads by title.
        
        Args:
            user_id: User identifier
            query: Search query
            limit: Maximum results
            
        Returns:
            List of matching thread metadata
        """
        threads = self.thread_manager.search_threads(
            user_id=user_id,
            query=query,
            limit=limit
        )
        
        # Pydantic v2
        return [thread.model_dump() for thread in threads]
    
    def _save_thread_to_db(self, thread_id: str, conversation_state: ConversationState) -> None:
        """
        Save conversation state and memory to database.
        
        Args:
            thread_id: Thread identifier
            conversation_state: Current conversation state
        """
        # Save conversation state
        self.thread_manager.save_thread_state(thread_id, conversation_state)
        
        # Save memory state if memory manager exists
        if thread_id in self.memory_managers:
            memory_data = self.memory_managers[thread_id].export_memory()
            self.thread_manager.save_memory_state(thread_id, memory_data)
            
            # Update thread message count
            message_count = len(memory_data.get("raw_history", []))
            
            # Update last message preview
            raw_history = memory_data.get("raw_history", [])
            last_message_preview = None
            if raw_history:
                last_msg = raw_history[-1]
                content = last_msg.get("content", "")
                # Truncate to 100 chars
                last_message_preview = content[:100] + "..." if len(content) > 100 else content
            
            self.thread_manager.update_thread(
                thread_id=thread_id,
                message_count=message_count,
                last_message_preview=last_message_preview
            )
    
    def _load_thread_from_db(self, thread_id: str) -> Optional[ConversationState]:
        """
        Load conversation state and memory from database.
        
        Args:
            thread_id: Thread identifier
            
        Returns:
            ConversationState or None if not found
        """
        # Load conversation state
        state_data = self.thread_manager.load_thread_state(thread_id)
        
        if state_data is None:
            return None
        
        # Reconstruct ConversationState from dict
        conversation_state = ConversationState(**state_data)
        
        # Load memory state
        memory_data = self.thread_manager.load_memory_state(thread_id)
        
        if memory_data:
            # Store memory data in conversation state
            conversation_state.memory_state = memory_data
            
            # Initialize memory manager with loaded data
            self._get_memory_manager(thread_id, memory_data)
        
        return conversation_state


# Example usage and testing
if __name__ == "__main__":
    # Initialize agent
    agent = ConversationalAgent(
        openai_api_key=os.getenv("OPENAI_API_KEY", "your-key-here")
    )
    
    # Test scenarios
    print("="*60)
    print("SCENARIO 1: Incomplete email request")
    print("="*60)
    response, state = agent.process_message(
        "Send an email about the meeting tomorrow"
    )
    print(f"Bot: {response}\n")
    print(f"Ready to execute: {agent.should_execute(state)}\n")
    
    print("="*60)
    print("SCENARIO 2: User provides recipient")
    print("="*60)
    response, state = agent.process_message(
        "Send it to john@example.com",
        conversation_state=state
    )
    print(f"Bot: {response}\n")
    print(f"Ready to execute: {agent.should_execute(state)}\n")
    
    if agent.should_execute(state):
        supervisor_input = agent.build_supervisor_input(state)
        print(f"Supervisor Input: {supervisor_input}\n")
    
    print("="*60)
    print("SCENARIO 3: Infeasible task")
    print("="*60)
    response, state = agent.process_message(
        "Book a flight to Paris for next week"
    )
    print(f"Bot: {response}\n")
    
    print("="*60)
    print("SCENARIO 4: Complex task")
    print("="*60)
    response, state = agent.process_message(
        "Find all emails from last month, summarize them, create a report, and send it to my team"
    )
    print(f"Bot: {response}\n")
