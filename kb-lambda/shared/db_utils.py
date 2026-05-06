"""
Shared DynamoDB utilities for Knowledge Base Lambda functions.
Provides table access and common operations.
"""
import os
import boto3
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Any
import json

# Initialize DynamoDB resource
dynamodb = boto3.resource('dynamodb')

# Table names from environment variables
DOCUMENTS_TABLE = os.environ.get('DOCUMENTS_TABLE', 'KB_Documents')
VERSIONS_TABLE = os.environ.get('VERSIONS_TABLE', 'KB_DocumentVersions')
SESSIONS_TABLE = os.environ.get('SESSIONS_TABLE', 'KB_ChatSessions')
MESSAGES_TABLE = os.environ.get('MESSAGES_TABLE', 'KB_ChatMessages')
LOGS_TABLE = os.environ.get('LOGS_TABLE', 'KB_Logs')

# Get table references
def get_documents_table():
    return dynamodb.Table(DOCUMENTS_TABLE)

def get_versions_table():
    return dynamodb.Table(VERSIONS_TABLE)

def get_sessions_table():
    return dynamodb.Table(SESSIONS_TABLE)

def get_messages_table():
    return dynamodb.Table(MESSAGES_TABLE)

def get_logs_table():
    return dynamodb.Table(LOGS_TABLE)


class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder for DynamoDB Decimal types."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def decimal_to_float(obj):
    """Recursively convert Decimal to float in dictionaries."""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [decimal_to_float(i) for i in obj]
    return obj


def float_to_decimal(obj):
    """Recursively convert float to Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: float_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [float_to_decimal(i) for i in obj]
    return obj


def now_iso():
    """Get current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# Document Operations
# ============================================================================

def save_document(doc_data: Dict) -> Dict:
    """Save document metadata to DynamoDB."""
    table = get_documents_table()
    doc_data['created_at'] = now_iso()
    # Convert all floats to Decimals for DynamoDB
    doc_data = float_to_decimal(doc_data)
    table.put_item(Item=doc_data)
    return doc_data


def get_document(doc_id: str) -> Optional[Dict]:
    """Get document by ID."""
    table = get_documents_table()
    response = table.get_item(Key={'doc_id': doc_id})
    item = response.get('Item')
    return decimal_to_float(item) if item else None


def get_document_by_filename(filename: str) -> Optional[Dict]:
    """Get document by filename using GSI."""
    table = get_documents_table()
    response = table.query(
        IndexName='file_name-index',
        KeyConditionExpression='file_name = :fn',
        ExpressionAttributeValues={':fn': filename}
    )
    items = response.get('Items', [])
    return decimal_to_float(items[0]) if items else None


def get_document_by_hash(content_hash: str) -> Optional[Dict]:
    """Get document by content hash using GSI."""
    if not content_hash or content_hash.startswith("temp-"):
        return None
    table = get_documents_table()
    response = table.query(
        IndexName='content_hash-index',
        KeyConditionExpression='content_hash = :ch',
        ExpressionAttributeValues={':ch': content_hash}
    )
    items = response.get('Items', [])
    return decimal_to_float(items[0]) if items else None


def list_all_documents() -> List[Dict]:
    """List all documents (for backward compatibility)."""
    return list_documents()


def list_documents(
    limit: int = 100,
    offset: int = 0,
    uploaded_by: str = None,
    order_by: str = 'upload_date',
    order_dir: str = 'DESC'
) -> List[Dict]:
    """
    List documents with pagination and filtering.
    
    Args:
        limit: Maximum number of results to return
        offset: Number of results to skip (for pagination)
        uploaded_by: Filter by user who uploaded
        order_by: Field to sort by (upload_date, file_name, file_size_bytes)
        order_dir: Sort direction (ASC or DESC)
    
    Returns:
        List of document dictionaries
    """
    table = get_documents_table()
    
    # Build filter expression if needed
    filter_expression = None
    expression_values = {}
    
    if uploaded_by:
        from boto3.dynamodb.conditions import Attr
        filter_expression = Attr('uploaded_by').eq(uploaded_by)
    
    # DynamoDB scan (we need to scan for list all, but with filter)
    scan_kwargs = {}
    if filter_expression:
        scan_kwargs['FilterExpression'] = filter_expression
    
    response = table.scan(**scan_kwargs)
    items = response.get('Items', [])
    
    # Handle DynamoDB pagination (get all items)
    while 'LastEvaluatedKey' in response:
        scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        response = table.scan(**scan_kwargs)
        items.extend(response.get('Items', []))
    
    # Convert Decimal to float
    items = [decimal_to_float(item) for item in items]
    
    # Sort in Python (DynamoDB scan doesn't support sorting)
    reverse = order_dir.upper() == 'DESC'
    
    def get_sort_key(item):
        value = item.get(order_by)
        if value is None:
            return '' if order_by in ('upload_date', 'file_name') else 0
        return value
    
    items.sort(key=get_sort_key, reverse=reverse)
    
    # Apply offset and limit
    if offset > 0:
        items = items[offset:]
    if limit > 0:
        items = items[:limit]
    
    return items


def get_document_count(uploaded_by: str = None) -> int:
    """
    Get total count of documents, optionally filtered by user.
    
    Args:
        uploaded_by: Filter by user who uploaded (optional)
    
    Returns:
        Total count of matching documents
    """
    table = get_documents_table()
    
    if uploaded_by:
        from boto3.dynamodb.conditions import Attr
        response = table.scan(
            FilterExpression=Attr('uploaded_by').eq(uploaded_by),
            Select='COUNT'
        )
    else:
        response = table.scan(Select='COUNT')
    
    count = response.get('Count', 0)
    
    # Handle pagination for accurate count
    while 'LastEvaluatedKey' in response:
        if uploaded_by:
            from boto3.dynamodb.conditions import Attr
            response = table.scan(
                FilterExpression=Attr('uploaded_by').eq(uploaded_by),
                Select='COUNT',
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
        else:
            response = table.scan(
                Select='COUNT',
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
        count += response.get('Count', 0)
    
    return count


def delete_document(doc_id: str) -> bool:
    """Delete document by ID."""
    table = get_documents_table()
    try:
        table.delete_item(Key={'doc_id': doc_id})
        return True
    except Exception as e:
        print(f"Error deleting document: {e}")
        return False


def update_document(doc_id: str, updates: Dict) -> Optional[Dict]:
    """Update document fields."""
    table = get_documents_table()
    
    # Convert all floats to Decimals for DynamoDB
    updates = float_to_decimal(updates)
    
    update_expr = "SET "
    expr_values = {}
    expr_names = {}
    
    for key, value in updates.items():
        safe_key = f"#{key}"
        expr_names[safe_key] = key
        expr_values[f":{key}"] = value
        update_expr += f"{safe_key} = :{key}, "
    
    update_expr = update_expr.rstrip(", ")
    
    try:
        response = table.update_item(
            Key={'doc_id': doc_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
            ReturnValues='ALL_NEW'
        )
        return decimal_to_float(response.get('Attributes'))
    except Exception as e:
        print(f"Error updating document: {e}")
        return None


# ============================================================================
# Document Version Operations
# ============================================================================

def save_document_version(version_data: Dict) -> Dict:
    """Save document version to history."""
    table = get_versions_table()
    version_data['archived_date'] = now_iso()
    # Convert floats to Decimals before saving to DynamoDB
    version_data = float_to_decimal(version_data)
    table.put_item(Item=version_data)
    return version_data


def get_document_versions(doc_id: str) -> List[Dict]:
    """Get all versions of a document."""
    table = get_versions_table()
    response = table.query(
        IndexName='doc_id-index',
        KeyConditionExpression='doc_id = :did',
        ExpressionAttributeValues={':did': doc_id}
    )
    return [decimal_to_float(item) for item in response.get('Items', [])]


def get_versions_by_filename(filename: str) -> List[Dict]:
    """Get version history by filename."""
    # First get current document
    current = get_document_by_filename(filename)
    if not current:
        return []
    
    # Get all versions
    versions = get_document_versions(current['doc_id'])
    
    # Add current version info
    versions.append({
        'version_number': current.get('current_version', 1),
        'upload_date': current.get('upload_date'),
        'file_name': current.get('file_name'),
        'uploaded_by': current.get('uploaded_by'),
        'is_current': True
    })
    
    return sorted(versions, key=lambda x: x.get('version_number', 0), reverse=True)


# ============================================================================
# Chat Session Operations
# ============================================================================

def create_session(user_id: str, title: str = None, session_id: str = None) -> Dict:
    """Create a new chat session."""
    import uuid
    table = get_sessions_table()
    
    session = {
        'session_id': session_id or str(uuid.uuid4()),
        'user_id': user_id,
        'title': title or 'New Chat',
        'created_at': now_iso(),
        'updated_at': now_iso(),
        'message_count': 0,
        'total_tokens_used': 0,
        'total_cost_usd': Decimal('0.0')
    }
    
    table.put_item(Item=session)
    return decimal_to_float(session)


def get_session(session_id: str) -> Optional[Dict]:
    """Get session by ID."""
    table = get_sessions_table()
    response = table.get_item(Key={'session_id': session_id})
    item = response.get('Item')
    return decimal_to_float(item) if item else None


def get_user_sessions(user_id: str) -> List[Dict]:
    """Get all sessions for a user."""
    table = get_sessions_table()
    response = table.query(
        IndexName='user_id-index',
        KeyConditionExpression='user_id = :uid',
        ExpressionAttributeValues={':uid': user_id}
    )
    sessions = [decimal_to_float(item) for item in response.get('Items', [])]
    return sorted(sessions, key=lambda x: x.get('updated_at', ''), reverse=True)


def update_session(session_id: str, updates: Dict) -> Optional[Dict]:
    """Update session fields."""
    table = get_sessions_table()
    updates['updated_at'] = now_iso()
    
    update_expr = "SET "
    expr_values = {}
    expr_names = {}
    
    for key, value in updates.items():
        safe_key = f"#{key}"
        expr_names[safe_key] = key
        if isinstance(value, float):
            value = Decimal(str(value))
        expr_values[f":{key}"] = value
        update_expr += f"{safe_key} = :{key}, "
    
    update_expr = update_expr.rstrip(", ")
    
    try:
        response = table.update_item(
            Key={'session_id': session_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
            ReturnValues='ALL_NEW'
        )
        return decimal_to_float(response.get('Attributes'))
    except Exception as e:
        print(f"Error updating session: {e}")
        return None


def delete_session(session_id: str) -> bool:
    """Delete session and all its messages."""
    try:
        # Delete all messages first
        messages = get_session_messages(session_id)
        messages_table = get_messages_table()
        for msg in messages:
            messages_table.delete_item(Key={'message_id': msg['message_id']})
        
        # Delete session
        sessions_table = get_sessions_table()
        sessions_table.delete_item(Key={'session_id': session_id})
        return True
    except Exception as e:
        print(f"Error deleting session: {e}")
        return False


def update_session_metadata(session_id: str, metadata: Dict) -> bool:
    """
    Update session metadata (documents_referenced, total_chunks_used, etc.)
    
    Args:
        session_id: Session ID to update
        metadata: Metadata dict to merge with existing
    
    Returns:
        bool: Success status
    """
    try:
        table = get_sessions_table()
        
        # Get current session
        response = table.get_item(Key={'session_id': session_id})
        session = response.get('Item', {})
        
        # Merge metadata
        current_metadata = session.get('metadata', {})
        if isinstance(current_metadata, str):
            import json
            current_metadata = json.loads(current_metadata)
        
        current_metadata.update(metadata)
        
        # Update session
        table.update_item(
            Key={'session_id': session_id},
            UpdateExpression='SET metadata = :meta, updated_at = :now',
            ExpressionAttributeValues={
                ':meta': float_to_decimal(current_metadata),
                ':now': now_iso()
            }
        )
        return True
    except Exception as e:
        print(f"Error updating session metadata: {e}")
        return False


def increment_session_counters(session_id: str, tokens: int = 0, cost: float = 0.0):
    """Increment session message count, tokens, and cost."""
    table = get_sessions_table()
    try:
        table.update_item(
            Key={'session_id': session_id},
            UpdateExpression="""
                SET message_count = if_not_exists(message_count, :zero) + :one,
                    total_tokens_used = if_not_exists(total_tokens_used, :zero) + :tokens,
                    total_cost_usd = if_not_exists(total_cost_usd, :zero_d) + :cost,
                    updated_at = :now
            """,
            ExpressionAttributeValues={
                ':one': 1,
                ':zero': 0,
                ':zero_d': Decimal('0.0'),
                ':tokens': tokens,
                ':cost': Decimal(str(cost)),
                ':now': now_iso()
            }
        )
    except Exception as e:
        print(f"Error incrementing session counters: {e}")


# ============================================================================
# Chat Message Operations
# ============================================================================

def save_message(session_id: str, role: str, content: str, 
                 sources: List = None, metadata: Dict = None) -> Dict:
    """Save a chat message."""
    import uuid
    table = get_messages_table()
    
    message = {
        'message_id': str(uuid.uuid4()),
        'session_id': session_id,
        'role': role,
        'content': content,
        'timestamp': now_iso(),
        'sources': sources or [],
        'metadata': metadata or {}
    }
    
    table.put_item(Item=message)
    
    # Increment session counter
    increment_session_counters(
        session_id,
        tokens=metadata.get('tokens_used', 0) if metadata else 0,
        cost=metadata.get('cost_usd', 0.0) if metadata else 0.0
    )
    
    return decimal_to_float(message)


def get_session_messages(session_id: str) -> List[Dict]:
    """Get all messages for a session."""
    table = get_messages_table()
    response = table.query(
        IndexName='session_id-index',
        KeyConditionExpression='session_id = :sid',
        ExpressionAttributeValues={':sid': session_id}
    )
    messages = [decimal_to_float(item) for item in response.get('Items', [])]
    return sorted(messages, key=lambda x: x.get('timestamp', ''))


# ============================================================================
# Logging Operations
# ============================================================================

def save_log(log_type: str, details: Dict) -> Dict:
    """Save a log entry."""
    import uuid
    table = get_logs_table()
    
    log_entry = {
        'log_id': str(uuid.uuid4()),
        'timestamp': now_iso(),
        'log_type': log_type,
        **details
    }
    
    # Convert all floats to Decimals for DynamoDB
    log_entry = float_to_decimal(log_entry)
    table.put_item(Item=log_entry)
    return log_entry


def get_logs(log_type: str = None, start_time: str = None, 
             limit: int = 100) -> List[Dict]:
    """Get logs, optionally filtered by type and time."""
    table = get_logs_table()
    
    if log_type and start_time:
        response = table.query(
            IndexName='log_type-timestamp-index',
            KeyConditionExpression='log_type = :lt AND #ts >= :st',
            ExpressionAttributeNames={'#ts': 'timestamp'},
            ExpressionAttributeValues={
                ':lt': log_type,
                ':st': start_time
            },
            Limit=limit,
            ScanIndexForward=False
        )
    elif log_type:
        response = table.query(
            IndexName='log_type-timestamp-index',
            KeyConditionExpression='log_type = :lt',
            ExpressionAttributeValues={':lt': log_type},
            Limit=limit,
            ScanIndexForward=False
        )
    else:
        response = table.scan(Limit=limit)
    
    return [decimal_to_float(item) for item in response.get('Items', [])]


def get_document_stats(start_time: str = None) -> Dict:
    """Get document processing statistics from logs (cumulative processing view).
    
    Two log entries are created per upload:
      1. 'ai_parse_async' or 'parse' from pdf_parse — has tokens_used, cost_usd
      2. 'upload' from kb_upload — has document_id, chunks_created, uploaded_by
    
    Strategy:
      - documents_processed: count of successful upload logs (each upload = 1 processing event,
        including re-uploads/version updates of the same file)
      - total_chunks: sum of chunks_created from upload logs (cumulative chunks processed)
      - tokens / cost: sum ALL parse logs (each parse is a real cost, including re-uploads)
      - success / failed: count only 'upload' logs to avoid double-counting with parse logs
      - avg_processing_time: from parse logs duration_ms
      
    Fallback: if no upload logs exist yet, fall back to KB_Documents table scan
    (e.g. legacy data before logging was added).
    """
    # Get all document logs in the period
    logs = get_logs('document', start_time)
    
    parse_ops = ('parse', 'ai_parse_async')
    
    # --- Tokens & Cost: sum ALL parse logs (no dedup) ---
    # Every parse invocation costs real tokens/money, even for re-uploads (v2, v3...)
    total_tokens = 0
    total_cost = 0.0
    durations = []
    
    for log in logs:
        if log.get('operation') in parse_ops:
            total_tokens += log.get('tokens_used', 0) or 0
            total_cost += log.get('cost_usd', 0) or 0
            dur = log.get('duration_ms', 0)
            if dur:
                durations.append(dur)
    
    # --- Documents Processed / Chunks / Success / Failed: from upload logs ---
    # Each upload log = 1 processing event (includes re-uploads as separate events)
    upload_logs = [log for log in logs if log.get('operation') == 'upload']
    
    if upload_logs:
        successful = sum(1 for log in upload_logs if log.get('success') == True)
        failed = sum(1 for log in upload_logs if log.get('success') == False or log.get('error'))
        # documents_processed = total successful uploads (each re-upload counts)
        total_docs = successful
        # total_chunks = cumulative chunks created across all uploads
        total_chunks = sum(log.get('chunks_created', 0) or 0 for log in upload_logs if log.get('success') == True)
    else:
        # Fallback: no upload logs yet — check parse logs or fall back to DynamoDB
        parse_logs = [log for log in logs if log.get('operation') in parse_ops]
        if parse_logs:
            successful = sum(1 for log in parse_logs if log.get('success') == True)
            failed = sum(1 for log in parse_logs if log.get('success') == False or log.get('error'))
            total_docs = successful
            total_chunks = sum(log.get('chunks_created', 0) or 0 for log in parse_logs if log.get('success') == True)
        else:
            # Legacy fallback: no logs at all, use KB_Documents table
            all_docs = list_documents(limit=1000)
            if start_time:
                filtered_docs = [
                    doc for doc in all_docs 
                    if doc.get('upload_date', '') >= start_time
                ]
            else:
                filtered_docs = all_docs
            total_docs = len(filtered_docs)
            total_chunks = sum(doc.get('chunks', 0) for doc in filtered_docs)
            successful = total_docs
            failed = 0
    
    avg_processing_time = sum(durations) / len(durations) if durations else 0
    total_attempts = successful + failed
    success_rate = (successful / total_attempts * 100) if total_attempts > 0 else 100.0
    
    return {
        'documents_processed': total_docs,
        'total_tokens': total_tokens,
        'total_cost_usd': total_cost,
        'total_chunks': total_chunks,
        'success_rate': success_rate,
        'successful': successful,
        'failed': failed,
        'avg_processing_time_ms': avg_processing_time
    }


def get_chat_stats(start_time: str = None) -> Dict:
    """Get chat usage statistics."""
    logs = get_logs('chat', start_time)
    
    sessions = set(log.get('session_id_hash') for log in logs if log.get('session_id_hash'))
    total_messages = len(logs)
    total_tokens = sum(log.get('tokens_used', 0) for log in logs)
    total_cost = sum(log.get('cost_usd', 0) for log in logs)
    
    durations = [log.get('duration_ms', 0) for log in logs if log.get('duration_ms')]
    avg_duration = sum(durations) / len(durations) if durations else 0
    
    return {
        'total_sessions': len(sessions),
        'total_messages': total_messages,
        'total_tokens': total_tokens,
        'total_cost_usd': total_cost,
        'avg_response_time_ms': avg_duration
    }
