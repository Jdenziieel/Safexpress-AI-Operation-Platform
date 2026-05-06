"""
S3 utilities for Knowledge Base Lambda functions.
Handles PDF file storage and retrieval.
"""
import os
import boto3
from typing import Dict, Optional, Tuple
from botocore.config import Config

# S3 configuration
KB_FILES_BUCKET = os.environ.get('KB_FILES_BUCKET', 'capstone-kb-files')

# S3 client with signature v4 for pre-signed URLs
s3_config = Config(signature_version='s3v4')
s3_client = boto3.client('s3', config=s3_config)


def generate_upload_url(
    user_id: str,
    filename: str,
    content_type: str = 'application/pdf',
    expires_in: int = 3600
) -> Dict:
    """
    Generate a pre-signed URL for direct file upload.
    
    Args:
        user_id: User ID for folder organization
        filename: Original filename
        content_type: MIME type
        expires_in: URL expiration in seconds
        
    Returns:
        dict: Contains upload_url, s3_key, and expires_in
    """
    import uuid
    from datetime import datetime
    
    # Generate unique key
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    unique_id = uuid.uuid4().hex[:8]
    s3_key = f"uploads/{user_id}/{timestamp}_{unique_id}_{filename}"
    
    # Generate pre-signed URL
    url = s3_client.generate_presigned_url(
        'put_object',
        Params={
            'Bucket': KB_FILES_BUCKET,
            'Key': s3_key,
            'ContentType': content_type
        },
        ExpiresIn=expires_in
    )
    
    return {
        'upload_url': url,
        's3_key': s3_key,
        'expires_in': expires_in,
        'bucket': KB_FILES_BUCKET
    }


def generate_download_url(s3_key: str, expires_in: int = 3600) -> str:
    """
    Generate a pre-signed URL for file download.
    
    Args:
        s3_key: S3 object key
        expires_in: URL expiration in seconds
        
    Returns:
        str: Pre-signed download URL
    """
    url = s3_client.generate_presigned_url(
        'get_object',
        Params={
            'Bucket': KB_FILES_BUCKET,
            'Key': s3_key
        },
        ExpiresIn=expires_in
    )
    return url


def get_file(s3_key: str) -> Tuple[bytes, Dict]:
    """
    Get file content from S3.
    
    Args:
        s3_key: S3 object key
        
    Returns:
        Tuple of (file_bytes, metadata)
    """
    response = s3_client.get_object(
        Bucket=KB_FILES_BUCKET,
        Key=s3_key
    )
    
    content = response['Body'].read()
    metadata = {
        'content_type': response.get('ContentType', 'application/octet-stream'),
        'content_length': response.get('ContentLength', len(content)),
        'last_modified': str(response.get('LastModified', '')),
        'e_tag': response.get('ETag', '').strip('"')
    }
    
    return content, metadata


def upload_file(s3_key: str, content: bytes, content_type: str = 'application/pdf') -> Dict:
    """
    Upload file content to S3.
    
    Args:
        s3_key: S3 object key
        content: File content as bytes
        content_type: MIME type
        
    Returns:
        dict: Upload result with ETag
    """
    response = s3_client.put_object(
        Bucket=KB_FILES_BUCKET,
        Key=s3_key,
        Body=content,
        ContentType=content_type
    )
    
    return {
        'bucket': KB_FILES_BUCKET,
        'key': s3_key,
        'e_tag': response.get('ETag', '').strip('"'),
        'version_id': response.get('VersionId')
    }


def delete_file(s3_key: str) -> bool:
    """
    Delete file from S3.
    
    Args:
        s3_key: S3 object key
        
    Returns:
        bool: True if deleted
    """
    try:
        s3_client.delete_object(
            Bucket=KB_FILES_BUCKET,
            Key=s3_key
        )
        return True
    except Exception as e:
        print(f"Error deleting S3 object: {e}")
        return False


def file_exists(s3_key: str) -> bool:
    """
    Check if file exists in S3.
    
    Args:
        s3_key: S3 object key
        
    Returns:
        bool: True if exists
    """
    try:
        s3_client.head_object(
            Bucket=KB_FILES_BUCKET,
            Key=s3_key
        )
        return True
    except s3_client.exceptions.ClientError:
        return False


def list_user_files(user_id: str, prefix: str = 'uploads') -> list:
    """
    List all files for a user.
    
    Args:
        user_id: User ID
        prefix: S3 prefix (default 'uploads')
        
    Returns:
        list: List of file info dicts
    """
    full_prefix = f"{prefix}/{user_id}/"
    
    response = s3_client.list_objects_v2(
        Bucket=KB_FILES_BUCKET,
        Prefix=full_prefix
    )
    
    files = []
    for obj in response.get('Contents', []):
        files.append({
            'key': obj['Key'],
            'size': obj['Size'],
            'last_modified': str(obj['LastModified']),
            'filename': obj['Key'].split('/')[-1]
        })
    
    return files


def save_processed_data(doc_id: str, data: Dict, filename: str = 'metadata.json') -> Dict:
    """
    Save processed document data to S3.
    
    Args:
        doc_id: Document ID
        data: Data to save (will be JSON serialized)
        filename: Filename in processed folder
        
    Returns:
        dict: Upload result
    """
    import json
    
    s3_key = f"processed/{doc_id}/{filename}"
    content = json.dumps(data, indent=2).encode('utf-8')
    
    return upload_file(s3_key, content, 'application/json')


def get_processed_data(doc_id: str, filename: str = 'metadata.json') -> Optional[Dict]:
    """
    Get processed document data from S3.
    
    Args:
        doc_id: Document ID
        filename: Filename in processed folder
        
    Returns:
        dict or None: Parsed JSON data
    """
    import json
    
    s3_key = f"processed/{doc_id}/{filename}"
    
    try:
        content, _ = get_file(s3_key)
        return json.loads(content.decode('utf-8'))
    except Exception as e:
        print(f"Error getting processed data: {e}")
        return None


def check_s3_connection() -> bool:
    """
    Check if S3 bucket is accessible.
    
    Returns:
        bool: True if accessible
    """
    try:
        s3_client.head_bucket(Bucket=KB_FILES_BUCKET)
        return True
    except Exception as e:
        print(f"S3 connection error: {e}")
        return False
