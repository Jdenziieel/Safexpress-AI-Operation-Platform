"""
Tier 0: Pattern-Based Quick Checks (No LLM - Instant Response)

Mixin class providing 6 pattern-based check methods that detect common
requests (greetings, repeats, capabilities, examples, help, status)
and return instant responses without any LLM token usage.

These methods are mixed into ConversationalAgent via inheritance.
"""

from typing import Optional, Dict, Any
from models import ConversationAnalysis, ConversationIntent, ConversationState


class Tier0ChecksMixin:
    """
    Mixin providing Tier 0 pattern-based quick checks.
    
    Mixed into ConversationalAgent to provide instant responses
    for common request patterns without LLM calls.
    
    Expects the host class to provide:
        - self._get_memory_manager(state_id, memory_state) -> ConversationMemoryManager
        - self.full_capabilities_summary: str
    """

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
            "good evening", "greetings", "howdy", "what's up", "sup", "yo",
            "hola", "hii", "hiii", "helo", "heya", "hi there", "hey there",
            "hello there", "good day", "morning", "evening", "afternoon",
            "wassup", "whats up", "what up", "g'day", "aloha"
        ]
        
        user_lower = user_message.lower().strip()
        
        # Check if it's JUST a greeting (no task request)
        # Must start with greeting and be short
        is_greeting = any(user_lower.startswith(g) for g in greetings) and len(user_message) < 30
        
        if is_greeting:
            # Make sure it's not "hi, send email to..." (greeting + task)
            task_indicators = ["send", "search", "create", "find", "schedule", "draft", "reply", "make", "write",
                               "forward", "delete", "update", "upload", "download", "list", "check", "add"]
            if not any(task in user_lower for task in task_indicators):
                print(f"⚡ Tier 0: Greeting detected - instant response (0 tokens)")
                
                greeting_response = """Hello! 👋 I'm your workspace assistant. Here's what I can help you with:

📧 **Email (Gmail)**
- Send, reply, forward, and draft emails
- Search your inbox with filters (date, sender, subject, attachments)
- Manage labels (star, mark important, archive)
- Download attachments and view full email threads

📄 **Documents (Google Docs)**
- Create new documents or use templates
- Upload your own templates and generate documents from them
- Add and edit content in existing docs

📊 **Spreadsheets (Google Sheets)**
- Create new spreadsheets
- Upload and map data from CSV/Excel files
- Update rows by date matching

📅 **Calendar (Google Calendar)**
- View upcoming events across all your calendars
- Create, update, and delete events
- Add Google Meet links and invite attendees
- Resolve scheduling conflicts automatically

📁 **Drive (Google Drive)**
- Upload files and organize into folders
- Search and list files across your Drive
- Create folder structures

**Try saying something like:**
- "Send an email to john@example.com about the project update"
- "Search my emails for invoices from last month"
- "Create a document titled Meeting Notes"
- "Schedule a meeting with Sarah tomorrow at 3pm"
- "Upload report.csv to my Q4 Reports folder"

What would you like to do?"""
                
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
            "come again", "pardon", "didn't catch that", "what was that",
            "can you repeat", "repeat that", "say it again", "one more time",
            "i missed that", "sorry what", "huh", "what again",
            "could you repeat", "tell me again", "run that by me again",
            "i didn't hear", "didn't understand", "say again"
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
            "what can i ask", "what are your features", "what are your abilities",
            "what services", "what tools", "list your capabilities",
            "what can you help with", "what do you offer", "what can i do",
            "what's available", "available tools", "available features",
            "show me your tools", "show capabilities", "your skills",
            "what can you assist", "what are you able to do",
            "tell me what you can do", "what can you handle",
            "what kind of tasks", "what operations", "supported features"
        ]
        
        user_lower = user_message.lower().strip()
        
        if any(q in user_lower for q in capability_questions):
            print(f"⚡ Tier 0: Capabilities request - returning cached list (0 tokens)")
            
            # Use cached full_capabilities_summary (already built in __init__)
            capabilities_response = f"""Here's everything I can help you with:

{self.full_capabilities_summary}

**Try saying something like:**
- "Send an email to john@example.com about the project update"
- "Search my emails for invoices from last month"
- "Forward the email from alice@company.com to bob@company.com"
- "Create a document titled Meeting Notes"
- "Create Board Meeting doc using MOMtemplate and TestData123"
- "Schedule a meeting with Sarah tomorrow at 3pm"
- "Upload report.csv to my Q4 Reports folder"
- "List all files in my Operations folder"

What would you like to do?"""
            
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
        example_keywords = [
            "example", "show me", "demonstrate", "sample", "give me an example",
            "give an example", "show examples", "some examples", "for example",
            "try out", "test it", "how does it work", "how to use",
            "what can i say", "what should i say", "what do i type",
            "give me a sample", "show me how it works", "demo"
        ]
        
        user_lower = user_message.lower().strip()
        
        if any(keyword in user_lower for keyword in example_keywords):
            print(f"⚡ Tier 0: Examples request - returning samples (0 tokens)")
            
            examples = """Here are some examples of what you can ask me:

📧 **Email Examples:**
- "Send an email to john@example.com about the Q4 report"
- "Search my emails from alice@company.com from last week"
- "Draft an email to the team about project updates"
- "Reply to the last email from bob@example.com"
- "Forward the invoice email to finance@company.com"
- "Star the email from the CEO"
- "Download the attachment from the latest report email"
- "Show me the full thread with sarah@example.com"

📄 **Document Examples:**
- "Create a Google Doc titled Meeting Notes"
- "Add a summary about Q4 performance to my document"
- "Create a Board Meeting doc using MOMtemplate template and TestData123 data"
- "Upload this template and create a new document called Project Plan"
- "List my Google Docs"

📊 **Spreadsheet Examples:**
- "Create a new spreadsheet called Sales Tracker"
- "Upload the CSV data to my Q4 Reports sheet"
- "Update the sheet with the latest date-matched data"

📅 **Calendar Examples:**
- "Schedule a meeting with Sarah tomorrow at 3pm"
- "Show my upcoming events for next week"
- "Create a team standup with a Google Meet link"
- "Move my 2pm meeting to 4pm"
- "Delete the cancelled event from yesterday"

📁 **Drive Examples:**
- "Upload report.pdf to my Operations/2024 folder"
- "List all files in my Reports folder"
- "Create a folder structure for Q1 2025"
- "Search for files named 'invoice'"

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
        help_keywords = [
            "help", "how", "guide", "tutorial", "teach me", "explain",
            "instructions", "show me how", "get started", "getting started",
            "how to start", "how do i begin", "how do i use", "how does this work",
            "i need help", "i'm new", "i am new", "first time", "beginner",
            "walk me through", "step by step", "how to use this", "usage",
            "what should i do", "where do i start", "i'm confused", "i'm lost",
            "not sure what to do", "don't know what to do"
        ]
        user_lower = user_message.lower().strip()
        
        # Check if this is a help request
        if not any(keyword in user_lower for keyword in help_keywords):
            return None
        
        # Check if it's a general help request (not task-specific like "how do I send email")
        task_indicators = [
            "send", "search", "find", "create", "delete", "schedule", "reply",
            "forward", "draft", "upload", "download", "update", "edit", "add",
            "list", "check", "make", "write", "remove", "star", "label"
        ]
        is_general_help = not any(task in user_lower for task in task_indicators)
        
        if is_general_help:
            print(f"🔍 Quick help: General help request detected")
            
            help_response = """I can help you manage your workspace across several Google services. Here's a quick guide:

📧 **Email (Gmail)**
- Send, reply, forward, and draft emails
- Search your inbox with filters (sender, date, subject, attachments)
- Manage labels — star, mark important, archive, move to trash
- Download email attachments
- View full email conversation threads

📄 **Documents (Google Docs)**
- Create new documents from scratch
- Use existing templates or upload your own
- Add and edit content in documents
- Create documents from template + data file combos

📊 **Spreadsheets (Google Sheets)**
- Create new spreadsheets
- Upload and map data from CSV/Excel files
- Update rows by date matching

📅 **Calendar (Google Calendar)**
- View upcoming events across all calendars
- Create, update, and delete events
- Add Google Meet links and invite attendees
- Handle scheduling conflicts automatically

📁 **Drive (Google Drive)**
- Upload files and organize into folders
- Search and list files
- Create folder structures

**Quick start — just type naturally:**
- "Send an email to john@example.com about the project update"
- "Search my emails for invoices from last month"
- "Create a document titled Meeting Notes"
- "Schedule a meeting with Sarah tomorrow at 3pm"
- "Upload report.csv to my Q4 Reports folder"

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
        status_keywords = [
            "status", "done", "finished", "complete", "did it work",
            "success", "result", "what happened", "is it done",
            "did it go through", "was it successful", "did it send",
            "any updates", "how did it go", "outcome", "did it finish",
            "is it complete", "has it been sent", "was it created",
            "did it fail", "any errors", "what's the result",
            "confirmation", "did you do it", "is it ready"
        ]
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
