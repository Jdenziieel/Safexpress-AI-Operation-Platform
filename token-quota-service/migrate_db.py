"""
Database migration script to clean up the token-quota-service database.

Changes:
1. Remove 'name' and 'user_name' columns from usage_log (keep user_id only)
2. Remove 'name' column from user_quotas (keep user_id only)
3. Remove 'org_id' column from usage_log and user_quotas
4. Drop 'org_quotas' table entirely
5. Ensure cost_usd defaults to 0.0 not NULL
"""

import sqlite3
import os

def migrate_database():
    db_path = os.path.join(os.path.dirname(__file__), "quota.db")
    
    print(f"🔧 Starting database migration for: {db_path}")
    print("-" * 60)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # SQLite doesn't support DROP COLUMN directly, so we need to recreate tables
    
    # Step 1: Recreate usage_log table without name, user_name, and org_id
    print("📝 Migrating usage_log table...")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usage_log_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            service TEXT NOT NULL,
            operation TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            total_tokens INTEGER NOT NULL,
            cost_usd REAL NOT NULL DEFAULT 0.0,
            request_id TEXT,
            session_id TEXT,
            metadata TEXT,
            timestamp TEXT NOT NULL
        )
    """)
    
    # Copy data from old table
    cursor.execute("""
        INSERT INTO usage_log_new 
        (id, user_id, service, operation, model, input_tokens, output_tokens, 
         total_tokens, cost_usd, request_id, session_id, metadata, timestamp)
        SELECT 
            id, user_id, service, operation, model, input_tokens, output_tokens,
            total_tokens, COALESCE(cost_usd, 0.0), request_id, session_id, metadata, timestamp
        FROM usage_log
    """)
    
    # Drop old table and rename new one
    cursor.execute("DROP TABLE usage_log")
    cursor.execute("ALTER TABLE usage_log_new RENAME TO usage_log")
    
    # Recreate indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_log(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_log(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_usage_service ON usage_log(service)")
    
    print("  ✅ usage_log migrated - removed name, user_name, org_id columns")
    
    # Step 2: Recreate user_quotas table without name, user_name, and org_id
    print("📝 Migrating user_quotas table...")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_quotas_new (
            user_id TEXT PRIMARY KEY,
            tier TEXT DEFAULT 'free',
            monthly_limit INTEGER DEFAULT 100000,
            current_usage INTEGER DEFAULT 0,
            current_cost_usd REAL NOT NULL DEFAULT 0.0,
            reset_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            deactivated_at TEXT
        )
    """)
    
    # Copy data from old table
    cursor.execute("""
        INSERT INTO user_quotas_new 
        (user_id, tier, monthly_limit, current_usage, current_cost_usd, 
         reset_date, created_at, updated_at, is_active, deactivated_at)
        SELECT 
            user_id, tier, monthly_limit, current_usage, COALESCE(current_cost_usd, 0.0),
            reset_date, created_at, updated_at, is_active, deactivated_at
        FROM user_quotas
    """)
    
    # Drop old table and rename new one
    cursor.execute("DROP TABLE user_quotas")
    cursor.execute("ALTER TABLE user_quotas_new RENAME TO user_quotas")
    
    # Recreate indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_tier ON user_quotas(tier)")
    
    print("  ✅ user_quotas migrated - removed name, user_name, org_id columns")
    
    # Step 3: Drop org_quotas table
    print("📝 Dropping org_quotas table...")
    cursor.execute("DROP TABLE IF EXISTS org_quotas")
    print("  ✅ org_quotas table dropped")
    
    # Commit changes
    conn.commit()
    
    # Verify the changes
    print("\n" + "-" * 60)
    print("📊 Verification:")
    
    cursor.execute("PRAGMA table_info(usage_log)")
    print("\nusage_log columns:")
    for row in cursor.fetchall():
        print(f"  - {row[1]} ({row[2]})")
    
    cursor.execute("PRAGMA table_info(user_quotas)")
    print("\nuser_quotas columns:")
    for row in cursor.fetchall():
        print(f"  - {row[1]} ({row[2]})")
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    print("\nAll tables:")
    for row in cursor.fetchall():
        print(f"  - {row[0]}")
    
    conn.close()
    print("\n✅ Database migration completed successfully!")


if __name__ == "__main__":
    migrate_database()
