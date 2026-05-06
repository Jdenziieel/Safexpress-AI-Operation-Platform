"""
Lambda Function: auth-accept-terms
Marks the currently authenticated user as having accepted the Terms & Conditions.

DynamoDB Tables:
- Users: Primary key = gmail
- AdminActivityLogs: Primary key = log_id (optional, for audit trail)
"""

import json
import boto3
import os
import uuid
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
users_table = dynamodb.Table(os.environ.get('USERS_TABLE', 'Users'))
logs_table = dynamodb.Table(os.environ.get('LOGS_TABLE', 'AdminActivityLogs'))

TERMS_VERSION = os.environ.get('TERMS_VERSION', '1.0')


def log_acceptance(gmail, fullname, version, ip_address):
    """Write an audit trail entry for T&C acceptance (best effort)."""
    try:
        now = datetime.utcnow().isoformat() + 'Z'
        logs_table.put_item(Item={
            'log_id': str(uuid.uuid4()),
            'admin_email': gmail,
            'admin_name': fullname,
            'action': 'accept_terms',
            'target_user_email': gmail,
            'target_user_name': fullname,
            'details': json.dumps({'terms_version': version}),
            'created_at': now,
            'ip_address': ip_address,
        })
    except Exception as e:
        print(f"Failed to log T&C acceptance: {e}")


def lambda_handler(event, context):
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'POST,OPTIONS',
    }

    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': ''}

    try:
        request_context = event.get('requestContext', {})
        authorizer = request_context.get('authorizer', {})
        gmail = (authorizer.get('gmail') or authorizer.get('email') or '').lower()
        fullname = authorizer.get('fullname', '')
        ip_address = request_context.get('identity', {}).get('sourceIp', '')

        if not gmail:
            return {
                'statusCode': 401,
                'headers': cors_headers,
                'body': json.dumps({'error': 'Not authenticated'}),
            }

        # Optional: allow the frontend to pin the version it accepted
        try:
            body = json.loads(event.get('body') or '{}')
        except Exception:
            body = {}
        version = body.get('version') or TERMS_VERSION

        now = datetime.utcnow().isoformat() + 'Z'

        users_table.update_item(
            Key={'gmail': gmail},
            UpdateExpression=(
                'SET terms_accepted = :t, '
                'terms_accepted_at = :n, '
                'terms_version_accepted = :v, '
                'updated_at = :n'
            ),
            ExpressionAttributeValues={
                ':t': True,
                ':n': now,
                ':v': version,
            },
        )

        log_acceptance(gmail, fullname, version, ip_address)

        print(f"User {gmail} accepted T&C v{version}")

        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'message': 'Terms accepted',
                'terms_accepted': True,
                'terms_version_accepted': version,
                'terms_accepted_at': now,
            }),
        }

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to accept terms: {str(e)}'}),
        }
