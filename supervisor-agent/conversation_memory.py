"""
Conversation Memory Manager - Implements Summary Buffer + Entity Memory

Combines concepts from LangChain's:
1. ConversationSummaryBufferMemory - Summarizes old messages when token limit exceeded
2. ConversationEntityMemory - Extracts and tracks important entities across conversation

This prevents context window overflow while maintaining conversation coherence.
"""

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from typing import Dict, List, Any, Optional
import json
import tiktoken
import time

# Import logging module
from logging_config import memory_logger as logger

# Import execution trace logger for direct trace.log writes
from execution_logger import trace

# Import LLM error handler for unified error handling
from llm_error_handler import handle_llm_error, LLMServiceException, is_llm_error

# Model centralized in models/models.py
from models.models import ConversationMemory


class ConversationMemoryManager:
    """
    Manages conversation memory with automatic summarization and entity extraction.
    
    Usage:
        memory_manager = ConversationMemoryManager(openai_api_key="sk-...")
        memory_manager.add_message("user", "Send email to john@example.com")
        memory_manager.add_message("assistant", "What's the subject?")
        context = memory_manager.get_context_for_llm()
    """
    
    def __init__(
        self,
        openai_api_key: str,
        model: str = "gpt-4o",
        temperature: float = 0.3,
        max_tokens_before_summary: int = 2000,
        encoding_name: str = "cl100k_base"
    ):
        """
        Initialize conversation memory manager.
        
        Args:
            openai_api_key: OpenAI API key for LLM calls
            model: LLM model to use for summarization/extraction
            temperature: LLM temperature (lower = more deterministic)
            max_tokens_before_summary: Token threshold for triggering summarization
            encoding_name: Tiktoken encoding name (cl100k_base for GPT-4/GPT-3.5)
        """
        self.llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            openai_api_key=openai_api_key
        )
        self.encoding = tiktoken.get_encoding(encoding_name)
        self.memory = ConversationMemory(
            MAX_TOKENS_BEFORE_SUMMARY=max_tokens_before_summary
        )
    
    def _count_tokens(self, text: str) -> int:
        """
        Count tokens in text using tiktoken.
        
        Args:
            text: Text to count tokens for
            
        Returns:
            Number of tokens
        """
        return len(self.encoding.encode(text))
    
    def _count_message_tokens(self, messages: List[Dict[str, str]]) -> int:
        """
        Count tokens for a list of messages.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            
        Returns:
            Total token count
        """
        total = 0
        for message in messages:
            # Count role + content tokens
            total += self._count_tokens(message.get('role', ''))
            total += self._count_tokens(message.get('content', ''))
            total += 4  # Overhead per message (formatting tokens)
        return total
    
    # Maximum raw history size to prevent unbounded memory growth
    MAX_RAW_HISTORY = 200

    def add_message(self, role: str, content: str) -> None:
        """
        Add a new message to conversation history (pure append, no LLM calls).
        Summarization is deferred to get_context_for_llm() so it only fires
        once per turn, right before the context is actually needed.
        
        Args:
            role: Message role ("user" or "assistant")
            content: Message content
        """
        message = {"role": role, "content": content}
        
        # Add to raw history (capped to prevent unbounded growth)
        self.memory.raw_history.append(message)
        if len(self.memory.raw_history) > self.MAX_RAW_HISTORY:
            self.memory.raw_history = self.memory.raw_history[-self.MAX_RAW_HISTORY:]
        
        # Add to working context
        self.memory.working_context.append(message)
        
        # Update token count
        message_tokens = self._count_tokens(role) + self._count_tokens(content) + 4
        self.memory.current_token_count += message_tokens
        
        if role == "assistant":
            preview = content[:200] + ("..." if len(content) > 200 else "")
            trace.info(f"Memory: added {role} message", {"tokens": message_tokens, "total": self.memory.current_token_count, "max": self.memory.MAX_TOKENS_BEFORE_SUMMARY, "response_preview": preview})
        else:
            trace.info(f"Memory: added {role} message", {"tokens": message_tokens, "total": self.memory.current_token_count, "max": self.memory.MAX_TOKENS_BEFORE_SUMMARY})
    
    def _summarize_conversation(self) -> None:
        """
        Summarize old conversation turns to free up context space.
        
        Process:
        1. Keep recent messages that fit within half the token budget
        2. Summarize everything older using LLM
        3. Extract entities from summarized portion
        4. Update summary and entity_memory
        """
        if len(self.memory.working_context) <= 2:
            # Too few messages to summarize
            trace.warning("Memory: not enough messages to summarize (need > 2)")
            return
        
        # Split by token budget: keep recent messages up to half the budget,
        # summarize everything older. This avoids the arbitrary midpoint split.
        keep_budget = self.memory.MAX_TOKENS_BEFORE_SUMMARY // 2
        kept_tokens = 0
        split_point = len(self.memory.working_context)
        for i in range(len(self.memory.working_context) - 1, -1, -1):
            msg = self.memory.working_context[i]
            msg_tokens = self._count_tokens(msg.get('role', '')) + self._count_tokens(msg.get('content', '')) + 4
            if kept_tokens + msg_tokens > keep_budget:
                break
            kept_tokens += msg_tokens
            split_point = i
        
        # Ensure we summarize at least something
        if split_point == 0:
            split_point = 1
        
        old_messages = self.memory.working_context[:split_point]
        recent_messages = self.memory.working_context[split_point:]
        
        trace.step("memory_summarize", f"summarizing {len(old_messages)} old messages, keeping {len(recent_messages)} recent", {"split_point": split_point, "tokens_before": self.memory.current_token_count})

        print(f"\n{'='*55}")
        print(f"📚 MEMORY SUMMARIZATION")
        print(f"{'='*55}")
        utilization = self.memory.current_token_count * 100 // max(1, self.memory.MAX_TOKENS_BEFORE_SUMMARY)
        print(f"   Token pressure: {self.memory.current_token_count}/{self.memory.MAX_TOKENS_BEFORE_SUMMARY} ({utilization}% full)")
        print(f"   Compressing {len(old_messages)} old messages → keeping {len(recent_messages)} recent")
        print(f"\n   📜 Messages being summarized:")
        for i, msg in enumerate(old_messages):
            role = msg.get('role', '?')
            content = msg.get('content', '')
            preview = content[:100] + '...' if len(content) > 100 else content
            print(f"      [{i+1}] {role.upper()}: {preview}")
        if self.memory.summary:
            print(f"\n   📋 Previous summary: {self.memory.summary[:150]}{'...' if len(self.memory.summary) > 150 else ''}")
        else:
            print(f"\n   📋 Previous summary: (none — first summarization)")

        # Format old messages for summarization
        conversation_text = ""
        for msg in old_messages:
            conversation_text += f"{msg['role'].upper()}: {msg['content']}\n"
        
        # Build summarization prompt — fixed instructions in system (cacheable),
        # dynamic conversation data in user message
        previous_summary = self.memory.summary or "No previous summary."
        
        system_prompt = """Summarize conversations by combining new turns with any previous summary. Return JSON only.

Output format:
{"summary": "<concise summary covering user goals, key info like emails/names/dates, and pending or completed tasks>"}

Preserve: user goals, key info (emails, names, dates), completed tasks, pending tasks."""

        user_prompt = f"""Previous summary: {previous_summary}

New turns:
{conversation_text}"""

        try:
            # === TOKEN TRACKING: Memory Summarization ===
            start_time = time.time()
            llm_response = self.llm.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                config={"timeout": 30}
            )
            duration_ms = (time.time() - start_time) * 1000
            
            # Extract token usage from response
            total_prompt_len = len(system_prompt) + len(user_prompt)
            input_tokens = 0
            output_tokens = 0
            cached_tokens = 0
            if hasattr(llm_response, 'response_metadata'):
                token_usage = llm_response.response_metadata.get('token_usage', {})
                input_tokens = token_usage.get('prompt_tokens', total_prompt_len // 4)
                output_tokens = token_usage.get('completion_tokens', len(llm_response.content) // 4)
                cached_tokens = token_usage.get('prompt_tokens_details', {}).get('cached_tokens', 0)
            else:
                input_tokens = total_prompt_len // 4
                output_tokens = len(llm_response.content) // 4
            
            # Log the LLM call with token tracking
            logger.llm_call(
                model=self.llm.model_name if hasattr(self.llm, 'model_name') else "gpt-4o",
                operation="memory_summarization",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
                tier="memory",
                prompt_summary=f"Summarizing {len(old_messages)} messages",
                success=True,
                cached_tokens=cached_tokens
            )
            
            response_text = llm_response.content.strip()
            
            # Handle code blocks
            if response_text.startswith("```json"):
                response_text = response_text[7:-3].strip()
            elif response_text.startswith("```"):
                response_text = response_text[3:-3].strip()
            
            summary_data = json.loads(response_text)

            new_summary = summary_data.get("summary", "")

            print(f"\n   📝 Summary output:")
            print(f"      {new_summary}")

            self.memory.summary = new_summary

            # Update working context (keep only recent messages)
            self.memory.working_context = recent_messages

            # Recalculate token count
            tokens_before = self.memory.current_token_count
            self.memory.current_token_count = self._count_message_tokens(recent_messages)
            token_reduction = tokens_before - self.memory.current_token_count

            print(f"\n   ✅ Token reduction: {tokens_before} → {self.memory.current_token_count} (saved {token_reduction} tokens, {len(old_messages)} messages compressed)")
            print(f"{'='*55}\n")

            logger.info(
                f"Memory summarized: {len(old_messages)} messages → {len(new_summary)} char summary, saved {token_reduction} tokens",
                component="memory",
                operation="summarization",
                extra={
                    "summary_preview": new_summary[:200],
                    "tokens_before": tokens_before,
                    "tokens_after": self.memory.current_token_count,
                    "token_reduction": token_reduction,
                }
            )
            trace.step("memory_summarize_done", f"summarization complete", {
                "summary_preview": self.memory.summary[:100],
                "tokens_before": tokens_before,
                "tokens_after": self.memory.current_token_count,
                "token_reduction": token_reduction,
                "new_token_count": self.memory.current_token_count,
            })
            
        except Exception as e:
            if is_llm_error(e):
                logger.llm_call(
                    model=self.llm.model_name if hasattr(self.llm, 'model_name') else "gpt-4o",
                    operation="memory_summarization",
                    input_tokens=(len(system_prompt) + len(user_prompt)) // 4,
                    output_tokens=0,
                    duration_ms=(time.time() - start_time) * 1000 if 'start_time' in locals() else 0,
                    tier="memory",
                    prompt_summary=f"Summarizing {len(old_messages)} messages",
                    success=False,
                    error=str(e),
                )
                trace.error(f"Memory: LLM service error during summarization", e)
                raise LLMServiceException(handle_llm_error(e))

            trace.warning(f"Memory: summarization failed", {"error": str(e)})
            # Fallback: just drop oldest message
            if len(self.memory.working_context) > 0:
                self.memory.working_context.pop(0)
                trace.warning("Memory: fallback — dropped oldest message")
                self.memory.current_token_count = self._count_message_tokens(self.memory.working_context)
    
    def get_context_for_llm(self) -> str:
        """
        Build complete context string for downstream LLM.
        Triggers summarization lazily if token threshold is exceeded,
        ensuring it happens at most once per turn.
        
        Combines:
        1. Conversation summary (if exists)
        2. Entity memory (if exists)
        3. Recent message history
        
        Returns:
            Formatted context string ready for LLM consumption
        """
        # Lazy summarization: only when context is actually needed
        if self.memory.current_token_count > self.memory.MAX_TOKENS_BEFORE_SUMMARY:
            trace.warning(f"Memory: token threshold exceeded, summarizing before context build", {"current": self.memory.current_token_count, "max": self.memory.MAX_TOKENS_BEFORE_SUMMARY})
            self._summarize_conversation()
        
        context_parts = []

        print(f"\n{'─'*55}")
        print(f"🧠 BUILDING LLM CONTEXT")
        print(f"{'─'*55}")

        # Add summary if exists
        if self.memory.summary:
            context_parts.append("CONVERSATION SUMMARY:")
            context_parts.append(self.memory.summary)
            context_parts.append("")
            print(f"   ✓ Summary ({len(self.memory.summary)} chars): {self.memory.summary[:120]}{'...' if len(self.memory.summary) > 120 else ''}")
        else:
            print(f"   ✗ Summary: none")

        # Add recent message history
        if self.memory.working_context:
            context_parts.append("RECENT CONVERSATION:")
            for msg in self.memory.working_context:
                context_parts.append(f"{msg['role'].upper()}: {msg['content']}")
            print(f"   ✓ Recent messages: {len(self.memory.working_context)}")
            for msg in self.memory.working_context:
                preview = msg.get('content', '')[:80]
                print(f"      {msg.get('role','?').upper()}: {preview}{'...' if len(msg.get('content','')) > 80 else ''}")
        else:
            print(f"   ✗ Recent messages: none")

        final_context = "\n".join(context_parts)
        context_tokens_est = len(final_context) // 4
        print(f"\n   📏 Final context: {len(final_context)} chars (~{context_tokens_est} tokens)")
        print(f"{'─'*55}\n")

        trace.step("context_built", f"context assembled: summary={'yes' if self.memory.summary else 'no'}, msgs={len(self.memory.working_context)}, ~{context_tokens_est} tokens", {
            "has_summary": bool(self.memory.summary),
            "recent_messages": len(self.memory.working_context),
            "context_chars": len(final_context),
            "context_tokens_est": context_tokens_est,
        })

        return final_context
    
    def get_recent_messages(self, n: int = 5) -> List[Dict[str, str]]:
        """
        Get the N most recent messages from working context.
        
        Args:
            n: Number of recent messages to return
            
        Returns:
            List of recent message dicts
        """
        return self.memory.working_context[-n:] if self.memory.working_context else []
    
    def get_full_history(self) -> List[Dict[str, str]]:
        """
        Get complete raw history (never truncated).
        
        Returns:
            Complete list of all messages
        """
        return self.memory.raw_history
    
    def get_entity_memory(self) -> Dict[str, List[str]]:
        """
        Get extracted entity memory.
        
        Returns:
            Dictionary of entity types and their values
        """
        return self.memory.entity_memory
    
    def get_summary(self) -> Optional[str]:
        """
        Get current conversation summary.
        
        Returns:
            Summary string or None if not yet summarized
        """
        return self.memory.summary
    
    def clear_memory(self) -> None:
        """
        Clear all memory (use with caution!).
        Resets to initial state.
        """
        self.memory = ConversationMemory(
            MAX_TOKENS_BEFORE_SUMMARY=self.memory.MAX_TOKENS_BEFORE_SUMMARY
        )
        trace.info("Memory: cleared")
    
    def export_memory(self) -> Dict[str, Any]:
        """
        Export memory state to dictionary for persistence.
        
        Returns:
            Dictionary containing all memory state
        """
        return {
            "raw_history": self.memory.raw_history,
            "working_context": self.memory.working_context,
            "entity_memory": self.memory.entity_memory,
            "summary": self.memory.summary,
            "current_token_count": self.memory.current_token_count,
            "MAX_TOKENS_BEFORE_SUMMARY": self.memory.MAX_TOKENS_BEFORE_SUMMARY
        }
    
    def load_memory(self, memory_dict: Dict[str, Any]) -> None:
        """
        Load memory state from dictionary.
        
        Args:
            memory_dict: Dictionary containing memory state (from export_memory)
        """
        self.memory = ConversationMemory(
            raw_history=memory_dict.get("raw_history", []),
            working_context=memory_dict.get("working_context", []),
            entity_memory=memory_dict.get("entity_memory", {}),
            summary=memory_dict.get("summary"),
            current_token_count=memory_dict.get("current_token_count", 0),
            MAX_TOKENS_BEFORE_SUMMARY=memory_dict.get("MAX_TOKENS_BEFORE_SUMMARY", 2000)
        )
        trace.info(f"Memory: loaded from state", {"total_messages": len(self.memory.raw_history), "working_context": len(self.memory.working_context), "has_summary": bool(self.memory.summary)})
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get memory statistics.
        
        Returns:
            Dictionary with memory stats
        """
        return {
            "total_messages": len(self.memory.raw_history),
            "working_context_messages": len(self.memory.working_context),
            "current_tokens": self.memory.current_token_count,
            "max_tokens": self.memory.MAX_TOKENS_BEFORE_SUMMARY,
            "token_utilization": f"{(self.memory.current_token_count / self.memory.MAX_TOKENS_BEFORE_SUMMARY) * 100:.1f}%",
            "has_summary": self.memory.summary is not None,
            "entity_types": len(self.memory.entity_memory),
            "total_entities": sum(len(entities) for entities in self.memory.entity_memory.values())
        }


# Example usage
if __name__ == "__main__":
    import os
    
    # Initialize memory manager
    memory_manager = ConversationMemoryManager(
        openai_api_key=os.getenv("OPENAI_API_KEY", "your-key-here"),
        max_tokens_before_summary=500  # Low threshold for testing
    )
    
    print("="*60)
    print("TESTING CONVERSATION MEMORY MANAGER")
    print("="*60)
    
    # Simulate conversation
    test_messages = [
        ("user", "I need to send an email to john@example.com about the Q4 planning meeting"),
        ("assistant", "What should the subject line be?"),
        ("user", "Use 'Q4 Planning Meeting - Action Items'"),
        ("assistant", "Great! What would you like the email body to say?"),
        ("user", "Hi John, following up on our discussion about Q4 goals. Can we schedule a meeting for next Tuesday at 3pm?"),
        ("assistant", "Perfect! Should I send this email now?"),
        ("user", "Yes, please send it"),
        ("assistant", "✅ Email sent successfully to john@example.com"),
        ("user", "Now search my emails for invoices from last month"),
        ("assistant", "I found 5 invoices from October. Would you like me to list them?"),
    ]
    
    # Add messages (this will trigger summarization when threshold exceeded)
    for role, content in test_messages:
        memory_manager.add_message(role, content)
        print()
    
    # Get stats
    print("="*60)
    print("MEMORY STATS")
    print("="*60)
    stats = memory_manager.get_stats()
    for key, value in stats.items():
        print(f"{key}: {value}")
    
    # Get context for LLM
    print("\n" + "="*60)
    print("CONTEXT FOR LLM")
    print("="*60)
    context = memory_manager.get_context_for_llm()
    print(context)
    
    # Export memory
    print("\n" + "="*60)
    print("EXPORT/LOAD TEST")
    print("="*60)
    exported = memory_manager.export_memory()
    print(f"Exported memory: {len(json.dumps(exported))} characters")
    
    # Create new manager and load
    new_manager = ConversationMemoryManager(
        openai_api_key=os.getenv("OPENAI_API_KEY", "your-key-here")
    )
    new_manager.load_memory(exported)
    print(f"Loaded into new manager: {new_manager.get_stats()['total_messages']} messages")
