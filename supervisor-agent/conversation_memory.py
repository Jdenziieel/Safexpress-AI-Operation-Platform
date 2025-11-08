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


class ConversationMemory(BaseModel):
    """
    Manages conversation history with automatic summarization and entity extraction.
    
    Components:
    - raw_history: Complete message history (never truncated, for record-keeping)
    - working_context: Recent messages that fit within token budget
    - entity_memory: Extracted entities (people, dates, tasks, etc.)
    - summary: Condensed summary of old conversations
    - MAX_TOKENS_BEFORE_SUMMARY: Threshold to trigger summarization
    """
    
    # Complete history (never truncated)
    raw_history: List[Dict[str, str]] = Field(default_factory=list)
    
    # Recent messages that fit in context window
    working_context: List[Dict[str, str]] = Field(default_factory=list)
    
    # Extracted entities from conversation
    entity_memory: Dict[str, Any] = Field(default_factory=dict)
    
    # Summary of old conversation turns
    summary: Optional[str] = None
    
    # Token threshold for triggering summarization
    MAX_TOKENS_BEFORE_SUMMARY: int = Field(default=2000)
    
    # Token count of current working context
    current_token_count: int = Field(default=0)
    
    class Config:
        arbitrary_types_allowed = True


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
    
    def add_message(self, role: str, content: str) -> None:
        """
        Add a new message to conversation history.
        Automatically triggers summarization if token threshold exceeded.
        
        Args:
            role: Message role ("user" or "assistant")
            content: Message content
        """
        message = {"role": role, "content": content}
        
        # Always add to raw history (complete record)
        self.memory.raw_history.append(message)
        
        # Add to working context
        self.memory.working_context.append(message)
        
        # Update token count
        message_tokens = self._count_tokens(role) + self._count_tokens(content) + 4
        self.memory.current_token_count += message_tokens
        
        print(f"📝 Added message: {role} ({message_tokens} tokens)")
        print(f"📊 Current context: {self.memory.current_token_count} / {self.memory.MAX_TOKENS_BEFORE_SUMMARY} tokens")
        
        # Check if summarization is needed
        if self.memory.current_token_count > self.memory.MAX_TOKENS_BEFORE_SUMMARY:
            print(f"⚠️ Token threshold exceeded! Triggering summarization...")
            self._summarize_conversation()
    
    def _summarize_conversation(self) -> None:
        """
        Summarize old conversation turns to free up context space.
        
        Process:
        1. Take first half of working_context (old messages)
        2. Generate summary using LLM
        3. Extract entities from summarized portion
        4. Update summary and entity_memory
        5. Keep only recent messages in working_context
        """
        if len(self.memory.working_context) <= 2:
            # Too few messages to summarize
            print("⚠️ Not enough messages to summarize (need > 2)")
            return
        
        # Split working context: old messages to summarize, recent to keep
        split_point = len(self.memory.working_context) // 2
        old_messages = self.memory.working_context[:split_point]
        recent_messages = self.memory.working_context[split_point:]
        
        print(f"📦 Summarizing {len(old_messages)} old messages, keeping {len(recent_messages)} recent")
        
        # Format old messages for summarization
        conversation_text = ""
        for msg in old_messages:
            conversation_text += f"{msg['role'].upper()}: {msg['content']}\n"
        
        # Build summarization prompt
        previous_summary = self.memory.summary or "No previous summary."
        
        summarization_prompt = f"""You are summarizing a conversation to preserve context while reducing tokens.

PREVIOUS SUMMARY:
{previous_summary}

NEW CONVERSATION TURNS TO SUMMARIZE:
{conversation_text}

Please provide:
1. A concise summary of the conversation (combine with previous summary if exists)
2. Extract key entities mentioned (people, dates, tasks, tools, etc.)

Return JSON with this structure:
{{
    "summary": "Concise summary preserving important context",
    "entities": {{
        "people": ["john@example.com", "Sarah"],
        "tasks": ["send email", "search invoices"],
        "dates": ["tomorrow at 3pm", "last week"],
        "documents": ["Meeting Notes", "Q4 Report"],
        "other": ["API key", "calendar event"]
    }}
}}

Focus on:
- User's goals and intent
- Key information provided (emails, names, dates, etc.)
- Action items or pending tasks
- Important context for future turns

Be concise but preserve all critical information."""

        try:
            llm_response = self.llm.invoke(
                [{"role": "user", "content": summarization_prompt}],
                config={"timeout": 30}
            )
            
            response_text = llm_response.content.strip()
            
            # Handle code blocks
            if response_text.startswith("```json"):
                response_text = response_text[7:-3].strip()
            elif response_text.startswith("```"):
                response_text = response_text[3:-3].strip()
            
            summary_data = json.loads(response_text)
            
            # Update memory with new summary
            self.memory.summary = summary_data.get("summary", "")
            
            # Merge entities with existing entity memory
            new_entities = summary_data.get("entities", {})
            for entity_type, entity_list in new_entities.items():
                if entity_type not in self.memory.entity_memory:
                    self.memory.entity_memory[entity_type] = []
                
                # Add new entities (avoid duplicates)
                for entity in entity_list:
                    if entity not in self.memory.entity_memory[entity_type]:
                        self.memory.entity_memory[entity_type].append(entity)
            
            # Update working context (keep only recent messages)
            self.memory.working_context = recent_messages
            
            # Recalculate token count
            self.memory.current_token_count = self._count_message_tokens(recent_messages)
            
            print(f"✅ Summarization complete!")
            print(f"   Summary: {self.memory.summary[:100]}...")
            print(f"   Entities: {len(self.memory.entity_memory)} types")
            print(f"   New context size: {self.memory.current_token_count} tokens")
            
        except Exception as e:
            print(f"⚠️ Summarization failed: {e}")
            # Fallback: just drop oldest message
            if len(self.memory.working_context) > 0:
                dropped = self.memory.working_context.pop(0)
                print(f"⚠️ Fallback: Dropped oldest message")
                self.memory.current_token_count = self._count_message_tokens(self.memory.working_context)
    
    def get_context_for_llm(self) -> str:
        """
        Build complete context string for downstream LLM.
        
        Combines:
        1. Conversation summary (if exists)
        2. Entity memory (if exists)
        3. Recent message history
        
        Returns:
            Formatted context string ready for LLM consumption
        """
        context_parts = []
        
        # Add summary if exists
        if self.memory.summary:
            context_parts.append("CONVERSATION SUMMARY:")
            context_parts.append(self.memory.summary)
            context_parts.append("")
        
        # Add entity memory if exists
        if self.memory.entity_memory:
            context_parts.append("KNOWN ENTITIES:")
            for entity_type, entities in self.memory.entity_memory.items():
                if entities:
                    context_parts.append(f"  {entity_type.upper()}: {', '.join(entities)}")
            context_parts.append("")
        
        # Add recent message history
        if self.memory.working_context:
            context_parts.append("RECENT CONVERSATION:")
            for msg in self.memory.working_context:
                context_parts.append(f"{msg['role'].upper()}: {msg['content']}")
        
        return "\n".join(context_parts)
    
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
        print("🗑️ Memory cleared")
    
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
        print(f"📥 Memory loaded: {len(self.memory.raw_history)} total messages")
    
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
