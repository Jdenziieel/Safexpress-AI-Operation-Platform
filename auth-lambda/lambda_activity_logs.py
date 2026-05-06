"""
Lambda Function: auth-activity-logs
Get admin activity logs with filtering and pagination (Admin only)
Migrated from: authserver/api/views.py -> get_admin_activity_logs()

DynamoDB Tables:
- AdminActivityLogs: Primary key = log_id, GSI on created_at
"""

import json
import boto3
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Attr
import os

dynamodb = boto3.resource('dynamodb')
logs_table = dynamodb.Table(os.environ.get('LOGS_TABLE', 'AdminActivityLogs'))

# Action display names (matches Django AdminActivityLog.ACTION_CHOICES)
ACTION_DISPLAY = {
    'onboard': 'Onboard User',
    'activate': 'Activate User',
    'deactivate': 'Deactivate User',
    'update_role': 'Update Role',
    'update_name': 'Update Name',
    'update': 'Update User'
}


def lambda_handler(event, context):
    """Get admin activity logs"""
    
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'GET,OPTIONS'
    }
    
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': ''}
    
    try:
        # Get admin info from authorizer context
        request_context = event.get('requestContext', {})
        authorizer = request_context.get('authorizer', {})
        admin_role = authorizer.get('role', '')
        
        # Check admin role
        if admin_role != 'admin':
            return {
                'statusCode': 403,
                'headers': cors_headers,
                'body': json.dumps({'error': 'Permission denied. Only admins can view activity logs.'})
            }
        
        # Get query parameters
        params = event.get('queryStringParameters') or {}
        action_filter = params.get('action')
        admin_email_filter = params.get('admin_email')
        target_email_filter = params.get('target_email')
        days = params.get('days', '30')
        limit = int(params.get('limit', '100'))
        offset = int(params.get('offset', '0'))
        
        # Build filter expression
        filter_expressions = []
        expr_attr_values = {}
        expr_attr_names = {}
        
        # Filter by action type
        if action_filter:
            filter_expressions.append('#action = :action')
            expr_attr_values[':action'] = action_filter
            expr_attr_names['#action'] = 'action'
        
        # Filter by admin email (contains)
        if admin_email_filter:
            filter_expressions.append('contains(admin_email, :admin_email)')
            expr_attr_values[':admin_email'] = admin_email_filter
        
        # Filter by target user email (contains)
        if target_email_filter:
            filter_expressions.append('contains(target_user_email, :target_email)')
            expr_attr_values[':target_email'] = target_email_filter
        
        # Filter by date range
        try:
            days_int = int(days)
            if days_int > 0:
                from_date = (datetime.utcnow() - timedelta(days=days_int)).isoformat() + 'Z'
                filter_expressions.append('created_at >= :from_date')
                expr_attr_values[':from_date'] = from_date
        except ValueError:
            pass
        
        # Prepare scan parameters
        scan_params = {}
        if filter_expressions:
            scan_params['FilterExpression'] = ' AND '.join(filter_expressions)
            scan_params['ExpressionAttributeValues'] = expr_attr_values
            if expr_attr_names:
                scan_params['ExpressionAttributeNames'] = expr_attr_names
        
        # Scan logs
        response = logs_table.scan(**scan_params)
        logs = response.get('Items', [])
        
        # Handle pagination for large datasets
        while 'LastEvaluatedKey' in response:
            scan_params['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = logs_table.scan(**scan_params)
            logs.extend(response.get('Items', []))
        
        # Sort by created_at (newest first)
        logs.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        # Get total count
        total_count = len(logs)
        
        # Apply pagination
        logs = logs[offset:offset + limit]
        
        # Format logs for response
        logs_data = []
        for log in logs:
            details = None
            if log.get('details'):
                try:
                    details = json.loads(log['details']) if isinstance(log['details'], str) else log['details']
                except:
                    details = log['details']
            
            logs_data.append({
                'id': log.get('log_id', ''),
                'admin_email': log.get('admin_email', ''),
                'admin_name': log.get('admin_name', ''),
                'action': log.get('action', ''),
                'action_display': ACTION_DISPLAY.get(log.get('action', ''), log.get('action', '')),
                'target_user_email': log.get('target_user_email', ''),
                'target_user_name': log.get('target_user_name', ''),
                'details': details,
                'ip_address': log.get('ip_address', ''),
                'created_at': log.get('created_at', '')
            })
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'count': total_count,
                'limit': limit,
                'offset': offset,
                'logs': logs_data
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to get activity logs: {str(e)}'})
        }
