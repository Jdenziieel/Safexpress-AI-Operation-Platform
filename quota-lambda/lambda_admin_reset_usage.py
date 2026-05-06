"""
Lambda Function: quota-admin-reset-usage
Manually reset a user's monthly usage (Admin only)

DynamoDB Tables:
- UserQuotas: Primary key = user_id
- QuotaAdminActions: Primary key = action_id
"""

import json
import boto3
from datetime import datetime, timezone
import uuid
import os
import calendar
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
quotas_table = dynamodb.Table(os.environ.get('USER_QUOTAS_TABLE', 'UserQuotas'))
actions_table = dynamodb.Table(os.environ.get('ADMIN_ACTIONS_TABLE', 'QuotaAdminActions'))
logs_table = dynamodb.Table(os.environ.get('USAGE_LOGS_TABLE', 'UsageLogs'))


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
    """Manually reset a user's monthly usage."""
    
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
        
        # Capture previous usage for logging
        previous_usage = int(user_data.get('current_usage', 0))
        previous_cost = float(user_data.get('current_cost_usd', 0))
        now = datetime.now(timezone.utc).isoformat()
        
        # Log usage snapshot to UsageLogs before zeroing (preserves history)
        if previous_usage > 0:
            try:
                logs_table.put_item(Item={
                    'log_id': str(uuid.uuid4()),
                    'user_id': user_id,
                    'fullname': user_data.get('fullname', ''),
                    'service': 'system',
                    'operation': 'admin_reset',
                    'model': 'N/A',
                    'input_tokens': 0,
                    'output_tokens': 0,
                    'total_tokens': previous_usage,
                    'cost_usd': Decimal(str(round(previous_cost, 6))),
                    'request_id': None,
                    'session_id': None,
                    'metadata': json.dumps({
                        'reset_type': 'manual',
                        'admin_id': admin_id,
                        'admin_name': admin_name,
                        'period_usage': previous_usage,
                        'period_cost_usd': round(previous_cost, 6),
                        'monthly_limit': int(user_data.get('monthly_limit', 100000))
                    }),
                    'timestamp': now
                })
            except Exception as e:
                print(f"Failed to log reset snapshot: {str(e)}")
        
        # Reset usage
        quotas_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression='SET current_usage = :zero, current_cost_usd = :zero_cost, updated_at = :now',
            ExpressionAttributeValues={
                ':zero': 0,
                ':zero_cost': Decimal('0.0'),
                ':now': now
            }
        )
        
        # Log admin action
        log_admin_action(admin_id, admin_name, 'reset_user_usage', user_id, 
                        user_data.get('fullname', ''),
                        {'previous_usage': previous_usage, 'previous_cost_usd': previous_cost})
        
        print(f"Admin {admin_id} reset usage for user {user_id} (was {previous_usage} tokens)")
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'success': True,
                'message': f'Reset usage for {user_id}',
                'previous_usage': previous_usage,
                'previous_cost_usd': previous_cost
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to reset usage: {str(e)}'})
        }
