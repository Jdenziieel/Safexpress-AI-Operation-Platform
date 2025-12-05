"""
Knowledge Base Log Storage - SQLite Database for KB-specific Logging

Provides specialized logging for:
- Document processing pipeline (admin operations)
- Chat session tracking (privacy-focused, no PII)
- System health and errors
- Usage aggregations for fast dashboard loading
"""

import sqlite3
import json
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from pathlib import Path
from config import Config


class KBLogStorage:
    """
    SQLite-based log storage for Knowledge Base system.
    
    Tables:
    - document_processing_logs: Admin document upload operations
    - chat_session_logs: User chat interactions (no PII)
    - system_logs: General system events and errors
    - usage_aggregates: Pre-computed stats for dashboards
    """
    
    def __init__(self, db_path: str = None):
        """Initialize KB log storage with SQLite database."""
        self.db_path = Path(db_path or Config.KB_LOGS_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
        print(f"✅ KB Log Storage initialized: {self.db_path}")
    
    def _get_connection(self):
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_database(self):
        """Create database tables if they don't exist."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Table 1: Document Processing Logs (Admin operations - full visibility)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_processing_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                
                -- Document identification
                document_id TEXT,
                filename TEXT NOT NULL,
                file_size_bytes INTEGER,
                content_hash TEXT,
                
                -- Processing pipeline tracking
                pipeline_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                stage_order INTEGER,
                
                -- LLM usage
                model TEXT,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                estimated_cost_usd REAL DEFAULT 0.0,
                duration_ms REAL DEFAULT 0.0,
                
                -- Results
                success INTEGER DEFAULT 1,
                chunks_created INTEGER DEFAULT 0,
                images_processed INTEGER DEFAULT 0,
                error TEXT,
                
                -- Admin who uploaded (VISIBLE for accountability)
                uploaded_by TEXT,
                
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Table 2: Chat Session Logs (User operations - privacy focused)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_session_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                
                -- Session tracking (hashed for privacy)
                session_id_hash TEXT,
                request_id TEXT NOT NULL,
                
                -- Pipeline stages
                stage TEXT NOT NULL,
                stage_order INTEGER,
                
                -- LLM usage
                model TEXT,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                estimated_cost_usd REAL DEFAULT 0.0,
                duration_ms REAL DEFAULT 0.0,
                
                -- Search metrics
                chunks_retrieved INTEGER DEFAULT 0,
                chunks_used INTEGER DEFAULT 0,
                
                -- Results
                success INTEGER DEFAULT 1,
                error TEXT,
                
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Table 3: System Logs (General events, errors, health)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,
                component TEXT NOT NULL,
                message TEXT NOT NULL,
                
                -- Optional context
                request_id TEXT,
                pipeline_id TEXT,
                error_type TEXT,
                stack_trace TEXT,
                
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Table 4: Usage Aggregates (Pre-computed stats)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usage_aggregates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                hour INTEGER,
                
                -- Document processing stats
                documents_processed INTEGER DEFAULT 0,
                total_chunks_created INTEGER DEFAULT 0,
                document_tokens INTEGER DEFAULT 0,
                document_cost_usd REAL DEFAULT 0.0,
                
                -- Chat stats
                chat_sessions INTEGER DEFAULT 0,
                chat_messages INTEGER DEFAULT 0,
                chat_tokens INTEGER DEFAULT 0,
                chat_cost_usd REAL DEFAULT 0.0,
                
                -- Search stats
                total_searches INTEGER DEFAULT 0,
                avg_chunks_retrieved REAL DEFAULT 0.0,
                
                -- Errors
                error_count INTEGER DEFAULT 0,
                
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date, hour)
            )
        """)
        
        # Create indexes for common queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_doc_logs_timestamp ON document_processing_logs(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_doc_logs_pipeline ON document_processing_logs(pipeline_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_logs_timestamp ON chat_session_logs(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_logs_request ON chat_session_logs(request_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_level ON system_logs(level)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_component ON system_logs(component)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_aggregates_date ON usage_aggregates(date)")
        
        conn.commit()
        conn.close()
    
    # =========================================================================
    # Document Processing Logs
    # =========================================================================
    
    def log_document_stage(
        self,
        pipeline_id: str,
        filename: str,
        stage: str,
        stage_order: int,
        model: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        duration_ms: float = 0.0,
        success: bool = True,
        chunks_created: int = 0,
        images_processed: int = 0,
        error: Optional[str] = None,
        uploaded_by: Optional[str] = None,
        document_id: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        content_hash: Optional[str] = None
    ):
        """Log a document processing stage."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO document_processing_logs (
                timestamp, document_id, filename, file_size_bytes, content_hash,
                pipeline_id, stage, stage_order,
                model, input_tokens, output_tokens, total_tokens, estimated_cost_usd, duration_ms,
                success, chunks_created, images_processed, error, uploaded_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            document_id, filename, file_size_bytes, content_hash,
            pipeline_id, stage, stage_order,
            model, input_tokens, output_tokens, total_tokens, estimated_cost_usd, duration_ms,
            1 if success else 0, chunks_created, images_processed, error, uploaded_by
        ))
        
        conn.commit()
        conn.close()
    
    def get_document_processing_stats(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """Get document processing statistics."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if not start_time:
            start_time = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        if not end_time:
            end_time = datetime.now(timezone.utc).isoformat()
        
        # Get overall stats
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT pipeline_id) as documents_processed,
                SUM(chunks_created) as total_chunks,
                SUM(total_tokens) as total_tokens,
                SUM(estimated_cost_usd) as total_cost,
                AVG(duration_ms) as avg_duration_ms,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate
            FROM document_processing_logs
            WHERE timestamp >= ? AND timestamp <= ?
        """, (start_time, end_time))
        
        row = cursor.fetchone()
        stats = {
            "documents_processed": row["documents_processed"] or 0,
            "total_chunks": row["total_chunks"] or 0,
            "total_tokens": row["total_tokens"] or 0,
            "total_cost_usd": row["total_cost"] or 0.0,
            "avg_processing_time_ms": row["avg_duration_ms"] or 0.0,
            "success_rate": row["success_rate"] or 100.0
        }
        
        # Get stats by stage
        cursor.execute("""
            SELECT 
                stage,
                COUNT(*) as calls,
                SUM(total_tokens) as tokens,
                SUM(estimated_cost_usd) as cost
            FROM document_processing_logs
            WHERE timestamp >= ? AND timestamp <= ?
            GROUP BY stage
        """, (start_time, end_time))
        
        stats["by_stage"] = {}
        for row in cursor.fetchall():
            stats["by_stage"][row["stage"]] = {
                "calls": row["calls"],
                "tokens": row["tokens"] or 0,
                "cost": row["cost"] or 0.0
            }
        
        # Get recent uploads
        cursor.execute("""
            SELECT 
                pipeline_id,
                filename,
                uploaded_by,
                MIN(timestamp) as started_at,
                MAX(timestamp) as completed_at,
                SUM(chunks_created) as chunks,
                SUM(total_tokens) as tokens,
                SUM(estimated_cost_usd) as cost,
                MIN(success) as success
            FROM document_processing_logs
            WHERE timestamp >= ? AND timestamp <= ?
            GROUP BY pipeline_id
            ORDER BY started_at DESC
            LIMIT ?
        """, (start_time, end_time, limit))
        
        stats["recent_uploads"] = []
        for row in cursor.fetchall():
            stats["recent_uploads"].append({
                "pipeline_id": row["pipeline_id"],
                "filename": row["filename"],
                "uploaded_by": row["uploaded_by"],
                "timestamp": row["started_at"],
                "chunks": row["chunks"] or 0,
                "tokens_used": row["tokens"] or 0,
                "cost_usd": row["cost"] or 0.0,
                "status": "success" if row["success"] == 1 else "failed"
            })
        
        conn.close()
        return stats
    
    # =========================================================================
    # Chat Session Logs
    # =========================================================================
    
    @staticmethod
    def hash_session_id(session_id: str) -> str:
        """Hash a session ID for privacy."""
        return hashlib.sha256(session_id.encode()).hexdigest()[:16]
    
    def log_chat_stage(
        self,
        request_id: str,
        stage: str,
        stage_order: int,
        session_id: Optional[str] = None,
        model: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        duration_ms: float = 0.0,
        chunks_retrieved: int = 0,
        chunks_used: int = 0,
        success: bool = True,
        error: Optional[str] = None
    ):
        """Log a chat processing stage."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        session_hash = self.hash_session_id(session_id) if session_id else None
        
        cursor.execute("""
            INSERT INTO chat_session_logs (
                timestamp, session_id_hash, request_id, stage, stage_order,
                model, input_tokens, output_tokens, total_tokens, estimated_cost_usd, duration_ms,
                chunks_retrieved, chunks_used, success, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            session_hash, request_id, stage, stage_order,
            model, input_tokens, output_tokens, total_tokens, estimated_cost_usd, duration_ms,
            chunks_retrieved, chunks_used, 1 if success else 0, error
        ))
        
        conn.commit()
        conn.close()
    
    def get_chat_stats(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get chat statistics (aggregated, no PII)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if not start_time:
            start_time = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        if not end_time:
            end_time = datetime.now(timezone.utc).isoformat()
        
        # Get overall chat stats
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT session_id_hash) as total_sessions,
                COUNT(DISTINCT request_id) as total_messages,
                SUM(total_tokens) as total_tokens,
                SUM(estimated_cost_usd) as total_cost,
                AVG(duration_ms) as avg_duration_ms,
                AVG(chunks_retrieved) as avg_chunks_retrieved,
                AVG(chunks_used) as avg_chunks_used
            FROM chat_session_logs
            WHERE timestamp >= ? AND timestamp <= ?
        """, (start_time, end_time))
        
        row = cursor.fetchone()
        stats = {
            "total_sessions": row["total_sessions"] or 0,
            "total_messages": row["total_messages"] or 0,
            "total_tokens": row["total_tokens"] or 0,
            "total_cost_usd": row["total_cost"] or 0.0,
            "avg_response_time_ms": row["avg_duration_ms"] or 0.0,
            "search_stats": {
                "avg_chunks_retrieved": row["avg_chunks_retrieved"] or 0.0,
                "avg_chunks_used": row["avg_chunks_used"] or 0.0
            }
        }
        
        # Get stats by stage
        cursor.execute("""
            SELECT 
                stage,
                COUNT(*) as calls,
                SUM(total_tokens) as tokens,
                SUM(estimated_cost_usd) as cost
            FROM chat_session_logs
            WHERE timestamp >= ? AND timestamp <= ?
            GROUP BY stage
        """, (start_time, end_time))
        
        stats["by_stage"] = {}
        for row in cursor.fetchall():
            stats["by_stage"][row["stage"]] = {
                "calls": row["calls"],
                "tokens": row["tokens"] or 0,
                "cost": row["cost"] or 0.0
            }
        
        # Calculate p95 response time
        cursor.execute("""
            SELECT duration_ms
            FROM chat_session_logs
            WHERE timestamp >= ? AND timestamp <= ? AND stage = 'response_generation'
            ORDER BY duration_ms
        """, (start_time, end_time))
        
        durations = [row["duration_ms"] for row in cursor.fetchall() if row["duration_ms"]]
        if durations:
            p95_index = int(len(durations) * 0.95)
            stats["p95_response_time_ms"] = durations[min(p95_index, len(durations) - 1)]
        else:
            stats["p95_response_time_ms"] = 0.0
        
        conn.close()
        return stats
    
    # =========================================================================
    # System Logs
    # =========================================================================
    
    def log_system_event(
        self,
        level: str,
        component: str,
        message: str,
        request_id: Optional[str] = None,
        pipeline_id: Optional[str] = None,
        error_type: Optional[str] = None,
        stack_trace: Optional[str] = None
    ):
        """Log a system event."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO system_logs (
                timestamp, level, component, message,
                request_id, pipeline_id, error_type, stack_trace
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            level, component, message,
            request_id, pipeline_id, error_type, stack_trace
        ))
        
        conn.commit()
        conn.close()
    
    def get_recent_errors(
        self,
        hours: int = 1,
        limit: int = 50
    ) -> Dict[str, Any]:
        """Get recent errors."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        start_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        # Count errors by component
        cursor.execute("""
            SELECT component, COUNT(*) as count
            FROM system_logs
            WHERE timestamp >= ? AND level IN ('ERROR', 'CRITICAL')
            GROUP BY component
        """, (start_time,))
        
        by_component = {}
        total_errors = 0
        for row in cursor.fetchall():
            by_component[row["component"]] = row["count"]
            total_errors += row["count"]
        
        # Get recent error details
        cursor.execute("""
            SELECT timestamp, level, component, message, pipeline_id, error_type
            FROM system_logs
            WHERE timestamp >= ? AND level IN ('ERROR', 'CRITICAL')
            ORDER BY timestamp DESC
            LIMIT ?
        """, (start_time, limit))
        
        recent = []
        for row in cursor.fetchall():
            recent.append({
                "timestamp": row["timestamp"],
                "level": row["level"],
                "component": row["component"],
                "message": row["message"],
                "pipeline_id": row["pipeline_id"],
                "error_type": row["error_type"]
            })
        
        conn.close()
        
        return {
            "period": f"{hours}h",
            "total_errors": total_errors,
            "by_component": by_component,
            "recent": recent
        }
    
    # =========================================================================
    # Cost Analysis
    # =========================================================================
    
    def get_cost_breakdown(
        self,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get cost breakdown by operation and model."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        start_time = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
        # Document processing costs
        cursor.execute("""
            SELECT SUM(estimated_cost_usd) as cost
            FROM document_processing_logs
            WHERE timestamp >= ?
        """, (start_time,))
        doc_cost = cursor.fetchone()["cost"] or 0.0
        
        # Chat costs
        cursor.execute("""
            SELECT SUM(estimated_cost_usd) as cost
            FROM chat_session_logs
            WHERE timestamp >= ?
        """, (start_time,))
        chat_cost = cursor.fetchone()["cost"] or 0.0
        
        # Costs and tokens by model (from both tables)
        cursor.execute("""
            SELECT model, SUM(estimated_cost_usd) as cost, SUM(total_tokens) as tokens
            FROM (
                SELECT model, estimated_cost_usd, total_tokens FROM document_processing_logs WHERE timestamp >= ?
                UNION ALL
                SELECT model, estimated_cost_usd, total_tokens FROM chat_session_logs WHERE timestamp >= ?
            )
            WHERE model IS NOT NULL
            GROUP BY model
        """, (start_time, start_time))
        
        by_model = {}
        for row in cursor.fetchall():
            by_model[row["model"]] = {
                "cost": row["cost"] or 0.0,
                "tokens": row["tokens"] or 0
            }
        
        # Daily trend
        cursor.execute("""
            SELECT 
                DATE(timestamp) as date,
                SUM(estimated_cost_usd) as cost
            FROM (
                SELECT timestamp, estimated_cost_usd FROM document_processing_logs WHERE timestamp >= ?
                UNION ALL
                SELECT timestamp, estimated_cost_usd FROM chat_session_logs WHERE timestamp >= ?
            )
            GROUP BY DATE(timestamp)
            ORDER BY date DESC
            LIMIT 30
        """, (start_time, start_time))
        
        daily_trend = []
        for row in cursor.fetchall():
            daily_trend.append({
                "date": row["date"],
                "cost": row["cost"] or 0.0
            })
        
        conn.close()
        
        return {
            "period": f"{days}d",
            "total_cost_usd": doc_cost + chat_cost,
            "by_operation": {
                "document_processing": doc_cost,
                "chat": chat_cost
            },
            "by_model": by_model,
            "daily_trend": daily_trend
        }
    
    # =========================================================================
    # Health Check
    # =========================================================================
    
    def get_health_summary(self) -> Dict[str, Any]:
        """Get system health summary."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Check for recent errors
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM system_logs
            WHERE timestamp >= ? AND level IN ('ERROR', 'CRITICAL')
        """, (one_hour_ago,))
        recent_errors = cursor.fetchone()["count"]
        
        # Determine status
        if recent_errors == 0:
            status = "All Systems Operational"
            indicator = "🟢"
        elif recent_errors < 5:
            status = "Minor Issues Detected"
            indicator = "🟡"
        else:
            status = "System Issues Detected"
            indicator = "🔴"
        
        conn.close()
        
        return {
            "status": status,
            "indicator": indicator,
            "recent_errors": recent_errors
        }
    
    # =========================================================================
    # Activity Logs (Safe for Admin Display)
    # =========================================================================
    
    def get_activity_logs(
        self,
        log_type: str = "all",
        start_time: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get activity logs safe for admin display.
        
        Sanitizes output to remove:
        - User content/queries
        - Session IDs
        - Stack traces
        - Internal paths
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if not start_time:
            start_time = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        
        logs = []
        
        if log_type == "documents":
            # Get document processing activities
            cursor.execute("""
                SELECT 
                    timestamp, filename, stage, success, 
                    chunks_created, total_tokens, estimated_cost_usd,
                    duration_ms, error, uploaded_by
                FROM document_processing_logs
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (start_time, limit))
            
            for row in cursor.fetchall():
                # Sanitize error message (remove paths, limit length)
                error_msg = None
                if row["error"]:
                    error_msg = self._sanitize_error(row["error"])
                
                logs.append({
                    "type": "document",
                    "timestamp": row["timestamp"],
                    "action": f"Document {row['stage'].replace('_', ' ')}",
                    "target": row["filename"],
                    "success": bool(row["success"]),
                    "details": {
                        "chunks_created": row["chunks_created"] or 0,
                        "tokens": row["total_tokens"] or 0,
                        "cost_usd": row["estimated_cost_usd"] or 0,
                        "duration_ms": row["duration_ms"] or 0,
                        "uploaded_by": row["uploaded_by"] or "System"
                    },
                    "error": error_msg
                })
        
        elif log_type == "chat":
            # Get chat activities (NO user content, just metrics)
            cursor.execute("""
                SELECT 
                    timestamp, stage, model, success,
                    total_tokens, estimated_cost_usd, duration_ms,
                    chunks_retrieved, chunks_used, error
                FROM chat_session_logs
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (start_time, limit))
            
            for row in cursor.fetchall():
                error_msg = None
                if row["error"]:
                    error_msg = self._sanitize_error(row["error"])
                
                logs.append({
                    "type": "chat",
                    "timestamp": row["timestamp"],
                    "action": f"Chat {row['stage'].replace('_', ' ')}",
                    "target": row["model"] or "gpt-4o",
                    "success": bool(row["success"]),
                    "details": {
                        "tokens": row["total_tokens"] or 0,
                        "cost_usd": row["estimated_cost_usd"] or 0,
                        "duration_ms": row["duration_ms"] or 0,
                        "chunks_retrieved": row["chunks_retrieved"] or 0,
                        "chunks_used": row["chunks_used"] or 0
                    },
                    "error": error_msg
                })
        
        elif log_type == "errors":
            # Get system errors (sanitized)
            cursor.execute("""
                SELECT 
                    timestamp, level, component, message
                FROM system_logs
                WHERE timestamp >= ? AND level IN ('ERROR', 'CRITICAL', 'WARNING')
                ORDER BY timestamp DESC
                LIMIT ?
            """, (start_time, limit))
            
            for row in cursor.fetchall():
                logs.append({
                    "type": "error",
                    "timestamp": row["timestamp"],
                    "action": f"{row['level']}: {row['component']}",
                    "target": row["component"],
                    "success": False,
                    "details": {},
                    "error": self._sanitize_error(row["message"])
                })
        
        conn.close()
        return logs
    
    def _sanitize_error(self, error_msg: str) -> str:
        """
        Sanitize error message for safe display.
        Removes file paths, truncates length, removes sensitive info.
        """
        if not error_msg:
            return None
        
        import re
        
        # Remove file paths (Windows and Unix)
        sanitized = re.sub(r'[A-Za-z]:\\[^\s]+', '[path]', error_msg)
        sanitized = re.sub(r'/[^\s]+/[^\s]+', '[path]', sanitized)
        
        # Remove line numbers from tracebacks
        sanitized = re.sub(r'line \d+', 'line X', sanitized)
        
        # Truncate to reasonable length
        if len(sanitized) > 200:
            sanitized = sanitized[:200] + "..."
        
        return sanitized


# Singleton instance
_kb_log_storage = None

def get_kb_log_storage() -> KBLogStorage:
    """Get or create the KB log storage instance."""
    global _kb_log_storage
    if _kb_log_storage is None:
        _kb_log_storage = KBLogStorage()
    return _kb_log_storage
