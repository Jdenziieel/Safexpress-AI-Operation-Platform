"""
Summarization Service - Post-execution result summarization.

Handles generating human-friendly summaries of execution results,
filtering technical context, and formatting error/no-results responses.
Extracted from ConversationalAgent to separate summarization concerns
from core conversation analysis logic.
"""

import json
import time
from typing import Optional, Dict, Any, List
from models.models import ConversationState
from llm_error_handler import handle_llm_error, LLMServiceException, is_llm_error
from logging_config import conversational_logger as logger
from execution_logger import trace


class SummarizationService:
    """
    Service layer for execution result summarization.

    Dependencies:
        llm: ChatOpenAI instance for LLM-powered summarization
    """

    def __init__(self, llm):
        """
        Args:
            llm: ChatOpenAI instance (shared with ConversationalAgent)
        """
        self.llm = llm

    def filter_context_for_user(self, final_context: Dict[str, Any]) -> Dict[str, Any]:
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
            "body_html", "body_clean", "body_full", "raw_content", "encoded_data", "body",  # Full body is too verbose
            
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
                            filtered_item = self.filter_context_for_user(item)  # Recursive
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
                filtered_nested = self.filter_context_for_user(value)  # Recursive
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
        user_relevant_context = self.filter_context_for_user(final_context)
        
        trace.step("summarization", "context filtering", {
            "before_fields": len(final_context),
            "before_chars": len(json.dumps(final_context)),
            "after_fields": len(user_relevant_context),
            "after_chars": len(json.dumps(user_relevant_context)),
        })
        
        # Build READABLE context with actual content
        context_text = self._build_readable_context(user_relevant_context)
        
        trace.step("summarization", f"generating LLM summary ({len(context_text)} chars context)")
        
        system_prompt = """You are a concise AI assistant summarizing task results.

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

        # === DEBUG: Show exactly what the summarization LLM receives ===
        print(f"\n{'='*60}")
        print(f"SUMMARIZATION LLM INPUT")
        print(f"{'='*60}")
        print(f"System prompt ({len(system_prompt)} chars):")
        print(system_prompt)
        print(f"{'─'*60}")
        print(f"User prompt ({len(user_prompt)} chars):")
        print(user_prompt)
        print(f"{'='*60}\n")

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
            cached_tokens = 0
            if hasattr(llm_response, 'response_metadata'):
                token_usage = llm_response.response_metadata.get('token_usage', {})
                input_tokens = token_usage.get('prompt_tokens', (len(system_prompt) + len(user_prompt)) // 4)
                output_tokens = token_usage.get('completion_tokens', len(llm_response.content) // 4)
                cached_tokens = token_usage.get('prompt_tokens_details', {}).get('cached_tokens', 0)
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
                success=True,
                cached_tokens=cached_tokens
            )
            
            summary = llm_response.content.strip()

            # === DEBUG: Show what the summarization LLM returned ===
            print(f"\n{'='*60}")
            print(f"SUMMARIZATION LLM OUTPUT ({len(summary)} chars, {duration_ms:.0f}ms)")
            print(f"  input_tokens={input_tokens}, output_tokens={output_tokens}, cached={cached_tokens}")
            print(f"{'='*60}")
            print(summary)
            print(f"{'='*60}\n")

            return summary
            
        except Exception as e:
            # Check if this is an LLM service error (rate limit, quota, etc.)
            if is_llm_error(e):
                trace.error("LLM service error in result summarization", e)
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
                raise LLMServiceException(handle_llm_error(e))
            
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
            trace.warning("Failed to generate LLM summary, using fallback", {"error": str(e)})
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
