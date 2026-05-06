"""
Lambda Function: auth-user-detail
Returns current authenticated user's details
Migrated from: authserver/api/views.py -> UserDetailView

DynamoDB Tables:
- Users: Primary key = gmail, GSI on user_id
"""

import json
import boto3
import os

dynamodb = boto3.resource('dynamodb')
users_table = dynamodb.Table(os.environ.get('USERS_TABLE', 'Users'))


def lambda_handler(event, context):
    """Get current user details from JWT claims"""
    
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'GET,OPTIONS'
    }
    
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': ''}
    
    try:
        # Get user info from authorizer context (set by jwt-api-authorizer)
        request_context = event.get('requestContext', {})
        authorizer = request_context.get('authorizer', {})
        
        user_id = authorizer.get('user_id')
        gmail = authorizer.get('gmail') or authorizer.get('email')
        
        if not user_id and not gmail:
            return {
                'statusCode': 401,
                'headers': cors_headers,
                'body': json.dumps({'error': 'Not authenticated'})
            }
        
        # Get full user details from DynamoDB
        user = None
        if gmail:
            response = users_table.get_item(Key={'gmail': gmail})
            user = response.get('Item')
        
        if not user and user_id:
            # Fallback to user_id lookup via GSI
            response = users_table.query(
                IndexName='user_id-index',
                KeyConditionExpression='user_id = :uid',
                ExpressionAttributeValues={':uid': user_id}
            )
            items = response.get('Items', [])
            if items:
                user = items[0]
        
        if not user:
            return {
                'statusCode': 404,
                'headers': cors_headers,
                'body': json.dumps({'error': 'User not found'})
            }
        
        # Return user data (matches Django UserSerializer format)
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'user_id': user['user_id'],
                'fullname': user.get('fullname', ''),
                'gmail': user['gmail'],
                'role': user.get('role', 'user'),
                'is_active': user.get('is_active', False),
                'picture': user.get('google_picture', ''),
                'created_at': user.get('created_at', ''),
                'created_by': user.get('created_by', ''),
                'terms_accepted': bool(user.get('terms_accepted', False)),
                'terms_version_accepted': user.get('terms_version_accepted'),
                'terms_accepted_at': user.get('terms_accepted_at'),
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to get user details: {str(e)}'})
        }
