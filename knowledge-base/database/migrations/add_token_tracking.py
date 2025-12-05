"""
Database migration to add token tracking to sessions table

Run this script to add token tracking capabilities:
python backend/database/migrations/add_token_tracking.py
"""
import sqlite3
import os

def migrate():
    """Add token tracking columns to sessions table"""
    # Get database path - use database/ subdirectory
    db_path = os.path.join(os.path.dirname(__file__), "..", "chat_sessions.db")
    
    print(f"Migrating database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # First, ensure the sessions table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                message_count INTEGER DEFAULT 0,
                metadata TEXT
            )
        """)
        print("✅ Ensured sessions table exists")
        
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(sessions)")
        columns = [col[1] for col in cursor.fetchall()]
        
        changes_made = False
        
        if 'total_tokens_used' not in columns:
            cursor.execute("ALTER TABLE sessions ADD COLUMN total_tokens_used INTEGER DEFAULT 0")
            print("✅ Added total_tokens_used column")
            changes_made = True
        else:
            print("⏭️  total_tokens_used column already exists")
        
        if 'total_cost_usd' not in columns:
            cursor.execute("ALTER TABLE sessions ADD COLUMN total_cost_usd REAL DEFAULT 0.0")
            print("✅ Added total_cost_usd column")
            changes_made = True
        else:
            print("⏭️  total_cost_usd column already exists")
        
        if 'last_token_update' not in columns:
            cursor.execute("ALTER TABLE sessions ADD COLUMN last_token_update TEXT")
            print("✅ Added last_token_update column")
            changes_made = True
        else:
            print("⏭️  last_token_update column already exists")
        
        if changes_made:
            conn.commit()
            print("\n✨ Migration completed successfully!")
        else:
            print("\n✨ No migration needed - all columns already exist")
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    print("="*60)
    print("Token Tracking Migration")
    print("="*60)
    migrate()
    print("="*60)
