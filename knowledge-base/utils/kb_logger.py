"""
KB Logger - Structured Logging with Pipeline Tracking

Provides logging utilities for Knowledge Base operations:
- Document processing pipeline tracking
- Chat session logging (privacy-focused)
- System event logging
"""

import uuid
import time
import traceback
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable
from functools import wraps
from contextlib import contextmanager

from database.kb_logs_db import get_kb_log_storage


class PipelineContext:
    """Context for tracking a document processing pipeline."""
    
    def __init__(self, filename: str, uploaded_by: Optional[str] = None):
        self.pipeline_id = f"doc-{uuid.uuid4().hex[:12]}"
        self.filename = filename
        self.uploaded_by = uploaded_by
        self.stage_order = 0
        self.start_time = time.time()
        self.document_id = None
        self.file_size_bytes = None
        self.content_hash = None
    
    def next_stage(self) -> int:
        """Get the next stage order number."""
        self.stage_order += 1
        return self.stage_order


class RequestContext:
    """Context for tracking a chat request."""
    
    def __init__(self, session_id: Optional[str] = None):
        self.request_id = f"req-{uuid.uuid4().hex[:12]}"
        self.session_id = session_id
        self.stage_order = 0
        self.start_time = time.time()
    
    def next_stage(self) -> int:
        """Get the next stage order number."""
        self.stage_order += 1
        return self.stage_order


class KBLogger:
    """Logger for Knowledge Base operations."""
    
    def __init__(self):
        self._storage = None
    
    @property
    def storage(self):
        """Lazy-load storage to avoid import issues."""
        if self._storage is None:
            self._storage = get_kb_log_storage()
        return self._storage
    
    # =========================================================================
    # Document Processing Logging
    # =========================================================================
    
    def create_pipeline_context(
        self,
        filename: str,
        uploaded_by: Optional[str] = None
    ) -> PipelineContext:
        """Create a new pipeline context for document processing."""
        ctx = PipelineContext(filename, uploaded_by)
        self.log_info("pdf", f"Starting document processing pipeline: {filename}", pipeline_id=ctx.pipeline_id)
        return ctx
    
    def log_document_stage(
        self,
        ctx: PipelineContext,
        stage: str,
        model: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        duration_ms: float = 0.0,
        success: bool = True,
        chunks_created: int = 0,
        images_processed: int = 0,
        error: Optional[str] = None
    ):
        """Log a document processing stage."""
        try:
            self.storage.log_document_stage(
                pipeline_id=ctx.pipeline_id,
                filename=ctx.filename,
                stage=stage,
                stage_order=ctx.next_stage(),
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=estimated_cost_usd,
                duration_ms=duration_ms,
                success=success,
                chunks_created=chunks_created,
                images_processed=images_processed,
                error=error,
                uploaded_by=ctx.uploaded_by,
                document_id=ctx.document_id,
                file_size_bytes=ctx.file_size_bytes,
                content_hash=ctx.content_hash
            )
        except Exception as e:
            print(f"[KBLogger] Error logging document stage: {e}")
    
    @contextmanager
    def document_stage(
        self,
        ctx: PipelineContext,
        stage: str,
        model: Optional[str] = None
    ):
        """Context manager for timing and logging a document processing stage."""
        start_time = time.time()
        result = {"success": True, "error": None, "tokens": {}}
        
        try:
            yield result
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
            self.log_error("pdf", f"Error in stage {stage}: {e}", pipeline_id=ctx.pipeline_id)
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000
            tokens = result.get("tokens", {})
            
            self.log_document_stage(
                ctx=ctx,
                stage=stage,
                model=model,
                input_tokens=tokens.get("input_tokens", 0),
                output_tokens=tokens.get("output_tokens", 0),
                total_tokens=tokens.get("total_tokens", 0),
                estimated_cost_usd=tokens.get("estimated_cost_usd", 0.0),
                duration_ms=duration_ms,
                success=result["success"],
                chunks_created=result.get("chunks_created", 0),
                images_processed=result.get("images_processed", 0),
                error=result["error"]
            )
    
    # =========================================================================
    # Chat Session Logging
    # =========================================================================
    
    def create_request_context(
        self,
        session_id: Optional[str] = None
    ) -> RequestContext:
        """Create a new request context for chat processing."""
        return RequestContext(session_id)
    
    def log_chat_stage(
        self,
        ctx: RequestContext,
        stage: str,
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
        try:
            self.storage.log_chat_stage(
                request_id=ctx.request_id,
                stage=stage,
                stage_order=ctx.next_stage(),
                session_id=ctx.session_id,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=estimated_cost_usd,
                duration_ms=duration_ms,
                chunks_retrieved=chunks_retrieved,
                chunks_used=chunks_used,
                success=success,
                error=error
            )
        except Exception as e:
            print(f"[KBLogger] Error logging chat stage: {e}")
    
    @contextmanager
    def chat_stage(
        self,
        ctx: RequestContext,
        stage: str,
        model: Optional[str] = None
    ):
        """Context manager for timing and logging a chat processing stage."""
        start_time = time.time()
        result = {"success": True, "error": None, "tokens": {}, "search": {}}
        
        try:
            yield result
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
            self.log_error("chat", f"Error in stage {stage}: {e}", request_id=ctx.request_id)
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000
            tokens = result.get("tokens", {})
            search = result.get("search", {})
            
            self.log_chat_stage(
                ctx=ctx,
                stage=stage,
                model=model,
                input_tokens=tokens.get("input_tokens", 0),
                output_tokens=tokens.get("output_tokens", 0),
                total_tokens=tokens.get("total_tokens", 0),
                estimated_cost_usd=tokens.get("estimated_cost_usd", 0.0),
                duration_ms=duration_ms,
                chunks_retrieved=search.get("chunks_retrieved", 0),
                chunks_used=search.get("chunks_used", 0),
                success=result["success"],
                error=result["error"]
            )
    
    # =========================================================================
    # System Logging
    # =========================================================================
    
    def log_info(
        self,
        component: str,
        message: str,
        request_id: Optional[str] = None,
        pipeline_id: Optional[str] = None
    ):
        """Log an info message."""
        try:
            self.storage.log_system_event(
                level="INFO",
                component=component,
                message=message,
                request_id=request_id,
                pipeline_id=pipeline_id
            )
        except Exception as e:
            print(f"[KBLogger] Error logging info: {e}")
    
    def log_warning(
        self,
        component: str,
        message: str,
        request_id: Optional[str] = None,
        pipeline_id: Optional[str] = None
    ):
        """Log a warning message."""
        try:
            self.storage.log_system_event(
                level="WARNING",
                component=component,
                message=message,
                request_id=request_id,
                pipeline_id=pipeline_id
            )
        except Exception as e:
            print(f"[KBLogger] Error logging warning: {e}")
    
    def log_error(
        self,
        component: str,
        message: str,
        request_id: Optional[str] = None,
        pipeline_id: Optional[str] = None,
        error_type: Optional[str] = None,
        exc_info: bool = False
    ):
        """Log an error message."""
        try:
            stack_trace = None
            if exc_info:
                stack_trace = traceback.format_exc()
            
            self.storage.log_system_event(
                level="ERROR",
                component=component,
                message=message,
                request_id=request_id,
                pipeline_id=pipeline_id,
                error_type=error_type,
                stack_trace=stack_trace
            )
        except Exception as e:
            print(f"[KBLogger] Error logging error: {e}")

    # =========================================================================
    # Simple Logging Methods (for quick integration)
    # =========================================================================
    
    def log_llm_call(
        self,
        pipeline_type: str,
        stage: str,
        model: str,
        tokens: int = 0,
        cost: float = 0.0,
        success: bool = True,
        error: Optional[str] = None,
        duration_ms: float = 0.0,
        chunks_retrieved: int = 0,
        chunks_used: int = 0,
        filename: Optional[str] = None,
        chunks_created: int = 0,
        pipeline_id: Optional[str] = None,
        session_id: Optional[str] = None
    ):
        """
        Simple logging method for LLM calls without context management.
        
        Args:
            pipeline_type: 'document_processing' or 'chat'
            stage: Processing stage name (e.g., 'text_chunking', 'response_generation')
            model: Model name (e.g., 'gpt-4o')
            tokens: Total tokens used
            cost: Estimated cost in USD
            success: Whether the call succeeded
            error: Error message if failed
            duration_ms: Duration in milliseconds
            chunks_retrieved: Number of chunks retrieved (for chat)
            chunks_used: Number of chunks used (for chat)
            filename: Document filename (for document processing)
            chunks_created: Number of chunks created (for document processing)
            pipeline_id: Pipeline ID for grouping related operations
            session_id: Session ID for chat (will be hashed for privacy)
        """
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            
            # Generate pipeline_id if not provided
            pid = pipeline_id or f"simple-{uuid.uuid4().hex[:8]}"
            
            if pipeline_type == "document_processing":
                # Log to document processing table
                self.storage.log_document_stage(
                    pipeline_id=pid,
                    filename=filename or "(unknown)",
                    stage=stage,
                    stage_order=0,
                    model=model,
                    input_tokens=0,
                    output_tokens=0,
                    total_tokens=tokens,
                    estimated_cost_usd=cost,
                    duration_ms=duration_ms,
                    success=success,
                    chunks_created=chunks_created,
                    images_processed=0,
                    error=error
                )
            elif pipeline_type == "chat":
                # Log to chat session table
                self.storage.log_chat_stage(
                    request_id=pid,
                    stage=stage,
                    stage_order=0,
                    session_id=session_id,
                    model=model,
                    input_tokens=0,
                    output_tokens=0,
                    total_tokens=tokens,
                    estimated_cost_usd=cost,
                    duration_ms=duration_ms,
                    chunks_retrieved=chunks_retrieved,
                    chunks_used=chunks_used,
                    success=success,
                    error=error
                )
            else:
                # Log as system event
                level = "INFO" if success else "ERROR"
                self.log_info(
                    component=pipeline_type,
                    message=f"{stage}: {tokens} tokens, ${cost:.6f}"
                ) if success else self.log_error(
                    component=pipeline_type,
                    message=f"{stage} failed: {error}"
                )
                
        except Exception as e:
            print(f"[KBLogger] Error in log_llm_call: {e}")


# Singleton instance
_kb_logger = None

def get_kb_logger() -> KBLogger:
    """Get or create the KB logger instance."""
    global _kb_logger
    if _kb_logger is None:
        _kb_logger = KBLogger()
    return _kb_logger
