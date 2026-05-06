"""
Lambda Function: quota-admin-actions
Get paginated admin action logs

DynamoDB Tables:
- QuotaAdminActions: Primary key = action_id, GSI = admin_id-timestamp-index
"""

import json
import boto3
from decimal import Decimal
import os

dynamodb = boto3.resource('dynamodb')
actions_table = dynamodb.Table(os.environ.get('ADMIN_ACTIONS_TABLE', 'QuotaAdminActions'))


def decimal_default(obj):
    """JSON serializer for Decimal objects."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError


def lambda_handler(event, context):
    """Get paginated admin action logs."""
    
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'GET,OPTIONS'
    }
    
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': ''}
    
    try:
        # Get query parameters
        query_params = event.get('queryStringParameters') or {}
        page = int(query_params.get('page', 1))
        page_size = int(query_params.get('page_size', 20))
        admin_id = query_params.get('admin_id')
        target_user_id = query_params.get('target_user_id')
        
        # Validate pagination
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 100:
            page_size = 20
        
        # Build query
        if admin_id:
            # Query by admin_id using GSI
            response = actions_table.query(
                IndexName='admin_id-timestamp-index',
                KeyConditionExpression='admin_id = :admin_id',
                ExpressionAttributeValues={':admin_id': admin_id},
                ScanIndexForward=False,  # Most recent first
                Limit=page_size * page  # Over-fetch to handle pagination
            )
            items = response.get('Items', [])
        elif target_user_id:
            # Scan by target_user_id (no index for this)
            response = actions_table.scan(
                FilterExpression='target_user_id = :target_user_id',
                ExpressionAttributeValues={':target_user_id': target_user_id}
            )
            items = response.get('Items', [])
            # Sort by timestamp descending
            items.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        else:
            # Scan all actions (no specific filter)
            response = actions_table.scan()
            items = response.get('Items', [])
            # Sort by timestamp descending
            items.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        # Apply pagination
        total = len(items)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_items = items[start_idx:end_idx]
        
        # Calculate total pages
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        
        # Format response
        result = {
            'logs': paginated_items,
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages
        }
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps(result, default=decimal_default)
        }
        
    except ValueError as e:
        return {
            'statusCode': 400,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Invalid parameter: {str(e)}'})
        }
    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': 'Internal server error'})
        }
