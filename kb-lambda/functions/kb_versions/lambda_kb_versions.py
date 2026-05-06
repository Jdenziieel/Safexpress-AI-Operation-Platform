"""
Lambda function for KB document versions endpoint.
GET /kb/document-versions/{file_name} - Get version history for a document

Matches original knowledge-base/api/kb_routes.py document-versions endpoint.
"""
import sys
import os
from urllib.parse import unquote

# Add shared modules to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.response_utils import (
    success_response, error_response, unauthorized_response, 
    server_error_response, options_response, get_path_parameter,
    get_user_from_authorizer
)
from shared.db_utils import get_document_by_filename, get_versions_by_filename


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
    Get version history for a document.
    
    Path: GET /kb/document-versions/{file_name}
    
    Returns:
    - current_version: Current active version info
    - version_history: List of archived versions
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
        
        # Get filename from path (URL decoded)
        file_name = get_path_parameter(event, 'file_name')
        if not file_name:
            return error_response("file_name is required", 400)
        
        # URL decode the filename
        file_name = unquote(file_name)
        
        print(f"[KB Versions] Getting versions for: {file_name}")
        
        # Get current document
        current_doc = get_document_by_filename(file_name)
        
        # Get version history
        versions = get_versions_by_filename(file_name)
        
        if not current_doc and not versions:
            return error_response(f"No document found with filename '{file_name}'", 404)
        
        # Format current version
        current_version = None
        if current_doc:
            size_bytes = current_doc.get('file_size_bytes', 0) or 0
            current_version = {
                'doc_id': current_doc['doc_id'],
                'file_name': current_doc['file_name'],
                'version': current_doc.get('current_version', 1),
                'upload_date': current_doc.get('upload_date'),
                'file_size_bytes': size_bytes,
                'file_size_formatted': format_file_size(size_bytes),
                'chunks': current_doc.get('chunks', 0),
                'uploaded_by': current_doc.get('uploaded_by') or 'anonymous',
                'is_current': True
            }
        
        # Format version history (skip incomplete placeholders with 0 chunks)
        formatted_versions = []
        for v in versions:
            chunk_count = int(v.get('chunks', 0) or 0)
            if chunk_count == 0:
                continue
            size_bytes = v.get('file_size_bytes', 0) or 0
            formatted_versions.append({
                'version_id': v.get('version_id'),
                'version': v.get('version_number', 1),
                'upload_date': v.get('upload_date'),
                'archived_date': v.get('archived_date'),
                'file_size_bytes': size_bytes,
                'file_size_formatted': format_file_size(size_bytes),
                'chunks': chunk_count,
                'uploaded_by': v.get('uploaded_by') or 'anonymous',
                'is_current': False
            })
        
        # Sort versions by version number descending
        formatted_versions.sort(key=lambda x: x.get('version', 0), reverse=True)
        
        return success_response({
            'success': True,
            'file_name': file_name,
            'current_version': current_version,
            'version_history': formatted_versions,
            'total_versions': len(formatted_versions) + (1 if current_version else 0)
        })
        
    except Exception as e:
        print(f"Error getting document versions: {e}")
        import traceback
        traceback.print_exc()
        return server_error_response(str(e))
