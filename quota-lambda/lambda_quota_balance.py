"""
Lambda Function: quota-balance
Get current quota balance for a user

DynamoDB Tables:
- UserQuotas: Primary key = user_id
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

TIER_LIMITS = {
    'free': 100_000,
    'pro': 1_000_000,
    'enterprise': 10_000_000,
    'unlimited': 999_999_999
}


def get_next_reset_date(current_reset_date_str=None):
    """Calculate the next reset date, preserving admin-set day-of-month."""
    now = datetime.now(timezone.utc)
    
    # Determine the day-of-month to carry forward
    reset_day = 1  # default: 1st of month
    if current_reset_date_str:
        try:
            current_reset = parse_reset_date(current_reset_date_str)
            reset_day = current_reset.day
        except (ValueError, TypeError):
            pass
    
    # Calculate next month
    if now.month == 12:
        next_year, next_month = now.year + 1, 1
    else:
        next_year, next_month = now.year, now.month + 1
    
    # Clamp day to valid range for the target month (e.g. 31 -> 28 for Feb)
    max_day = calendar.monthrange(next_year, next_month)[1]
    reset_day = min(reset_day, max_day)
    
    return datetime(next_year, next_month, reset_day, tzinfo=timezone.utc).isoformat()


def parse_reset_date(reset_date_str):
    """Parse reset date strings and normalize naive values to UTC."""
    parsed = datetime.fromisoformat(str(reset_date_str).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def check_and_reset_quota(user_data):
    """Check if quota needs reset and return updated data."""
    now = datetime.now(timezone.utc)
    reset_date_str = user_data.get('reset_date', '')
    
    if reset_date_str:
        try:
            reset_date = parse_reset_date(reset_date_str)
            if now >= reset_date:
                prev_usage = int(user_data.get('current_usage', 0))
                prev_cost = float(user_data.get('current_cost_usd', 0))

                # See lambda_quota_check.py for the rationale on the
                # ConditionExpression and the snapshot-after-update
                # ordering — both are required to keep audit rows
                # exactly-once under racing chats / cron / admin views.
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
                                    'triggered_by': 'quota_balance',
                                    'period_end': reset_date_str,
                                    'period_usage': prev_usage,
                                    'period_cost_usd': round(prev_cost, 6),
                                    'monthly_limit': int(user_data.get('monthly_limit', 100000))
                                }),
                                'timestamp': now.isoformat()
                            })
                        except Exception as e:
                            print(f"[quota-balance] Failed to log reset snapshot: {str(e)}")
                except ClientError as ce:
                    if ce.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
                        try:
                            refreshed = quotas_table.get_item(
                                Key={'user_id': user_data['user_id']}
                            ).get('Item')
                            if refreshed:
                                user_data = refreshed
                        except Exception as fetch_err:
                            print(f"[quota-balance] post-conflict refetch failed for {user_data.get('user_id')}: {fetch_err}")
                    else:
                        print(f"[quota-balance] reset write failed for {user_data.get('user_id')}: {ce}")
        except (ValueError, TypeError):
            pass
    
    return user_data


def lambda_handler(event, context):
    """Get current quota balance for a user."""
    
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'GET,OPTIONS'
    }
    
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': ''}
    
    try:
        # Get user_id from path parameters
        path_params = event.get('pathParameters', {}) or {}
        user_id = path_params.get('user_id')
        
        if not user_id:
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'user_id is required'})
            }
        
        # Get user quota (include inactive for balance check)
        response = quotas_table.get_item(Key={'user_id': user_id})
        user_data = response.get('Item')
        
        if not user_data:
            return {
                'statusCode': 404,
                'headers': cors_headers,
                'body': json.dumps({'error': f'User {user_id} not found. User must be onboarded by an admin first.'})
            }
        
        # Check and reset quota if needed (only for active users)
        if user_data.get('is_active', True):
            user_data = check_and_reset_quota(user_data)
        
        monthly_limit = int(user_data.get('monthly_limit', TIER_LIMITS['free']))
        current_usage = int(user_data.get('current_usage', 0))
        remaining = monthly_limit - current_usage
        warning = current_usage >= (monthly_limit * 0.8)
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'allowed': remaining > 0 and user_data.get('is_active', True),
                'remaining_tokens': max(0, remaining),
                'monthly_limit': monthly_limit,
                'current_usage': current_usage,
                'percentage_used': round(current_usage / monthly_limit * 100, 1) if monthly_limit > 0 else 0,
                'warning': warning,
                'warning_message': 'Approaching monthly token limit (80% used)' if warning else None,
                'tier': user_data.get('tier', 'free'),
                'resets_at': user_data.get('reset_date', ''),
                'is_active': user_data.get('is_active', True)
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to get balance: {str(e)}'})
        }
