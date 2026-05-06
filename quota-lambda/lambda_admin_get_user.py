"""
Lambda Function: quota-admin-get-user
Get detailed quota info for a specific user (Admin only)

DynamoDB Tables:
- UserQuotas: Primary key = user_id
- UsageLogs:  Primary key = log_id

Lazy-reset note (2026-05-01 fix)
--------------------------------
Mirrors lambda_admin_list_users.py. Without this, the per-user admin
detail view would show stale `current_usage` for any user who hadn't
chatted yet this period. We now run the canonical reset helper before
formatting the response, with a ConditionExpression so concurrent
resets (chat / cron / parallel admin click) can't race each other.
"""

import json
import boto3
from datetime import datetime, timezone
import os
import uuid
import calendar
from decimal import Decimal
from botocore.exceptions import ClientError

dynamodb = boto3.resource('dynamodb')
quotas_table = dynamodb.Table(os.environ.get('USER_QUOTAS_TABLE', 'UserQuotas'))
logs_table = dynamodb.Table(os.environ.get('USAGE_LOGS_TABLE', 'UsageLogs'))


def parse_reset_date(reset_date_str):
    parsed = datetime.fromisoformat(str(reset_date_str).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def get_next_reset_date(current_reset_date_str=None):
    now = datetime.now(timezone.utc)
    reset_day = 1
    if current_reset_date_str:
        try:
            reset_day = parse_reset_date(current_reset_date_str).day
        except (ValueError, TypeError):
            pass
    if now.month == 12:
        next_year, next_month = now.year + 1, 1
    else:
        next_year, next_month = now.year, now.month + 1
    max_day = calendar.monthrange(next_year, next_month)[1]
    reset_day = min(reset_day, max_day)
    return datetime(next_year, next_month, reset_day, tzinfo=timezone.utc).isoformat()


def check_and_reset_quota(user_data):
    """Reset usage to 0 if reset_date has passed; idempotent under races."""
    now = datetime.now(timezone.utc)
    reset_date_str = user_data.get('reset_date', '')
    if not reset_date_str:
        return user_data
    try:
        reset_date = parse_reset_date(reset_date_str)
    except (ValueError, TypeError):
        return user_data
    if now < reset_date:
        return user_data

    prev_usage = int(user_data.get('current_usage', 0))
    prev_cost = float(user_data.get('current_cost_usd', 0))

    # See lambda_quota_check.py for the snapshot-after-update rationale —
    # writing the audit row only on conditional-success keeps auto_reset
    # rows exactly-once across all racing paths.
    new_reset = get_next_reset_date(reset_date_str)
    try:
        quotas_table.update_item(
            Key={'user_id': user_data['user_id']},
            UpdateExpression='SET current_usage = :zero, current_cost_usd = :zero_cost, reset_date = :reset, updated_at = :now',
            ConditionExpression='reset_date = :old_reset',
            ExpressionAttributeValues={
                ':zero': 0,
                ':zero_cost': Decimal('0.0'),
                ':reset': new_reset,
                ':old_reset': reset_date_str,
                ':now': now.isoformat()
            }
        )
        user_data['current_usage'] = 0
        user_data['current_cost_usd'] = Decimal('0.0')
        user_data['reset_date'] = new_reset

        if prev_usage > 0:
            try:
                logs_table.put_item(Item={
                    'log_id': str(uuid.uuid4()),
                    'user_id': user_data['user_id'],
                    'fullname': user_data.get('fullname', ''),
                    'service': 'system',
                    'operation': 'auto_reset',
                    'model': 'N/A',
                    'input_tokens': 0,
                    'output_tokens': 0,
                    'total_tokens': prev_usage,
                    'cost_usd': Decimal(str(round(prev_cost, 6))),
                    'request_id': None,
                    'session_id': None,
                    'metadata': json.dumps({
                        'reset_type': 'auto',
                        'triggered_by': 'admin_get_user',
                        'period_end': reset_date_str,
                        'period_usage': prev_usage,
                        'period_cost_usd': round(prev_cost, 6),
                        'monthly_limit': int(user_data.get('monthly_limit', 100000))
                    }),
                    'timestamp': now.isoformat()
                })
            except Exception as e:
                print(f"[admin-get-user] failed to log reset snapshot for {user_data.get('user_id')}: {e}")
    except ClientError as ce:
        if ce.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            try:
                refreshed = quotas_table.get_item(Key={'user_id': user_data['user_id']}).get('Item')
                if refreshed:
                    user_data = refreshed
            except Exception as fetch_err:
                print(f"[admin-get-user] post-conflict refetch failed for {user_data.get('user_id')}: {fetch_err}")
        else:
            print(f"[admin-get-user] reset write failed for {user_data.get('user_id')}: {ce}")
    return user_data


def lambda_handler(event, context):
    """Get detailed quota info for a specific user."""

    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'GET,OPTIONS'
    }

    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': ''}

    try:
        request_context = event.get('requestContext', {})
        authorizer = request_context.get('authorizer', {})
        admin_role = authorizer.get('role', '')

        if admin_role.lower() not in ['admin', 'staff']:
            return {
                'statusCode': 403,
                'headers': cors_headers,
                'body': json.dumps({'error': 'Admin access required'})
            }

        path_params = event.get('pathParameters', {}) or {}
        user_id = path_params.get('user_id')

        if not user_id:
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'user_id is required'})
            }

        query_params = event.get('queryStringParameters', {}) or {}
        include_inactive = query_params.get('include_inactive', 'false').lower() == 'true'

        response = quotas_table.get_item(Key={'user_id': user_id})
        item = response.get('Item')

        if not item:
            return {
                'statusCode': 404,
                'headers': cors_headers,
                'body': json.dumps({'error': f'User {user_id} not found'})
            }

        if not include_inactive and not item.get('is_active', True):
            return {
                'statusCode': 404,
                'headers': cors_headers,
                'body': json.dumps({'error': f'User {user_id} not found (deactivated)'})
            }

        # Lazy-reset before formatting so the admin sees the canonical
        # post-reset numbers, not whatever was last written by chat traffic.
        if item.get('is_active', True):
            item = check_and_reset_quota(item)

        user = {
            'user_id': item['user_id'],
            'fullname': item.get('fullname', ''),
            'tier': item.get('tier', 'free'),
            'monthly_limit': int(item.get('monthly_limit', 100000)),
            'current_usage': int(item.get('current_usage', 0)),
            'current_cost_usd': float(item.get('current_cost_usd', 0)),
            'reset_date': item.get('reset_date', ''),
            'created_at': item.get('created_at', ''),
            'updated_at': item.get('updated_at', ''),
            'is_active': item.get('is_active', True),
            'deactivated_at': item.get('deactivated_at')
        }

        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps(user)
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to get user: {str(e)}'})
        }
