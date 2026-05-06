"""
Lambda Function: auth-deactivate-user
Deactivate a user account - soft delete (Admin only)
Migrated from: authserver/api/views.py -> deactivate_user()

DynamoDB Tables:
- Users: Primary key = gmail, GSI on user_id
- AdminActivityLogs: Primary key = log_id
"""

import json
import boto3
from datetime import datetime
import uuid
import urllib.request
import urllib.error
import os

dynamodb = boto3.resource('dynamodb')
users_table = dynamodb.Table(os.environ.get('USERS_TABLE', 'Users'))
logs_table = dynamodb.Table(os.environ.get('LOGS_TABLE', 'AdminActivityLogs'))

QUOTA_SERVICE_URL = os.environ.get('QUOTA_SERVICE_URL', 'http://localhost:8011')


def call_quota_service(endpoint, method='POST', headers=None):
    """Call the quota service API"""
    try:
        url = f"{QUOTA_SERVICE_URL}{endpoint}"
        req = urllib.request.Request(url, method=method)
        req.add_header('Content-Type', 'application/json')
        
        if headers:
            for key, value in headers.items():
                req.add_header(key, value)
        
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, {'error': str(e)}
    except Exception as e:
        print(f"Quota service error: {str(e)}")
        return None, {'error': str(e)}


def log_activity(admin_email, admin_name, action, target_email, target_name, details, ip_address=''):
    """Log admin activity to DynamoDB"""
    try:
        now = datetime.utcnow().isoformat() + 'Z'
        logs_table.put_item(Item={
            'log_id': str(uuid.uuid4()),
            'admin_email': admin_email,
            'admin_name': admin_name,
            'action': action,
            'target_user_email': target_email,
            'target_user_name': target_name,
            'details': json.dumps(details) if details else None,
            'created_at': now,
            'ip_address': ip_address
        })
    except Exception as e:
        print(f"Failed to log activity: {str(e)}")


def lambda_handler(event, context):
    """Deactivate user account"""
    
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'DELETE,OPTIONS'
    }
    
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': ''}
    
    try:
        # Get admin info
        request_context = event.get('requestContext', {})
        authorizer = request_context.get('authorizer', {})
        admin_role = authorizer.get('role', '')
        admin_email = authorizer.get('gmail') or authorizer.get('email', '')
        admin_name = authorizer.get('fullname', '')
        ip_address = request_context.get('identity', {}).get('sourceIp', '')
        
        if admin_role != 'admin':
            return {
                'statusCode': 403,
                'headers': cors_headers,
                'body': json.dumps({'error': 'Permission denied. Only admins can deactivate users.'})
            }
        
        # Get user email from path parameters
        path_params = event.get('pathParameters', {}) or {}
        user_email = path_params.get('email', '').lower()
        user_id = path_params.get('user_id', '')
        
        if not user_email and not user_id:
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'User email or user_id is required'})
            }
        
        # Get existing user
        user = None
        if user_email:
            response = users_table.get_item(Key={'gmail': user_email})
            user = response.get('Item')
        
        if not user and user_id:
            # Look up by user_id using GSI
            response = users_table.query(
                IndexName='user_id-index',
                KeyConditionExpression='user_id = :uid',
                ExpressionAttributeValues={':uid': user_id}
            )
            items = response.get('Items', [])
            if items:
                user = items[0]
                user_email = user['gmail']
        
        if not user:
            return {
                'statusCode': 404,
                'headers': cors_headers,
                'body': json.dumps({'error': 'User not found'})
            }
        
        # Prevent self-deactivation
        if user_email == admin_email or user.get('user_id') == authorizer.get('user_id'):
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'You cannot deactivate your own account.'})
            }
        
        # Check if already deactivated
        if not user.get('is_active', False):
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'User is already deactivated.'})
            }
        
        # Deactivate user
        now = datetime.utcnow().isoformat() + 'Z'
        users_table.update_item(
            Key={'gmail': user_email},
            UpdateExpression='SET is_active = :active, updated_at = :now',
            ExpressionAttributeValues={
                ':active': False,
                ':now': now
            }
        )
        
        # Deactivate user's quota in token-quota-service
        quota_deactivated = False
        auth_header = event.get('headers', {}).get('Authorization', '') or event.get('headers', {}).get('authorization', '')
        headers = {'Authorization': auth_header} if auth_header else None
        
        status, _ = call_quota_service(
            f"/quota/admin/user/{user['user_id']}/deactivate",
            method='POST',
            headers=headers
        )
        if status == 200:
            quota_deactivated = True
        
        # Log activity
        log_activity(admin_email, admin_name, 'deactivate', user_email, user.get('fullname', ''),
                    {'previous_status': 'active', 'new_status': 'inactive', 'quota_deactivated': quota_deactivated},
                    ip_address)
        
        print(f"Admin {admin_email} deactivated user {user_email}")
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'message': f'User {user_email} has been deactivated.',
                'user': {
                    'user_id': user['user_id'],
                    'fullname': user.get('fullname', ''),
                    'gmail': user_email,
                    'is_active': False
                },
                'quota_deactivated': quota_deactivated
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to deactivate user: {str(e)}'})
        }
