"""
Conversational Agent - Pre-Supervisor Validation & Clarification Layer

This agent sits BEFORE the supervisor and handles:
1. Validating if user request has all necessary information
2. Asking clarification questions
3. Checking if task is feasible with available tools
4. Managing multi-turn conversations
5. Suggesting alternatives for complex tasks
"""

from langchain_openai import ChatOpenAI
from typing import Optional, List, Dict, Any
import json
import os
import re
import time
import httpx

# Import shared data models
from models import ConversationIntent, ConversationState, ConversationAnalysis

# Import agent capabilities for feasibility checking
from agent_capabilities_v2 import agent_capabilities

# Import utility functions for agent filtering
from utils import identify_relevant_agents, get_filtered_capabilities

# Import LLM error handler for unified error handling
from llm_error_handler import handle_llm_error, LLMServiceException, is_llm_error

# Import execution trace logger
from execution_logger import trace

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

# Import Tier 0 pattern-based checks mixin
from checks import Tier0ChecksMixin

# Import services
from services.thread_service import ThreadService
from services.delivery_order_service import DeliveryOrderService
from services.summarization_service import SummarizationService


class ConversationalAgent(Tier0ChecksMixin):
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
        
        # Thread service for thread CRUD operations (delegates to thread_manager + memory)
        self.thread_service = ThreadService(
            thread_manager=self.thread_manager,
            memory_managers=self.memory_managers,
            process_message_fn=self.process_message,
            get_memory_manager_fn=self._get_memory_manager,
        )
        
        # Delivery order workflow service
        self.delivery_order_service = DeliveryOrderService()
        
        # Summarization service for post-execution result summaries
        self.summarization_service = SummarizationService(llm=self.llm)

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
        
        # 1. Get or create memory manager for this conversation
        memory_manager = self._get_memory_manager(state_id, conversation_state.memory_state if conversation_state else None)
        
        # Add user message to memory manager (automatically handles summarization)
        memory_manager.add_message("user", user_message)
        
        # Also store in messages table if this is a persistent thread
        if auto_save and state_id != "default":
            self.thread_manager.add_message(state_id, "user", user_message)
        
        # Initialize conversation state if new
        if conversation_state is None:
            conversation_state = ConversationState()
        
        # === DELIVERY ORDER ADAPTER ===
        def _finalize_delivery(response: str, state: ConversationState) -> tuple[str, ConversationState]:
            """Save state & return — shared epilogue for every delivery stage."""
            memory_manager.add_message("assistant", response)
            if auto_save and state_id != "default":
                self.thread_manager.add_message(state_id, "assistant", response)
            self._save_memory_to_state(state, state_id)
            if auto_save and state_id != "default":
                self.thread_service.save_thread_to_db(state_id, state)
            return response, state

        delivery_result = self.delivery_order_service.route_delivery_stage(
            user_message, conversation_state, _finalize_delivery
        )
        if delivery_result is not None:
            return delivery_result
        # === END DELIVERY ORDER ADAPTER ===
        
        # Continue with standard message analysis for non-delivery-order requests
        analysis = self.analyze_request(user_message, conversation_state, state_id, uploaded_file=uploaded_file)

        trace.analysis_result(
            intent=str(analysis.intent) if hasattr(analysis, 'intent') else "unknown",
            ready=analysis.execution_ready if hasattr(analysis, 'execution_ready') else False,
            missing_fields=analysis.missing_fields if hasattr(analysis, 'missing_fields') else []
        )

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
            elif analysis.clarification_question:
                # Use the pre-built response from Tier 0 checks (greetings, help, capabilities, etc.)
                response = analysis.clarification_question
            else:
                response = "I'm here to help you manage your emails, documents, spreadsheets, calendar, and Drive. What would you like me to do?"

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
            response += f"\n**Available capabilities:**\n{self.full_capabilities_summary}"
        
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
            self.thread_service.save_thread_to_db(state_id, conversation_state)
        
        return response, conversation_state
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
                raise LLMServiceException(handle_llm_error(llm_error))
            
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
        
    def _build_capabilities_summary(self, agent_names: Optional[List[str]] = None) -> str:
        """
        Build comprehensive summary of available tools with their required arguments.
        NOW INCLUDES workflow documentation for multi-step operations.

        Args:
            agent_names: Optional list of agent names to include. If None, includes all agents.

        Returns:
            Formatted string with capabilities
        """
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

            # Add workflow documentation ONCE per agent (not per tool)
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
    # TIER 0: Pattern-based checks moved to checks/tier0_checks.py (Tier0ChecksMixin)
    # Methods: _quick_greeting_check, _quick_repeat_check, 
    #          _quick_capability_list_check, _quick_examples_check,
    #          _quick_help_check, _quick_status_check
    # =============================================================================

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
                raise LLMServiceException(handle_llm_error(e))
            
            print(f"⚠️ Unified quick check failed: {e}, falling back to full analysis")
            return None, "specific"  # Fallback: default to specific
        
        # Default: proceed to full analysis
        return None, "specific"  # Fallback: default to specific
    
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
        if not conversation_state.execution_summary:
            info = conversation_state.extracted_info
            task_type = info.get("task_type", "task")

            if task_type == "template_upload":
                uploaded_file = info.get("uploaded_file", {})
                filename = uploaded_file.get("filename", "template")

                if info.get("save_to_drive"):
                    execution_summary = f"Upload template '{info.get('template_name', filename)}' to Google Drive Templates folder and create document '{info.get('document_title')}' from it"
                else:
                    execution_summary = f"Create document '{info.get('document_title')}' from uploaded template '{filename}'"
            else:
                parts = []
                for key, value in info.items():
                    if key != "task_type":
                        parts.append(f"{key}: {value}")
                execution_summary = f"{task_type} with " + ", ".join(parts)
        else:
            execution_summary = conversation_state.execution_summary

        supervisor_input = execution_summary

        if conversation_state.extracted_info:
            supervisor_input += "\n\nParameters:\n"
            for key, value in conversation_state.extracted_info.items():
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
