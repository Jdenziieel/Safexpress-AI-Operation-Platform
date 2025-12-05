"""
Migration: Add 'name' column back to user_quotas table.

The previous migration accidentally removed the 'name' column.
This script:
1. Adds 'name' column to user_quotas if it doesn't exist
2. Populates the names for known users
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "quota.db")

# Known users to populate
KNOWN_USERS = {
    "5ace696a-1501-46f4-803c-116b9d3bd309": "Josh Denziel Joves",
    "a13657f1-3bbe-4bee-8b16-dc649f457412": "Lance Hilario",
    "c3f4c15a-604f-4e75-bdbd-11572761c2eb": "Carlos Carla",
}

def migrate():
    print(f"📦 Connecting to database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check current schema
    cursor.execute("PRAGMA table_info(user_quotas)")
    columns = {row['name'] for row in cursor.fetchall()}
    print(f"Current columns: {columns}")
    
    if 'name' not in columns:
        print("Adding 'name' column to user_quotas...")
        cursor.execute("ALTER TABLE user_quotas ADD COLUMN name TEXT")
        conn.commit()
        print("  ✅ Added 'name' column")
    else:
        print("  ✅ 'name' column already exists")
    
    # Populate known users
    print("\nPopulating user names...")
    for user_id, name in KNOWN_USERS.items():
        cursor.execute(
            "UPDATE user_quotas SET name = ? WHERE user_id = ?",
            (name, user_id)
        )
        if cursor.rowcount > 0:
            print(f"  ✅ Updated {user_id}: {name}")
        else:
            print(f"  ⚠️ User {user_id} not found in database")
    
    conn.commit()
    
    # Verify
    print("\n📊 Final user_quotas table:")
    cursor.execute("SELECT user_id, name, tier, monthly_limit FROM user_quotas")
    for row in cursor.fetchall():
        print(f"  {row['user_id']}: {row['name']} ({row['tier']}, limit: {row['monthly_limit']})")
    
    conn.close()
    print("\n✅ Migration complete!")

if __name__ == "__main__":
    migrate()
