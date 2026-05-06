"""
Lambda function for KB delete endpoint.
DELETE /kb/delete/{doc_id} - Delete document (Admin role required)
"""
import sys
import os

# Add shared modules to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.response_utils import (
    success_response, error_response, unauthorized_response, 
    server_error_response, options_response, get_path_parameter,
    forbidden_response, get_user_from_authorizer
)
from shared.db_utils import get_document, delete_document, save_log
from shared.weaviate_utils import delete_document_chunks, close_weaviate_client
from shared.s3_utils import delete_file as s3_delete_file


def lambda_handler(event, context):
    """
    Delete a document from the knowledge base.
    
    Requires Admin role.
    
    Path: DELETE /kb/delete/{doc_id}
    """
    # Handle CORS preflight
    if event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
        return options_response()
    
    try:
        # Get user from API Gateway authorizer context (admin role enforced by authorizer)
        try:
            user = get_user_from_authorizer(event)
            user_id = user['user_id']
            user_email = user.get('email') or user_id
        except Exception as e:
            return unauthorized_response(str(e))
        
        # Get document ID from path
        doc_id = get_path_parameter(event, 'doc_id')
        if not doc_id:
            return error_response("doc_id is required", 400)
        
        print(f"[KB Delete] User: {user_email}, Document: {doc_id}")
        
        # Get document to verify it exists
        document = get_document(doc_id)
        if not document:
            return error_response(f"Document {doc_id} not found", 404)
        
        file_name = document.get('file_name', 'unknown')
        s3_key = document.get('s3_key')  # None for legacy docs (pre-s3_key tracking)
        
        # Delete from Weaviate
        print(f"[KB Delete] Deleting chunks from Weaviate...")
        chunks_deleted = delete_document_chunks(doc_id)
        print(f"[KB Delete] Deleted {chunks_deleted} chunks from Weaviate")
        
        # Delete from DynamoDB
        print(f"[KB Delete] Deleting document metadata...")
        delete_document(doc_id)
        
        # Delete the original PDF from S3 (best-effort).
        # We do this AFTER Weaviate + DDB so a transient S3 error never blocks
        # the canonical KB delete. Missing s3_key (legacy doc) is silent —
        # those orphans are handled by the bucket-level lifecycle rule.
        s3_deleted = False
        if s3_key:
            print(f"[KB Delete] Deleting source PDF from S3: {s3_key}")
            try:
                s3_deleted = s3_delete_file(s3_key)
                if s3_deleted:
                    print(f"[KB Delete] Successfully removed S3 object {s3_key}")
                else:
                    print(f"[KB Delete] WARN: S3 delete returned False for {s3_key} (already gone?)")
            except Exception as e:
                print(f"[KB Delete] WARN: S3 delete error for {s3_key}: {e}")
        else:
            print(f"[KB Delete] No s3_key on document (legacy upload) — skipping S3 delete")
        
        # Log the deletion
        try:
            save_log('document', {
                'operation': 'delete',
                'document_id': doc_id,
                'file_name': file_name,
                'chunks_deleted': chunks_deleted,
                's3_key': s3_key,
                's3_deleted': s3_deleted,
                'deleted_by': user_email,
                'success': True
            })
        except Exception as e:
            print(f"Logging warning: {e}")
        
        return success_response({
            'success': True,
            'message': f"Successfully deleted document '{file_name}'",
            'deleted_doc': {
                'doc_id': doc_id,
                'file_name': file_name,
                'chunks': document.get('chunks', 0),
                'chunks_deleted': chunks_deleted,
                's3_deleted': s3_deleted
            },
            # Legacy fields for backward compatibility
            'doc_id': doc_id,
            'file_name': file_name,
            'chunks_deleted': chunks_deleted,
            'deleted': True
        })
        
    except Exception as e:
        print(f"Error deleting document: {e}")
        import traceback
        traceback.print_exc()
        
        return server_error_response(str(e))
    
    finally:
        try:
            close_weaviate_client()
        except:
            pass
