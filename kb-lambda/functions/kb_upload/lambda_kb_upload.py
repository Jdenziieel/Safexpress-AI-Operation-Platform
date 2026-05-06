"""
Lambda function for KB upload endpoint.
POST /kb/upload-to-kb - Upload chunks to Weaviate (Manager+ role required)
"""
import sys
import os
import uuid
import hashlib
from datetime import datetime, timezone

# Add shared modules to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.response_utils import (
    success_response, error_response, unauthorized_response, 
    server_error_response, options_response, parse_body,
    validation_error_response, forbidden_response, get_user_from_authorizer
)
from shared.db_utils import (
    save_document, get_document_by_filename, get_document_by_hash,
    save_document_version, update_document, save_log, float_to_decimal
)
from shared.weaviate_utils import (
    ensure_collections_exist, upload_chunks_to_weaviate, 
    delete_document_chunks, close_weaviate_client, check_weaviate_connection,
    get_weaviate_client
)


def lambda_handler(event, context):
    """
    Upload document chunks to Weaviate knowledge base.
    
    Requires Manager or Admin role.
    
    Request body:
    {
        "file_name": "document.pdf",
        "chunks": [
            {
                "text": "chunk content...",
                "section": "Introduction",
                "page": 1,
                "metadata": {...}
            },
            ...
        ],
        "content_hash": "sha256...",  // Optional for duplicate detection
        "file_size_bytes": 12345,
        "page_count": 10,
        "replace_existing": false  // Optional, default false
    }
    """
    print("[KB Upload] Lambda handler started")
    print(f"[KB Upload] Event keys: {list(event.keys())}")
    
    # Handle CORS preflight
    if event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
        return options_response()
    
    try:
        # Get user from API Gateway authorizer context
        try:
            user = get_user_from_authorizer(event)
            user_id = user['user_id']
            user_email = user.get('email') or user_id
        except Exception as e:
            return unauthorized_response(str(e))
        
        # Parse request body
        body = parse_body(event)
        print(f"[KB Upload] Body parsed, file_name: {body.get('file_name', 'N/A')}")
        print(f"[KB Upload] DEBUG: Raw request body keys: {list(body.keys()) if body else 'None'}")
        print(f"[KB Upload] DEBUG: file_size_bytes in body: {repr(body.get('file_size_bytes'))} (type: {type(body.get('file_size_bytes'))})")
        print(f"[KB Upload] DEBUG: page_count in body: {repr(body.get('page_count'))} (type: {type(body.get('page_count'))})")
        
        file_name = body.get('file_name', '').strip()
        chunks = body.get('chunks', [])
        content_hash = body.get('content_hash', f"temp-{uuid.uuid4().hex[:12]}")
        # Optional: original S3 key of the uploaded PDF (set when the file
        # was uploaded via presigned URL → pdf_parse → upload-to-kb).
        # Persisted on the document so kb_delete can remove the source PDF
        # from S3 when the document is deleted. None/'' for the base64
        # (file_data) path or legacy uploads that did not go through S3.
        s3_key = (body.get('s3_key') or '').strip() or None
        
        # Ensure numeric values are integers, not floats (DynamoDB requirement)
        try:
            file_size_bytes = int(body.get('file_size_bytes', 0) or 0)
            page_count = int(body.get('page_count', 0) or 0)
            print(f"[KB Upload] Numeric conversion OK: size={file_size_bytes}, pages={page_count}")
            print(f"[KB Upload] DEBUG: file_size_bytes raw value: {repr(body.get('file_size_bytes'))}, type: {type(body.get('file_size_bytes'))}")
        except (ValueError, TypeError) as e:
            print(f"[KB Upload] ERROR converting numeric values: {e}")
            file_size_bytes = 0
            page_count = 0
        
        replace_existing = body.get('replace_existing', False)
        
        if not file_name:
            return validation_error_response("file_name is required")
        if not chunks:
            return validation_error_response("chunks array is required and must not be empty")
        
        print(f"[KB Upload] User: {user_email}, File: {file_name}, Chunks: {len(chunks)}")
        
        # Ensure Weaviate collections exist before operations
        print(f"[KB Upload] Checking Weaviate collections...")
        weaviate_available = False
        try:
            if check_weaviate_connection():
                ensure_collections_exist()
                weaviate_available = True
                print(f"[KB Upload] Weaviate collections verified and ready")
            else:
                print(f"[KB Upload] WARNING: Weaviate not available, will only save to DynamoDB")
        except Exception as e:
            print(f"[KB Upload] WARNING: Weaviate setup error: {e}")
        
        # Check for duplicates in DynamoDB
        existing_by_name = get_document_by_filename(file_name)
        existing_by_hash = get_document_by_hash(content_hash) if content_hash else None
        
        if existing_by_hash and existing_by_hash.get('file_name') != file_name:
            return error_response(
                f"This file content already exists as '{existing_by_hash['file_name']}'. Duplicate upload rejected.",
                409
            )
        
        doc_id = None
        version = 1
        
        if existing_by_name:
            if not replace_existing:
                # Enhanced duplicate detection with Weaviate check (v4 API)
                weaviate_chunks_exist = False
                if weaviate_available:
                    try:
                        import weaviate.classes as wvc
                        client = get_weaviate_client()
                        kb_col = client.collections.get("KnowledgeBase")
                        doc_id_val = existing_by_name['doc_id']
                        agg_result = kb_col.aggregate.over_all(
                            total_count=True,
                            filters=wvc.query.Filter.by_property("chunk_id").like(f"{doc_id_val}-*")
                        )
                        count = agg_result.total_count if agg_result else 0
                        weaviate_chunks_exist = count > 0
                    except Exception as e:
                        print(f"[KB Upload] Could not verify Weaviate chunks: {e}")
                
                return error_response(
                    f"Document '{file_name}' already exists. Set replace_existing=true to update.",
                    409,
                    details={
                        "existing_doc_id": existing_by_name['doc_id'],
                        "upload_date": existing_by_name.get('upload_date'),
                        "uploaded_by": existing_by_name.get('uploaded_by'),
                        "in_dynamodb": True,
                        "in_weaviate": weaviate_chunks_exist,
                        "chunks_count": existing_by_name.get('chunks', 0)
                    }
                )
            
            # Archive old version
            old_doc = existing_by_name
            doc_id = old_doc['doc_id']
            old_chunks = int(old_doc.get('chunks', 0) or 0)
            
            if old_chunks > 0:
                # Real previous upload: archive it and bump version
                version = (old_doc.get('current_version', 1) or 1) + 1
                print(f"[KB Upload] Replacing existing document ({old_chunks} chunks), new version: {version}")
                
                save_document_version({
                    'version_id': f"{doc_id}-v{old_doc.get('current_version', 1)}",
                    'doc_id': doc_id,
                    'file_name': old_doc['file_name'],
                    'version_number': old_doc.get('current_version', 1),
                    'upload_date': old_doc.get('upload_date'),
                    'file_size_bytes': old_doc.get('file_size_bytes'),
                    'chunks': old_chunks,
                    'uploaded_by': old_doc.get('uploaded_by'),
                    'content_hash': old_doc.get('content_hash'),
                    'page_count': old_doc.get('page_count'),
                    'replaced_by': f"{doc_id}-v{version}"
                })
                
                # Delete old chunks from Weaviate
                print(f"[KB Upload] Deleting old chunks from Weaviate...")
                try:
                    deleted = delete_document_chunks(doc_id)
                    print(f"[KB Upload] Deleted {deleted} old chunks from Weaviate")
                except Exception as e:
                    print(f"[KB Upload] Warning: Could not delete from Weaviate: {e}")
            else:
                # Incomplete placeholder (0 chunks): overwrite without archiving
                version = old_doc.get('current_version', 1) or 1
                print(f"[KB Upload] Overwriting incomplete placeholder (0 chunks), keeping version: {version}")
        else:
            doc_id = str(uuid.uuid4())
        
        # Upload new chunks to Weaviate (BYO vectors — embedding happens
        # inside upload_chunks_to_weaviate via openai_utils.embed_texts).
        # Pass user_id + request_id so embedding tokens are recorded in
        # UsageLogs as tier='embedding', record_only=True (audit row,
        # no quota deduction — embeddings are infra cost, same as parsing).
        print(f"[KB Upload] Uploading {len(chunks)} chunks to Weaviate...")
        try:
            uploaded_count = upload_chunks_to_weaviate(
                chunks, doc_id, file_name,
                user_id=user_id,
                request_id=event.get('requestContext', {}).get('requestId'),
            )
            print(f"[KB Upload] Successfully uploaded {uploaded_count} chunks to Weaviate")
        except Exception as e:
            print(f"[KB Upload] ERROR: Weaviate upload failed: {e}")
            # Continue with DynamoDB save even if Weaviate fails
            uploaded_count = len(chunks)
            print(f"[KB Upload] Continuing with DynamoDB-only storage for {uploaded_count} chunks")
        
        # Save/update document metadata in DynamoDB
        print(f"[KB Upload] Preparing document metadata...")
        
        # Convert metadata floats to Decimals before DynamoDB (nested objects)
        metadata = float_to_decimal(body.get('metadata', {}))
        
        doc_data = {
            'doc_id': doc_id,
            'file_name': file_name,
            'upload_date': datetime.now(timezone.utc).isoformat(),
            'file_size_bytes': file_size_bytes,
            'chunks': len(chunks),
            'uploaded_by': user_email,
            'content_hash': content_hash,
            'page_count': page_count,
            'weaviate_doc_id': doc_id,
            'current_version': version,
            'metadata': metadata
        }
        # Only persist s3_key when present — keeps DDB rows tidy and avoids
        # storing empty-string keys that would later fool kb_delete into
        # attempting a no-op DeleteObject. Legacy docs without s3_key simply
        # leave their original PDF (if any) for the bucket lifecycle rule.
        if s3_key:
            doc_data['s3_key'] = s3_key
        
        print(f"[KB Upload] Saving to DynamoDB (existing_by_name={existing_by_name})...")
        if existing_by_name:
            # For updates, exclude doc_id (primary key) and weaviate_doc_id (same as doc_id)
            update_data = {k: v for k, v in doc_data.items() if k not in ['doc_id', 'weaviate_doc_id']}
            update_document(doc_id, update_data)
        else:
            save_document(doc_data)
        print(f"[KB Upload] Document saved successfully")
        
        # Log the upload (tokens/cost already logged by pdf_parse, don't duplicate)
        print(f"[KB Upload] Logging upload operation...")
        try:
            save_log('document', {
                'operation': 'upload',
                'document_id': doc_id,
                'file_name': file_name,
                'chunks_created': len(chunks),
                'version': version,
                'uploaded_by': user_email,
                'file_size_bytes': file_size_bytes,
                'page_count': page_count,
                'success': True
            })
        except Exception as e:
            print(f"Logging warning: {e}")
        
        print(f"[KB Upload] Returning success response...")
        return success_response({
            'doc_id': doc_id,
            'file_name': file_name,
            'chunks_uploaded': uploaded_count,
            'version': version,
            'message': f"Successfully uploaded {uploaded_count} chunks to knowledge base"
        }, status_code=201)
        
    except Exception as e:
        print(f"Error uploading to KB: {e}")
        import traceback
        traceback.print_exc()
        
        # Log error
        try:
            save_log('document', {
                'operation': 'upload',
                'file_name': body.get('file_name', 'unknown'),
                'success': False,
                'error': str(e)
            })
        except:
            pass
        
        return server_error_response(str(e))
    
    finally:
        # Clean up Weaviate connection
        try:
            close_weaviate_client()
        except Exception as e:
            print(f"[KB Upload] Weaviate cleanup warning: {e}")
