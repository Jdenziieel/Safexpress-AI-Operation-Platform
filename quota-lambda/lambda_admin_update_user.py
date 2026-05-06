"""
Lambda Function: quota-admin-update-user
Update a user's quota settings (Admin only)

DynamoDB Tables:
- UserQuotas: Primary key = user_id
- QuotaAdminActions: Primary key = action_id
"""

import json
import boto3
from datetime import datetime, timezone
import uuid
import os
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
quotas_table = dynamodb.Table(os.environ.get('USER_QUOTAS_TABLE', 'UserQuotas'))
actions_table = dynamodb.Table(os.environ.get('ADMIN_ACTIONS_TABLE', 'QuotaAdminActions'))

TIER_LIMITS = {
    'free': 100_000,
    'pro': 1_000_000,
    'enterprise': 10_000_000,
    'unlimited': 999_999_999
}


def log_admin_action(admin_id, admin_name, action, target_user_id, target_user_name, details):
    """Log admin action to DynamoDB."""
    try:
        actions_table.put_item(Item={
            'action_id': str(uuid.uuid4()),
            'admin_id': admin_id or 'system',
            'admin_name': admin_name or 'System',
            'action': action,
            'target_user_id': target_user_id,
            'target_user_name': target_user_name,
            'details': json.dumps(details) if details else None,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
    except Exception as e:
        print(f"Failed to log admin action: {str(e)}")


def _normalize_reset_date(value):
    """Normalize a reset_date string to canonical UTC ISO with a `Z` suffix.

    Accepts the formats this Lambda has produced or received historically:
      - ''                              → None  (no value stored yet)
      - 'YYYY-MM-DD'                    (HTML <input type="date"> payload)
      - 'YYYY-MM-DDTHH:MM:SSZ'          (canonical, what we now write)
      - 'YYYY-MM-DDTHH:MM:SS+00:00'     (legacy: datetime.isoformat() output)
      - 'YYYY-MM-DDTHH:MM:SS'           (naive — treated as UTC)
      - non-UTC offsets                 (converted to UTC)

    Returns the canonical form 'YYYY-MM-DDTHH:MM:SSZ', or None for an
    empty / unparseable input.

    Why this exists:
        The previous code compared old_values['reset_date'] and the
        request's reset_date as raw strings. Because Python's
        datetime.isoformat() emits '+00:00' but this Lambda re-saves
        with a literal 'Z', equivalent UTC instants compared unequal
        and a spurious audit row was written every time an admin
        re-saved the same date — which was confusing in the Token
        Management → Recent Admin Actions table (the row showed
        "reset_date  +00:00 → Z" with both sides representing the
        same moment).
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    # Plain YYYY-MM-DD from <input type="date"> — assume midnight UTC.
    if 'T' not in s:
        s = f"{s}T00:00:00+00:00"

    # datetime.fromisoformat below 3.11 doesn't accept the trailing 'Z'
    # shorthand. Substitute the explicit offset so the same code path
    # handles both Python 3.9 (current Lambda runtime floor) and 3.11+.
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'

    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def lambda_handler(event, context):
    """Update a user's quota settings."""
    
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'PUT,OPTIONS'
    }
    
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': ''}
    
    try:
        # Get admin info from authorizer
        request_context = event.get('requestContext', {})
        authorizer = request_context.get('authorizer', {})
        admin_role = authorizer.get('role', '')
        admin_id = authorizer.get('user_id', authorizer.get('gmail', ''))
        admin_name = authorizer.get('fullname', '')
        
        # Check admin role
        if admin_role.lower() not in ['admin', 'staff']:
            return {
                'statusCode': 403,
                'headers': cors_headers,
                'body': json.dumps({'error': 'Admin access required'})
            }
        
        # Get user_id from path parameters
        path_params = event.get('pathParameters', {}) or {}
        user_id = path_params.get('user_id')
        
        if not user_id:
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'user_id is required'})
            }
        
        # Get current user
        response = quotas_table.get_item(Key={'user_id': user_id})
        user_data = response.get('Item')
        
        if not user_data:
            return {
                'statusCode': 404,
                'headers': cors_headers,
                'body': json.dumps({'error': f'User {user_id} not found'})
            }
        
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        tier = body.get('tier')
        monthly_limit = body.get('monthly_limit')
        reset_date = body.get('reset_date')
        
        # Capture old values for logging
        old_values = {
            'tier': user_data.get('tier', 'free'),
            'monthly_limit': int(user_data.get('monthly_limit', 100000)),
            'reset_date': user_data.get('reset_date', '')
        }
        
        # Build update expression
        update_parts = ['updated_at = :now']
        expr_values = {':now': datetime.now(timezone.utc).isoformat()}
        changes = {}

        # Tier: compare lowercased on both sides so a re-save with
        # different casing isn't treated as a change. The frontend
        # already sends lowercase, but DDB rows from earlier code may
        # have any casing — defensive.
        if tier:
            new_tier = tier.lower()
            old_tier = (old_values['tier'] or '').lower()
            if new_tier != old_tier:
                update_parts.append('tier = :tier')
                expr_values[':tier'] = new_tier
                changes['tier'] = {'from': old_values['tier'], 'to': new_tier}

                # If tier changes and no custom limit, use tier default
                if monthly_limit is None:
                    monthly_limit = TIER_LIMITS.get(new_tier, TIER_LIMITS['free'])

        if monthly_limit is not None and monthly_limit != old_values['monthly_limit']:
            update_parts.append('monthly_limit = :limit')
            expr_values[':limit'] = monthly_limit
            changes['monthly_limit'] = {'from': old_values['monthly_limit'], 'to': monthly_limit}

        # reset_date: compare canonical UTC instants, not raw strings.
        # Without this, re-saving the same date logs a phantom audit row
        # like "reset_date 2026-05-01T00:00:00+00:00 → 2026-05-01T00:00:00Z"
        # because the old DDB value uses '+00:00' (Python isoformat) while
        # this Lambda writes the literal 'Z' suffix. See _normalize_reset_date.
        if reset_date:
            new_normalized = _normalize_reset_date(reset_date)
            old_normalized = _normalize_reset_date(old_values['reset_date'])
            if new_normalized and new_normalized != old_normalized:
                update_parts.append('reset_date = :reset')
                expr_values[':reset'] = new_normalized
                # `from` keeps the raw old DDB value so the audit log shows
                # exactly what was previously stored (incl. legacy '+00:00'
                # rows). `to` is canonical so future comparisons are stable.
                changes['reset_date'] = {
                    'from': old_values['reset_date'],
                    'to': new_normalized,
                }
        
        if len(update_parts) == 1:
            # No changes
            return {
                'statusCode': 200,
                'headers': cors_headers,
                'body': json.dumps({
                    'message': 'No changes made',
                    'user': {
                        'user_id': user_id,
                        'fullname': user_data.get('fullname', ''),
                        'tier': old_values['tier'],
                        'monthly_limit': old_values['monthly_limit'],
                        'current_usage': int(user_data.get('current_usage', 0)),
                        'is_active': user_data.get('is_active', True)
                    }
                })
            }
        
        # Apply updates
        update_expr = 'SET ' + ', '.join(update_parts)
        
        quotas_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values
        )
        
        # Log admin action
        if changes:
            log_admin_action(admin_id, admin_name, 'update_user_quota', user_id, 
                           user_data.get('fullname', ''), changes)
        
        # Get updated user
        response = quotas_table.get_item(Key={'user_id': user_id})
        updated = response.get('Item', {})
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'message': f'User {user_id} quota updated',
                'user': {
                    'user_id': user_id,
                    'fullname': updated.get('fullname', ''),
                    'tier': updated.get('tier', 'free'),
                    'monthly_limit': int(updated.get('monthly_limit', 100000)),
                    'current_usage': int(updated.get('current_usage', 0)),
                    'is_active': updated.get('is_active', True)
                },
                'changes': changes
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to update user quota: {str(e)}'})
        }
