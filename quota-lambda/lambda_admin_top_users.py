"""
Lambda Function: quota-admin-top-users
Get top users by token usage (Admin only)

DynamoDB Tables:
- UsageLogs: Primary key = log_id
- UserQuotas: Primary key = user_id (for fullname lookup)
"""

import json
import boto3
from datetime import datetime, timezone, timedelta
import os
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource('dynamodb')
logs_table = dynamodb.Table(os.environ.get('USAGE_LOGS_TABLE', 'UsageLogs'))
quotas_table = dynamodb.Table(os.environ.get('USER_QUOTAS_TABLE', 'UserQuotas'))


def lambda_handler(event, context):
    """Get top users by token usage."""
    
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'GET,OPTIONS'
    }
    
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': ''}
    
    try:
        # Get admin info from authorizer
        request_context = event.get('requestContext', {})
        authorizer = request_context.get('authorizer', {})
        admin_role = authorizer.get('role', '')
        
        # Check admin role
        if admin_role.lower() not in ['admin', 'staff']:
            return {
                'statusCode': 403,
                'headers': cors_headers,
                'body': json.dumps({'error': 'Admin access required'})
            }
        
        # Get query parameters
        query_params = event.get('queryStringParameters', {}) or {}
        limit = int(query_params.get('limit', 10))
        hours = int(query_params.get('hours', 24))
        
        limit = min(max(limit, 1), 50)  # 1-50 users
        hours = min(max(hours, 1), 720)  # 1-720 hours (30 days)
        
        start_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        # Scan usage logs for the time period
        scan_kwargs = {
            'FilterExpression': Attr('timestamp').gte(start_time)
        }
        
        all_logs = []
        response = logs_table.scan(**scan_kwargs)
        all_logs.extend(response.get('Items', []))
        
        # Handle pagination
        while 'LastEvaluatedKey' in response:
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = logs_table.scan(**scan_kwargs)
            all_logs.extend(response.get('Items', []))
        
        # Group by user
        by_user = {}
        
        for log in all_logs:
            user_id = log.get('user_id', 'unknown')
            tokens = int(log.get('total_tokens', 0))
            cost = float(log.get('cost_usd', 0))
            
            if user_id not in by_user:
                by_user[user_id] = {
                    'user_id': user_id,
                    'fullname': log.get('fullname', ''),
                    'total_tokens': 0,
                    'total_cost_usd': 0.0,
                    'call_count': 0
                }
            
            by_user[user_id]['total_tokens'] += tokens
            by_user[user_id]['total_cost_usd'] += cost
            by_user[user_id]['call_count'] += 1
            
            # Update fullname if we have a newer one
            if log.get('fullname') and not by_user[user_id]['fullname']:
                by_user[user_id]['fullname'] = log.get('fullname')
        
        # Convert to list and sort by total tokens
        top_users = list(by_user.values())
        top_users.sort(key=lambda x: x['total_tokens'], reverse=True)
        
        # Limit results
        top_users = top_users[:limit]
        
        # Round costs
        for user in top_users:
            user['total_cost_usd'] = round(user['total_cost_usd'], 6)
        
        # Try to fill in missing fullnames from UserQuotas table
        for user in top_users:
            if not user['fullname']:
                try:
                    quota_response = quotas_table.get_item(Key={'user_id': user['user_id']})
                    if 'Item' in quota_response:
                        user['fullname'] = quota_response['Item'].get('fullname', '')
                except Exception:
                    pass
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'top_users': top_users,
                'period_hours': hours,
                'total_returned': len(top_users)
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to get top users: {str(e)}'})
        }
