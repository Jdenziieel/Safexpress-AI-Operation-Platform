"""
Thread Manager - Persistent Thread Storage and Management (SQLite)

Handles:
- Thread creation and metadata
- Thread listing per user
- Thread continuation (load from DB)
- Thread archiving/deletion
- Thread search
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
import json
import sqlite3
from pathlib import Path


class ThreadMetadata(BaseModel):
    """Metadata for a conversation thread"""
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat()
        }
    )
    
    thread_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    title: Optional[str] = None  # Auto-generated from first message
    message_count: int = 0
    status: str = "active"  # active, archived, deleted
    last_message_preview: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class ThreadManager:
    """
    Manages conversation threads with SQLite persistent storage.
    
    Database Tables:
    - threads: Main thread metadata
    - thread_states: Conversation state (JSON blob)
    - memory_states: Memory state (JSON blob)
    
    Features:
    - Create/list/get/update/delete threads
    - Thread metadata tracking
    - Search threads by user/title/tags
    - Load thread state for continuation
    - Auto-generate thread titles
    """
    
    def __init__(self, db_path: str = "threads.db"):
        """
        Initialize thread manager with SQLite database.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self._init_database()
        print(f"✅ SQLite thread manager initialized: {self.db_path}")
    
    def _get_connection(self):
        """Get a database connection with foreign keys enabled"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    
    def _init_database(self):
        """Create database tables if they don't exist"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Enable foreign key constraints (MUST be done for each connection in SQLite)
        cursor.execute("PRAGMA foreign_keys = ON")
        
        # Threads table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS threads (
                thread_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                title TEXT,
                message_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                last_message_preview TEXT,
                tags TEXT
            )
        """)
        
        # Thread states table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS thread_states (
                thread_id TEXT PRIMARY KEY,
                conversation_state TEXT,
                FOREIGN KEY (thread_id) REFERENCES threads(thread_id) ON DELETE CASCADE
            )
        """)
        
        # Memory states table  
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_states (
                thread_id TEXT PRIMARY KEY,
                memory_state TEXT,
                FOREIGN KEY (thread_id) REFERENCES threads(thread_id) ON DELETE CASCADE
            )
        """)
        
        # Messages table - individual conversation turns
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (thread_id) REFERENCES threads(thread_id) ON DELETE CASCADE
            )
        """)
        
        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON threads(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON threads(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_updated_at ON threads(updated_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at)")
        
        conn.commit()
        conn.close()
    
    def create_thread(
        self, 
        user_id: str, 
        thread_id: Optional[str] = None,
        title: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> ThreadMetadata:
        """
        Create a new thread.
        
        Args:
            user_id: User identifier
            thread_id: Optional custom thread ID (auto-generated if None)
            title: Optional thread title
            tags: Optional tags for categorization
        
        Returns:
            ThreadMetadata of created thread
        """
        import uuid
        
        if thread_id is None:
            thread_id = f"{user_id}_{uuid.uuid4().hex[:8]}"
        
        now = datetime.utcnow().isoformat()
        tags_json = json.dumps(tags or [])
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO threads (thread_id, user_id, created_at, updated_at, title, message_count, status, tags)
            VALUES (?, ?, ?, ?, ?, 0, 'active', ?)
        """, (thread_id, user_id, now, now, title or "New Conversation", tags_json))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Created thread: {thread_id} for user: {user_id}")
        
        return ThreadMetadata(
            thread_id=thread_id,
            user_id=user_id,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
            title=title or "New Conversation",
            message_count=0,
            status="active",
            tags=tags or []
        )
    
    def get_thread(self, thread_id: str) -> Optional[ThreadMetadata]:
        """Get thread metadata by ID"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT thread_id, user_id, created_at, updated_at, title,
                   message_count, status, last_message_preview, tags
            FROM threads
            WHERE thread_id = ?
        """, (thread_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        # Parse tags safely
        try:
            tags = json.loads(row[8]) if row[8] else []
        except (json.JSONDecodeError, TypeError):
            tags = []
        
        return ThreadMetadata(
            thread_id=row[0],
            user_id=row[1],
            created_at=datetime.fromisoformat(row[2]),
            updated_at=datetime.fromisoformat(row[3]),
            title=row[4],
            message_count=row[5],
            status=row[6],
            last_message_preview=row[7],
            tags=tags
        )
    
    def list_threads(
        self, 
        user_id: str,
        status: str = "active",
        limit: int = 50,
        offset: int = 0
    ) -> List[ThreadMetadata]:
        """List threads for a user"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT thread_id, user_id, created_at, updated_at, title,
                   message_count, status, last_message_preview, tags
            FROM threads
            WHERE user_id = ? AND status = ?
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
        """, (user_id, status, limit, offset))
        
        rows = cursor.fetchall()
        conn.close()
        
        threads = []
        for row in rows:
            # Parse tags safely
            try:
                tags = json.loads(row[8]) if row[8] else []
            except (json.JSONDecodeError, TypeError):
                tags = []
            
            threads.append(ThreadMetadata(
                thread_id=row[0],
                user_id=row[1],
                created_at=datetime.fromisoformat(row[2]),
                updated_at=datetime.fromisoformat(row[3]),
                title=row[4],
                message_count=row[5],
                status=row[6],
                last_message_preview=row[7],
                tags=tags
            ))
        
        return threads
    
    def update_thread(
        self,
        thread_id: str,
        title: Optional[str] = None,
        message_count: Optional[int] = None,
        last_message_preview: Optional[str] = None,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None
    ):
        """Update thread metadata"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        updates = ["updated_at = ?"]
        params = [datetime.utcnow().isoformat()]
        
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if message_count is not None:
            updates.append("message_count = ?")
            params.append(message_count)
        if last_message_preview is not None:
            updates.append("last_message_preview = ?")
            params.append(last_message_preview)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if tags is not None:
            updates.append("tags = ?")
            params.append(json.dumps(tags))
        
        params.append(thread_id)
        
        sql = f"UPDATE threads SET {', '.join(updates)} WHERE thread_id = ?"
        cursor.execute(sql, params)
        
        conn.commit()
        conn.close()
    
    def save_thread_state(self, thread_id: str, state: Any):
        """Save ConversationState to database"""
        # Handle Pydantic v2 models
        if hasattr(state, 'model_dump'):
            state_dict = state.model_dump()
        else:
            state_dict = state  # Already a dict
        
        state_json = json.dumps(state_dict, default=str)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO thread_states (thread_id, conversation_state)
            VALUES (?, ?)
        """, (thread_id, state_json))
        
        conn.commit()
        conn.close()
    
    def load_thread_state(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """Load ConversationState from database"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT conversation_state FROM thread_states WHERE thread_id = ?
        """, (thread_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row or not row[0]:
            return None
        
        return json.loads(row[0])
    
    def save_memory_state(self, thread_id: str, memory: Dict[str, Any]):
        """Save ConversationMemory to database"""
        memory_json = json.dumps(memory, default=str)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO memory_states (thread_id, memory_state)
            VALUES (?, ?)
        """, (thread_id, memory_json))
        
        conn.commit()
        conn.close()
    
    def load_memory_state(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """Load ConversationMemory from database"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT memory_state FROM memory_states WHERE thread_id = ?
        """, (thread_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row or not row[0]:
            return None
        
        return json.loads(row[0])
    
    def archive_thread(self, thread_id: str):
        """Archive a thread (soft delete)"""
        self.update_thread(thread_id, status="archived")
        print(f"📦 Archived thread: {thread_id}")
    
    def delete_thread(self, thread_id: str, hard_delete: bool = False):
        """Delete a thread (soft or hard delete)"""
        if hard_delete:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM memory_states WHERE thread_id = ?", (thread_id,))
            cursor.execute("DELETE FROM thread_states WHERE thread_id = ?", (thread_id,))
            cursor.execute("DELETE FROM threads WHERE thread_id = ?", (thread_id,))
            
            conn.commit()
            conn.close()
            print(f"🗑️ Hard deleted thread: {thread_id}")
        else:
            self.update_thread(thread_id, status="deleted")
            print(f"🗑️ Soft deleted thread: {thread_id}")
    
    def search_threads(
        self,
        user_id: str,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 20
    ) -> List[ThreadMetadata]:
        """Search threads by title or tags"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        sql = """
            SELECT thread_id, user_id, created_at, updated_at, title,
                   message_count, status, last_message_preview, tags
            FROM threads
            WHERE user_id = ? AND status = 'active'
        """
        params = [user_id]
        
        if query:
            sql += " AND (title LIKE ? OR last_message_preview LIKE ?)"
            params.extend([f"%{query}%", f"%{query}%"])
        
        if tags:
            for tag in tags:
                sql += " AND tags LIKE ?"
                params.append(f'%"{tag}"%')
        
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        
        threads = []
        for row in rows:
            # Parse tags safely
            try:
                tags = json.loads(row[8]) if row[8] else []
            except (json.JSONDecodeError, TypeError):
                tags = []
            
            threads.append(ThreadMetadata(
                thread_id=row[0],
                user_id=row[1],
                created_at=datetime.fromisoformat(row[2]),
                updated_at=datetime.fromisoformat(row[3]),
                title=row[4],
                message_count=row[5],
                status=row[6],
                last_message_preview=row[7],
                tags=tags
            ))
        
        return threads
    
    def auto_generate_title(self, first_message: str, max_length: int = 50) -> str:
        """
        Auto-generate thread title from first message.
        
        Args:
            first_message: First user message in thread
            max_length: Maximum title length
        
        Returns:
            Generated title
        """
        # Simple title generation (could use LLM for better results)
        title = first_message.strip()
        if len(title) > max_length:
            title = title[:max_length] + "..."
        return title
    
    def get_thread_count(self, user_id: str, status: str = "active") -> int:
        """Get count of threads for a user"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) FROM threads
            WHERE user_id = ? AND status = ?
        """, (user_id, status))
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count
    
    def add_message(self, thread_id: str, role: str, content: str) -> int:
        """
        Add a message to a thread.
        
        Args:
            thread_id: Thread identifier
            role: Message role ('user' or 'assistant')
            content: Message content
        
        Returns:
            message_id of the created message
        """
        now = datetime.utcnow().isoformat()
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO messages (thread_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
        """, (thread_id, role, content, now))
        
        message_id = cursor.lastrowid
        
        # Update thread message count and last message preview
        preview = content[:100] if len(content) > 100 else content
        cursor.execute("""
            UPDATE threads 
            SET message_count = message_count + 1,
                last_message_preview = ?,
                updated_at = ?
            WHERE thread_id = ?
        """, (preview, now, thread_id))
        
        conn.commit()
        conn.close()
        
        return message_id
    
    def get_messages(self, thread_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """
        Get messages from a thread.
        
        Args:
            thread_id: Thread identifier
            limit: Maximum number of messages to return
            offset: Offset for pagination
        
        Returns:
            List of message dictionaries with id, role, content, created_at
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT message_id, thread_id, role, content, created_at
            FROM messages
            WHERE thread_id = ?
            ORDER BY created_at ASC
            LIMIT ? OFFSET ?
        """, (thread_id, limit, offset))
        
        rows = cursor.fetchall()
        conn.close()
        
        messages = []
        for row in rows:
            messages.append({
                'message_id': row[0],
                'thread_id': row[1],
                'role': row[2],
                'content': row[3],
                'created_at': row[4]
            })
        
        return messages
    
    def get_message_count(self, thread_id: str) -> int:
        """Get count of messages in a thread"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) FROM messages WHERE thread_id = ?
        """, (thread_id,))
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count


# Example usage
if __name__ == "__main__":
    print("="*80)
    print("THREAD MANAGER DEMO - SQLite")
    print("="*80)
    
    manager = ThreadManager("threads_demo.db")
    
    # Create threads
    print("\n1. Creating threads...")
    thread1 = manager.create_thread(
        user_id="user_123",
        title="Email to john@example.com",
        tags=["email", "work"]
    )
    print(f"   Thread 1: {thread1.thread_id}")
    
    thread2 = manager.create_thread(
        user_id="user_123",
        title="Search for invoices",
        tags=["search", "invoices"]
    )
    print(f"   Thread 2: {thread2.thread_id}")
    
    # List threads
    print("\n2. Listing threads for user_123...")
    threads = manager.list_threads("user_123")
    print(f"   Found {len(threads)} threads:")
    for t in threads:
        print(f"   - {t.title} ({t.thread_id})")
    
    # Update thread
    print("\n3. Updating thread metadata...")
    manager.update_thread(
        thread1.thread_id,
        message_count=5,
        last_message_preview="Send email to john@example.com with subject..."
    )
    print(f"   Updated thread: {thread1.thread_id}")
    
    # Save state
    print("\n4. Saving thread state...")
    sample_state = {
        "extracted_info": {"to": "john@example.com", "subject": "Meeting"},
        "missing_fields": ["body"],
        "intent": "needs_clarification"
    }
    manager.save_thread_state(thread1.thread_id, sample_state)
    print(f"   Saved state for: {thread1.thread_id}")
    
    # Add messages to thread
    print("\n5. Adding messages to thread...")
    msg1_id = manager.add_message(thread1.thread_id, "user", "Send an email to john@example.com")
    msg2_id = manager.add_message(thread1.thread_id, "assistant", "I'd be happy to help you send an email. What should the subject be?")
    msg3_id = manager.add_message(thread1.thread_id, "user", "The subject is 'Meeting Notes'")
    msg4_id = manager.add_message(thread1.thread_id, "assistant", "Great! What would you like to say in the email body?")
    print(f"   Added 4 messages (IDs: {msg1_id}, {msg2_id}, {msg3_id}, {msg4_id})")
    
    # Get messages
    print("\n6. Retrieving messages from thread...")
    messages = manager.get_messages(thread1.thread_id)
    print(f"   Found {len(messages)} messages:")
    for msg in messages:
        role_icon = "👤" if msg['role'] == 'user' else "🤖"
        content_preview = msg['content'][:50] + "..." if len(msg['content']) > 50 else msg['content']
        print(f"   {role_icon} {msg['role']}: {content_preview}")
    
    # Load state
    print("\n7. Loading thread state...")
    loaded_state = manager.load_thread_state(thread1.thread_id)
    print(f"   Loaded state: {loaded_state}")
    
    # Search threads
    print("\n8. Searching threads...")
    results = manager.search_threads("user_123", query="email")
    print(f"   Search 'email': {len(results)} results")
    for r in results:
        print(f"   - {r.title}")
    
    # Archive thread
    print("\n9. Archiving thread...")
    manager.archive_thread(thread2.thread_id)
    
    # List active threads
    print("\n10. Listing active threads...")
    active = manager.list_threads("user_123", status="active")
    print(f"   Active threads: {len(active)}")
    
    # Get count
    print("\n11. Getting thread count...")
    count = manager.get_thread_count("user_123")
    print(f"   Total active threads for user_123: {count}")
    
    print("\n" + "="*80)

