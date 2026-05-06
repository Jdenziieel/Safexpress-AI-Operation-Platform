"""
Lambda Function: quota-admin-summary
Get aggregate usage summary across all users and services (Admin only)

DynamoDB Tables:
- UsageLogs: Primary key = log_id
- UserQuotas: Primary key = user_id
"""

import json
import boto3
from datetime import datetime, timezone, timedelta
import os
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource('dynamodb')
quotas_table = dynamodb.Table(os.environ.get('USER_QUOTAS_TABLE', 'UserQuotas'))
logs_table = dynamodb.Table(os.environ.get('USAGE_LOGS_TABLE', 'UsageLogs'))


def lambda_handler(event, context):
    """Get aggregate usage summary across all users and services."""
    
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'GET,OPTIONS'
    }
    
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': ''}
    
    try:
        # Get admin info from authorizer
        request_context = event.get('requestContext', {})
        authorizer = request_context.get('authorizer', {})
        admin_role = authorizer.get('role', '')
        
        # Check admin role
        if admin_role.lower() not in ['admin', 'staff']:
            return {
                'statusCode': 403,
                'headers': cors_headers,
                'body': json.dumps({'error': 'Admin access required'})
            }
        
        # Get query parameters
        query_params = event.get('queryStringParameters', {}) or {}
        hours = int(query_params.get('hours', 24))
        hours = min(max(hours, 1), 720)  # Limit to 1-720 hours (30 days)
        
        start_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        # Scan usage logs for the time period
        # Note: For production, consider using GSI on timestamp
        scan_kwargs = {
            'FilterExpression': Attr('timestamp').gte(start_time)
        }
        
        all_logs = []
        response = logs_table.scan(**scan_kwargs)
        all_logs.extend(response.get('Items', []))
        
        # Handle pagination
        while 'LastEvaluatedKey' in response:
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = logs_table.scan(**scan_kwargs)
            all_logs.extend(response.get('Items', []))
        
        # Calculate totals
        total_tokens = 0
        total_cost = 0.0
        total_operations = len(all_logs)
        unique_users = set()
        by_service = {}
        # by_day powers the "Platform tokens per day" line chart in
        # Token Management → Platform Overview. Same scan, just an
        # extra group-by — cheaper than a separate endpoint and the
        # zero-fill below makes the frontend render trivial (no
        # missing-day gymnastics on the React side).
        by_day = {}
        
        for log in all_logs:
            tokens = int(log.get('total_tokens', 0))
            cost = float(log.get('cost_usd', 0))
            service = log.get('service', 'unknown')
            user_id = log.get('user_id', '')
            model = log.get('model', '')
            ts = log.get('timestamp', '') or ''
            # Day bucket = first 10 chars of ISO timestamp (YYYY-MM-DD).
            # We deliberately do NOT bucket by local time — UsageLogs is
            # always UTC, so admin dashboards staying UTC keeps "day"
            # boundaries aligned with the reset job.
            day_key = ts[:10] if len(ts) >= 10 else None
            
            total_tokens += tokens
            total_cost += cost
            unique_users.add(user_id)
            
            if service not in by_service:
                by_service[service] = {
                    'service': service,
                    'total_tokens': 0,
                    'total_cost_usd': 0.0,
                    'call_count': 0,
                    'models_used': set()
                }
            
            by_service[service]['total_tokens'] += tokens
            by_service[service]['total_cost_usd'] += cost
            by_service[service]['call_count'] += 1
            if model:
                by_service[service]['models_used'].add(model)

            if day_key:
                day = by_day.setdefault(day_key, {
                    'date': day_key,
                    'total_tokens': 0,
                    'total_cost_usd': 0.0,
                    'call_count': 0,
                })
                day['total_tokens'] += tokens
                day['total_cost_usd'] += cost
                day['call_count'] += 1
        
        # Convert sets to lists for JSON serialization
        service_list = []
        for service_data in by_service.values():
            service_list.append({
                'service': service_data['service'],
                'total_tokens': service_data['total_tokens'],
                'total_cost_usd': round(service_data['total_cost_usd'], 4),
                'call_count': service_data['call_count'],
                'models_used': list(service_data['models_used'])
            })

        # Zero-fill missing days across the full window so the line
        # chart has a continuous x-axis. Without this, idle days
        # would silently disappear and the "trend" the admin sees
        # would visually compress periods of no traffic.
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(hours=hours)
        day_cursor = datetime(start_dt.year, start_dt.month, start_dt.day, tzinfo=timezone.utc)
        last_day = datetime(end_dt.year, end_dt.month, end_dt.day, tzinfo=timezone.utc)
        # Cap zero-fill at 366 days so a year-long window doesn't blow
        # the response payload — same effective ceiling as the `hours`
        # clamp above (720h ≈ 30 days), but defensive in case the cap
        # is ever raised.
        zero_fill_safety = 0
        while day_cursor <= last_day and zero_fill_safety < 366:
            key = day_cursor.strftime('%Y-%m-%d')
            if key not in by_day:
                by_day[key] = {
                    'date': key,
                    'total_tokens': 0,
                    'total_cost_usd': 0.0,
                    'call_count': 0,
                }
            day_cursor += timedelta(days=1)
            zero_fill_safety += 1

        day_list = sorted(
            (
                {**d, 'total_cost_usd': round(d['total_cost_usd'], 4)}
                for d in by_day.values()
            ),
            key=lambda r: r['date']
        )
        
        # Get tier breakdown from user quotas
        quotas_response = quotas_table.scan(
            ProjectionExpression='tier'
        )
        by_tier = {}
        for item in quotas_response.get('Items', []):
            tier = item.get('tier', 'free')
            by_tier[tier] = by_tier.get(tier, 0) + 1
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'period_hours': hours,
                'total_users': len(unique_users),
                'total_tokens': total_tokens,
                'total_cost_usd': round(total_cost, 4),
                'total_operations': total_operations,
                'by_service': service_list,
                'by_tier': by_tier,
                'by_day': day_list
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to get summary: {str(e)}'})
        }
