"""
Lambda Function: quota-scheduled-reset
Cron-driven monthly quota reset for ALL users (no user activity required).

Trigger
-------
EventBridge schedule rule, recommended cron: `cron(5 0 * * ? *)`
(daily at 00:05 UTC). Belt-and-suspenders with the lazy-reset paths
in lambda_quota_check / quota_balance / quota_usage / quota_report
and the admin lazy-reset added in lambda_admin_list_users /
lambda_admin_get_user.

Why this exists
---------------
Before this Lambda, the only way a user's `current_usage` got zeroed
when their `reset_date` passed was if SOMETHING called one of the
lazy-reset paths for that specific user — i.e. they had to chat, or
an admin had to open the Token Management page (after that page also
got the lazy-reset). For users who registered, used a few tokens, and
then went silent, their stale `current_usage` would persist until they
came back. That looked like a bug to admins watching the dashboard
roll over on the 1st.

This Lambda runs once a day, scans `UserQuotas`, and resets every row
whose `reset_date` has passed. The same `ConditionExpression` used in
the lazy paths makes this safe to run concurrently with chat traffic
crossing the boundary — whoever wins the conditional write
materialises the canonical state; the loser observes
ConditionalCheckFailedException and re-fetches.

DynamoDB Tables
---------------
- UserQuotas: Primary key = user_id    (read + conditional update)
- UsageLogs:  Primary key = log_id     (auto_reset audit row per reset)
"""

import json
import os
import uuid
import calendar
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr
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


def _scan_all_quotas():
    """Yield every UserQuotas item, paginating through scan results."""
    scan_kwargs = {}
    while True:
        response = quotas_table.scan(**scan_kwargs)
        for item in response.get('Items', []):
            yield item
        last_key = response.get('LastEvaluatedKey')
        if not last_key:
            return
        scan_kwargs['ExclusiveStartKey'] = last_key


def _reset_one_user(item, now):
    """Reset a single user. Returns one of: 'reset', 'skipped',
    'not_due', 'race', 'error', along with diagnostic info."""
    user_id = item.get('user_id')
    if not user_id:
        return ('skipped', 'missing_user_id')

    # Skip deactivated users — their reset_date is intentionally
    # frozen so a future restore preserves their last billing window.
    if not item.get('is_active', True):
        return ('skipped', 'inactive')

    reset_date_str = item.get('reset_date', '')
    if not reset_date_str:
        return ('skipped', 'no_reset_date')

    try:
        reset_date = parse_reset_date(reset_date_str)
    except (ValueError, TypeError):
        return ('error', f'unparseable_reset_date:{reset_date_str}')

    if now < reset_date:
        return ('not_due', None)

    prev_usage = int(item.get('current_usage', 0))
    prev_cost = float(item.get('current_cost_usd', 0))

    # See lambda_quota_check.py for the snapshot-after-update rationale.
    # The cron is the most likely racer (it sweeps every active user at
    # 00:05 UTC, exactly when chats also tend to fire), so getting this
    # ordering wrong here is what would inflate audit dashboards the most.
    new_reset = get_next_reset_date(reset_date_str)
    try:
        quotas_table.update_item(
            Key={'user_id': user_id},
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

        if prev_usage > 0:
            try:
                logs_table.put_item(Item={
                    'log_id': str(uuid.uuid4()),
                    'user_id': user_id,
                    'fullname': item.get('fullname', ''),
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
                        'triggered_by': 'scheduled_reset',
                        'period_end': reset_date_str,
                        'period_usage': prev_usage,
                        'period_cost_usd': round(prev_cost, 6),
                        'monthly_limit': int(item.get('monthly_limit', 100000))
                    }),
                    'timestamp': now.isoformat()
                })
            except Exception as e:
                print(f"[scheduled-reset] {user_id}: failed to log snapshot: {e}")

        return ('reset', {'prev_usage': prev_usage, 'new_reset_date': new_reset})
    except ClientError as ce:
        code = ce.response.get('Error', {}).get('Code')
        if code == 'ConditionalCheckFailedException':
            # Another path (chat reporting / admin view) crossed the
            # boundary in the milliseconds before us and already
            # reset this user. Not an error — the canonical state is
            # already correct. No snapshot row is written here; the
            # winning path owns that responsibility.
            return ('race', None)
        return ('error', f'ddb:{code}')
    except Exception as e:
        return ('error', f'unexpected:{e}')


def lambda_handler(event, context):
    """Scan UserQuotas and reset everyone whose reset_date has passed.

    Designed to be invoked by EventBridge `cron(5 0 * * ? *)` (daily at
    00:05 UTC). Safe to invoke manually for ad-hoc reconciliation —
    the ConditionExpression makes repeated runs idempotent.
    """
    started_at = datetime.now(timezone.utc)
    now = started_at  # captured once so the snapshot timestamp matches what's
                      # written to the conditional update / audit row

    counts = {'reset': 0, 'skipped': 0, 'not_due': 0, 'race': 0, 'error': 0, 'scanned': 0}
    errors_sample = []
    resets_sample = []

    try:
        for item in _scan_all_quotas():
            counts['scanned'] += 1
            outcome, info = _reset_one_user(item, now)
            counts[outcome] = counts.get(outcome, 0) + 1
            if outcome == 'reset' and len(resets_sample) < 25:
                resets_sample.append({
                    'user_id': item.get('user_id'),
                    'fullname': item.get('fullname', ''),
                    'prev_usage': info.get('prev_usage'),
                    'new_reset_date': info.get('new_reset_date'),
                })
            elif outcome == 'error' and len(errors_sample) < 10:
                errors_sample.append({
                    'user_id': item.get('user_id'),
                    'reason': info,
                })

        elapsed_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        result = {
            'status': 'ok',
            'started_at': started_at.isoformat(),
            'elapsed_ms': elapsed_ms,
            'counts': counts,
            'resets_sample': resets_sample,
            'errors_sample': errors_sample,
        }
        print(f"[scheduled-reset] complete: {json.dumps(counts)} in {elapsed_ms}ms")
        return result

    except Exception as e:
        import traceback
        traceback.print_exc()
        elapsed_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        return {
            'status': 'error',
            'error': str(e),
            'started_at': started_at.isoformat(),
            'elapsed_ms': elapsed_ms,
            'counts': counts,
        }
