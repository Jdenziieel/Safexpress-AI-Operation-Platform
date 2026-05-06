"""
Lambda Function: quota-admin-usage-breakdown
Get detailed usage breakdown for a user by service (Admin only)

DynamoDB Tables:
- UsageLogs: Primary key = log_id
"""

import json
import boto3
from datetime import datetime, timezone, timedelta
import os
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource('dynamodb')
logs_table = dynamodb.Table(os.environ.get('USAGE_LOGS_TABLE', 'UsageLogs'))


def lambda_handler(event, context):
    """Get detailed usage breakdown for a user by service."""
    
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
        
        # Get user_id from path parameters
        path_params = event.get('pathParameters', {}) or {}
        user_id = path_params.get('user_id')
        
        if not user_id:
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'user_id is required'})
            }
        
        # Get query parameters
        query_params = event.get('queryStringParameters', {}) or {}
        hours = int(query_params.get('hours', 24))
        hours = min(max(hours, 1), 720)  # Limit to 1-720 hours (30 days)
        
        start_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        # Scan usage logs for the user in the time period
        scan_kwargs = {
            'FilterExpression': Attr('user_id').eq(user_id) & Attr('timestamp').gte(start_time)
        }
        
        all_logs = []
        response = logs_table.scan(**scan_kwargs)
        all_logs.extend(response.get('Items', []))
        
        # Handle pagination
        while 'LastEvaluatedKey' in response:
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = logs_table.scan(**scan_kwargs)
            all_logs.extend(response.get('Items', []))
        
        # Group by service
        by_service = {}
        
        for log in all_logs:
            service = log.get('service', 'unknown')
            tokens = int(log.get('total_tokens', 0))
            cost = float(log.get('cost_usd', 0))
            
            if service not in by_service:
                by_service[service] = {
                    'service': service,
                    'total_tokens': 0,
                    'total_cost_usd': 0.0,
                    'call_count': 0,
                    'models_used': set(),
                    'operations': set()
                }
            
            by_service[service]['total_tokens'] += tokens
            by_service[service]['total_cost_usd'] += cost
            by_service[service]['call_count'] += 1
            
            model = log.get('model', '')
            operation = log.get('operation', '')
            if model:
                by_service[service]['models_used'].add(model)
            if operation:
                by_service[service]['operations'].add(operation)
        
        # Convert sets to lists and format response
        usage_breakdown = []
        for service, data in by_service.items():
            usage_breakdown.append({
                'service': data['service'],
                'total_tokens': data['total_tokens'],
                'total_cost_usd': round(data['total_cost_usd'], 6),
                'call_count': data['call_count'],
                'models_used': list(data['models_used']),
                'operations': list(data['operations'])
            })
        
        # Sort by total tokens descending
        usage_breakdown.sort(key=lambda x: x['total_tokens'], reverse=True)
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps(usage_breakdown)
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to get usage breakdown: {str(e)}'})
        }
