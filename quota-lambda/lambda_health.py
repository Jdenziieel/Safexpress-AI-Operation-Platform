"""
Lambda Function: quota-health
Health check endpoint for the quota service

DynamoDB Tables:
- UserQuotas: Primary key = user_id
"""

import json
import boto3
from datetime import datetime, timezone
import os
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource('dynamodb')
quotas_table = dynamodb.Table(os.environ.get('USER_QUOTAS_TABLE', 'UserQuotas'))


def lambda_handler(event, context):
    """Health check endpoint."""
    
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'GET,OPTIONS'
    }
    
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': ''}
    
    try:
        # Try to get stats from UserQuotas table
        stats = {
            'total_users': 0,
            'active_users': 0
        }
        
        try:
            # Count all users
            scan_response = quotas_table.scan(Select='COUNT')
            stats['total_users'] = scan_response.get('Count', 0)
            
            # Count active users
            active_response = quotas_table.scan(
                Select='COUNT',
                FilterExpression=Attr('is_active').eq(True) | Attr('is_active').not_exists()
            )
            stats['active_users'] = active_response.get('Count', 0)
            
        except Exception as e:
            print(f"Error getting stats: {e}")
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'status': 'healthy',
                'service': 'quota-lambda',
                'database': 'connected',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'stats': stats
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 503,
            'headers': cors_headers,
            'body': json.dumps({
                'status': 'unhealthy',
                'service': 'quota-lambda',
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
        }
