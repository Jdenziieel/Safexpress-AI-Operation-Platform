# database/chat_db.py
import sqlite3
import json
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Optional

class ChatDatabase:
    def __init__(self, db_path: str = "database/chat_sessions.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                message_count INTEGER DEFAULT 0,
                total_tokens_used INTEGER DEFAULT 0,
                total_cost_usd REAL DEFAULT 0.0,
                last_token_update TEXT,
                metadata TEXT
            )
        """)
        
        # Messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                sources TEXT,
                metadata TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions (session_id)
            )
        """)
        
        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_user ON sessions(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_session ON messages(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_timestamp ON messages(timestamp)")
        
        conn.commit()
        conn.close()
    
    def create_session(self, user_id: str, title: str = None) -> Dict:
        """Create new chat session"""
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO sessions (session_id, user_id, title, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, user_id, title, now, now, json.dumps({})))
        
        conn.commit()
        conn.close()
        
        return {
            'session_id': session_id,
            'user_id': user_id,
            'title': title or 'New Chat',
            'created_at': now,
            'message_count': 0
        }
    
    def update_session_title(self, session_id: str, title: str) -> bool:
        """Update session title"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE sessions SET title = ?, updated_at = ?
                WHERE session_id = ?
            """, (title, datetime.now(timezone.utc).isoformat(), session_id))
            
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            
            return affected > 0
        except Exception as e:
            print(f"Error updating session title: {e}")
            return False
    
    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        sources: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None
    ) -> Dict:
        """Save a message to the session"""
        message_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO messages (message_id, session_id, role, content, timestamp, sources, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            message_id,
            session_id,
            role,
            content,
            now,
            json.dumps(sources or []),
            json.dumps(metadata or {})
        ))
        
        # Update session
        cursor.execute("""
            UPDATE sessions
            SET updated_at = ?, message_count = message_count + 1
            WHERE session_id = ?
        """, (now, session_id))
        
        # Update token usage if this is an assistant message with token data
        if role == "assistant" and metadata and 'tokens_used' in metadata:
            tokens = metadata['tokens_used']
            # Estimate cost: $5/1M input + $15/1M output, approximate 50/50 split = $10/1M average
            cost = (tokens / 1_000_000) * 10
            
            cursor.execute("""
                UPDATE sessions
                SET total_tokens_used = total_tokens_used + ?,
                    total_cost_usd = total_cost_usd + ?,
                    last_token_update = ?
                WHERE session_id = ?
            """, (tokens, cost, now, session_id))
        
        # Auto-generate title from first user message
        cursor.execute("""
            SELECT title, message_count FROM sessions WHERE session_id = ?
        """, (session_id,))
        
        result = cursor.fetchone()
        if result:
            current_title, message_count = result
            if message_count == 1 and role == "user" and (not current_title or current_title == "New Chat"):
                title = content[:50] + "..." if len(content) > 50 else content
                cursor.execute("""
                    UPDATE sessions SET title = ? WHERE session_id = ?
                """, (title, session_id))
        
        conn.commit()
        conn.close()
        
        return {
            'message_id': message_id,
            'session_id': session_id,
            'role': role,
            'content': content,
            'sources': sources or [],
            'metadata': metadata or {},
            'timestamp': now
        }
    
    def get_session_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> List[Dict]:
        """Get all messages for a session"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = """
            SELECT * FROM messages
            WHERE session_id = ?
            ORDER BY timestamp ASC
        """
        
        if limit:
            query += f" LIMIT {limit} OFFSET {offset}"
        
        cursor.execute(query, (session_id,))
        rows = cursor.fetchall()
        conn.close()
        
        messages = []
        for row in rows:
            messages.append({
                'message_id': row['message_id'],
                'session_id': row['session_id'],
                'role': row['role'],
                'content': row['content'],
                'timestamp': row['timestamp'],
                'sources': json.loads(row['sources']) if row['sources'] else [],
                'metadata': json.loads(row['metadata']) if row['metadata'] else {}
            })
        
        return messages
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """Get session by ID"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM sessions WHERE session_id = ?
        """, (session_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return {
            'session_id': row['session_id'],
            'user_id': row['user_id'],
            'title': row['title'] or 'New Chat',
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
            'message_count': row['message_count'],
            'metadata': json.loads(row['metadata']) if row['metadata'] else {}
        }
    
    def get_user_sessions(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0
    ) -> tuple[List[Dict], int]:
        """Get all sessions for a user with pagination"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get total count
        cursor.execute("""
            SELECT COUNT(*) FROM sessions WHERE user_id = ?
        """, (user_id,))
        total = cursor.fetchone()[0]
        
        # Get sessions
        cursor.execute("""
            SELECT * FROM sessions
            WHERE user_id = ?
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
        """, (user_id, limit, offset))
        
        rows = cursor.fetchall()
        conn.close()
        
        sessions = []
        for row in rows:
            sessions.append({
                'session_id': row['session_id'],
                'user_id': row['user_id'],
                'title': row['title'] or 'New Chat',
                'created_at': row['created_at'],
                'updated_at': row['updated_at'],
                'message_count': row['message_count'],
                'metadata': json.loads(row['metadata']) if row['metadata'] else {}
            })
        
        return sessions, total
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its messages"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Delete messages first (foreign key constraint)
        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        
        # Delete session
        cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        return affected > 0
    
    def update_session_metadata(self, session_id: str, metadata: Dict) -> bool:
        """Update session metadata"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE sessions
            SET metadata = ?, updated_at = ?
            WHERE session_id = ?
        """, (json.dumps(metadata), datetime.now(timezone.utc).isoformat(), session_id))
        
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        return affected > 0
    
    def get_session_token_usage(self, session_id: str) -> Optional[Dict]:
        """Get token usage statistics for a session"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT total_tokens_used, total_cost_usd, last_token_update
            FROM sessions
            WHERE session_id = ?
        """, (session_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return {
            'total_tokens': row['total_tokens_used'] or 0,
            'total_cost_usd': row['total_cost_usd'] or 0.0,
            'last_update': row['last_token_update']
        }
    
    def get_user_total_tokens(self, user_id: str) -> Dict:
        """Get total token usage across all sessions for a user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                SUM(total_tokens_used) as total_tokens,
                SUM(total_cost_usd) as total_cost,
                COUNT(*) as session_count
            FROM sessions
            WHERE user_id = ?
        """, (user_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        return {
            'total_tokens': row[0] or 0,
            'total_cost_usd': row[1] or 0.0,
            'session_count': row[2] or 0
        }

