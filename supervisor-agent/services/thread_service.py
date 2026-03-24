"""
Thread Service - Business logic for thread management.

Handles thread CRUD operations, state persistence, and memory management.
Extracted from ConversationalAgent to separate thread management concerns
from conversation analysis logic.
"""

from typing import Optional, List, Dict, Any, Callable
from models.models import ConversationState
from thread_manager import ThreadManager


class ThreadService:
    """
    Service layer for conversation thread management.

    Coordinates between ThreadManager (DB), memory managers, and
    the conversation processing pipeline.

    Dependencies:
        thread_manager: ThreadManager instance for DB operations
        memory_managers: Shared dict of ConversationMemoryManager instances
        process_message_fn: Callable to process a message through ConversationalAgent
        get_memory_manager_fn: Callable to get/create a memory manager for a conversation
    """

    def __init__(
        self,
        thread_manager: ThreadManager,
        memory_managers: Dict[str, Any],
        process_message_fn: Callable,
        get_memory_manager_fn: Callable,
    ):
        self.thread_manager = thread_manager
        self.memory_managers = memory_managers
        self.process_message_fn = process_message_fn
        self.get_memory_manager_fn = get_memory_manager_fn

    def create_new_thread(
        self,
        user_id: str,
        initial_message: Optional[str] = None
    ) -> tuple[str, ConversationState, Optional[str]]:
        """
        Create a new conversation thread with persistent storage.

        Args:
            user_id: Unique identifier for the user
            initial_message: Optional first message to process

        Returns:
            Tuple of (thread_id, initial_conversation_state, bot_response)
            bot_response is None if no initial_message provided
        """
        # 1. Create thread in database in thread_manager.py
        thread_metadata = self.thread_manager.create_thread(
            user_id=user_id
        )
        thread_id = thread_metadata.thread_id

        # 2. Initialize conversation state
        conversation_state = ConversationState()
        bot_response = None

        # 3. Process initial message if provided go to conversational_agent.py process_message method.
        new_title = None
        if initial_message:
            bot_response, conversation_state = self.process_message_fn(
                user_message=initial_message,
                conversation_state=conversation_state,
                state_id=thread_id,
                auto_save=True
            )

            # Auto-generate title from first message
            new_title = self.thread_manager.auto_generate_title(initial_message)
            self.thread_manager.update_thread(thread_id, title=new_title)
        else:
            # Save initial empty state
            self.save_thread_to_db(thread_id, conversation_state)

        print(f"✅ Created new thread: {thread_id} for user: {user_id} with title: {new_title}")

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
        conversation_state = self.load_thread_from_db(thread_id)

        if conversation_state is None:
            raise ValueError(f"Thread {thread_id} not found")

        # Process the new message with auto-save enabled
        response, conversation_state = self.process_message_fn(
            user_message=new_message,
            conversation_state=conversation_state,
            state_id=thread_id,
            auto_save=True
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

    def save_thread_to_db(self, thread_id: str, conversation_state: ConversationState) -> None:
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

    def load_thread_from_db(self, thread_id: str) -> Optional[ConversationState]:
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
            self.get_memory_manager_fn(thread_id, memory_data)

        return conversation_state
