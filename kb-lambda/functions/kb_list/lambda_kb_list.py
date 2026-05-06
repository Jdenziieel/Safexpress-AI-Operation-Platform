"""
Lambda function for KB list endpoint.
GET /kb/list-kb - List all documents in knowledge base

Matches original knowledge-base/api/kb_routes.py list_documents endpoint
with pagination, filtering, and human-readable file sizes.
"""
import sys
import os

# Add shared modules to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.response_utils import (
    success_response, error_response, unauthorized_response, 
    server_error_response, options_response, get_user_from_authorizer,
    get_query_parameter
)
from shared.db_utils import list_documents, get_document_count
from shared.weaviate_utils import get_weaviate_documents, close_weaviate_client


def format_file_size(size_bytes: int) -> str:
    """Convert bytes to human-readable format."""
    if size_bytes is None:
        return "0 B"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


def lambda_handler(event, context):
    """
    List all documents in the knowledge base with pagination and filtering.
    
    Query Parameters:
    - limit: Maximum number of results (default: 100)
    - offset: Number of results to skip for pagination (default: 0)
    - uploaded_by: Filter by user (optional)
    - order_by: Field to sort by (default: upload_date)
    - order_dir: Sort direction ASC/DESC (default: DESC)
    
    Returns list of uploaded documents with:
    - file_name: Original filename
    - upload_date: When file was uploaded
    - file_size_bytes: File size in bytes
    - file_size_formatted: Human-readable file size
    - chunks: Number of chunks created
    - uploaded_by: User who uploaded the file
    - page_count: Number of pages in document
    """
    # Handle CORS preflight
    if event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
        return options_response()
    
    try:
        # Get user from API Gateway authorizer context
        try:
            user = get_user_from_authorizer(event)
        except Exception as e:
            return unauthorized_response(str(e))
        
        # Parse query parameters
        limit = int(get_query_parameter(event, 'limit', '100'))
        offset = int(get_query_parameter(event, 'offset', '0'))
        uploaded_by = get_query_parameter(event, 'uploaded_by', None)
        order_by = get_query_parameter(event, 'order_by', 'upload_date')
        order_dir = get_query_parameter(event, 'order_dir', 'DESC').upper()
        
        # Validate parameters
        limit = max(1, min(limit, 500))  # Cap at 500
        offset = max(0, offset)
        if order_dir not in ('ASC', 'DESC'):
            order_dir = 'DESC'
        
        print(f"[KB List] Fetching documents: limit={limit}, offset={offset}, uploaded_by={uploaded_by}")
        
        # Get documents from DynamoDB
        documents = list_documents(
            limit=limit,
            offset=offset,
            uploaded_by=uploaded_by,
            order_by=order_by,
            order_dir=order_dir
        )
        
        # Get total count for pagination
        total_count = get_document_count(uploaded_by=uploaded_by)
        
        # Try to enrich with Weaviate chunk counts
        weaviate_map = {}
        try:
            weaviate_docs = get_weaviate_documents()
            weaviate_map = {doc['doc_id']: doc['chunk_count'] for doc in weaviate_docs}
        except Exception as e:
            print(f"Warning: Could not get Weaviate chunk counts: {e}")
        
        # Format response with human-readable file sizes
        formatted_docs = []
        for doc in documents:
            size_bytes = doc.get('file_size_bytes', 0) or 0
            chunk_count = weaviate_map.get(doc['doc_id'], doc.get('chunks', 0))
            
            formatted_docs.append({
                'doc_id': doc['doc_id'],
                'file_name': doc['file_name'],
                'upload_date': doc.get('upload_date'),
                'file_size_bytes': size_bytes,
                'file_size_formatted': format_file_size(size_bytes),
                'chunks': doc.get('chunks', 0),
                'chunk_count': chunk_count,  # From Weaviate if available
                'uploaded_by': doc.get('uploaded_by') or 'anonymous',
                'page_count': doc.get('page_count'),
                'current_version': doc.get('current_version', 1),
                'content_hash': doc.get('content_hash')
            })
        
        return success_response({
            'success': True,
            'total_count': total_count,
            'count': len(formatted_docs),
            'offset': offset,
            'limit': limit,
            'documents': formatted_docs
        })
        
    except Exception as e:
        print(f"Error listing KB documents: {e}")
        import traceback
        traceback.print_exc()
        return server_error_response(str(e))
    
    finally:
        try:
            close_weaviate_client()
        except:
            pass
