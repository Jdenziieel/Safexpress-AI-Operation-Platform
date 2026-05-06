"""
Lambda Function: auth-token-refresh
Handles JWT token refresh
Migrated from: Django SimpleJWT TokenRefreshView

DynamoDB Tables:
- Users: Primary key = gmail, GSI on user_id
"""

import json
import boto3
import hashlib
import hmac
import base64
from datetime import datetime, timedelta
import uuid
import os

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
secrets_client = boto3.client('secretsmanager')
users_table = dynamodb.Table(os.environ.get('USERS_TABLE', 'Users'))

# Cache for secrets
_secrets_cache = {}


def get_secret(secret_name):
    """Get secret from Secrets Manager with caching"""
    if secret_name in _secrets_cache:
        return _secrets_cache[secret_name]
    
    response = secrets_client.get_secret_value(SecretId=secret_name)
    secret = json.loads(response['SecretString'])
    _secrets_cache[secret_name] = secret
    return secret


def decode_jwt(token, secret):
    """Decode and verify a JWT token"""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None, "Invalid token format"
        
        header_b64, payload_b64, signature_b64 = parts
        
        # Verify signature
        message = f"{header_b64}.{payload_b64}"
        expected_signature = hmac.new(
            secret.encode(),
            message.encode(),
            hashlib.sha256
        ).digest()
        expected_signature_b64 = base64.urlsafe_b64encode(expected_signature).rstrip(b'=').decode()
        
        if signature_b64 != expected_signature_b64:
            return None, "Invalid signature"
        
        # Decode payload
        # Add padding if needed
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += '=' * padding
        
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode())
        
        # Check expiration
        if payload.get('exp', 0) < datetime.utcnow().timestamp():
            return None, "Token expired"
        
        # Check token type
        if payload.get('token_type') != 'refresh':
            return None, "Invalid token type"
        
        return payload, None
        
    except Exception as e:
        return None, f"Token decode error: {str(e)}"


def generate_jwt(payload, secret):
    """Generate a JWT token"""
    header = {"alg": "HS256", "typ": "JWT"}
    
    header_b64 = base64.urlsafe_b64encode(
        json.dumps(header, separators=(',', ':')).encode()
    ).rstrip(b'=').decode()
    
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(',', ':')).encode()
    ).rstrip(b'=').decode()
    
    message = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        secret.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).rstrip(b'=').decode()
    
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def lambda_handler(event, context):
    """Handle token refresh request"""
    
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'POST,OPTIONS'
    }
    
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': ''}
    
    try:
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        refresh_token = body.get('refresh')
        
        if not refresh_token:
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'Refresh token is required'})
            }
        
        # Get JWT secret
        jwt_secret = get_secret(os.environ.get('JWT_SECRET', 'prod/app/jwt'))['JWT_SECRET_KEY']
        
        # Decode and verify refresh token
        payload, error = decode_jwt(refresh_token, jwt_secret)
        
        if error:
            return {
                'statusCode': 401,
                'headers': cors_headers,
                'body': json.dumps({'error': error})
            }
        
        user_id = payload.get('user_id')
        
        # Get user from DynamoDB using GSI on user_id
        response = users_table.query(
            IndexName='user_id-index',
            KeyConditionExpression='user_id = :uid',
            ExpressionAttributeValues={':uid': user_id}
        )
        
        items = response.get('Items', [])
        if not items:
            return {
                'statusCode': 404,
                'headers': cors_headers,
                'body': json.dumps({'error': 'User not found'})
            }
        
        user = items[0]
        
        # Check if user is still active
        if not user.get('is_active', False):
            return {
                'statusCode': 401,
                'headers': cors_headers,
                'body': json.dumps({'error': 'User account is deactivated'})
            }
        
        # Generate new access token
        now = datetime.utcnow()
        access_exp = now + timedelta(minutes=60)
        
        access_payload = {
            'token_type': 'access',
            'exp': int(access_exp.timestamp()),
            'iat': int(now.timestamp()),
            'jti': str(uuid.uuid4()),
            'user_id': user['user_id'],
            'role': user.get('role', 'user'),
            'fullname': user.get('fullname', ''),
            'gmail': user['gmail'],
            'picture': user.get('google_picture', '')
        }
        
        new_access_token = generate_jwt(access_payload, jwt_secret)
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'access': new_access_token
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Token refresh failed: {str(e)}'})
        }
