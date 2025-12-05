"""Knowledge base API endpoints."""
import os
import glob
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, status, Header, Depends
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from database.operations import insert_document, replace_document, delete_document_and_chunks
from database.document_db import DocumentDatabase
from services.weaviate_service import query_weaviate
from middleware.security_middleware import (
    validate_string_length,
    sanitize_filename,
    MAX_QUERY_LENGTH,
    MAX_FILENAME_LENGTH
)
from middleware.rbac import Roles, require_roles, require_admin, require_manager_or_above
import traceback

kb_router = APIRouter(prefix='/kb', tags=['knowledge-base'])

# Request models with validation
class UploadToKBRequest(BaseModel):
    chunks: List[Dict[str, Any]] = Field(..., min_length=1, max_length=10000)
    document_metadata: Dict[str, Any] = Field(default_factory=dict)
    source_filename: str = Field(..., min_length=1, max_length=MAX_FILENAME_LENGTH)
    content_hash: Optional[str] = Field(None, description="SHA256 hash of file content for duplicate detection")
    file_size_bytes: Optional[int] = Field(None, description="File size in bytes")
    force_replace: bool = Field(False, description="If true, replace existing document with same filename")
    
    @field_validator('source_filename')
    @classmethod
    def validate_filename(cls, v):
        if not v or not v.strip():
            raise ValueError("Filename cannot be empty")
        return sanitize_filename(v)
    
    @field_validator('chunks')
    @classmethod
    def validate_chunks(cls, v):
        if not v:
            raise ValueError("At least one chunk is required")
        if len(v) > 10000:
            raise ValueError("Maximum 10000 chunks allowed per document")
        return v

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=MAX_QUERY_LENGTH)
    limit: Optional[int] = Field(5, ge=1, le=100)
    generate_answer: Optional[bool] = True
    
    @field_validator('query')
    @classmethod
    def validate_query(cls, v):
        if not v or not v.strip():
            raise ValueError("Query cannot be empty")
        return validate_string_length(v.strip(), MAX_QUERY_LENGTH, "query")


@kb_router.post('/upload-to-kb')
async def upload_to_kb(
    request: UploadToKBRequest,
    authorization: Optional[str] = Header(None),
    current_user: dict = Depends(require_manager_or_above)  # Only managers/admins can upload
):
    """
    Upload processed chunks to knowledge base and save metadata to document database.
    
    IMPORTANT: Duplicate detection happens in /pdf/parse-pdf endpoint to save parsing costs.
    This endpoint focuses on uploading pre-validated chunks to Weaviate and tracking in local database.
    
    Expects JSON body with:
    - chunks: list of chunk objects (required)
    - document_metadata: document metadata dict
    - source_filename: name of source PDF (required)
    - content_hash: SHA256 hash (saved to local DB only)
    - file_size_bytes: file size in bytes (saved to local DB only)
    - force_replace (optional): if true, replace existing document
    
    Returns success status and document ID.
    """
    # DEBUG: Log what we received
    print(f"[DEBUG] Upload request received:")
    print(f"[DEBUG] - source_filename: {request.source_filename}")
    print(f"[DEBUG] - content_hash: {request.content_hash}")
    print(f"[DEBUG] - file_size_bytes: {request.file_size_bytes}")
    print(f"[DEBUG] - chunks count: {len(request.chunks)}")
    print(f"[DEBUG] - force_replace: {request.force_replace}")
    
    if not request.chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No chunks provided"
        )
    
    # Extract user from JWT token
    uploaded_by = None  # Will be set if token is valid
    
    if authorization:
        try:
            token = authorization.replace("Bearer ", "")
            
            # Google OAuth uses RS256, not HS256, so we need to decode WITHOUT verification
            # The token was already verified by the auth server
            import jwt as jose_jwt
            payload = jose_jwt.decode(token, options={"verify_signature": False})
            
            # Extract name from JWT payload
            uploaded_by = payload.get("name") or payload.get("email")
            
            if uploaded_by:
                print(f"[DEBUG] ✅ Successfully extracted uploaded_by: {uploaded_by}")
                print(f"[DEBUG] JWT payload keys: {list(payload.keys())}")
            else:
                print(f"[WARNING] ⚠️ JWT payload missing 'name' and 'email' fields")
                print(f"[WARNING] Available fields: {list(payload.keys())}")
                
        except Exception as e:
            print(f"[WARNING] ⚠️ Failed to decode JWT token: {str(e)}")
            uploaded_by = None
    else:
        print(f"[WARNING] ⚠️ No authorization header provided")
    
    # Final check - if still None, we have a problem
    if not uploaded_by:
        print(f"[ERROR] ❌ Could not extract user information from JWT token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide a valid JWT token with user information."
        )
    
    try:
        doc_db = DocumentDatabase()
        
        # ═══════════════════════════════════════════════════════════════════════
        # NOTE: Primary duplicate detection happens in /pdf/parse-pdf endpoint
        # to save parsing costs. This endpoint handles force_replace for updates.
        # ═══════════════════════════════════════════════════════════════════════
        
        # Check if we need to replace an existing document
        existing_doc = doc_db.check_duplicate_by_filename(request.source_filename)
        
        if existing_doc and not request.force_replace:
            # This shouldn't normally happen if parse-pdf was called first,
            # but handle it gracefully for direct API calls
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "duplicate_filename",
                    "message": f"Document '{request.source_filename}' already exists.",
                    "existing_doc": existing_doc,
                    "suggestion": "Set force_replace=true to overwrite."
                }
            )
        
        # Prepare file metadata for Weaviate Document collection (minimal fields only)
        file_metadata = {
            "file_name": request.source_filename,
            "page_count": request.document_metadata.get('total_pages', 0) or max(
                (chunk.get('metadata', {}).get('page', 0) for chunk in request.chunks), 
                default=0
            )
        }
        
        # Get current timestamp for created_at
        current_timestamp = datetime.now().isoformat()
        
        # Remove file extension for cleaner chunk_id prefix
        base_filename = os.path.splitext(request.source_filename)[0]
        
        # Add chunk_id and created_at to each chunk if not present
        for i, chunk in enumerate(request.chunks):
            # Ensure chunk_id includes the filename for proper document grouping
            if not chunk.get('chunk_id'):
                chunk['chunk_id'] = f"{base_filename}-chunk-{i}"
            
            # Ensure created_at is set for new uploads
            if not chunk.get('metadata'):
                chunk['metadata'] = {}
            if not chunk['metadata'].get('created_at'):
                chunk['metadata']['created_at'] = current_timestamp
        
        # ═══════════════════════════════════════════════════════════════════════
        # DOCUMENT REPLACEMENT/INSERTION LOGIC
        # ═══════════════════════════════════════════════════════════════════════
        
        action = "uploaded"
        version_info = None
        
        if existing_doc and request.force_replace:
            print(f"[INFO] Replacing existing document: {existing_doc['file_name']} (ID: {existing_doc['doc_id']})")
            
            # Get current version before archiving
            current_doc_version = existing_doc.get('current_version', 1)
            
            # Archive the current version before replacing
            version_id = doc_db.archive_document_version(existing_doc['doc_id'], replaced_by=uploaded_by)
            if version_id:
                print(f"[INFO] Archived previous version: {version_id}")
            
            # Get next version number
            next_version = doc_db.get_next_version_number(request.source_filename)
            version_info = {
                "previous_version_archived": True,
                "new_version": next_version,
                "previous_version": {
                    "version_number": current_doc_version,
                    "doc_id": existing_doc['doc_id'],
                    "uploaded_by": existing_doc.get('uploaded_by'),
                    "upload_date": existing_doc.get('upload_date')
                }
            }
            
            # Delete from SQLite document database
            doc_db.delete_document(existing_doc['doc_id'])
            # Delete from Weaviate using weaviate_doc_id
            try:
                weaviate_id = existing_doc.get('weaviate_doc_id')
                if weaviate_id:
                    delete_document_and_chunks(weaviate_id)
                    print(f"[INFO] Deleted from Weaviate: {weaviate_id}")
                else:
                    print(f"[WARN] No weaviate_doc_id found for document {existing_doc['doc_id']}")
            except Exception as e:
                print(f"[WARN] Failed to delete from Weaviate (may not exist): {e}")
            action = "replaced"
        
        # Insert new document to Weaviate
        weaviate_doc_id = insert_document(file_metadata, request.chunks)
        
        # Save to document tracking database
        doc_id = str(uuid.uuid4())  # Separate ID for our database
        
        # Generate a temporary hash if not provided (use doc_id to ensure uniqueness)
        content_hash = request.content_hash or f"temp-{doc_id}"
        
        # Determine version number
        current_version = version_info['new_version'] if version_info else 1
        
        doc_db.insert_document({
            "doc_id": doc_id,
            "file_name": request.source_filename,
            "file_size_bytes": request.file_size_bytes or 0,
            "chunks": len(request.chunks),
            "uploaded_by": uploaded_by,
            "content_hash": content_hash,
            "page_count": file_metadata["page_count"],
            "weaviate_doc_id": weaviate_doc_id,
            "metadata": request.document_metadata
        }, version=current_version)
        
        print(f"[INFO] Successfully {action} {len(request.chunks)} chunks to knowledge base")
        print(f"[INFO] Document saved to database: {doc_id} (Version {current_version})")
        print(f"[INFO] Weaviate doc_id: {weaviate_doc_id}")
        print(f"[INFO] Uploaded by: {uploaded_by or 'anonymous'}")
        
        return {
            "success": True, 
            "message": f"Successfully {action} {len(request.chunks)} chunks to knowledge base",
            "doc_id": doc_id,
            "weaviate_doc_id": weaviate_doc_id,
            "action": action,
            "version": current_version,
            "version_info": version_info
        }
        
    except HTTPException:
        # Re-raise HTTP exceptions (like 409 Conflict)
        raise
    except Exception as e:
        print(f"[ERROR] Failed to upload to knowledge base: {str(e)}")
        print(f"[ERROR] Request data - filename: {request.source_filename}, chunks: {len(request.chunks)}, content_hash: {request.content_hash}, file_size: {request.file_size_bytes}")
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@kb_router.get('/list-kb')
async def list_kb_files(
    limit: int = 100,
    offset: int = 0,
    uploaded_by: Optional[str] = None,
    order_by: str = "upload_date",
    order_dir: str = "DESC",
    authorization: Optional[str] = Header(None)
):
    """
    List all knowledge base files from document database.
    
    Query params:
    - limit: Maximum number of results (default: 100)
    - offset: Number of results to skip for pagination (default: 0)
    - uploaded_by: Filter by user (optional)
    - order_by: Field to sort by (default: upload_date)
    - order_dir: Sort direction ASC/DESC (default: DESC)
    
    Returns list of uploaded documents with:
    - file_name: Original filename
    - upload_date: When file was uploaded
    - file_size_bytes: File size in bytes
    - chunks: Number of chunks created
    - uploaded_by: User who uploaded the file
    """
    try:
        doc_db = DocumentDatabase()
        
        # Get documents from database
        documents = doc_db.list_documents(
            limit=limit,
            offset=offset,
            uploaded_by=uploaded_by,
            order_by=order_by,
            order_dir=order_dir
        )
        
        # Get total count for pagination
        total_count = doc_db.get_document_count(uploaded_by=uploaded_by)
        
        # Format response with human-readable file sizes
        formatted_docs = []
        for doc in documents:
            # Convert bytes to readable format
            size_bytes = doc["file_size_bytes"]
            if size_bytes < 1024:
                size_str = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                size_str = f"{size_bytes / 1024:.2f} KB"
            else:
                size_str = f"{size_bytes / (1024 * 1024):.2f} MB"
            
            formatted_docs.append({
                "doc_id": doc["doc_id"],
                "file_name": doc["file_name"],
                "upload_date": doc["upload_date"],
                "file_size_bytes": doc["file_size_bytes"],
                "file_size_formatted": size_str,
                "chunks": doc["chunks"],
                "uploaded_by": doc["uploaded_by"] or "anonymous",
                "page_count": doc.get("page_count")
            })
        
        return {
            "success": True,
            "total_count": total_count,
            "count": len(formatted_docs),
            "offset": offset,
            "limit": limit,
            "documents": formatted_docs
        }

    except Exception as e:
        print(f"[ERROR] Failed to list documents: {str(e)}")
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@kb_router.post('/query')
async def query_knowledge_base(request: QueryRequest):
    """
    Query the knowledge base with a question.
    
    Expects JSON body with:
    - query: the question to ask (required)
    - limit: max number of results to return (optional, default: 5)
    - generate_answer: whether to generate AI answer (optional, default: True)
    
    Returns:
    - results: list of relevant chunks
    - answer: AI-generated answer (if generate_answer=True)
    - metadata: query metadata
    """
    if not request.query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query text is required"
        )
    
    try:
        # Query the knowledge base
        result = query_weaviate(
            query_text=request.query,
            limit=request.limit,
            generate_answer=request.generate_answer
        )
        
        return {
            "success": True,
            "query": request.query,
            "results": result.get('results', []),
            "answer": result.get('answer'),
            "metadata": {
                "result_count": len(result.get('results', [])),
                "generated_at": datetime.now().isoformat(),
                "limit": request.limit
            }
        }
        
    except Exception as e:
        print(f"[ERROR] Query failed: {str(e)}")
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query failed: {str(e)}"
        )

@kb_router.delete('/delete/{doc_id}')
async def delete_document(
    doc_id: str,
    authorization: Optional[str] = Header(None),
    current_user: dict = Depends(require_admin)  # Only admins can delete documents
):
    """
    Delete a document from the knowledge base and local database.
    
    Args:
        doc_id: Document ID to delete
    
    Returns:
        Success message and deleted document info
    """
    try:
        doc_db = DocumentDatabase()
        
        # Get document info before deleting
        doc_info = doc_db.get_document(doc_id)
        
        if not doc_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document with ID '{doc_id}' not found"
            )
        
        # Delete from Weaviate
        weaviate_doc_id = doc_info.get('weaviate_doc_id')
        if weaviate_doc_id:
            delete_document_and_chunks(weaviate_doc_id)
        
        # Delete from local database
        doc_db.delete_document(doc_id)
        
        print(f"[INFO] Successfully deleted document: {doc_id}")
        print(f"[INFO] File name: {doc_info['file_name']}")
        
        return {
            "success": True,
            "message": f"Successfully deleted document '{doc_info['file_name']}'",
            "deleted_doc": {
                "doc_id": doc_id,
                "file_name": doc_info['file_name'],
                "chunks": doc_info['chunks']
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Failed to delete document: {str(e)}")
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@kb_router.get('/document-versions/{file_name}')
async def get_document_versions(
    file_name: str,
    authorization: Optional[str] = Header(None)
):
    """
    Get version history for a document by file name.
    
    Path params:
    - file_name: Name of the file to get version history for
    
    Returns:
    - current_version: Current active version info
    - version_history: List of archived versions
    """
    try:
        doc_db = DocumentDatabase()
        
        # Get current document
        current_doc = doc_db.get_document_by_filename(file_name)
        
        # Get version history
        versions = doc_db.get_document_versions(file_name)
        
        if not current_doc and not versions:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No document found with filename '{file_name}'"
            )
        
        # Format current version
        current_version = None
        if current_doc:
            current_version = {
                "doc_id": current_doc["doc_id"],
                "file_name": current_doc["file_name"],
                "version": current_doc.get("current_version", 1),
                "upload_date": current_doc["upload_date"],
                "file_size_bytes": current_doc["file_size_bytes"],
                "chunks": current_doc["chunks"],
                "uploaded_by": current_doc.get("uploaded_by") or "anonymous",
                "is_current": True
            }
        
        # Format version history
        formatted_versions = []
        for v in versions:
            formatted_versions.append({
                "version_id": v["version_id"],
                "version": v["version_number"],
                "upload_date": v["upload_date"],
                "archived_date": v["archived_date"],
                "file_size_bytes": v["file_size_bytes"],
                "chunks": v["chunks"],
                "uploaded_by": v.get("uploaded_by") or "anonymous",
                "is_current": False
            })
        
        return {
            "success": True,
            "file_name": file_name,
            "current_version": current_version,
            "version_history": formatted_versions,
            "total_versions": len(formatted_versions) + (1 if current_version else 0)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Failed to get document versions: {str(e)}")
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )
