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

# Import agent capabilities for feasibility checking
from agent_capabilities import agent_capabilities


class ConversationIntent(str, Enum):
    """Intent classification for conversation state"""
    NEEDS_CLARIFICATION = "needs_clarification"  # Missing info, ask user
    NOT_FEASIBLE = "not_feasible"  # Can't do with current tools
    TOO_COMPLEX = "too_complex"  # Task needs breaking down
    READY_TO_EXECUTE = "ready_to_execute"  # All info present, proceed
    SMALL_TALK = "small_talk"  # Not a task request


class ConversationState(BaseModel):
    """Tracks conversation history and extracted information"""
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
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
    
    def __init__(self, openai_api_key: str, model: str = "gpt-4o", temperature: float = 0.3):
        self.llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            openai_api_key=openai_api_key
        )
        self.capabilities_summary = self._build_capabilities_summary()
    
    def _build_capabilities_summary(self) -> str:
        """Build comprehensive summary of available tools with their required arguments"""
        capabilities = []
        for agent_name, agent_info in agent_capabilities.items():
            capabilities.append(f"\n**{agent_name.upper()}:**")
            tools = agent_info.get("tools", {})
            for tool_name, tool_info in tools.items():
                # Get tool description
                desc = tool_info.get("description", "")
                capabilities.append(f"  • {tool_name}: {desc}")
                
                # Extract required and optional args
                args = tool_info.get("args", {})
                required_args = [k for k, v in args.items() if "(required)" in str(v)]
                optional_args = [k for k, v in args.items() if "(optional)" in str(v)]
                
                if required_args:
                    capabilities.append(f"    Required: {', '.join(required_args)}")
                if optional_args:
                    capabilities.append(f"    Optional: {', '.join(optional_args)}")
        
        return "\n".join(capabilities)
    
    def analyze_request(
        self, 
        user_message: str, 
        conversation_state: ConversationState
    ) -> ConversationAnalysis:
        """
        Analyze user message to determine intent and completeness.
        
        Args:
            user_message: Current user input
            conversation_state: Previous conversation context
            
        Returns:
            ConversationAnalysis with intent, missing fields, and questions
        """
        
        # Build conversation history for context
        history_text = ""
        if conversation_state.conversation_history:
            history_text = "PREVIOUS CONVERSATION:\n"
            for turn in conversation_state.conversation_history[-5:]:  # Last 5 turns
                history_text += f"{turn['role'].upper()}: {turn['content']}\n"
            history_text += "\n"
        
        # Add execution context if available
        exec_context = ""
        if conversation_state.executed_count > 0:
            exec_context = f"\nEXECUTION CONTEXT:\n"
            exec_context += f"- This conversation has executed {conversation_state.executed_count} task(s)\n"
            exec_context += f"- Last execution: {conversation_state.last_executed_at or 'unknown'}\n"
            if conversation_state.execution_history:
                last_exec = conversation_state.execution_history[-1]
                exec_context += f"- Last status: {last_exec.get('status', 'unknown')}\n"
                exec_context += f"- Last message: {last_exec.get('message', 'N/A')}\n"
            exec_context += "- User may be asking to modify, redo, or continue from previous execution\n\n"
        
        # Build system prompt with capabilities
        system_prompt = f"""You are a conversational AI assistant that validates and clarifies user requests before executing them.

AVAILABLE CAPABILITIES:
{self.capabilities_summary}

YOUR ROLE:
1. Understand what the user wants to do
2. Check if we have the tools to do it (refer to AVAILABLE CAPABILITIES above)
3. Extract all necessary information from the conversation
4. Identify required fields from the tool definitions above
5. Ask clarification questions if information is missing
6. Explain limitations if task is not feasible
7. Suggest alternatives for complex or infeasible tasks

IMPORTANT CONTEXT ABOUT EXECUTION:
- After successful execution, the conversation continues (is NOT deleted)
- If user asks to modify/redo a task that was just executed, treat it as a NEW request
- Check if execution_history has recent entries - if so, acknowledge the previous execution
- If executed_count > 0, user might be asking for modifications or re-runs

ANALYSIS INSTRUCTIONS:
1. Classify intent: needs_clarification, not_feasible, too_complex, ready_to_execute, or small_talk
2. Extract all information mentioned so far (combine current + history)
3. List missing required fields
4. If missing fields exist, generate a helpful clarification question
5. If task is too complex, break it down or suggest alternatives
6. If not feasible, explain why and suggest what IS possible
7. Provide execution summary if ready to execute

Return your analysis as JSON with this structure:
{{
    "intent": "needs_clarification | not_feasible | too_complex | ready_to_execute | small_talk",
    "task_type": "send_email | search_emails | reply_to_email | manage_calendar | etc",
    "extracted_info": {{
        "recipient": "john@example.com",
        "subject": "Meeting notes",
        "body": "..."
    }},
    "missing_fields": ["recipient", "subject"],
    "clarification_question": "Who would you like to send this email to?",
    "reasoning": "User wants to send an email but didn't specify recipient",
    "suggested_alternatives": ["Search for similar emails first", "Create a draft instead"],
    "execution_ready": false,
    "execution_summary": "Send email to john@example.com with subject 'Meeting notes'"
}}

Be conversational, helpful, and specific in your clarification questions.
Examples of good questions:
- "Who would you like to send this email to?"
- "What should the subject line be?"
- "When should this meeting take place? Please provide a date and time."
- "I can search emails by sender, subject, or date. What would you like to search for?"

Examples of bad questions:
- "What are the details?" (too vague)
- "Please provide all information." (not specific)
"""

        user_prompt = f"""{history_text}{exec_context}CURRENT USER MESSAGE: {user_message}

Analyze this request and determine if we have enough information to execute it."""

        # Call LLM with timeout and retry
        try:
            llm_response = self.llm.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                config={"timeout": 320}  # 320 second timeout
            )
        except Exception as llm_error:
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
            
            # Handle code blocks
            if response_text.startswith("```json"):
                response_text = response_text[7:-3].strip()
            elif response_text.startswith("```"):
                response_text = response_text[3:-3].strip()
            
            # Parse JSON
            analysis_dict = json.loads(response_text)
            
            # Validate required fields exist
            required_fields = ["intent", "task_type", "extracted_info", "missing_fields", "execution_ready"]
            for field in required_fields:
                if field not in analysis_dict:
                    raise ValueError(f"Missing required field: {field}")
            
            return ConversationAnalysis(**analysis_dict)
            
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
                clarification_question="I'm not sure I understood that. Could you please rephrase what you'd like me to do?",
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
    
    def process_message(
        self, 
        user_message: str, 
        conversation_state: Optional[ConversationState] = None
    ) -> tuple[str, ConversationState]:
        """
        Process a user message and return response + updated state.
        
        Args:
            user_message: User's input
            conversation_state: Previous conversation state (None for new conversation)
            
        Returns:
            Tuple of (response_text, updated_conversation_state)
        """
        # Initialize state if new conversation
        if conversation_state is None:
            conversation_state = ConversationState()
        
        # Add user message to history
        conversation_state.conversation_history.append({
            "role": "user",
            "content": user_message
        })
        
        # Analyze the request
        analysis = self.analyze_request(user_message, conversation_state)
        
        # Update state with analysis (merge carefully to avoid overwriting valid data)
        conversation_state.intent = analysis.intent
        
        # Only update extracted_info with non-empty values from analysis
        for key, value in analysis.extracted_info.items():
            if value is not None and value != "":
                conversation_state.extracted_info[key] = value
        
        conversation_state.missing_fields = analysis.missing_fields
        conversation_state.clarification_question = analysis.clarification_question
        conversation_state.ready_for_execution = analysis.execution_ready
        conversation_state.execution_summary = analysis.execution_summary
        
        # Generate response based on intent
        if analysis.intent == ConversationIntent.SMALL_TALK:
            response = "I'm here to help you manage your emails, calendar, and documents. What would you like me to do?"
        
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
            # Note: With auto-execution, this will run immediately
            # Remove "Should I proceed?" since it auto-executes
        
        else:
            response = "I'm processing your request..."
        
        # Add assistant response to history
        conversation_state.conversation_history.append({
            "role": "assistant",
            "content": response
        })
        
        return response, conversation_state
    
    def should_execute(self, conversation_state: ConversationState) -> bool:
        """Check if conversation is ready for execution"""
        return conversation_state.ready_for_execution
    
    def build_supervisor_input(self, conversation_state: ConversationState) -> str:
        """
        Build a complete, well-formed input for the supervisor agent.
        
        Args:
            conversation_state: Current conversation state
            
        Returns:
            Clean input string for supervisor
        """
        if not conversation_state.execution_summary:
            # Fallback: reconstruct from extracted info
            info = conversation_state.extracted_info
            task_type = info.get("task_type", "task")
            
            # Build sentence from extracted info
            parts = []
            for key, value in info.items():
                if key != "task_type":
                    parts.append(f"{key}: {value}")
            
            return f"{task_type} with " + ", ".join(parts)
        
        return conversation_state.execution_summary
    
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
            "body_html", "body_clean", "raw_content", "encoded_data",
            
            # Internal flags
            "is_draft", "is_sent", "is_read", "has_attachments", "body_has_tables",
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
        
        Args:
            conversation_state: Current conversation state
            final_context: The final_context from orchestrator (all variables)
            execution_status: Status of execution (success, error, etc.)
            execution_message: Raw execution message
            
        Returns:
            Human-friendly summary for the user
        """
        
        # Build context for LLM
        original_request = conversation_state.execution_summary or "your request"
        
        # FILTER: Remove technical fields user doesn't care about
        user_relevant_context = self._filter_context_for_user(final_context)
        
        print(f"📊 Context filtering:")
        print(f"   Before: {len(final_context)} fields, {len(json.dumps(final_context))} chars")
        print(f"   After: {len(user_relevant_context)} fields, {len(json.dumps(user_relevant_context))} chars")
        
        # Format filtered context for readability
        context_summary = []
        for key, value in user_relevant_context.items():
            if isinstance(value, list):
                context_summary.append(f"- {key}: {len(value)} items")
                if len(value) > 0 and isinstance(value[0], dict):
                    # Show first item preview with user-relevant fields only
                    sample_keys = list(value[0].keys())[:5]
                    context_summary.append(f"  (fields: {', '.join(sample_keys)})")
            elif isinstance(value, dict):
                context_summary.append(f"- {key}: object with {len(value)} fields")
            else:
                context_summary.append(f"- {key}: {value}")
        
        context_text = "\n".join(context_summary) if context_summary else "No data returned"
        
        system_prompt = f"""You are a helpful assistant that explains task execution results to users in a friendly, conversational way.

Your job is to:
1. Confirm what task was completed
2. Highlight the key results and data
3. Explain what variables/data are now available
4. Be concise but informative

Keep your response under 200 words. Use emojis sparingly for clarity.
Focus on what matters to the user, not technical details."""

        user_prompt = f"""The user requested: "{original_request}"

Execution Status: {execution_status}
System Message: {execution_message}

Final Context (Available Data):
{context_text}

Please summarize what was accomplished and what data is now available in a friendly, user-facing way."""

        try:
            llm_response = self.llm.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                config={"timeout": 30}
            )
            
            summary = llm_response.content.strip()
            return summary
            
        except Exception as e:
            # Fallback to simple summary if LLM fails
            print(f"⚠️ Failed to generate LLM summary: {e}")
            
            if execution_status == "success":
                return f"✅ Successfully completed: {original_request}\n\nResults:\n{context_text}"
            else:
                return f"❌ Failed to complete: {original_request}\n\nError: {execution_message}"


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
