"""
Lambda Function: quota-admin-list-users
List all users with their quota status (Admin only)

DynamoDB Tables:
- UserQuotas: Primary key = user_id
- UsageLogs:  Primary key = log_id  (auto-reset snapshots written here)

Lazy-reset note (2026-05-01 fix)
--------------------------------
Before this fix, this endpoint dumped raw DynamoDB rows. If a user's
reset_date had passed but they hadn't hit any chat endpoint yet (which
is what triggers the lazy reset in lambda_quota_check / quota_balance /
quota_report), the admin would see stale `current_usage` and the old
`reset_date` until the user themselves came online. We now run the same
check_and_reset_quota helper per row, so the Token Management table is
always consistent with the canonical quota state — even for users who
never chatted this period. This is paired with a daily EventBridge
scheduled-reset Lambda; the lazy path here just keeps the admin view
real-time between cron runs.
"""

import json
import boto3
from datetime import datetime, timezone
import os
import uuid
import calendar
from decimal import Decimal
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

dynamodb = boto3.resource('dynamodb')
quotas_table = dynamodb.Table(os.environ.get('USER_QUOTAS_TABLE', 'UserQuotas'))
logs_table = dynamodb.Table(os.environ.get('USAGE_LOGS_TABLE', 'UsageLogs'))


def parse_reset_date(reset_date_str):
    """Parse reset_date strings written by any of the quota lambdas.

    Tolerates both '...+00:00' (Python isoformat) and '...Z' suffixes,
    and naive timestamps (treated as UTC).
    """
    parsed = datetime.fromisoformat(str(reset_date_str).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def get_next_reset_date(current_reset_date_str=None):
    """Calculate the next reset date, preserving admin-set day-of-month.

    Mirrors the helper in lambda_quota_check.py — same contract so the
    canonical state is identical regardless of which path triggered the
    reset (chat / balance / admin-view / scheduled cron).
    """
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
    """Reset usage to 0 if reset_date has passed; idempotent under races.

    Uses ConditionExpression='reset_date = :old_reset' so two concurrent
    callers (e.g. admin-list-users + a chat report) racing the same
    boundary can't double-write — the loser sees ConditionalCheckFailed,
    we re-fetch the row, and it will already reflect the winner's reset.
    """
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

    # Snapshot is written AFTER the conditional update succeeds so the
    # admin lazy-reset path doesn't add a duplicate auto_reset row when
    # a chat / cron / parallel admin click already crossed the boundary.
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
                        'triggered_by': 'admin_list_users',
                        'period_end': reset_date_str,
                        'period_usage': prev_usage,
                        'period_cost_usd': round(prev_cost, 6),
                        'monthly_limit': int(user_data.get('monthly_limit', 100000))
                    }),
                    'timestamp': now.isoformat()
                })
            except Exception as e:
                print(f"[admin-list-users] failed to log reset snapshot for {user_data.get('user_id')}: {e}")
    except ClientError as ce:
        if ce.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            # Another path (chat / scheduled cron / parallel admin view)
            # already advanced reset_date — re-fetch so we return the
            # canonical post-reset state. Do NOT write a snapshot row.
            try:
                refreshed = quotas_table.get_item(Key={'user_id': user_data['user_id']}).get('Item')
                if refreshed:
                    user_data = refreshed
            except Exception as fetch_err:
                print(f"[admin-list-users] post-conflict refetch failed for {user_data.get('user_id')}: {fetch_err}")
        else:
            print(f"[admin-list-users] reset write failed for {user_data.get('user_id')}: {ce}")
    return user_data


def lambda_handler(event, context):
    """List all users with their quota status."""

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

        query_params = event.get('queryStringParameters', {}) or {}
        # `limit` is now applied client-side after sort, NOT as a per-scan
        # cap. The previous code passed Limit=50 to scan(), which is a
        # SCAN-level cap (rows examined, not rows matching the filter).
        # With FilterExpression you can get back fewer than 50 items —
        # or zero — even when many more match. We now paginate fully and
        # slice at the end so the admin always sees a correct, complete
        # tenant list.
        try:
            limit = int(query_params.get('limit', 200))
        except (TypeError, ValueError):
            limit = 200
        # Hard cap: 1000 rows in the response so a runaway tenant doesn't
        # blow the Lambda payload limit (6MB). max_pages bounds the scan
        # itself so we never spin past ~10MB of DDB data even at extreme
        # filter ratios. Both can grow when the tenant base does.
        limit = max(1, min(limit, 1000))
        max_pages = 25
        tier_filter = query_params.get('tier')
        include_inactive = query_params.get('include_inactive', 'false').lower() == 'true'

        scan_kwargs = {}
        filter_expressions = []

        if not include_inactive:
            filter_expressions.append(Attr('is_active').eq(True) | Attr('is_active').not_exists())

        if tier_filter:
            filter_expressions.append(Attr('tier').eq(tier_filter))

        if filter_expressions:
            combined_filter = filter_expressions[0]
            for expr in filter_expressions[1:]:
                combined_filter = combined_filter & expr
            scan_kwargs['FilterExpression'] = combined_filter

        # Paginate the scan fully. DDB returns at most 1MB per page, then
        # hands back a LastEvaluatedKey to resume from. Without this loop
        # any tenant base that doesn't fit in one page silently truncates
        # — admins would see only a subset of users in Token Management.
        items = []
        pages = 0
        response = quotas_table.scan(**scan_kwargs)
        items.extend(response.get('Items', []))
        pages += 1
        while 'LastEvaluatedKey' in response and pages < max_pages:
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = quotas_table.scan(**scan_kwargs)
            items.extend(response.get('Items', []))
            pages += 1
        if 'LastEvaluatedKey' in response:
            print(f"[admin-list-users] scan capped at {max_pages} pages "
                  f"({len(items)} items so far) — bump max_pages if the "
                  f"tenant base grew past this size")

        # Lazy-reset each row in-flight. Reset is rare (only fires once per
        # user per period) so the extra work is negligible in steady state;
        # at the month boundary it converges admin display with the
        # canonical UserQuotas state.
        users = []
        reset_count = 0
        for item in items:
            before_reset = item.get('reset_date', '')
            if item.get('is_active', True):
                item = check_and_reset_quota(item)
                if item.get('reset_date', '') != before_reset:
                    reset_count += 1
            users.append({
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
            })

        if reset_count:
            print(f"[admin-list-users] auto-reset {reset_count} user(s) during list")

        users.sort(key=lambda x: x['current_usage'], reverse=True)

        # Slice client-side AFTER sort so the admin sees the top-N by
        # usage, not a random first-page-of-scan subset. `total` reports
        # the full count so the UI can show "showing X of Y".
        full_total = len(users)
        if len(users) > limit:
            users = users[:limit]

        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'users': users,
                'total': full_total,
                'returned': len(users),
                'limit': limit,
                'auto_reset_count': reset_count
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
