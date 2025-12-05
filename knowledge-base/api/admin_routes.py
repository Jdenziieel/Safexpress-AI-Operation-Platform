"""
Admin Routes - Monitoring Endpoints for Knowledge Base

Provides admin-only endpoints for:
- System health status
- Document processing statistics
- Chat usage statistics (aggregated, no PII)
- Cost breakdown
- Error logs
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from datetime import datetime, timedelta, timezone

from database.kb_logs_db import get_kb_log_storage
from database.weaviate_client import get_weaviate_client

admin_router = APIRouter(prefix='/admin', tags=['admin'])


@admin_router.get('/health')
async def get_health():
    """
    Get system health status.
    
    Returns traffic light indicator:
    - 🟢 All Systems Operational
    - 🟡 Minor Issues Detected
    - 🔴 System Issues Detected
    """
    try:
        storage = get_kb_log_storage()
        health = storage.get_health_summary()
        
        # Check Weaviate connection
        weaviate_status = "unknown"
        weaviate_docs_count = 0
        try:
            client = get_weaviate_client()
            if client.is_connected():
                weaviate_status = "connected"
                # Get document count from Weaviate
                try:
                    kb_collection = client.collections.get("KnowledgeBase")
                    weaviate_docs_count = len(kb_collection)
                except:
                    pass
            else:
                weaviate_status = "disconnected"
        except Exception as e:
            weaviate_status = f"error: {str(e)[:50]}"
        
        return {
            "status": health["status"],
            "indicator": health["indicator"],
            "services": {
                "database": {"status": "connected"},
                "weaviate": {"status": weaviate_status, "chunks_stored": weaviate_docs_count}
            },
            "recent_errors": health["recent_errors"]
        }
    
    except Exception as e:
        return {
            "status": "Unable to determine status",
            "indicator": "🟡",
            "services": {
                "database": {"status": "unknown"},
                "weaviate": {"status": "unknown"}
            },
            "error": str(e)
        }


@admin_router.get('/weaviate-documents')
async def get_weaviate_documents(
    limit: int = Query(50, ge=1, le=200, description="Maximum documents to return")
):
    """
    Get documents stored in vector database.
    
    Returns document info from SQLite documents table:
    - filename, upload_date, uploaded_by, version, total_chunks
    """
    try:
        from database.document_db import DocumentDatabase
        
        # Get documents from SQLite (authoritative source)
        doc_db = DocumentDatabase()
        sql_documents = doc_db.list_documents(limit=limit, order_by="upload_date", order_dir="DESC")
        
        # Build response from SQLite data
        documents = []
        total_chunks = 0
        
        for doc in sql_documents:
            chunks = doc.get("chunks", 0)
            total_chunks += chunks
            
            documents.append({
                "doc_id": doc.get("doc_id"),
                "filename": doc.get("file_name", "unknown"),
                "upload_date": doc.get("upload_date"),
                "uploaded_by": doc.get("uploaded_by") or "anonymous",
                "version": doc.get("current_version", 1),
                "total_chunks": chunks,
                "page_count": doc.get("page_count"),
                "file_size_bytes": doc.get("file_size_bytes"),
                "weaviate_doc_id": doc.get("weaviate_doc_id")
            })
        
        return {
            "documents": documents,
            "total_documents": len(documents),
            "total_chunks": total_chunks
        }
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"documents": [], "error": str(e), "total_documents": 0, "total_chunks": 0}


@admin_router.get('/documents')
async def get_document_stats(
    period: str = Query("24h", description="Time period: 1h, 6h, 24h, 7d, 30d")
):
    """
    Get document processing statistics.
    
    Shows admin uploads with full visibility for accountability.
    """
    try:
        storage = get_kb_log_storage()
        
        # Parse period
        period_map = {
            "1h": timedelta(hours=1),
            "6h": timedelta(hours=6),
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30)
        }
        delta = period_map.get(period, timedelta(hours=24))
        start_time = (datetime.now(timezone.utc) - delta).isoformat()
        
        stats = storage.get_document_processing_stats(start_time=start_time)
        stats["period"] = period
        
        return stats
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting document stats: {str(e)}")


@admin_router.get('/chat-stats')
async def get_chat_stats(
    period: str = Query("24h", description="Time period: 1h, 6h, 24h, 7d, 30d")
):
    """
    Get chat usage statistics (aggregated, no PII).
    
    Does NOT expose:
    - User IDs
    - Session IDs (only hashed internally)
    - Message content
    - User queries
    """
    try:
        storage = get_kb_log_storage()
        
        # Parse period
        period_map = {
            "1h": timedelta(hours=1),
            "6h": timedelta(hours=6),
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30)
        }
        delta = period_map.get(period, timedelta(hours=24))
        start_time = (datetime.now(timezone.utc) - delta).isoformat()
        
        stats = storage.get_chat_stats(start_time=start_time)
        stats["period"] = period
        
        return stats
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting chat stats: {str(e)}")


@admin_router.get('/costs')
async def get_cost_breakdown(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze")
):
    """
    Get cost breakdown by operation and model.
    """
    try:
        storage = get_kb_log_storage()
        return storage.get_cost_breakdown(days=days)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting cost breakdown: {str(e)}")


@admin_router.get('/errors')
async def get_errors(
    hours: int = Query(1, ge=1, le=24, description="Hours to look back"),
    limit: int = Query(50, ge=1, le=200, description="Maximum errors to return")
):
    """
    Get recent errors and warnings.
    """
    try:
        storage = get_kb_log_storage()
        return storage.get_recent_errors(hours=hours, limit=limit)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting errors: {str(e)}")


@admin_router.get('/stats')
async def get_combined_stats(
    period: str = Query("24h", description="Time period: 1h, 6h, 24h, 7d, 30d")
):
    """
    Get combined statistics for the admin dashboard.
    
    This is a convenience endpoint that combines document and chat stats.
    """
    try:
        storage = get_kb_log_storage()
        
        # Parse period
        period_map = {
            "1h": timedelta(hours=1),
            "6h": timedelta(hours=6),
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30)
        }
        delta = period_map.get(period, timedelta(hours=24))
        start_time = (datetime.now(timezone.utc) - delta).isoformat()
        
        doc_stats = storage.get_document_processing_stats(start_time=start_time)
        chat_stats = storage.get_chat_stats(start_time=start_time)
        
        # Calculate totals
        total_tokens = (doc_stats.get("total_tokens", 0) or 0) + (chat_stats.get("total_tokens", 0) or 0)
        total_cost = (doc_stats.get("total_cost_usd", 0) or 0) + (chat_stats.get("total_cost_usd", 0) or 0)
        
        return {
            "period": period,
            "documents": {
                "processed": doc_stats.get("documents_processed", 0),
                "chunks_created": doc_stats.get("total_chunks", 0),
                "tokens": doc_stats.get("total_tokens", 0) or 0,
                "cost_usd": doc_stats.get("total_cost_usd", 0) or 0
            },
            "chat": {
                "sessions": chat_stats.get("total_sessions", 0),
                "messages": chat_stats.get("total_messages", 0),
                "tokens": chat_stats.get("total_tokens", 0) or 0,
                "cost_usd": chat_stats.get("total_cost_usd", 0) or 0,
                "avg_response_time_ms": chat_stats.get("avg_response_time_ms", 0)
            },
            "totals": {
                "tokens": total_tokens,
                "cost_usd": total_cost
            }
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting combined stats: {str(e)}")


@admin_router.get('/activity-logs')
async def get_activity_logs(
    hours: int = Query(24, ge=1, le=168, description="Hours to look back (max 7 days)"),
    limit: int = Query(50, ge=1, le=200, description="Maximum logs to return"),
    log_type: str = Query("all", description="Filter by type: all, documents, chat, errors")
):
    """
    Get recent activity logs for admin monitoring.
    
    Returns sanitized logs safe for display:
    - Document processing activities (uploads, stages, errors)
    - Chat processing activities (no user content, just metrics)
    - System errors (no stack traces)
    
    Does NOT expose:
    - User queries or message content
    - Session IDs (even hashed)
    - Stack traces
    - Internal paths
    """
    try:
        storage = get_kb_log_storage()
        
        start_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        logs = []
        
        # Get document processing logs
        if log_type in ["all", "documents"]:
            doc_logs = storage.get_activity_logs(
                log_type="documents",
                start_time=start_time,
                limit=limit
            )
            logs.extend(doc_logs)
        
        # Get chat activity logs (sanitized - no user content)
        if log_type in ["all", "chat"]:
            chat_logs = storage.get_activity_logs(
                log_type="chat",
                start_time=start_time,
                limit=limit
            )
            logs.extend(chat_logs)
        
        # Get error logs (sanitized - no stack traces)
        if log_type in ["all", "errors"]:
            error_logs = storage.get_activity_logs(
                log_type="errors",
                start_time=start_time,
                limit=limit
            )
            logs.extend(error_logs)
        
        # Sort by timestamp descending
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        # Limit total results
        logs = logs[:limit]
        
        return {
            "logs": logs,
            "total": len(logs),
            "period_hours": hours,
            "filter": log_type
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting activity logs: {str(e)}")
