"""
Lambda Function: quota-admin-create-user
Create a new user quota (Admin only)

DynamoDB Tables:
- UserQuotas: Primary key = user_id
- QuotaAdminActions: Primary key = action_id
"""

import json
import boto3
from datetime import datetime, timezone
import uuid
import os
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
quotas_table = dynamodb.Table(os.environ.get('USER_QUOTAS_TABLE', 'UserQuotas'))
actions_table = dynamodb.Table(os.environ.get('ADMIN_ACTIONS_TABLE', 'QuotaAdminActions'))

TIER_LIMITS = {
    'free': 100_000,
    'pro': 1_000_000,
    'enterprise': 10_000_000,
    'unlimited': 999_999_999
}


def get_next_reset_date():
    """Calculate the first day of next month."""
    now = datetime.now(timezone.utc)
    if now.month == 12:
        return datetime(now.year + 1, 1, 1, tzinfo=timezone.utc).isoformat()
    return datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc).isoformat()


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
    """Create a new user quota."""
    
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
        
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        user_id = body.get('user_id')
        fullname = body.get('fullname', '')
        tier = body.get('tier', 'free').lower()
        
        if not user_id:
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'user_id is required'})
            }
        
        # Check if user already exists
        response = quotas_table.get_item(Key={'user_id': user_id})
        existing = response.get('Item')
        
        if existing:
            if existing.get('is_active', True):
                return {
                    'statusCode': 400,
                    'headers': cors_headers,
                    'body': json.dumps({'error': f'User {user_id} already has an active quota'})
                }
            else:
                # Restore the deactivated user
                now = datetime.now(timezone.utc).isoformat()
                quotas_table.update_item(
                    Key={'user_id': user_id},
                    UpdateExpression='SET is_active = :active, deactivated_at = :null, updated_at = :now, fullname = :name',
                    ExpressionAttributeValues={
                        ':active': True,
                        ':null': None,
                        ':now': now,
                        ':name': fullname or existing.get('fullname', '')
                    }
                )
                
                log_admin_action(admin_id, admin_name, 'restore_user', user_id, fullname, {'tier': tier})
                
                response = quotas_table.get_item(Key={'user_id': user_id})
                user_data = response.get('Item')
                
                return {
                    'statusCode': 200,
                    'headers': cors_headers,
                    'body': json.dumps({
                        'message': f'User {user_id} has been restored',
                        'user': {
                            'user_id': user_data['user_id'],
                            'fullname': user_data.get('fullname', ''),
                            'tier': user_data.get('tier', 'free'),
                            'monthly_limit': int(user_data.get('monthly_limit', 100000)),
                            'current_usage': int(user_data.get('current_usage', 0)),
                            'is_active': True
                        }
                    })
                }
        
        # Create new user quota
        now = datetime.now(timezone.utc).isoformat()
        monthly_limit = TIER_LIMITS.get(tier, TIER_LIMITS['free'])
        
        user_item = {
            'user_id': user_id,
            'fullname': fullname,
            'tier': tier,
            'monthly_limit': monthly_limit,
            'current_usage': 0,
            'current_cost_usd': Decimal('0.0'),
            'reset_date': get_next_reset_date(),
            'created_at': now,
            'updated_at': now,
            'is_active': True,
            'deactivated_at': None
        }
        
        quotas_table.put_item(Item=user_item)
        
        log_admin_action(admin_id, admin_name, 'create_user', user_id, fullname, {'tier': tier})
        
        print(f"Created quota for user {user_id} (tier: {tier})")
        
        return {
            'statusCode': 201,
            'headers': cors_headers,
            'body': json.dumps({
                'message': f'User {user_id} quota created successfully',
                'user': {
                    'user_id': user_id,
                    'fullname': fullname,
                    'tier': tier,
                    'monthly_limit': monthly_limit,
                    'current_usage': 0,
                    'is_active': True
                }
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to create user quota: {str(e)}'})
        }
