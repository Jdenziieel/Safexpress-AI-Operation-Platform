"""
Migration: Rename 'name' column to 'fullname' in user_quotas table.

This ensures consistency with the auth_user table which uses 'fullname'.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "quota.db")

def migrate():
    print(f"📦 Connecting to database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check current schema
    cursor.execute("PRAGMA table_info(user_quotas)")
    columns = {row['name'] for row in cursor.fetchall()}
    print(f"Current columns: {columns}")
    
    if 'name' in columns and 'fullname' not in columns:
        print("Renaming 'name' column to 'fullname'...")
        # SQLite doesn't support RENAME COLUMN in older versions, so we need to recreate
        cursor.execute("ALTER TABLE user_quotas RENAME COLUMN name TO fullname")
        conn.commit()
        print("  ✅ Renamed 'name' to 'fullname'")
    elif 'fullname' in columns:
        print("  ✅ 'fullname' column already exists")
    elif 'name' not in columns and 'fullname' not in columns:
        print("Adding 'fullname' column...")
        cursor.execute("ALTER TABLE user_quotas ADD COLUMN fullname TEXT")
        conn.commit()
        print("  ✅ Added 'fullname' column")
    
    # Verify
    cursor.execute("PRAGMA table_info(user_quotas)")
    columns = [row['name'] for row in cursor.fetchall()]
    print(f"\nFinal columns: {columns}")
    
    # Show data
    print("\n📊 user_quotas data:")
    cursor.execute("SELECT user_id, fullname, tier FROM user_quotas")
    for row in cursor.fetchall():
        print(f"  {row['user_id']}: {row['fullname']} ({row['tier']})")
    
    conn.close()
    print("\n✅ Migration complete!")

if __name__ == "__main__":
    migrate()
