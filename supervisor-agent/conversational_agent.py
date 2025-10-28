"""
Conversational Agent - Pre-Supervisor Validation & Clarification Layer

This agent sits BEFORE the supervisor and handles:
1. Validating if user request has all necessary information
2. Asking clarification questions
3. Checking if task is feasible with available tools
4. Managing multi-turn conversations
5. Suggesting alternatives for complex tasks
"""

from pydantic import BaseModel
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
    conversation_history: List[Dict[str, str]] = []
    extracted_info: Dict[str, Any] = {}
    missing_fields: List[str] = []
    intent: Optional[ConversationIntent] = None
    clarification_question: Optional[str] = None
    ready_for_execution: bool = False
    execution_summary: Optional[str] = None  # Human-readable summary


class ConversationAnalysis(BaseModel):
    """LLM's analysis of the user request"""
    intent: ConversationIntent
    task_type: str  # e.g., "send_email", "search_emails", "manage_calendar"
    extracted_info: Dict[str, Any]
    missing_fields: List[str]
    clarification_question: Optional[str]
    reasoning: str
    suggested_alternatives: Optional[List[str]] = None
    execution_ready: bool
    execution_summary: Optional[str]


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
        """Build human-readable summary of what the system can do"""
        capabilities = []
        for agent_name, agent_info in agent_capabilities.items():
            tools = agent_info.get("tools", {})
            tool_names = list(tools.keys())
            capabilities.append(f"- {agent_name}: {', '.join(tool_names)}")
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
        
        # Build system prompt with capabilities
        system_prompt = f"""You are a conversational AI assistant that validates and clarifies user requests before executing them.

AVAILABLE CAPABILITIES:
{self.capabilities_summary}

YOUR ROLE:
1. Understand what the user wants to do
2. Check if we have the tools to do it
3. Extract all necessary information from the conversation
4. Ask clarification questions if information is missing
5. Explain limitations if task is not feasible
6. Suggest alternatives for complex or infeasible tasks

TASK TYPES AND REQUIRED FIELDS:

**Send/Create Email:**
- Required: recipient (to), subject, body/content
- Optional: attachments, cc, bcc
- Note: We create drafts first for safety, then optionally send

**Reply to Email:**
- Required: which email to reply to (identified by subject, sender, or recency), reply content
- Optional: Include original message

**Search Emails:**
- Required: search criteria (subject, sender, date range, keywords)
- Optional: labels (INBOX, SENT, UNREAD, etc.)

**Manage Drafts:**
- For searching: query criteria
- For sending: which draft to send

**Calendar Events:**
- Required: event title, date/time, duration OR start/end time
- Optional: attendees, location, description

**Google Drive:**
- Required: file name OR file ID, operation type (upload, download, search)
- Optional: folder location, permissions

**Google Docs:**
- Required: document ID OR title, operation (create, edit, read)
- Optional: content, formatting

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

        user_prompt = f"""{history_text}CURRENT USER MESSAGE: {user_message}

Analyze this request and determine if we have enough information to execute it."""

        # Call LLM
        llm_response = self.llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ])
        
        # Parse response
        try:
            response_text = llm_response.content.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:-3].strip()
            elif response_text.startswith("```"):
                response_text = response_text[3:-3].strip()
            
            analysis_dict = json.loads(response_text)
            
            return ConversationAnalysis(**analysis_dict)
            
        except json.JSONDecodeError as e:
            # Fallback: treat as needing clarification
            return ConversationAnalysis(
                intent=ConversationIntent.NEEDS_CLARIFICATION,
                task_type="unknown",
                extracted_info={},
                missing_fields=["all"],
                clarification_question="I'm not sure I understood that. Could you please rephrase what you'd like me to do?",
                reasoning=f"Failed to parse LLM response: {e}",
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
        
        # Update state with analysis
        conversation_state.intent = analysis.intent
        conversation_state.extracted_info.update(analysis.extracted_info)
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
            response += f"\nShould I proceed?"
        
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
