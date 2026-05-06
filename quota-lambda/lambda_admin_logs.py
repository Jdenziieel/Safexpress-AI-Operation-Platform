"""
Lambda Function: quota-admin-logs
Get paginated usage logs (Admin only)

DynamoDB Tables:
- UsageLogs: Primary key = log_id
"""

import json
import boto3
from datetime import datetime, timezone
import os
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource('dynamodb')
logs_table = dynamodb.Table(os.environ.get('USAGE_LOGS_TABLE', 'UsageLogs'))


def lambda_handler(event, context):
    """Get paginated usage logs."""
    
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
        page = int(query_params.get('page', 1))
        page_size = int(query_params.get('page_size', 20))
        user_id_filter = query_params.get('user_id')
        service_filter = query_params.get('service')
        
        # Limit page size
        page_size = min(max(page_size, 1), 100)
        
        # Build filter expression
        filter_expressions = []
        
        if user_id_filter:
            filter_expressions.append(Attr('user_id').eq(user_id_filter))
        
        if service_filter:
            filter_expressions.append(Attr('service').eq(service_filter))
        
        # Scan with filters
        scan_kwargs = {}
        if filter_expressions:
            combined_filter = filter_expressions[0]
            for expr in filter_expressions[1:]:
                combined_filter = combined_filter & expr
            scan_kwargs['FilterExpression'] = combined_filter
        
        # Get all matching logs (DynamoDB doesn't support offset pagination natively)
        all_logs = []
        response = logs_table.scan(**scan_kwargs)
        all_logs.extend(response.get('Items', []))
        
        # Handle pagination
        while 'LastEvaluatedKey' in response:
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = logs_table.scan(**scan_kwargs)
            all_logs.extend(response.get('Items', []))
        
        # Sort by timestamp descending
        all_logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        # Calculate pagination
        total = len(all_logs)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_logs = all_logs[start_idx:end_idx]
        
        # Format logs
        logs = []
        for log in page_logs:
            logs.append({
                'id': log.get('log_id', ''),
                'user_id': log.get('user_id', ''),
                'fullname': log.get('fullname', ''),
                'service': log.get('service', ''),
                'operation': log.get('operation', ''),
                'model': log.get('model', ''),
                'input_tokens': int(log.get('input_tokens', 0)),
                'output_tokens': int(log.get('output_tokens', 0)),
                'total_tokens': int(log.get('total_tokens', 0)),
                'cost_usd': float(log.get('cost_usd', 0)),
                'request_id': log.get('request_id'),
                'session_id': log.get('session_id'),
                'metadata': log.get('metadata'),
                'timestamp': log.get('timestamp', '')
            })
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'logs': logs,
                'total': total,
                'page': page,
                'page_size': page_size,
                'total_pages': (total + page_size - 1) // page_size if page_size > 0 else 0
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to get logs: {str(e)}'})
        }
