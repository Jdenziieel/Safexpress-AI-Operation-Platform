"""
Log Storage - SQLite Database for Log Persistence

Provides:
- SQLite storage for all log entries
- Efficient querying, sorting, filtering
- Full-text search on log messages
- Automatic log rotation/cleanup
- Statistics and aggregations
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path
from enum import Enum
from dataclasses import asdict

# Import from models (single source of truth)
from models.models import LogLevel


class LogStorage:
    """
    SQLite-based log storage with querying capabilities.
    
    Features:
    - Store all log types (LLM, Agent, Progress, Error, etc.)
    - Query by level, component, request_id, conversation_id, time range
    - Full-text search on messages
    - Token usage aggregations
    - Automatic cleanup of old logs
    """
    
    def __init__(self, db_path: str = "logs.db"):
        """
        Initialize log storage with SQLite database.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self._init_database()
    
    def _get_connection(self):
        """Get a database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Return rows as dict-like objects
        return conn
    
    def _init_database(self):
        """Create database tables if they don't exist"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Main logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,
                logger TEXT NOT NULL,
                message TEXT NOT NULL,
                request_id TEXT,
                conversation_id TEXT,
                thread_id TEXT,
                component TEXT,
                operation TEXT,
                data TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # LLM calls table (for token tracking and cost analysis)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS llm_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                request_id TEXT,
                conversation_id TEXT,
                user_id TEXT,
                service TEXT DEFAULT 'supervisor',
                model TEXT NOT NULL,
                tier TEXT,
                operation TEXT,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                estimated_cost_usd REAL DEFAULT 0.0,
                duration_ms REAL DEFAULT 0.0,
                success INTEGER DEFAULT 1,
                prompt_summary TEXT,
                error TEXT,
                cumulative_tokens INTEGER,
                cumulative_cost_usd REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Migration: add columns if they don't exist (for existing databases)
        try:
            cursor.execute("ALTER TABLE llm_calls ADD COLUMN user_id TEXT")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE llm_calls ADD COLUMN service TEXT DEFAULT 'supervisor'")
        except Exception:
            pass
        
        # Agent calls table (for execution tracking)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                request_id TEXT,
                conversation_id TEXT,
                agent_name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                step_number INTEGER,
                total_steps INTEGER,
                inputs TEXT,
                success INTEGER DEFAULT 1,
                duration_ms REAL DEFAULT 0.0,
                output_summary TEXT,
                error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Request summaries table (for per-request token totals)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS request_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT UNIQUE NOT NULL,
                conversation_id TEXT,
                thread_id TEXT,
                started_at TEXT,
                completed_at TEXT,
                total_duration_ms REAL DEFAULT 0.0,
                total_input_tokens INTEGER DEFAULT 0,
                total_output_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                total_cost_usd REAL DEFAULT 0.0,
                llm_call_count INTEGER DEFAULT 0,
                agent_call_count INTEGER DEFAULT 0,
                success INTEGER DEFAULT 1,
                error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Pending actions table (for human-in-the-loop approval workflow)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_id TEXT UNIQUE NOT NULL,
                thread_id TEXT,
                conversation_id TEXT,
                request_id TEXT,
                step_number INTEGER,
                agent_name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                description TEXT,
                inputs TEXT,
                output_variables TEXT,
                risk_level TEXT DEFAULT 'MODERATE',
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT,
                decided_at TEXT,
                decided_by TEXT,
                execution_result TEXT,
                error TEXT
            )
        """)
        
        # Model pricing table (admin-modifiable per-model rates)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS model_pricing (
                model TEXT PRIMARY KEY,
                input_rate_per_1k REAL NOT NULL,
                output_rate_per_1k REAL NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT
            )
        """)
        
        # System settings table (key-value store for admin config)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        # Create indexes for common queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_request_id ON logs(request_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_conversation_id ON logs(conversation_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_component ON logs(component)")
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_request_id ON llm_calls(request_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_timestamp ON llm_calls(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_model ON llm_calls(model)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_user_id ON llm_calls(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_operation ON llm_calls(operation)")
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_request_id ON agent_calls(request_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_timestamp ON agent_calls(timestamp)")
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_request_summaries_conversation ON request_summaries(conversation_id)")
        
        # Pending actions indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_actions_action_id ON pending_actions(action_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_actions_thread_id ON pending_actions(thread_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_actions_status ON pending_actions(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_actions_expires_at ON pending_actions(expires_at)")
        
        # Create FTS (Full-Text Search) virtual table for message search
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS logs_fts USING fts5(
                message,
                content='logs',
                content_rowid='id'
            )
        """)
        
        # Triggers to keep FTS in sync
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS logs_ai AFTER INSERT ON logs BEGIN
                INSERT INTO logs_fts(rowid, message) VALUES (new.id, new.message);
            END
        """)
        
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS logs_ad AFTER DELETE ON logs BEGIN
                INSERT INTO logs_fts(logs_fts, rowid, message) VALUES('delete', old.id, old.message);
            END
        """)
        
        conn.commit()
        conn.close()
    
    # =========================================================================
    # INSERT METHODS
    # =========================================================================
    
    def insert_log(
        self,
        log_entry: Optional[Dict[str, Any]] = None,
        timestamp: Optional[str] = None,
        level: Optional[str] = None,
        logger: Optional[str] = None,
        message: Optional[str] = None,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        component: Optional[str] = None,
        operation: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Insert a general log entry.
        
        Can be called with a dict (log_entry) or individual parameters.
        
        Args:
            log_entry: A complete log entry dict (from StructuredLogger._build_log_entry)
            OR individual parameters:
            timestamp, level, logger, message, etc.
        """
        # If log_entry dict is provided, extract values from it
        if log_entry is not None:
            timestamp = log_entry.get("timestamp", timestamp)
            level = log_entry.get("level", level)
            logger = log_entry.get("logger", logger)
            message = log_entry.get("message", message)
            request_id = log_entry.get("request_id", request_id)
            conversation_id = log_entry.get("conversation_id", conversation_id)
            thread_id = log_entry.get("thread_id", thread_id)
            component = log_entry.get("component", component)
            operation = log_entry.get("operation", operation)
            data = log_entry.get("data", data)
        
        # Validate required fields
        if not timestamp or not level or not logger or not message:
            raise ValueError("timestamp, level, logger, and message are required")
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO logs (timestamp, level, logger, message, request_id, 
                            conversation_id, thread_id, component, operation, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp, level, logger, message, request_id,
            conversation_id, thread_id, component, operation,
            json.dumps(data) if data else None
        ))
        
        log_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return log_id
    
    def insert_llm_call(
        self,
        timestamp: str,
        model: str,
        operation: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        estimated_cost_usd: float,
        duration_ms: float,
        success: bool = True,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        tier: Optional[str] = None,
        prompt_summary: Optional[str] = None,
        error: Optional[str] = None,
        cumulative_tokens: Optional[int] = None,
        cumulative_cost_usd: Optional[float] = None,
        user_id: Optional[str] = None,
        service: str = "supervisor"
    ) -> int:
        """Insert an LLM call record"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO llm_calls (timestamp, request_id, conversation_id, user_id, service,
                                  model, tier, operation, input_tokens, output_tokens,
                                  total_tokens, estimated_cost_usd, duration_ms, success,
                                  prompt_summary, error, cumulative_tokens, cumulative_cost_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp, request_id, conversation_id, user_id, service,
            model, tier, operation, input_tokens, output_tokens,
            total_tokens, estimated_cost_usd, duration_ms, 1 if success else 0,
            prompt_summary, error, cumulative_tokens, cumulative_cost_usd
        ))
        
        call_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return call_id
    
    def insert_agent_call(
        self,
        timestamp: str,
        agent_name: str,
        tool_name: str,
        step_number: int,
        total_steps: int,
        inputs: Dict[str, Any],
        success: bool,
        duration_ms: float,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        output_summary: Optional[str] = None,
        error: Optional[str] = None
    ) -> int:
        """Insert an agent call record"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO agent_calls (timestamp, request_id, conversation_id, agent_name,
                                    tool_name, step_number, total_steps, inputs, success,
                                    duration_ms, output_summary, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp, request_id, conversation_id, agent_name,
            tool_name, step_number, total_steps, json.dumps(inputs),
            1 if success else 0, duration_ms, output_summary, error
        ))
        
        call_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return call_id
    
    def insert_request_summary(
        self,
        request_id: str,
        conversation_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        total_duration_ms: float = 0.0,
        total_input_tokens: int = 0,
        total_output_tokens: int = 0,
        total_tokens: int = 0,
        total_cost_usd: float = 0.0,
        llm_call_count: int = 0,
        agent_call_count: int = 0,
        success: bool = True,
        error: Optional[str] = None
    ) -> int:
        """Insert or update a request summary"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO request_summaries (
                request_id, conversation_id, thread_id, started_at, completed_at,
                total_duration_ms, total_input_tokens, total_output_tokens, total_tokens,
                total_cost_usd, llm_call_count, agent_call_count, success, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            request_id, conversation_id, thread_id, started_at, completed_at,
            total_duration_ms, total_input_tokens, total_output_tokens, total_tokens,
            total_cost_usd, llm_call_count, agent_call_count, 1 if success else 0, error
        ))
        
        summary_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return summary_id
    
    # =========================================================================
    # QUERY METHODS
    # =========================================================================
    
    def get_logs(
        self,
        level: Optional[str] = None,
        component: Optional[str] = None,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        search_query: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "timestamp",
        sort_order: str = "DESC"
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        Query logs with filtering, sorting, and pagination.
        
        Args:
            level: Filter by log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            component: Filter by component (llm, orchestrator, api, etc.)
            request_id: Filter by request ID
            conversation_id: Filter by conversation ID
            thread_id: Filter by thread ID
            start_time: Filter logs after this timestamp (ISO format)
            end_time: Filter logs before this timestamp (ISO format)
            search_query: Full-text search in message
            limit: Maximum number of results
            offset: Skip first N results (for pagination)
            sort_by: Column to sort by (timestamp, level, component)
            sort_order: ASC or DESC
            
        Returns:
            Tuple of (list of log entries, total count)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Build base query and count query
        base_conditions = ""
        params = []
        
        # Build query dynamically
        if search_query:
            # Use FTS for text search
            base_query = """
                SELECT l.* FROM logs l
                JOIN logs_fts fts ON l.id = fts.rowid
                WHERE logs_fts MATCH ?
            """
            count_query = """
                SELECT COUNT(*) FROM logs l
                JOIN logs_fts fts ON l.id = fts.rowid
                WHERE logs_fts MATCH ?
            """
            params = [search_query]
        else:
            base_query = "SELECT * FROM logs WHERE 1=1"
            count_query = "SELECT COUNT(*) FROM logs WHERE 1=1"
            params = []
        
        # Add filters
        conditions = ""
        filter_params = []
        
        if level:
            conditions += " AND level = ?"
            filter_params.append(level)
        
        if component:
            conditions += " AND component = ?"
            filter_params.append(component)
        
        if request_id:
            conditions += " AND request_id = ?"
            filter_params.append(request_id)
        
        if conversation_id:
            conditions += " AND conversation_id = ?"
            filter_params.append(conversation_id)
        
        if thread_id:
            conditions += " AND thread_id = ?"
            filter_params.append(thread_id)
        
        if start_time:
            conditions += " AND timestamp >= ?"
            filter_params.append(start_time)
        
        if end_time:
            conditions += " AND timestamp <= ?"
            filter_params.append(end_time)
        
        # Get total count first
        count_params = params + filter_params
        cursor.execute(count_query + conditions, count_params)
        total = cursor.fetchone()[0]
        
        # Validate sort column to prevent SQL injection
        valid_sort_columns = ["timestamp", "level", "component", "logger", "id"]
        if sort_by not in valid_sort_columns:
            sort_by = "timestamp"
        
        sort_order = "DESC" if sort_order.upper() == "DESC" else "ASC"
        
        # Add sort and pagination
        query = base_query + conditions + f" ORDER BY {sort_by} {sort_order} LIMIT ? OFFSET ?"
        query_params = params + filter_params + [limit, offset]
        
        cursor.execute(query, query_params)
        rows = cursor.fetchall()
        
        # Convert to list of dicts
        results = []
        for row in rows:
            entry = dict(row)
            # Parse JSON data field
            if entry.get("data"):
                try:
                    entry["data"] = json.loads(entry["data"])
                except json.JSONDecodeError:
                    pass
            results.append(entry)
        
        conn.close()
        return results, total
    
    def get_llm_calls(
        self,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        model: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        sort_order: str = "DESC"
    ) -> List[Dict[str, Any]]:
        """Query LLM calls with filtering"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM llm_calls WHERE 1=1"
        params = []
        
        if request_id:
            query += " AND request_id = ?"
            params.append(request_id)
        
        if conversation_id:
            query += " AND conversation_id = ?"
            params.append(conversation_id)
        
        if model:
            query += " AND model = ?"
            params.append(model)
        
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time)
        
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time)
        
        sort_order = "DESC" if sort_order.upper() == "DESC" else "ASC"
        query += f" ORDER BY timestamp {sort_order} LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        results = [dict(row) for row in rows]
        conn.close()
        return results
    
    def get_agent_calls(
        self,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        tool_name: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        sort_order: str = "DESC"
    ) -> List[Dict[str, Any]]:
        """Query agent calls with filtering"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM agent_calls WHERE 1=1"
        params = []
        
        if request_id:
            query += " AND request_id = ?"
            params.append(request_id)
        
        if conversation_id:
            query += " AND conversation_id = ?"
            params.append(conversation_id)
        
        if agent_name:
            query += " AND agent_name = ?"
            params.append(agent_name)
        
        if tool_name:
            query += " AND tool_name = ?"
            params.append(tool_name)
        
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time)
        
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time)
        
        sort_order = "DESC" if sort_order.upper() == "DESC" else "ASC"
        query += f" ORDER BY timestamp {sort_order} LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        results = []
        for row in rows:
            entry = dict(row)
            if entry.get("inputs"):
                try:
                    entry["inputs"] = json.loads(entry["inputs"])
                except json.JSONDecodeError:
                    pass
            results.append(entry)
        
        conn.close()
        return results
    
    def get_request_summaries(
        self,
        conversation_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        sort_order: str = "DESC"
    ) -> List[Dict[str, Any]]:
        """Query request summaries"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM request_summaries WHERE 1=1"
        params = []
        
        if conversation_id:
            query += " AND conversation_id = ?"
            params.append(conversation_id)
        
        if start_time:
            query += " AND started_at >= ?"
            params.append(start_time)
        
        if end_time:
            query += " AND completed_at <= ?"
            params.append(end_time)
        
        sort_order = "DESC" if sort_order.upper() == "DESC" else "ASC"
        query += f" ORDER BY completed_at {sort_order} LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        results = [dict(row) for row in rows]
        conn.close()
        return results
    
    # =========================================================================
    # STATISTICS & AGGREGATIONS
    # =========================================================================
    
    def get_token_usage_stats(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        group_by: str = "day"  # day, hour, model
    ) -> Dict[str, Any]:
        """Get aggregated token usage statistics"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Build time filter
        time_filter = ""
        params = []
        if start_time:
            time_filter += " AND timestamp >= ?"
            params.append(start_time)
        if end_time:
            time_filter += " AND timestamp <= ?"
            params.append(end_time)
        
        # Total stats
        cursor.execute(f"""
            SELECT 
                COUNT(*) as total_calls,
                SUM(input_tokens) as total_input_tokens,
                SUM(output_tokens) as total_output_tokens,
                SUM(total_tokens) as total_tokens,
                SUM(estimated_cost_usd) as total_cost_usd,
                AVG(duration_ms) as avg_duration_ms,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_calls,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed_calls
            FROM llm_calls
            WHERE 1=1 {time_filter}
        """, params)
        
        totals = dict(cursor.fetchone())
        
        # Group by model (with input/output split)
        cursor.execute(f"""
            SELECT 
                model,
                COUNT(*) as calls,
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens,
                SUM(total_tokens) as tokens,
                SUM(estimated_cost_usd) as cost_usd,
                AVG(duration_ms) as avg_duration_ms
            FROM llm_calls
            WHERE 1=1 {time_filter}
            GROUP BY model
            ORDER BY cost_usd DESC
        """, params)
        
        by_model = [dict(row) for row in cursor.fetchall()]
        
        # Group by tier
        cursor.execute(f"""
            SELECT 
                tier,
                COUNT(*) as calls,
                SUM(total_tokens) as tokens,
                SUM(estimated_cost_usd) as cost_usd
            FROM llm_calls
            WHERE 1=1 {time_filter}
            GROUP BY tier
            ORDER BY calls DESC
        """, params)
        
        by_tier = [dict(row) for row in cursor.fetchall()]
        
        # Group by operation
        cursor.execute(f"""
            SELECT 
                operation,
                COUNT(*) as calls,
                SUM(total_tokens) as tokens,
                SUM(estimated_cost_usd) as cost_usd,
                GROUP_CONCAT(DISTINCT model) as models_used
            FROM llm_calls
            WHERE 1=1 {time_filter}
            GROUP BY operation
            ORDER BY cost_usd DESC
        """, params)
        
        by_operation = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        return {
            "totals": totals,
            "by_model": by_model,
            "by_tier": by_tier,
            "by_operation": by_operation
        }
    
    def get_token_summary(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get token usage summary (alias for get_token_usage_stats).
        Used by API endpoints.
        """
        return self.get_token_usage_stats(start_time, end_time)
    
    def get_request_analytics(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get analytics for recent requests.
        
        Returns token usage, cost, and call count per request.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        time_filter = ""
        params = []
        if start_time:
            time_filter += " AND timestamp >= ?"
            params.append(start_time)
        if end_time:
            time_filter += " AND timestamp <= ?"
            params.append(end_time)
        
        cursor.execute(f"""
            SELECT 
                request_id,
                MIN(timestamp) as started_at,
                MAX(timestamp) as ended_at,
                COUNT(*) as llm_calls,
                SUM(input_tokens) as total_input_tokens,
                SUM(output_tokens) as total_output_tokens,
                SUM(total_tokens) as total_tokens,
                SUM(estimated_cost_usd) as total_cost_usd,
                GROUP_CONCAT(DISTINCT model) as models_used
            FROM llm_calls
            WHERE request_id IS NOT NULL {time_filter}
            GROUP BY request_id
            ORDER BY started_at DESC
            LIMIT ?
        """, params + [limit])
        
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return results
    
    def get_log_counts(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> Dict[str, int]:
        """Get log counts by level"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        time_filter = ""
        params = []
        if start_time:
            time_filter += " AND timestamp >= ?"
            params.append(start_time)
        if end_time:
            time_filter += " AND timestamp <= ?"
            params.append(end_time)
        
        cursor.execute(f"""
            SELECT level, COUNT(*) as count
            FROM logs
            WHERE 1=1 {time_filter}
            GROUP BY level
        """, params)
        
        counts = {row["level"]: row["count"] for row in cursor.fetchall()}
        conn.close()
        
        return counts
    
    def search_logs(
        self,
        query: str,
        level: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        Full-text search across log messages.
        
        Args:
            query: Search query string
            level: Optional level filter
            start_time: Optional start time filter
            end_time: Optional end time filter
            limit: Maximum results
            offset: Pagination offset
            
        Returns:
            Tuple of (matching logs, total count)
        """
        return self.get_logs(
            level=level,
            start_time=start_time,
            end_time=end_time,
            search_query=query,
            limit=limit,
            offset=offset
        )
    
    # =========================================================================
    # CLEANUP
    # =========================================================================
    
    def clear_logs(self, before_time: Optional[str] = None) -> int:
        """
        Clear logs from database.
        
        Args:
            before_time: If provided, only delete logs before this time (ISO format).
                        If None, deletes ALL logs.
        
        Returns:
            Number of deleted records
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        total_deleted = 0
        
        if before_time:
            # Delete logs before specific time
            cursor.execute("DELETE FROM logs WHERE timestamp < ?", (before_time,))
            total_deleted += cursor.rowcount
            
            cursor.execute("DELETE FROM llm_calls WHERE timestamp < ?", (before_time,))
            total_deleted += cursor.rowcount
            
            cursor.execute("DELETE FROM agent_calls WHERE timestamp < ?", (before_time,))
            total_deleted += cursor.rowcount
            
            cursor.execute("DELETE FROM request_summaries WHERE completed_at < ?", (before_time,))
            total_deleted += cursor.rowcount
        else:
            # Delete ALL logs
            cursor.execute("DELETE FROM logs")
            total_deleted += cursor.rowcount
            
            cursor.execute("DELETE FROM llm_calls")
            total_deleted += cursor.rowcount
            
            cursor.execute("DELETE FROM agent_calls")
            total_deleted += cursor.rowcount
            
            cursor.execute("DELETE FROM request_summaries")
            total_deleted += cursor.rowcount
        
        conn.commit()
        conn.close()
        
        print(f"Cleared {total_deleted} log records")
        return total_deleted
    
    def cleanup_old_logs(self, days_to_keep: int = 30) -> int:
        """
        Delete logs older than specified days.
        
        Args:
            days_to_keep: Number of days of logs to retain
            
        Returns:
            Number of deleted records
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cutoff = (datetime.utcnow() - timedelta(days=days_to_keep)).isoformat()
        
        # Delete from all tables
        cursor.execute("DELETE FROM logs WHERE timestamp < ?", (cutoff,))
        logs_deleted = cursor.rowcount
        
        cursor.execute("DELETE FROM llm_calls WHERE timestamp < ?", (cutoff,))
        llm_deleted = cursor.rowcount
        
        cursor.execute("DELETE FROM agent_calls WHERE timestamp < ?", (cutoff,))
        agent_deleted = cursor.rowcount
        
        cursor.execute("DELETE FROM request_summaries WHERE completed_at < ?", (cutoff,))
        summary_deleted = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        total_deleted = logs_deleted + llm_deleted + agent_deleted + summary_deleted
        print(f"Cleaned up {total_deleted} old log records (older than {days_to_keep} days)")
        
        return total_deleted

    # =========================================================================
    # MODEL PRICING METHODS
    # =========================================================================

    def seed_model_pricing(self, default_pricing: Dict[str, Dict[str, float]]):
        """
        Seed model_pricing table with defaults if empty.
        Only inserts models that don't already exist (preserves admin edits).
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()

        for model, rates in default_pricing.items():
            if model == "default":
                continue
            cursor.execute(
                "INSERT OR IGNORE INTO model_pricing (model, input_rate_per_1k, output_rate_per_1k, updated_at, updated_by) VALUES (?, ?, ?, ?, ?)",
                (model, rates["input"], rates["output"], now, "system_seed")
            )

        conn.commit()
        conn.close()

    def get_all_model_pricing(self) -> List[Dict[str, Any]]:
        """Return every row from model_pricing."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT model, input_rate_per_1k, output_rate_per_1k, updated_at, updated_by FROM model_pricing ORDER BY model")
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_model_pricing(self, model: str) -> Optional[Dict[str, float]]:
        """Get pricing for a single model. Returns None if not found."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT input_rate_per_1k, output_rate_per_1k FROM model_pricing WHERE model = ?", (model,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {"input": row["input_rate_per_1k"], "output": row["output_rate_per_1k"]}

    def update_model_pricing(
        self, model: str, input_rate: float, output_rate: float, updated_by: str = "admin"
    ) -> bool:
        """Update or insert pricing for a model. Returns True if a row was affected."""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute(
            "INSERT OR REPLACE INTO model_pricing (model, input_rate_per_1k, output_rate_per_1k, updated_at, updated_by) VALUES (?, ?, ?, ?, ?)",
            (model, input_rate, output_rate, now, updated_by)
        )
        affected = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return affected

    # =========================================================================
    # SYSTEM SETTINGS METHODS
    # =========================================================================

    def get_setting(self, key: str) -> Optional[str]:
        """Get a system setting value by key."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        """Set a system setting (insert or update)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute(
            "INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, now)
        )
        conn.commit()
        conn.close()

    # =========================================================================
    # USAGE SUMMARY METHODS
    # =========================================================================

    def get_usage_summary(self) -> Dict[str, Any]:
        """
        Return conversation and request counts for today, this week, this month.
        Uses request_summaries table with completed_at timestamps.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        now = datetime.utcnow()
        today_start = (now - timedelta(hours=24)).isoformat()
        week_start = (now - timedelta(days=7)).isoformat()
        month_start = (now - timedelta(days=30)).isoformat()

        def _counts(start: str):
            cursor.execute(
                "SELECT COUNT(*) as requests, COUNT(DISTINCT conversation_id) as conversations "
                "FROM request_summaries WHERE completed_at >= ?",
                (start,)
            )
            row = cursor.fetchone()
            return {"conversations": row["conversations"] or 0, "requests": row["requests"] or 0}

        result = {
            "today": _counts(today_start),
            "this_week": _counts(week_start),
            "this_month": _counts(month_start),
        }

        conn.close()
        return result

    def get_avg_response_time(
        self, start_time: Optional[str] = None, end_time: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Return system-wide average response time from request_summaries.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        time_filter = ""
        params = []
        if start_time:
            time_filter += " AND completed_at >= ?"
            params.append(start_time)
        if end_time:
            time_filter += " AND completed_at <= ?"
            params.append(end_time)

        cursor.execute(
            f"SELECT AVG(total_duration_ms) as avg_ms, COUNT(*) as total "
            f"FROM request_summaries WHERE total_duration_ms > 0 {time_filter}",
            params
        )
        row = cursor.fetchone()
        conn.close()
        return {
            "avg_response_time_ms": round(row["avg_ms"], 0) if row["avg_ms"] else 0,
            "total_requests": row["total"] or 0,
        }

    # =========================================================================
    # PENDING ACTIONS METHODS
    # =========================================================================
    
    def insert_pending_action(
        self,
        action_id: str,
        agent_name: str,
        tool_name: str,
        step_number: Optional[int] = None,
        description: Optional[str] = None,
        inputs: Optional[Dict[str, Any]] = None,
        output_variables: Optional[Dict[str, str]] = None,
        risk_level: str = "MODERATE",
        thread_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        expires_in_minutes: int = 30
    ) -> int:
        """
        Insert a pending action awaiting approval.
        
        Args:
            action_id: Unique action identifier
            agent_name: Name of the agent to execute
            tool_name: Name of the tool to call
            step_number: Step number in workflow
            description: Human-readable description
            inputs: Input parameters for the action
            output_variables: Output variable mapping
            risk_level: SAFE, MODERATE, or DANGEROUS
            thread_id: Associated thread
            conversation_id: Associated conversation
            request_id: Associated request
            expires_in_minutes: How long before action expires
            
        Returns:
            Database row ID
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        now = datetime.utcnow()
        expires_at = (now + timedelta(minutes=expires_in_minutes)).isoformat()
        
        cursor.execute("""
            INSERT INTO pending_actions (
                action_id, thread_id, conversation_id, request_id,
                step_number, agent_name, tool_name, description,
                inputs, output_variables, risk_level, status,
                created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """, (
            action_id, thread_id, conversation_id, request_id,
            step_number, agent_name, tool_name, description,
            json.dumps(inputs) if inputs else None,
            json.dumps(output_variables) if output_variables else None,
            risk_level, now.isoformat(), expires_at
        ))
        
        row_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        print(f"Stored pending action: {action_id} ({agent_name}.{tool_name})")
        return row_id
    
    def get_pending_action(self, action_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a pending action by ID.
        
        Args:
            action_id: Action identifier
            
        Returns:
            Action dict or None if not found
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM pending_actions WHERE action_id = ?
        """, (action_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return self._row_to_action_dict(row)
    
    def get_pending_actions(
        self,
        thread_id: Optional[str] = None,
        status: str = "pending",
        include_expired: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get pending actions, optionally filtered by thread.
        
        Args:
            thread_id: Filter by thread (None for all)
            status: Filter by status (default: 'pending')
            include_expired: Include expired actions
            
        Returns:
            List of pending action dicts
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM pending_actions WHERE status = ?"
        params = [status]
        
        if thread_id:
            query += " AND thread_id = ?"
            params.append(thread_id)
        
        if not include_expired:
            query += " AND (expires_at IS NULL OR expires_at > ?)"
            params.append(datetime.utcnow().isoformat())
        
        query += " ORDER BY created_at DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_action_dict(row) for row in rows]
    
    def update_pending_action_status(
        self,
        action_id: str,
        status: str,
        decided_by: Optional[str] = None,
        execution_result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> bool:
        """
        Update the status of a pending action.
        
        Args:
            action_id: Action identifier
            status: New status (approved, rejected, expired, executed)
            decided_by: Who made the decision (user ID)
            execution_result: Result of execution (if executed)
            error: Error message (if failed)
            
        Returns:
            True if updated, False if not found
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE pending_actions 
            SET status = ?, decided_at = ?, decided_by = ?, 
                execution_result = ?, error = ?
            WHERE action_id = ?
        """, (
            status, 
            datetime.utcnow().isoformat(),
            decided_by,
            json.dumps(execution_result) if execution_result else None,
            error,
            action_id
        ))
        
        updated = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        if updated:
            print(f"Updated action {action_id} status to: {status}")
        
        return updated
    
    def delete_pending_action(self, action_id: str) -> bool:
        """
        Delete a pending action.
        
        Args:
            action_id: Action identifier
            
        Returns:
            True if deleted, False if not found
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM pending_actions WHERE action_id = ?", (action_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return deleted
    
    def cleanup_expired_actions(self) -> int:
        """
        Mark expired pending actions as 'expired'.
        
        Returns:
            Number of actions marked as expired
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        now = datetime.utcnow().isoformat()
        
        cursor.execute("""
            UPDATE pending_actions 
            SET status = 'expired', decided_at = ?
            WHERE status = 'pending' AND expires_at < ?
        """, (now, now))
        
        count = cursor.rowcount
        conn.commit()
        conn.close()
        
        if count > 0:
            print(f"Marked {count} expired pending actions")
        
        return count

    def cleanup_expired_pending_actions(self, expire_minutes: int = 5) -> int:
        """
        Mark pending actions older than expire_minutes as 'expired'.
        
        Unlike cleanup_expired_actions which uses the stored expires_at column,
        this method uses a dynamic age threshold.
        
        Args:
            expire_minutes: Mark actions older than this many minutes as expired
            
        Returns:
            Number of actions marked as expired
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        now = datetime.utcnow()
        cutoff = (now - timedelta(minutes=expire_minutes)).isoformat()
        
        cursor.execute("""
            UPDATE pending_actions 
            SET status = 'expired', decided_at = ?
            WHERE status = 'pending' AND created_at < ?
        """, (now.isoformat(), cutoff))
        
        count = cursor.rowcount
        conn.commit()
        conn.close()
        
        if count > 0:
            print(f"Marked {count} expired pending actions (older than {expire_minutes}m)")
        
        return count
    
    def _row_to_action_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a database row to an action dictionary."""
        return {
            "id": row["id"],
            "action_id": row["action_id"],
            "thread_id": row["thread_id"],
            "conversation_id": row["conversation_id"],
            "request_id": row["request_id"],
            "step_number": row["step_number"],
            "agent_name": row["agent_name"],
            "tool_name": row["tool_name"],
            "description": row["description"],
            "inputs": json.loads(row["inputs"]) if row["inputs"] else None,
            "output_variables": json.loads(row["output_variables"]) if row["output_variables"] else None,
            "risk_level": row["risk_level"],
            "status": row["status"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "decided_at": row["decided_at"],
            "decided_by": row["decided_by"],
            "execution_result": json.loads(row["execution_result"]) if row["execution_result"] else None,
            "error": row["error"]
        }


# Global instance (lazy initialization, don't create on import)
# log_storage = LogStorage()  # Commented out - use get_log_storage() from logging_config instead
