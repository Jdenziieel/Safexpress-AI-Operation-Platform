"""
Lambda function for admin documents endpoints.
GET /kb-admin/weaviate-documents - List documents in Weaviate
GET /kb-admin/documents - Get document processing stats
"""
import sys
import os
from datetime import datetime, timezone, timedelta

# Add shared modules to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.response_utils import (
    success_response, error_response, unauthorized_response, 
    server_error_response, options_response, get_route_path,
    get_query_parameter, get_user_from_authorizer
)
from shared.db_utils import list_all_documents, get_document_stats
from shared.weaviate_utils import get_weaviate_documents, close_weaviate_client


def lambda_handler(event, context):
    """
    Handle admin document endpoints.
    
    Routes:
    - GET /kb-admin/weaviate-documents - List documents in Weaviate
    - GET /kb-admin/documents - Get document processing stats
    """
    # Handle CORS preflight
    if event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
        return options_response()
    
    try:
        # Get user from API Gateway authorizer context (admin role enforced by authorizer)
        try:
            user = get_user_from_authorizer(event)
        except Exception as e:
            return unauthorized_response(str(e))
        
        # Determine route
        path = get_route_path(event)
        
        if 'weaviate-documents' in path:
            return get_weaviate_documents_handler()
        else:
            return get_document_stats_handler(event)
        
    except Exception as e:
        print(f"Error in admin documents: {e}")
        import traceback
        traceback.print_exc()
        return server_error_response(str(e))
    
    finally:
        try:
            close_weaviate_client()
        except:
            pass


def get_weaviate_documents_handler():
    """Get list of documents in Weaviate with chunk counts."""
    try:
        # Get documents from DynamoDB
        db_documents = list_all_documents()
        
        # Get documents from Weaviate
        weaviate_docs = get_weaviate_documents()
        weaviate_map = {doc['doc_id']: doc for doc in weaviate_docs}
        
        # Merge information
        documents = []
        total_chunks = 0
        
        for doc in db_documents:
            doc_id = doc['doc_id']
            weaviate_info = weaviate_map.get(doc_id, {})
            chunks = weaviate_info.get('chunk_count', doc.get('chunks', 0))
            total_chunks += chunks
            
            documents.append({
                'doc_id': doc_id,
                'filename': doc.get('file_name', 'unknown'),
                'upload_date': doc.get('upload_date'),
                'uploaded_by': doc.get('uploaded_by', 'anonymous'),
                'version': doc.get('current_version', 1),
                'total_chunks': chunks,
                'page_count': doc.get('page_count'),
                'file_size_bytes': doc.get('file_size_bytes'),
                'weaviate_doc_id': doc.get('weaviate_doc_id')
            })
        
        return success_response({
            'documents': documents,
            'total_documents': len(documents),
            'total_chunks': total_chunks
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return success_response({
            'documents': [],
            'error': str(e),
            'total_documents': 0,
            'total_chunks': 0
        })


def get_document_stats_handler(event):
    """Get document processing statistics."""
    # Parse period parameter
    period = get_query_parameter(event, 'period', '24h')
    
    period_map = {
        '1h': timedelta(hours=1),
        '6h': timedelta(hours=6),
        '24h': timedelta(hours=24),
        '7d': timedelta(days=7),
        '30d': timedelta(days=30)
    }
    
    delta = period_map.get(period, timedelta(hours=24))
    start_time = (datetime.now(timezone.utc) - delta).isoformat()
    
    # Get stats from logs
    stats = get_document_stats(start_time)
    stats['period'] = period
    
    return success_response(stats)
