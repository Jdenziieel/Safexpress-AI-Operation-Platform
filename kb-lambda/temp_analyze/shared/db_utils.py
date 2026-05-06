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
    """List all documents."""
    table = get_documents_table()
    response = table.scan()
    items = response.get('Items', [])
    
    # Handle pagination
    while 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        items.extend(response.get('Items', []))
    
    return [decimal_to_float(item) for item in items]


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
    """Get document processing statistics."""
    logs = get_logs('document', start_time)
    
    total_docs = len(set(log.get('document_id') for log in logs if log.get('document_id')))
    total_tokens = sum(log.get('tokens_used', 0) for log in logs)
    total_cost = sum(log.get('cost_usd', 0) for log in logs)
    total_chunks = sum(log.get('chunks_created', 0) for log in logs)
    
    return {
        'documents_processed': total_docs,
        'total_tokens': total_tokens,
        'total_cost_usd': total_cost,
        'total_chunks': total_chunks
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
