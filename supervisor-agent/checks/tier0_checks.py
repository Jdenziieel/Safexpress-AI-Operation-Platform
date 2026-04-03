"""
Tier 0: Pattern-Based Quick Checks (No LLM - Instant Response)

Mixin class providing 7 pattern-based check methods that detect common
requests (pending action approval, greetings, repeats, capabilities, examples, help, status)
and return instant responses without any LLM token usage.

These methods are mixed into ConversationalAgent via inheritance.
"""

from typing import Optional, Dict, Any, Tuple
from models import ConversationAnalysis, ConversationIntent, ConversationState
from execution_logger import trace


class Tier0ChecksMixin:
    """
    Mixin providing Tier 0 pattern-based quick checks.
    
    Mixed into ConversationalAgent to provide instant responses
    for common request patterns without LLM calls.
    
    Expects the host class to provide:
        - self._get_memory_manager(state_id, memory_state) -> ConversationMemoryManager
        - self.full_capabilities_summary: str
    """

    def _quick_pending_action_check(self, user_message: str, conversation_state: ConversationState) -> Optional[ConversationAnalysis]:
        """
        GATE CHECK: When workflow is paused awaiting approval, intercept all input.
        
        - approve/proceed → returns signal to execute the pending action
        - cancel/reject → returns signal to cancel with summary
        - anything else when paused → reminds user to handle pending action
        - approve when NOT paused → "nothing pending"
        
        Returns:
            ConversationAnalysis with approval/rejection handling, or None to pass through
        """
        user_lower = user_message.lower().strip()
        
        approve_patterns = [
            "yes", "approve", "proceed", "send it", "go ahead", "confirm",
            "do it", "execute", "ok", "okay", "sure", "yep", "yeah",
            "approved", "send", "continue", "go", "accept", "y"
        ]
        
        reject_patterns = [
            "no", "cancel", "reject", "stop", "don't", "dont", "abort",
            "nevermind", "never mind", "nah", "nope", "skip", "decline",
            "cancelled", "rejected", "n"
        ]
        
        details_patterns = [
            "what is pending", "show details", "what action", "pending action",
            "what are you waiting for", "show me", "details"
        ]
        
        is_approve = any(user_lower == p or user_lower.startswith(p + " ") or user_lower.startswith(p + ",") for p in approve_patterns)
        is_reject = any(user_lower == p or user_lower.startswith(p + " ") or user_lower.startswith(p + ",") for p in reject_patterns)
        is_details = any(p in user_lower for p in details_patterns)
        
        # === CASE 1: Workflow IS paused with pending actions ===
        if conversation_state.workflow_paused and conversation_state.pending_actions:
            pending = conversation_state.pending_actions[0]  # Current pending action
            action_id = pending.get("action_id", "unknown")
            description = pending.get("description", "Unknown action")
            tool_name = pending.get("tool", "unknown")
            
            if is_approve:
                trace.step("tier0", f"pending action APPROVED via chat: {action_id}")
                return ConversationAnalysis(
                    intent=ConversationIntent.SMALL_TALK,
                    task_type="pending_action_approved",
                    extracted_info={"action_id": action_id, "decision": "approve"},
                    missing_fields=[],
                    response_text="⏳ Executing approved action...",
                    reasoning=f"User approved pending action: {tool_name}",
                    execution_ready=False,
                    execution_summary=None
                )
            
            if is_reject:
                trace.step("tier0", f"pending action REJECTED via chat: {action_id}")
                
                # Build cancellation summary
                cancel_msg = f" **Action Cancelled**\n\n"
                cancel_msg += f"The following action has been cancelled:\n"
                cancel_msg += f"- **Action:** {description}\n"
                if pending.get("inputs"):
                    inputs = pending["inputs"]
                    if inputs.get("to"):
                        cancel_msg += f"- **Recipient:** {inputs['to']}\n"
                    if inputs.get("subject"):
                        cancel_msg += f"- **Subject:** {inputs['subject']}\n"
                
                # Check if there were remaining steps
                remaining_count = len(conversation_state.remaining_steps)
                if remaining_count > 0:
                    cancel_msg += f"\n⏭ **{remaining_count} remaining step(s) were also cancelled.**\n"
                
                cancel_msg += "\nIs there anything else you'd like to do?"
                
                return ConversationAnalysis(
                    intent=ConversationIntent.SMALL_TALK,
                    task_type="pending_action_rejected",
                    extracted_info={"action_id": action_id, "decision": "reject"},
                    missing_fields=[],
                    response_text=cancel_msg,
                    reasoning=f"User rejected pending action: {tool_name}",
                    execution_ready=False,
                    execution_summary=None
                )
            
            if is_details:
                trace.step("tier0", f"pending action details requested: {action_id}")
                details_msg = _build_rich_approval_message(pending)
                return ConversationAnalysis(
                    intent=ConversationIntent.SMALL_TALK,
                    task_type="pending_action_details",
                    extracted_info={},
                    missing_fields=[],
                    response_text=details_msg,
                    reasoning="User asked for pending action details",
                    execution_ready=False,
                    execution_summary=None
                )
            
            # Anything else while paused — remind user
            trace.step("tier0", "message blocked — workflow paused, pending action requires decision")
            reminder_msg = f"⏸ **Action Awaiting Your Decision**\n\n"
            reminder_msg += f"**{description}**\n\n"
            reminder_msg += f"Please reply with:\n"
            reminder_msg += f"- **\"approve\"** or **\"yes\"** to proceed\n"
            reminder_msg += f"- **\"cancel\"** or **\"no\"** to cancel\n"
            reminder_msg += f"- **\"details\"** to see full action info"
            
            return ConversationAnalysis(
                intent=ConversationIntent.SMALL_TALK,
                task_type="pending_action_reminder",
                extracted_info={},
                missing_fields=[],
                response_text=reminder_msg,
                reasoning="User sent unrelated message while action is pending",
                execution_ready=False,
                execution_summary=None
            )
        
        # === CASE 2: No pending actions, but user says approve/reject ===
        if is_approve and not conversation_state.workflow_paused:
            # Only intercept bare "approve" / "yes" — don't intercept "yes, send an email"
            if len(user_lower.split()) <= 3:
                # Let it fall through to Tier 0.5 which handles confirmation properly
                return None
        
        # Not a pending action scenario — pass through
        return None

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
                trace.step("tier0", "greeting detected — instant response (0 tokens)")
                
                greeting_response = """Hello! I'm your workspace assistant. Here's what I can help you with:

**Email (Gmail)**
- Send, reply, forward, and draft emails
- Search your inbox with filters (date, sender, subject, attachments)
- Manage labels (star, mark important, archive)
- Download attachments and view full email threads

**Documents (Google Docs)**
- Create new documents or use templates
- Upload your own templates and generate documents from them
- Add and edit content in existing docs

**Spreadsheets (Google Sheets)**
- Create new spreadsheets
- Upload and map data from CSV/Excel files
- Update rows by date matching

**Calendar (Google Calendar)**
- View upcoming events across all your calendars
- Create, update, and delete events
- Add Google Meet links and invite attendees
- Resolve scheduling conflicts automatically

**Drive (Google Drive)**
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
                    response_text=greeting_response,
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
            trace.step("tier0", "quick repeat request — retrieving last response (0 tokens)")
            
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
                    response_text=f"Sure, here's what I said:\n\n{last_assistant}",
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
            trace.step("tier0", "quick capabilities request — returning cached list (0 tokens)")
            
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
                response_text=capabilities_response,
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
            trace.step("tier0", "quick examples request — returning samples (0 tokens)")
            
            examples = """Here are some examples of what you can ask me:

**Email Examples:**
- "Send an email to john@example.com about the Q4 report"
- "Search my emails from alice@company.com from last week"
- "Draft an email to the team about project updates"
- "Reply to the last email from bob@example.com"
- "Forward the invoice email to finance@company.com"
- "Star the email from the CEO"
- "Download the attachment from the latest report email"
- "Show me the full thread with sarah@example.com"

**Document Examples:**
- "Create a Google Doc titled Meeting Notes"
- "Add a summary about Q4 performance to my document"
- "Create a Board Meeting doc using MOMtemplate template and TestData123 data"
- "Upload this template and create a new document called Project Plan"
- "List my Google Docs"

**Spreadsheet Examples:**
- "Create a new spreadsheet called Sales Tracker"
- "Upload the CSV data to my Q4 Reports sheet"
- "Update the sheet with the latest date-matched data"

**Calendar Examples:**
- "Schedule a meeting with Sarah tomorrow at 3pm"
- "Show my upcoming events for next week"
- "Create a team standup with a Google Meet link"
- "Move my 2pm meeting to 4pm"
- "Delete the cancelled event from yesterday"

**Drive Examples:**
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
                response_text=examples,
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
            "help", "guide", "tutorial", "teach me", "explain",
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
            trace.step("tier0", "quick general help request detected (0 tokens)")
            
            help_response = """I can help you manage your workspace across several Google services. Here's a quick guide:

**Email (Gmail)**
- Send, reply, forward, and draft emails
- Search your inbox with filters (sender, date, subject, attachments)
- Manage labels — star, mark important, archive, move to trash
- Download email attachments
- View full email conversation threads

**Documents (Google Docs)**
- Create new documents from scratch
- Use existing templates or upload your own
- Add and edit content in documents
- Create documents from template + data file combos

**Spreadsheets (Google Sheets)**
- Create new spreadsheets
- Upload and map data from CSV/Excel files
- Update rows by date matching

**Calendar (Google Calendar)**
- View upcoming events across all calendars
- Create, update, and delete events
- Add Google Meet links and invite attendees
- Handle scheduling conflicts automatically

**Drive (Google Drive)**
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
                response_text=help_response,
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
        if not conversation_state.has_executed:
            return None
        
        trace.step("tier0", "quick status check request detected (0 tokens)")
        
        status = conversation_state.last_execution_status or "unknown"
        message = conversation_state.last_execution_message or "No details available"
        
        if status == "success":
            status_response = f" **Last execution: Successful**\n\n{message}\n\nAnything else you'd like to do?"
        elif status == "error":
            status_response = f" **Last execution: Failed**\n\n**Error:** {message}\n\nWould you like to try again or do something else?"
        else:
            status_response = f" **Last execution status:** {status}\n\n{message}"
        
        trace.step("tier0", "quick_status_check returning", {
            "status": status,
            "message_preview": message[:120] if message else None,
        })
        
        return ConversationAnalysis(
            intent=ConversationIntent.SMALL_TALK,
            task_type="status_check",
            extracted_info={},
            missing_fields=[],
            response_text=status_response,
            reasoning="User checking execution status",
            execution_ready=False,
            execution_summary=None
        )


    def _quick_confirm_or_cancel_check(self, user_message: str, conversation_state: ConversationState) -> Optional[ConversationAnalysis]:
        """
        Intercept bare confirmations/cancellations when state is unambiguous.
        Saves an LLM call for "yes", "approve", "cancel", "no" when we already
        know the conversation is awaiting confirmation.
        
        Only triggers for short messages (<=3 words) to avoid catching
        compound inputs like "yes, but change the recipient".
        """
        user_lower = user_message.lower().strip()
        word_count = len(user_lower.split())

        if word_count > 3:
            return None

        is_awaiting_confirmation = (
            not conversation_state.ready_for_execution
            and conversation_state.intent == ConversationIntent.READY_TO_EXECUTE
            and not conversation_state.missing_fields
        )

        if not is_awaiting_confirmation:
            return None

        confirm_words = {"yes", "ok", "okay", "sure", "yep", "yeah", "y", "confirm", "approve", "proceed", "go", "go ahead", "do it", "send it", "continue"}
        cancel_words = {"no", "cancel", "stop", "abort", "nah", "nope", "n", "reject", "nevermind", "never mind", "forget it"}

        if user_lower in confirm_words:
            trace.step("tier0", "bare confirmation — skipping Tier 0.5")
            return ConversationAnalysis(
                intent=ConversationIntent.READY_TO_EXECUTE,
                task_type=conversation_state.extracted_info.get("task_type", "task"),
                extracted_info=conversation_state.extracted_info,
                missing_fields=[],
                clarification_question=None,
                reasoning="User confirmed (Tier 0 pattern match)",
                execution_ready=True,
                execution_summary=conversation_state.execution_summary
            )

        if user_lower in cancel_words:
            trace.step("tier0", "bare cancellation — skipping Tier 0.5")
            cancelled_info = conversation_state.extracted_info.copy()
            return ConversationAnalysis(
                intent=ConversationIntent.CANCELLED,
                task_type="cancellation",
                extracted_info={},
                missing_fields=[],
                clarification_question=None,
                reasoning=f"User cancelled (Tier 0 pattern match). Previous data: {cancelled_info}",
                execution_ready=False,
                execution_summary=None
            )

        return None


def _build_rich_approval_message(pending_action: dict) -> str:
    """
    Build a rich, detailed approval message for a pending action.
    Shows danger reason, all relevant fields (recipient, subject, body, etc.).
    """
    tool = pending_action.get("tool", "unknown")
    risk_level = pending_action.get("risk_level", "DANGEROUS")
    description = pending_action.get("description", "Unknown action")
    inputs = pending_action.get("inputs", {})
    step_number = pending_action.get("step_number")
    total_steps = pending_action.get("total_steps")
    
    # Risk emoji
    risk_emoji = "" if risk_level == "CRITICAL" else ""
    risk_label = "CRITICAL" if risk_level == "CRITICAL" else "DANGEROUS"
    
    msg = f"{risk_emoji} **Action Requires Approval** — {risk_label}\n\n"
    
    if step_number and total_steps:
        msg += f" Step {step_number} of {total_steps}\n\n"
    
    msg += f"**{description}**\n\n"
    
    # Tool-specific details
    if tool in ("send_draft_email", "send_email_with_attachment"):
        msg += " **Sending Email**\n"
        if inputs.get("to"):
            msg += f"- **To:** {inputs['to']}\n"
        if inputs.get("subject"):
            msg += f"- **Subject:** {inputs['subject']}\n"
        if inputs.get("body"):
            body_preview = inputs["body"][:300]
            if len(inputs["body"]) > 300:
                body_preview += "..."
            msg += f"- **Body preview:**\n  > {body_preview}\n"
        if inputs.get("cc"):
            msg += f"- **CC:** {inputs['cc']}\n"
        if inputs.get("bcc"):
            msg += f"- **BCC:** {inputs['bcc']}\n"
    
    elif tool == "reply_to_email":
        msg += "↩ **Replying to Email**\n"
        if inputs.get("message_id"):
            msg += f"- **Message ID:** {inputs['message_id']}\n"
        if inputs.get("reply_body"):
            body_preview = inputs["reply_body"][:300]
            if len(inputs["reply_body"]) > 300:
                body_preview += "..."
            msg += f"- **Reply preview:**\n  > {body_preview}\n"
    
    elif tool == "add_text":
        msg += " **Adding Text to Document**\n"
        if inputs.get("document_id"):
            msg += f"- **Document ID:** {inputs['document_id']}\n"
        if inputs.get("text"):
            text_preview = inputs["text"][:300]
            if len(inputs["text"]) > 300:
                text_preview += "..."
            msg += f"- **Text preview:**\n  > {text_preview}\n"
    
    elif tool == "share_file":
        msg += " **Sharing File**\n"
        if inputs.get("file_id"):
            msg += f"- **File ID:** {inputs['file_id']}\n"
        if inputs.get("email"):
            msg += f"- **Share with:** {inputs['email']}\n"
        if inputs.get("role"):
            msg += f"- **Permission:** {inputs['role']}\n"
    
    elif tool in ("delete_email", "delete_file", "delete_event"):
        msg += " **Deleting Resource**\n"
        for key, value in inputs.items():
            msg += f"- **{key}:** {value}\n"
    
    elif tool in ("edit_doc", "update_doc"):
        msg += " **Editing Document**\n"
        if inputs.get("document_id"):
            msg += f"- **Document ID:** {inputs['document_id']}\n"
        if inputs.get("old_text"):
            msg += f"- **Find:** {inputs['old_text'][:100]}{'...' if len(inputs.get('old_text', '')) > 100 else ''}\n"
        if inputs.get("new_text"):
            msg += f"- **Replace with:** {inputs['new_text'][:100]}{'...' if len(inputs.get('new_text', '')) > 100 else ''}\n"
    
    else:
        # Generic — show all non-empty inputs
        msg += f" **{tool}**\n"
        for key, value in inputs.items():
            if value:
                val_str = str(value)
                if len(val_str) > 200:
                    val_str = val_str[:200] + "..."
                msg += f"- **{key}:** {val_str}\n"
    
    msg += f"\n---\n"
    msg += f"Reply **\"approve\"** to proceed or **\"cancel\"** to stop."
    
    return msg
