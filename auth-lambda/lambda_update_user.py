"""
Lambda Function: auth-update-user
Update user details (Admin only)
Migrated from: authserver/api/views.py -> update_user()

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
    """Update user details"""
    
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'PATCH,PUT,OPTIONS'
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
                'body': json.dumps({'error': 'Permission denied. Only admins can update users.'})
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
        
        # Parse updates from request body
        body = json.loads(event.get('body', '{}'))
        
        update_expr_parts = ['updated_at = :now']
        expr_values = {':now': datetime.utcnow().isoformat() + 'Z'}
        expr_names = {}
        changes = {}
        old_values = {}
        
        # Update fullname if provided
        if 'fullname' in body and body['fullname'] != user.get('fullname'):
            update_expr_parts.append('fullname = :name')
            expr_values[':name'] = body['fullname']
            old_values['fullname'] = user.get('fullname')
            changes['fullname'] = body['fullname']
            
            # Sync fullname to UserQuotas table
            try:
                quota_table_name = os.environ.get('USER_QUOTAS_TABLE', 'UserQuotas')
                quota_table = dynamodb.Table(quota_table_name)
                quota_table.update_item(
                    Key={'user_id': user.get('user_id', '')},
                    UpdateExpression='SET fullname = :name',
                    ExpressionAttributeValues={':name': body['fullname']}
                )
            except Exception as e:
                print(f"Warning: Failed to sync fullname to quota table: {str(e)}")
        
        # Update role if provided
        if 'role' in body and body['role'] != user.get('role'):
            if body['role'] not in ['admin', 'manager', 'user']:
                return {
                    'statusCode': 400,
                    'headers': cors_headers,
                    'body': json.dumps({'error': 'Invalid role. Must be admin, manager, or user'})
                }
            update_expr_parts.append('#r = :role')
            expr_values[':role'] = body['role']
            expr_names['#r'] = 'role'
            old_values['role'] = user.get('role')
            changes['role'] = body['role']
        
        # Update is_active if provided
        if 'is_active' in body and body['is_active'] != user.get('is_active'):
            update_expr_parts.append('is_active = :active')
            expr_values[':active'] = body['is_active']
            old_values['is_active'] = user.get('is_active')
            changes['is_active'] = body['is_active']
            
            # Handle quota activation/deactivation
            auth_header = event.get('headers', {}).get('Authorization', '') or event.get('headers', {}).get('authorization', '')
            headers = {'Authorization': auth_header} if auth_header else None
            
            if body['is_active'] and not user.get('is_active'):
                # Reactivating - restore quota
                status, _ = call_quota_service(
                    f"/quota/admin/user/{user['user_id']}/restore",
                    method='POST',
                    headers=headers
                )
                changes['quota_restored'] = (status == 200)
            elif not body['is_active'] and user.get('is_active'):
                # Deactivating - deactivate quota
                status, _ = call_quota_service(
                    f"/quota/admin/user/{user['user_id']}/deactivate",
                    method='POST',
                    headers=headers
                )
                changes['quota_deactivated'] = (status == 200)
        
        if len(update_expr_parts) == 1:
            # No changes besides updated_at
            return {
                'statusCode': 200,
                'headers': cors_headers,
                'body': json.dumps({
                    'message': 'No changes made',
                    'user': {
                        'user_id': user['user_id'],
                        'fullname': user.get('fullname', ''),
                        'gmail': user['gmail'],
                        'role': user.get('role', 'user'),
                        'is_active': bool(user.get('is_active', False))
                    }
                })
            }
        
        # Apply updates
        update_expr = 'SET ' + ', '.join(update_expr_parts)
        update_args = {
            'Key': {'gmail': user_email},
            'UpdateExpression': update_expr,
            'ExpressionAttributeValues': expr_values,
            'ReturnValues': 'ALL_NEW'
        }
        if expr_names:
            update_args['ExpressionAttributeNames'] = expr_names
        
        result = users_table.update_item(**update_args)
        updated_user = result.get('Attributes', {})
        
        # Log activity if there were changes
        if changes:
            action = 'update'
            if 'role' in changes and len(changes) == 1:
                action = 'update_role'
            elif 'fullname' in changes and len(changes) == 1:
                action = 'update_name'
            
            log_activity(admin_email, admin_name, action, user_email, 
                        updated_user.get('fullname', ''),
                        {'old_values': old_values, 'new_values': changes}, ip_address)
        
        print(f"Admin {admin_email} updated user {user_email}: {changes}")
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'message': f'User {user_email} has been updated.',
                'user': {
                    'user_id': updated_user.get('user_id', ''),
                    'fullname': updated_user.get('fullname', ''),
                    'gmail': updated_user.get('gmail', ''),
                    'role': updated_user.get('role', 'user'),
                    'is_active': bool(updated_user.get('is_active', False))
                },
                'changes': changes
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to update user: {str(e)}'})
        }
