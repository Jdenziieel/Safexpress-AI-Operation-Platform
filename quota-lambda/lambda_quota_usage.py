"""
Lambda Function: quota-usage
Report token usage after LLM operations (alias for quota-report)

This is a compatibility endpoint that accepts the simplified format from kb-lambda
and forwards it to the full quota report logic.

DEPRECATED
----------
Kept only for backwards compatibility with legacy kb-lambda clients that sent
the simplified {tokens_used, cost_usd} payload. As of the token-logging-schema
alignment, all kb-lambda and supervisor-agent clients now POST to
`/quota/report` (see lambda_quota_report.py) with the canonical payload:

    {
        "user_id", "service", "operation", "model",
        "input_tokens", "output_tokens", "cost_usd"
    }

This endpoint should NOT receive new traffic. Once monitoring confirms zero
hits for one full quota period it can be removed entirely.

DynamoDB Tables:
- UserQuotas: Primary key = user_id
- UsageLogs: Primary key = log_id
"""

import json
import boto3
from datetime import datetime, timezone
import uuid
import os
import calendar
from decimal import Decimal
from botocore.exceptions import ClientError

dynamodb = boto3.resource('dynamodb')
quotas_table = dynamodb.Table(os.environ.get('USER_QUOTAS_TABLE', 'UserQuotas'))
logs_table = dynamodb.Table(os.environ.get('USAGE_LOGS_TABLE', 'UsageLogs'))

# Default model pricing (USD per 1K tokens).
# Kept in sync with lambda_quota_report.py MODEL_PRICING and
# kb-lambda/shared/openai_utils.py PRICING. Only touched on restart;
# admin overrides (if you add them later) should live in DynamoDB.
# See supervisor-agent model-change guide §1 / TOKEN_LOGGING_REFERENCE §6.1
# for family cache discounts. Source of truth: that doc.
MODEL_PRICING = {
    # GPT-5.4 family — current flagship (2026-04). 90% cache discount.
    'gpt-5.4':              {'input': 0.0025,   'cached_input': 0.00025,   'output': 0.015},
    'gpt-5.4-mini':         {'input': 0.00075,  'cached_input': 0.000075,  'output': 0.0045},
    'gpt-5.4-nano':         {'input': 0.0002,   'cached_input': 0.00002,   'output': 0.00125},
    'gpt-5.4-pro':          {'input': 0.03,     'cached_input': 0.03,      'output': 0.18},
    # GPT-5.2 / 5.1 refreshes
    'gpt-5.2':              {'input': 0.00175,  'cached_input': 0.000175,  'output': 0.014},
    'gpt-5.2-pro':          {'input': 0.021,    'cached_input': 0.021,     'output': 0.168},
    'gpt-5.1':              {'input': 0.00125,  'cached_input': 0.000125,  'output': 0.01},
    # GPT-5 launch family (Aug 2025) — 90% cache discount
    'gpt-5':                {'input': 0.00125,  'cached_input': 0.000125,  'output': 0.01},
    'gpt-5-mini':           {'input': 0.00025,  'cached_input': 0.000025,  'output': 0.002},
    'gpt-5-nano':           {'input': 0.00005,  'cached_input': 0.000005,  'output': 0.0004},
    'gpt-5-pro':            {'input': 0.015,    'cached_input': 0.015,     'output': 0.12},
    # GPT-4.1 family (1M context; 75% cache discount)
    'gpt-4.1':              {'input': 0.002,    'cached_input': 0.0005,    'output': 0.008},
    'gpt-4.1-mini':         {'input': 0.0004,   'cached_input': 0.0001,    'output': 0.0016},
    'gpt-4.1-nano':         {'input': 0.0001,   'cached_input': 0.000025,  'output': 0.0004},
    # GPT-4o family (50% cache discount)
    'gpt-4o':               {'input': 0.0025,   'cached_input': 0.00125,   'output': 0.01},
    'gpt-4o-mini':          {'input': 0.00015,  'cached_input': 0.000075,  'output': 0.0006},
    # Reasoning models — reasoning tokens billed as output
    'o1':                   {'input': 0.015,    'cached_input': 0.0075,    'output': 0.06},
    'o1-pro':               {'input': 0.15,     'cached_input': 0.15,      'output': 0.6},
    'o1-mini':              {'input': 0.0011,   'cached_input': 0.00055,   'output': 0.0044},
    'o3':                   {'input': 0.002,    'cached_input': 0.0005,    'output': 0.008},
    'o3-mini':              {'input': 0.0011,   'cached_input': 0.00055,   'output': 0.0044},
    'o3-pro':               {'input': 0.02,     'cached_input': 0.02,      'output': 0.08},
    'o4-mini':              {'input': 0.0011,   'cached_input': 0.000275,  'output': 0.0044},
    # Legacy (no prompt caching)
    'gpt-4':                {'input': 0.03,     'cached_input': 0.03,      'output': 0.06},
    'gpt-4-turbo':          {'input': 0.01,     'cached_input': 0.01,      'output': 0.03},
    'gpt-3.5-turbo':        {'input': 0.0005,   'cached_input': 0.0005,    'output': 0.0015},
    # Embedding models (vector search; not LLMs — output rate is 0)
    'text-embedding-3-small': {'input': 0.00002, 'cached_input': 0.00002, 'output': 0},
    'text-embedding-3-large': {'input': 0.00013, 'cached_input': 0.00013, 'output': 0},
    # Fallback for unknown models — gpt-4.1 rates
    'default':              {'input': 0.002,    'cached_input': 0.0005,    'output': 0.008},
}


def estimate_cost(model, total_tokens):
    """
    Legacy path: estimate cost from total_tokens only.

    This endpoint (/quota/usage) is the deprecated compat shim — it only ever
    received `{tokens_used}` without split, so we can't apply the cached-token
    discount here. Assumes roughly 40/60 input/output for chat, no caching.
    New callers should POST to /quota/report instead with
    {input_tokens, output_tokens, cached_tokens}.
    """
    rates = MODEL_PRICING.get(model) or MODEL_PRICING['default']
    input_tokens = int(total_tokens * 0.4)
    output_tokens = int(total_tokens * 0.6)
    return (input_tokens / 1000 * rates['input']) + (output_tokens / 1000 * rates['output'])


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
                # ConditionExpression and snapshot-after-update ordering.
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
                                    'triggered_by': 'quota_usage',
                                    'period_end': reset_date_str,
                                    'period_usage': prev_usage,
                                    'period_cost_usd': round(prev_cost, 6),
                                    'monthly_limit': int(user_data.get('monthly_limit', 100000))
                                }),
                                'timestamp': now.isoformat()
                            })
                        except Exception as e:
                            print(f"[quota-usage] Failed to log reset snapshot: {str(e)}")
                except ClientError as ce:
                    if ce.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
                        try:
                            refreshed = quotas_table.get_item(
                                Key={'user_id': user_data['user_id']}
                            ).get('Item')
                            if refreshed:
                                user_data = refreshed
                        except Exception as fetch_err:
                            print(f"[quota-usage] post-conflict refetch failed for {user_data.get('user_id')}: {fetch_err}")
                    else:
                        print(f"[quota-usage] reset write failed for {user_data.get('user_id')}: {ce}")
        except (ValueError, TypeError):
            pass
    return user_data


def lambda_handler(event, context):
    """
    Report token usage after an LLM operation.
    
    Accepts simplified format from kb-lambda:
    {
        "user_id": "xxx",
        "tokens_used": 1234,
        "service": "knowledge-base",
        "operation": "chat",
        "cost_usd": 0.01  (optional)
    }
    
    Also accepts full format:
    {
        "user_id": "xxx",
        "service": "knowledge-base",
        "operation": "chat",
        "model": "gpt-4o",
        "input_tokens": 500,
        "output_tokens": 700
    }
    """
    
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
        service = body.get('service', 'unknown')
        operation = body.get('operation', 'unknown')
        
        # Handle different input formats
        # Simplified format (from kb-lambda)
        tokens_used = body.get('tokens_used', 0)
        
        # Full format (from quota-report)
        input_tokens = body.get('input_tokens', 0)
        output_tokens = body.get('output_tokens', 0)
        model = body.get('model', 'gpt-4o')
        
        # Calculate total tokens
        if tokens_used > 0:
            total_tokens = tokens_used
            # Estimate input/output split for logging
            input_tokens = int(tokens_used * 0.4)
            output_tokens = int(tokens_used * 0.6)
        else:
            total_tokens = input_tokens + output_tokens
        
        cost_usd = body.get('cost_usd')
        request_id = body.get('request_id')
        session_id = body.get('session_id')
        metadata = body.get('metadata')
        
        # Validate required fields
        if not user_id:
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'user_id is required'})
            }
        
        if total_tokens <= 0:
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'tokens_used or input_tokens/output_tokens required'})
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
        
        # Auto-reset if quota period has expired
        user_data = check_and_reset_quota(user_data)
        
        # Calculate cost if not provided
        if cost_usd is None:
            cost_usd = estimate_cost(model, total_tokens)
        
        now = datetime.now(timezone.utc).isoformat()
        
        # Log the usage
        log_item = {
            'log_id': str(uuid.uuid4()),
            'user_id': user_id,
            'fullname': user_data.get('fullname', ''),
            'service': service,
            'operation': operation,
            'model': model,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': total_tokens,
            'cost_usd': Decimal(str(round(cost_usd, 6))),
            'request_id': request_id,
            'session_id': session_id,
            'metadata': json.dumps(metadata) if metadata else None,
            'timestamp': now
        }
        
        logs_table.put_item(Item=log_item)
        
        # Atomic ADD instead of read-modify-write SET — see
        # lambda_quota_report.py for the rationale (parallel chats
        # racing on the same user used to lose tokens).
        monthly_limit = int(user_data.get('monthly_limit', 100000))
        update_response = quotas_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression='ADD current_usage :delta_tokens, current_cost_usd :delta_cost SET updated_at = :now',
            ExpressionAttributeValues={
                ':delta_tokens': int(total_tokens),
                ':delta_cost': Decimal(str(round(cost_usd, 6))),
                ':now': now
            },
            ReturnValues='UPDATED_NEW'
        )
        updated_attrs = update_response.get('Attributes', {}) or {}
        new_usage = int(updated_attrs.get('current_usage', int(user_data.get('current_usage', 0)) + total_tokens))
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'success': True,
                'new_usage': new_usage,
                'remaining': max(0, monthly_limit - new_usage)
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to report usage: {str(e)}'})
        }
