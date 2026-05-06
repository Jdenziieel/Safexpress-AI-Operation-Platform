"""
Lambda Function: quota-check
Pre-flight quota check before LLM operations

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

# Tier limits (monthly tokens)
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

                # Preserve admin-set day-of-month in next reset date.
                # ConditionExpression makes the reset idempotent under
                # concurrent traffic: if quota_balance / quota_report /
                # admin-list / scheduled-cron raced us and already
                # advanced reset_date, our write fails with
                # ConditionalCheckFailedException and we re-fetch the
                # canonical post-reset row instead of clobbering the
                # winner's accumulated tokens with another :zero.
                #
                # The snapshot row is intentionally written AFTER the
                # successful conditional update — if we wrote it first,
                # losing the conditional race would still leave a stale
                # auto_reset row in UsageLogs and admin / user-history
                # dashboards would double-count the period's totals.
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
                    user_data['current_cost_usd'] = 0.0
                    user_data['reset_date'] = new_reset

                    # Conditional update succeeded — WE are the canonical
                    # writer for this period boundary. Write the audit row.
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
                                    'triggered_by': 'quota_check',
                                    'period_end': reset_date_str,
                                    'period_usage': prev_usage,
                                    'period_cost_usd': round(prev_cost, 6),
                                    'monthly_limit': int(user_data.get('monthly_limit', 100000))
                                }),
                                'timestamp': now.isoformat()
                            })
                        except Exception as e:
                            print(f"[quota-check] Failed to log reset snapshot: {str(e)}")
                except ClientError as ce:
                    if ce.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
                        # Another path won the race; do NOT write a snapshot.
                        try:
                            refreshed = quotas_table.get_item(
                                Key={'user_id': user_data['user_id']}
                            ).get('Item')
                            if refreshed:
                                user_data = refreshed
                        except Exception as fetch_err:
                            print(f"[quota-check] post-conflict refetch failed for {user_data.get('user_id')}: {fetch_err}")
                    else:
                        print(f"[quota-check] reset write failed for {user_data.get('user_id')}: {ce}")
        except (ValueError, TypeError):
            pass
    
    return user_data


def lambda_handler(event, context):
    """Pre-flight quota check before an LLM operation."""
    
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'POST,OPTIONS'
    }
    
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': ''}
    
    try:
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        user_id = body.get('user_id')
        estimated_tokens = body.get('estimated_tokens', 0)
        
        if not user_id:
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'user_id is required'})
            }
        
        # Get user quota
        response = quotas_table.get_item(Key={'user_id': user_id})
        user_data = response.get('Item')
        
        if not user_data:
            return {
                'statusCode': 404,
                'headers': cors_headers,
                'body': json.dumps({'error': f'User {user_id} not found. User must be onboarded by an admin first.'})
            }
        
        # Check if user is active
        if not user_data.get('is_active', True):
            return {
                'statusCode': 403,
                'headers': cors_headers,
                'body': json.dumps({
                    'error': 'User account is deactivated',
                    'is_deactivated': True,
                    'message': 'Your account has been deactivated. Please contact an administrator.'
                })
            }
        
        # Check and reset quota if needed
        user_data = check_and_reset_quota(user_data)
        
        monthly_limit = int(user_data.get('monthly_limit', TIER_LIMITS['free']))
        current_usage = int(user_data.get('current_usage', 0))
        remaining = monthly_limit - current_usage
        
        # Check if operation would exceed quota
        allowed = remaining >= estimated_tokens
        
        # Warning threshold (80% used)
        warning = current_usage >= (monthly_limit * 0.8)
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'allowed': allowed,
                'remaining_tokens': max(0, remaining),
                'monthly_limit': monthly_limit,
                'current_usage': current_usage,
                'percentage_used': round(current_usage / monthly_limit * 100, 1) if monthly_limit > 0 else 0,
                'warning': warning,
                'warning_message': 'Approaching monthly token limit (80% used)' if warning else None,
                'tier': user_data.get('tier', 'free'),
                'resets_at': user_data.get('reset_date', '')
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to check quota: {str(e)}'})
        }
