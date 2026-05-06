"""
Lambda Function: quota-admin-deactivate
Soft delete (deactivate) a user's quota access (Admin only)

DynamoDB Tables:
- UserQuotas: Primary key = user_id
- QuotaAdminActions: Primary key = action_id
"""

import json
import boto3
from datetime import datetime, timezone
import uuid
import os

dynamodb = boto3.resource('dynamodb')
quotas_table = dynamodb.Table(os.environ.get('USER_QUOTAS_TABLE', 'UserQuotas'))
actions_table = dynamodb.Table(os.environ.get('ADMIN_ACTIONS_TABLE', 'QuotaAdminActions'))


def log_admin_action(admin_id, admin_name, action, target_user_id, target_user_name, details):
    """Log admin action to DynamoDB."""
    try:
        actions_table.put_item(Item={
            'action_id': str(uuid.uuid4()),
            'admin_id': admin_id or 'system',
            'admin_name': admin_name or 'System',
            'action': action,
            'target_user_id': target_user_id,
            'target_user_name': target_user_name,
            'details': json.dumps(details) if details else None,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
    except Exception as e:
        print(f"Failed to log admin action: {str(e)}")


def lambda_handler(event, context):
    """Soft delete (deactivate) a user's quota access."""
    
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'POST,OPTIONS'
    }
    
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': ''}
    
    try:
        # Get admin info from authorizer
        request_context = event.get('requestContext', {})
        authorizer = request_context.get('authorizer', {})
        admin_role = authorizer.get('role', '')
        admin_id = authorizer.get('user_id', authorizer.get('gmail', ''))
        admin_name = authorizer.get('fullname', '')
        
        # Check admin role
        if admin_role.lower() not in ['admin', 'staff']:
            return {
                'statusCode': 403,
                'headers': cors_headers,
                'body': json.dumps({'error': 'Admin access required'})
            }
        
        # Get user_id from path parameters
        path_params = event.get('pathParameters', {}) or {}
        user_id = path_params.get('user_id')
        
        if not user_id:
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'user_id is required'})
            }
        
        # Get current user
        response = quotas_table.get_item(Key={'user_id': user_id})
        user_data = response.get('Item')
        
        if not user_data:
            return {
                'statusCode': 404,
                'headers': cors_headers,
                'body': json.dumps({'error': f'User {user_id} not found'})
            }
        
        # Check if already deactivated
        if not user_data.get('is_active', True):
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': f'User {user_id} is already deactivated'})
            }
        
        # Deactivate user
        now = datetime.now(timezone.utc).isoformat()
        quotas_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression='SET is_active = :inactive, deactivated_at = :now, updated_at = :now',
            ExpressionAttributeValues={
                ':inactive': False,
                ':now': now
            }
        )
        
        # Log admin action
        log_admin_action(admin_id, admin_name, 'deactivate_user', user_id, 
                        user_data.get('fullname', ''),
                        {
                            'tier': user_data.get('tier', 'free'),
                            'usage_at_deactivation': int(user_data.get('current_usage', 0))
                        })
        
        print(f"Admin {admin_id} deactivated user {user_id}")
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'success': True,
                'message': f'User {user_id} has been deactivated'
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
