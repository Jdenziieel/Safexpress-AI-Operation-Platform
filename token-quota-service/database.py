"""
SQLite Database for Token Quota Service

Tables:
1. user_quotas - User quota limits and current usage
2. org_quotas - Organization-level quotas (optional)
3. usage_log - Detailed log of all token usage
"""

import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path
import json
import os

from models import (
    UserQuota, QuotaTier, TIER_LIMITS,
    ServiceUsage, UsageSummary
)


class QuotaDatabase:
    """SQLite database for quota management."""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), "quota.db")
        self.db_path = db_path
        self._connection = None
    
    @property
    def conn(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
        return self._connection
    
    def initialize(self):
        """Create tables if they don't exist."""
        cursor = self.conn.cursor()
        
        # User quotas table (with fullname, no org_id)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_quotas (
                user_id TEXT PRIMARY KEY,
                fullname TEXT,
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
        
        # Usage log table (with fullname for display)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                fullname TEXT,
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
        
        # Admin actions log table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_actions_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id TEXT,
                admin_name TEXT,
                action TEXT NOT NULL,
                target_user_id TEXT,
                target_user_name TEXT,
                details TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        
        # Indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_log(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_log(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_usage_service ON usage_log(service)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_tier ON user_quotas(tier)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_admin_actions_timestamp ON admin_actions_log(timestamp)")
        
        self.conn.commit()
        print(f"✓ Database initialized: {self.db_path}")
    
    def _get_next_reset_date(self) -> str:
        """Calculate the first day of next month."""
        now = datetime.now(timezone.utc)
        if now.month == 12:
            next_month = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            next_month = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
        return next_month.isoformat()
    
    def _now(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()
    
    # ==========================================================================
    # USER QUOTA OPERATIONS
    # ==========================================================================
    
    def get_user_quota(self, user_id: str, include_inactive: bool = False) -> Optional[UserQuota]:
        """Get quota info for a user. By default only returns active users."""
        cursor = self.conn.cursor()
        
        if include_inactive:
            cursor.execute(
                "SELECT * FROM user_quotas WHERE user_id = ?",
                (user_id,)
            )
        else:
            # Only return active users (is_active = 1 or NULL for backwards compatibility)
            cursor.execute(
                "SELECT * FROM user_quotas WHERE user_id = ? AND (is_active = 1 OR is_active IS NULL)",
                (user_id,)
            )
        row = cursor.fetchone()
        
        if row:
            # Handle is_active: treat NULL as True (active) for backwards compatibility
            is_active_val = row["is_active"] if "is_active" in row.keys() else None
            is_active = True if is_active_val is None else bool(is_active_val)
            
            return UserQuota(
                user_id=row["user_id"],
                fullname=row["fullname"] if "fullname" in row.keys() else None,
                tier=row["tier"],
                monthly_limit=row["monthly_limit"],
                current_usage=row["current_usage"] or 0,
                current_cost_usd=row["current_cost_usd"] or 0.0,
                reset_date=row["reset_date"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                is_active=is_active,
                deactivated_at=row["deactivated_at"] if "deactivated_at" in row.keys() else None
            )
        return None
    
    def create_user_quota(
        self,
        user_id: str,
        fullname: str = None,
        tier: str = QuotaTier.FREE.value
    ) -> UserQuota:
        """Create a new user with default quota."""
        now = self._now()
        reset_date = self._get_next_reset_date()
        monthly_limit = TIER_LIMITS.get(QuotaTier(tier), TIER_LIMITS[QuotaTier.FREE])
        
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO user_quotas 
            (user_id, fullname, tier, monthly_limit, current_usage, current_cost_usd, reset_date, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, 0.0, ?, ?, ?)
        """, (user_id, fullname, tier, monthly_limit, reset_date, now, now))
        
        self.conn.commit()
        
        return self.get_user_quota(user_id)
    
    def update_user_quota(
        self,
        user_id: str,
        tier: str = None,
        monthly_limit: int = None,
        reset_date: str = None
    ) -> UserQuota:
        """Update user quota settings."""
        updates = []
        params = []
        
        if tier is not None:
            updates.append("tier = ?")
            params.append(tier)
            # If tier changes and no custom limit, use tier default
            if monthly_limit is None:
                try:
                    monthly_limit = TIER_LIMITS[QuotaTier(tier)]
                except ValueError:
                    pass
        
        if monthly_limit is not None:
            updates.append("monthly_limit = ?")
            params.append(monthly_limit)
        
        if reset_date is not None:
            # Convert date string to ISO format if needed
            if 'T' not in reset_date:
                reset_date = f"{reset_date}T00:00:00Z"
            updates.append("reset_date = ?")
            params.append(reset_date)
        
        if updates:
            updates.append("updated_at = ?")
            params.append(self._now())
            params.append(user_id)
            
            cursor = self.conn.cursor()
            cursor.execute(
                f"UPDATE user_quotas SET {', '.join(updates)} WHERE user_id = ?",
                params
            )
            self.conn.commit()
        
        return self.get_user_quota(user_id)
    
    def update_fullname(self, user_id: str, fullname: str) -> bool:
        """Update user's display name."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE user_quotas SET fullname = ?, updated_at = ? WHERE user_id = ?",
            (fullname, self._now(), user_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0
    
    def check_and_reset_quota(self, user_id: str) -> UserQuota:
        """Check if quota needs reset and reset if necessary."""
        user = self.get_user_quota(user_id)
        if not user:
            return None
        
        now = datetime.now(timezone.utc)
        reset_date = datetime.fromisoformat(user.reset_date.replace('Z', '+00:00'))
        
        if now >= reset_date:
            # Reset the quota
            cursor = self.conn.cursor()
            new_reset = self._get_next_reset_date()
            cursor.execute("""
                UPDATE user_quotas 
                SET current_usage = 0, current_cost_usd = 0.0, reset_date = ?, updated_at = ?
                WHERE user_id = ?
            """, (new_reset, self._now(), user_id))
            self.conn.commit()
            return self.get_user_quota(user_id)
        
        return user
    
    def update_user_usage(self, user_id: str, tokens: int, cost_usd: float = 0.0) -> int:
        """Add tokens to user's current usage. Returns new total."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE user_quotas 
            SET current_usage = current_usage + ?,
                current_cost_usd = current_cost_usd + ?,
                updated_at = ?
            WHERE user_id = ?
        """, (tokens, cost_usd, self._now(), user_id))
        self.conn.commit()
        
        # Return new usage
        cursor.execute("SELECT current_usage FROM user_quotas WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return row["current_usage"] if row else 0
    
    def reset_user_usage(self, user_id: str):
        """Manually reset a user's usage (admin function)."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE user_quotas 
            SET current_usage = 0, current_cost_usd = 0.0, updated_at = ?
            WHERE user_id = ?
        """, (self._now(), user_id))
        self.conn.commit()
    
    def list_users(
        self,
        limit: int = 50,
        offset: int = 0,
        tier: str = None,
        include_inactive: bool = False
    ) -> List[UserQuota]:
        """List users with their quota status."""
        cursor = self.conn.cursor()
        
        # Build WHERE clause
        conditions = []
        params = []
        
        if not include_inactive:
            conditions.append("(is_active = 1 OR is_active IS NULL)")
        
        if tier:
            conditions.append("tier = ?")
            params.append(tier)
        
        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)
        
        query = f"""
            SELECT * FROM user_quotas 
            {where_clause}
            ORDER BY current_usage DESC
            LIMIT ? OFFSET ?
        """
        cursor.execute(query, params + [limit, offset])
        
        def parse_user_row(row):
            # Handle is_active: treat NULL as True (active) for backwards compatibility
            is_active_val = row["is_active"] if "is_active" in row.keys() else None
            is_active = True if is_active_val is None else bool(is_active_val)
            
            return UserQuota(
                user_id=row["user_id"],
                fullname=row["fullname"] if "fullname" in row.keys() else None,
                tier=row["tier"],
                monthly_limit=row["monthly_limit"],
                current_usage=row["current_usage"],
                current_cost_usd=row["current_cost_usd"] or 0.0,
                reset_date=row["reset_date"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                is_active=is_active,
                deactivated_at=row["deactivated_at"] if "deactivated_at" in row.keys() else None
            )
        
        return [parse_user_row(row) for row in cursor.fetchall()]
    
    def soft_delete_user(self, user_id: str) -> bool:
        """Soft delete a user (deactivate). Returns True if successful."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE user_quotas 
            SET is_active = 0, deactivated_at = ?, updated_at = ?
            WHERE user_id = ?
        """, (self._now(), self._now(), user_id))
        self.conn.commit()
        return cursor.rowcount > 0
    
    def restore_user(self, user_id: str) -> bool:
        """Restore a soft-deleted user. Returns True if successful."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE user_quotas 
            SET is_active = 1, deactivated_at = NULL, updated_at = ?
            WHERE user_id = ?
        """, (self._now(), user_id))
        self.conn.commit()
        return cursor.rowcount > 0
    
    # ==========================================================================
    # USAGE LOGGING
    # ==========================================================================
    
    def log_usage(
        self,
        user_id: str,
        service: str,
        operation: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float = None,
        request_id: str = None,
        session_id: str = None,
        metadata: Dict[str, Any] = None,
        fullname: str = None
    ):
        """Log a token usage event."""
        total_tokens = input_tokens + output_tokens
        
        # Estimate cost if not provided
        if cost_usd is None:
            cost_usd = self._estimate_cost(model, input_tokens, output_tokens)
        
        # If fullname not provided, try to get it from user_quotas
        if fullname is None:
            user = self.get_user_quota(user_id)
            if user:
                fullname = user.fullname
        
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO usage_log 
            (user_id, fullname, service, operation, model, input_tokens, output_tokens, 
             total_tokens, cost_usd, request_id, session_id, metadata, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, fullname, service, operation, model,
            input_tokens, output_tokens, total_tokens, cost_usd,
            request_id, session_id,
            json.dumps(metadata) if metadata else None,
            self._now()
        ))
        self.conn.commit()
    
    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost based on model pricing."""
        pricing = {
            "gpt-4o": {"input": 0.0025, "output": 0.01},
            "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
            "gpt-4": {"input": 0.03, "output": 0.06},
            "gpt-4-turbo": {"input": 0.01, "output": 0.03},
            "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
            "text-embedding-3-small": {"input": 0.00002, "output": 0},
            "text-embedding-3-large": {"input": 0.00013, "output": 0},
        }
        
        rates = pricing.get(model, {"input": 0.01, "output": 0.03})
        return (input_tokens / 1000 * rates["input"]) + (output_tokens / 1000 * rates["output"])
    
    # ==========================================================================
    # ANALYTICS
    # ==========================================================================
    
    def get_usage_summary(self, hours: int = 24) -> UsageSummary:
        """Get aggregate usage summary."""
        start_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        cursor = self.conn.cursor()
        
        # Total stats
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT user_id) as total_users,
                SUM(total_tokens) as total_tokens,
                SUM(cost_usd) as total_cost,
                COUNT(*) as total_operations
            FROM usage_log
            WHERE timestamp >= ?
        """, (start_time,))
        
        stats = cursor.fetchone()
        
        # By service
        cursor.execute("""
            SELECT 
                service,
                SUM(total_tokens) as total_tokens,
                SUM(cost_usd) as total_cost,
                COUNT(*) as call_count,
                GROUP_CONCAT(DISTINCT model) as models
            FROM usage_log
            WHERE timestamp >= ?
            GROUP BY service
        """, (start_time,))
        
        by_service = [
            ServiceUsage(
                service=row["service"],
                total_tokens=row["total_tokens"] or 0,
                total_cost_usd=row["total_cost"] or 0.0,
                call_count=row["call_count"],
                models_used=row["models"].split(",") if row["models"] else []
            )
            for row in cursor.fetchall()
        ]
        
        # By tier
        cursor.execute("""
            SELECT tier, COUNT(*) as count
            FROM user_quotas
            GROUP BY tier
        """)
        by_tier = {row["tier"]: row["count"] for row in cursor.fetchall()}
        
        return UsageSummary(
            period_hours=hours,
            total_users=stats["total_users"] or 0,
            total_tokens=stats["total_tokens"] or 0,
            total_cost_usd=stats["total_cost"] or 0.0,
            total_operations=stats["total_operations"] or 0,
            by_service=by_service,
            by_tier=by_tier
        )
    
    def get_user_usage_breakdown(self, user_id: str, hours: int = 24) -> List[ServiceUsage]:
        """Get usage breakdown for a specific user."""
        start_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT 
                service,
                SUM(total_tokens) as total_tokens,
                SUM(cost_usd) as total_cost,
                COUNT(*) as call_count,
                GROUP_CONCAT(DISTINCT model) as models
            FROM usage_log
            WHERE user_id = ? AND timestamp >= ?
            GROUP BY service
        """, (user_id, start_time))
        
        return [
            ServiceUsage(
                service=row["service"],
                total_tokens=row["total_tokens"] or 0,
                total_cost_usd=row["total_cost"] or 0.0,
                call_count=row["call_count"],
                models_used=row["models"].split(",") if row["models"] else []
            )
            for row in cursor.fetchall()
        ]
    
    def get_top_users(self, limit: int = 10, hours: int = 24) -> List[Dict]:
        """Get top users by token usage."""
        start_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT 
                u.user_id,
                u.tier,
                SUM(l.total_tokens) as total_tokens,
                SUM(l.cost_usd) as total_cost
            FROM usage_log l
            JOIN user_quotas u ON l.user_id = u.user_id
            WHERE l.timestamp >= ?
            GROUP BY u.user_id
            ORDER BY total_tokens DESC
            LIMIT ?
        """, (start_time, limit))
        
        return [
            {
                "user_id": row["user_id"],
                "tier": row["tier"],
                "total_tokens": row["total_tokens"] or 0,
                "total_cost_usd": row["total_cost"] or 0.0
            }
            for row in cursor.fetchall()
        ]
    
    def get_usage_logs(
        self, 
        limit: int = 50, 
        offset: int = 0, 
        user_id: str = None,
        service: str = None
    ) -> tuple:
        """Get usage logs with pagination."""
        cursor = self.conn.cursor()
        
        # Build WHERE clause
        conditions = []
        params = []
        
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        
        if service:
            conditions.append("service = ?")
            params.append(service)
        
        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)
        
        # Get total count
        count_query = f"SELECT COUNT(*) as count FROM usage_log {where_clause}"
        cursor.execute(count_query, params)
        total = cursor.fetchone()["count"]
        
        # Get logs
        query = f"""
            SELECT id, user_id, fullname, service, operation, model, 
                   input_tokens, output_tokens, total_tokens, cost_usd,
                   request_id, session_id, metadata, timestamp
            FROM usage_log 
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """
        cursor.execute(query, params + [limit, offset])
        
        logs = [
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "fullname": row["fullname"] if "fullname" in row.keys() else None,
                "service": row["service"],
                "operation": row["operation"],
                "model": row["model"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "total_tokens": row["total_tokens"],
                "cost_usd": row["cost_usd"] or 0.0,
                "request_id": row["request_id"],
                "session_id": row["session_id"],
                "metadata": row["metadata"],
                "timestamp": row["timestamp"]
            }
            for row in cursor.fetchall()
        ]
        
        return logs, total
    
    # ==========================================================================
    # ADMIN ACTION LOGGING
    # ==========================================================================
    
    def log_admin_action(
        self,
        action: str,
        admin_id: str = None,
        admin_name: str = None,
        target_user_id: str = None,
        target_user_name: str = None,
        details: Dict[str, Any] = None
    ):
        """Log an admin action for audit trail."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO admin_actions_log 
            (admin_id, admin_name, action, target_user_id, target_user_name, details, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            admin_id, admin_name, action,
            target_user_id, target_user_name,
            json.dumps(details) if details else None,
            self._now()
        ))
        self.conn.commit()
    
    def get_admin_actions(
        self,
        limit: int = 50,
        offset: int = 0,
        admin_id: str = None,
        target_user_id: str = None
    ) -> tuple:
        """Get admin action logs with pagination."""
        cursor = self.conn.cursor()
        
        # Build WHERE clause
        conditions = []
        params = []
        
        if admin_id:
            conditions.append("admin_id = ?")
            params.append(admin_id)
        
        if target_user_id:
            conditions.append("target_user_id = ?")
            params.append(target_user_id)
        
        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)
        
        # Get total count
        count_query = f"SELECT COUNT(*) as count FROM admin_actions_log {where_clause}"
        cursor.execute(count_query, params)
        total = cursor.fetchone()["count"]
        
        # Get logs
        query = f"""
            SELECT id, admin_id, admin_name, action, target_user_id, target_user_name, 
                   details, timestamp
            FROM admin_actions_log 
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """
        cursor.execute(query, params + [limit, offset])
        
        logs = [
            {
                "id": row["id"],
                "admin_id": row["admin_id"],
                "admin_name": row["admin_name"],
                "action": row["action"],
                "target_user_id": row["target_user_id"],
                "target_user_name": row["target_user_name"],
                "details": json.loads(row["details"]) if row["details"] else None,
                "timestamp": row["timestamp"]
            }
            for row in cursor.fetchall()
        ]
        
        return logs, total
    
    def get_stats(self) -> Dict[str, Any]:
        """Get basic database stats."""
        cursor = self.conn.cursor()
        
        cursor.execute("SELECT COUNT(*) as count FROM user_quotas")
        user_count = cursor.fetchone()["count"]
        
        cursor.execute("SELECT COUNT(*) as count FROM usage_log")
        log_count = cursor.fetchone()["count"]
        
        cursor.execute("SELECT SUM(total_tokens) as sum FROM usage_log")
        total_tokens = cursor.fetchone()["sum"] or 0
        
        return {
            "total_users": user_count,
            "total_log_entries": log_count,
            "total_tokens_tracked": total_tokens
        }


# ==============================================================================
# SINGLETON INSTANCE
# ==============================================================================

_db_instance: Optional[QuotaDatabase] = None


def get_db() -> QuotaDatabase:
    """Get singleton database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = QuotaDatabase()
    return _db_instance
