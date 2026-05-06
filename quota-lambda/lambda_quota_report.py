"""
Lambda Function: quota-report
Report token usage after LLM operations

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

# Model pricing (USD per 1K tokens).
# Columns: input / cached_input / output.
# Family cache-discount conventions (see supervisor-agent model-change guide §1):
#   gpt-5.4*  → 90% off cached input (current flagship, 2026-04)
#   gpt-5.2 / gpt-5.1 / gpt-5*  → 90% off cached input
#   gpt-4.1*  → 75% off cached input
#   gpt-4o*   → 50% off cached input
#   o1 / o3 / o4-mini  → 50% off cached input (reasoning models; reasoning
#                        tokens are billed as output — use sparingly)
#   *-pro variants  → no cache discount (cached_input == input)
#   gpt-4 / gpt-4-turbo / gpt-3.5-turbo → no cache discount (legacy)
# The `default` row tracks gpt-4.1 so unknown-model fallback still bills plausibly.
# IMPORTANT: keep in sync with kb-lambda/shared/openai_utils.py PRICING and
# quota-lambda/lambda_quota_usage.py MODEL_PRICING. Source of truth is the
# supervisor-agent TOKEN_LOGGING_REFERENCE §6.1.
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
    # Fallback for unknown models — gpt-4.1 rates (matches OPENAI_MODEL default)
    'default':              {'input': 0.002,    'cached_input': 0.0005,    'output': 0.008},
}


def _get_rates(model):
    """Resolve pricing row; if cached_input missing (legacy rows), fall back to input*0.5."""
    rates = MODEL_PRICING.get(model) or MODEL_PRICING['default']
    if 'cached_input' not in rates:
        rates = {**rates, 'cached_input': rates['input'] * 0.5}
    return rates


def estimate_cost(model, input_tokens, output_tokens, cached_tokens=0):
    """
    Estimate cost using the supervisor-agent guide §4 formula:

        non_cached_input = max(input_tokens - cached_tokens, 0)
        cost = (non_cached_input * input_rate
              + cached_tokens     * cached_rate
              + output_tokens     * output_rate) / 1000

    Invariant: `input_tokens` INCLUDES cached_tokens (cached is a subset
    that gets the discount). Do not subtract cached from input outside here.
    """
    rates = _get_rates(model)
    cached = max(int(cached_tokens or 0), 0)
    non_cached_input = max(int(input_tokens or 0) - cached, 0)
    return (
        (non_cached_input * rates['input'])
        + (cached * rates['cached_input'])
        + (int(output_tokens or 0) * rates['output'])
    ) / 1000.0


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
                # ordering. CRITICAL here in particular because this
                # Lambda is the canonical chat-side reporter — two
                # parallel chats crossing the boundary used to both
                # write a snapshot row before either had committed
                # the reset, double-counting the period in audit
                # dashboards (and inflating the user-history aggregates
                # the Profile page renders).
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
                                    'triggered_by': 'quota_report',
                                    'period_end': reset_date_str,
                                    'period_usage': prev_usage,
                                    'period_cost_usd': round(prev_cost, 6),
                                    'monthly_limit': int(user_data.get('monthly_limit', 100000))
                                }),
                                'timestamp': now.isoformat()
                            })
                        except Exception as e:
                            print(f"[quota-report] Failed to log reset snapshot: {str(e)}")
                except ClientError as ce:
                    if ce.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
                        try:
                            refreshed = quotas_table.get_item(
                                Key={'user_id': user_data['user_id']}
                            ).get('Item')
                            if refreshed:
                                user_data = refreshed
                        except Exception as fetch_err:
                            print(f"[quota-report] post-conflict refetch failed for {user_data.get('user_id')}: {fetch_err}")
                    else:
                        print(f"[quota-report] reset write failed for {user_data.get('user_id')}: {ce}")
        except (ValueError, TypeError):
            pass
    return user_data


def lambda_handler(event, context):
    """Report token usage after an LLM operation."""
    
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
        service = body.get('service')
        operation = body.get('operation')
        model = body.get('model')
        input_tokens = int(body.get('input_tokens', 0) or 0)
        output_tokens = int(body.get('output_tokens', 0) or 0)
        # cached_tokens is a subset of input_tokens (OpenAI bills the same
        # prompt_tokens number; cached gets the discounted rate).
        # See supervisor-agent model-change guide §1 / §4.
        # Tolerate the supervisor-agent client convention of shipping
        # cached_tokens INSIDE the metadata blob: pull from top-level first,
        # fall back to metadata.cached_tokens. (TOKEN_LOGGING_REFERENCE §7.2)
        _raw_metadata = body.get('metadata') or {}
        cached_tokens = int(
            body.get('cached_tokens',
                     _raw_metadata.get('cached_tokens', 0) if isinstance(_raw_metadata, dict) else 0)
            or 0
        )
        cost_usd = body.get('cost_usd')
        request_id = body.get('request_id')
        session_id = body.get('session_id')
        metadata = _raw_metadata or None
        # Schema fields aligned with supervisor-agent `llm_calls`:
        tier = body.get('tier')                        # "0.5" / "1" / "chat" / "classifier" / etc.
        duration_ms = body.get('duration_ms')          # wall-clock ms for the LLM call
        success = body.get('success')                  # bool — must log failures too
        error = body.get('error')                      # error message string when success=False
        prompt_summary = body.get('prompt_summary')    # first ~200 chars of the user prompt
        # `record_only` (default False) writes the row to UsageLogs but DOES
        # NOT touch UserQuotas.current_usage / current_cost_usd. Used by
        # PDF-parse and any other "audit trail without billing" path so doc
        # processing doesn't drain the uploader's chat balance. The row is
        # tagged with record_only=True so admin dashboards can filter it
        # in/out cleanly. Cost dashboards SHOULD include record-only rows
        # (they reflect real OpenAI spend); per-user quota gauges should
        # EXCLUDE them (they didn't deduct).
        record_only = bool(body.get('record_only', False))
        
        # Validate required fields
        if not all([user_id, service, operation, model]):
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'user_id, service, operation, and model are required'})
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
        
        # Calculate cost if not provided by caller.
        # Applies the cached-token discount when cached_tokens > 0.
        if cost_usd is None:
            cost_usd = estimate_cost(model, input_tokens, output_tokens, cached_tokens=cached_tokens)
        
        total_tokens = input_tokens + output_tokens
        now = datetime.now(timezone.utc).isoformat()
        
        # Log the usage (schema additions are all optional / nullable — existing
        # analytics queries that only read the legacy fields keep working).
        # `record_only` is persisted on the row so admin dashboards can split
        # billable rows from audit-only rows without re-deriving the flag.
        log_item = {
            'log_id': str(uuid.uuid4()),
            'user_id': user_id,
            'fullname': user_data.get('fullname', ''),
            'service': service,
            'operation': operation,
            'model': model,
            'tier': tier,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': total_tokens,
            'cached_tokens': cached_tokens,
            'cost_usd': Decimal(str(round(cost_usd, 6))),
            'duration_ms': Decimal(str(duration_ms)) if duration_ms is not None else None,
            'success': bool(success) if success is not None else True,
            'error': error,
            'prompt_summary': (prompt_summary or '')[:200] if prompt_summary else None,
            'request_id': request_id,
            'session_id': session_id,
            'metadata': json.dumps(metadata) if metadata else None,
            'record_only': record_only,
            'timestamp': now
        }

        logs_table.put_item(Item=log_item)

        # Update user's cumulative usage — SKIPPED for record_only rows so
        # PDF parsing (and any other audit-only path) doesn't drain the
        # uploader's chat balance. The UsageLogs row above still carries
        # the full token / cost breakdown for cost-attribution dashboards.
        #
        # We use DynamoDB's atomic ADD operator instead of a read-modify-
        # write SET. Two parallel chats reporting at the same time used
        # to clobber each other's totals (each computed
        #   new_usage = snapshot.current_usage + my_tokens
        # from a stale snapshot, then SET — the slower write would lose
        # the faster write's tokens). ADD :delta is server-side
        # incremental and cannot lose updates.
        current_usage_snapshot = int(user_data.get('current_usage', 0))
        current_cost_snapshot = float(user_data.get('current_cost_usd', 0))
        monthly_limit = int(user_data.get('monthly_limit', 100000))

        if record_only:
            new_usage = current_usage_snapshot
            new_cost = current_cost_snapshot
        else:
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
            new_usage = int(updated_attrs.get('current_usage', current_usage_snapshot + total_tokens))
            new_cost = float(updated_attrs.get('current_cost_usd', current_cost_snapshot + cost_usd))

        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'success': True,
                'record_only': record_only,
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
