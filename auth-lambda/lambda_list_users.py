"""
Lambda Function: auth-list-users
List all users with optional filtering (Admin only)
Migrated from: authserver/api/views.py -> list_users()

DynamoDB Tables:
- Users: Primary key = gmail
"""

import json
import boto3
import os

dynamodb = boto3.resource('dynamodb')
users_table = dynamodb.Table(os.environ.get('USERS_TABLE', 'Users'))


def lambda_handler(event, context):
    """List all users with optional filters"""
    
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
                'body': json.dumps({'error': 'Permission denied. Only admins can view all users.'})
            }
        
        # Get query parameters
        params = event.get('queryStringParameters') or {}
        role_filter = params.get('role')
        is_active_filter = params.get('is_active')
        
        # Scan all users
        response = users_table.scan()
        users = response.get('Items', [])
        
        # Handle pagination if needed (for large datasets)
        while 'LastEvaluatedKey' in response:
            response = users_table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
            users.extend(response.get('Items', []))
        
        # Apply filters
        if role_filter:
            users = [u for u in users if u.get('role') == role_filter]
        
        if is_active_filter is not None:
            is_active_bool = is_active_filter.lower() == 'true'
            users = [u for u in users if u.get('is_active') == is_active_bool]
        
        # Sort by created_at (newest first)
        users.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        # Format users for response
        users_data = []
        for user in users:
            users_data.append({
                'user_id': user.get('user_id', ''),
                'fullname': user.get('fullname', ''),
                'gmail': user.get('gmail', ''),
                'role': user.get('role', 'user'),
                'is_active': bool(user.get('is_active', False)),
                'picture': user.get('google_picture', ''),
                'created_at': user.get('created_at', ''),
                'created_by': user.get('created_by', '')
            })
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'count': len(users_data),
                'users': users_data
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to list users: {str(e)}'})
        }
