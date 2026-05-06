"""
Lambda function for admin stats endpoints.
GET /kb-admin/chat-stats - Get chat statistics
GET /kb-admin/costs - Get cost breakdown
GET /kb-admin/errors - Get recent errors
GET /kb-admin/stats - Get combined statistics
GET /kb-admin/activity-logs - Get activity logs
"""
import sys
import os
from datetime import datetime, timezone, timedelta

# Add shared modules to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.response_utils import (
    success_response, error_response, unauthorized_response, 
    server_error_response, options_response, get_route_path,
    get_query_parameter, get_user_from_authorizer
)
from shared.db_utils import get_chat_stats, get_document_stats, get_logs


def lambda_handler(event, context):
    """
    Handle admin stats endpoints.
    
    Routes:
    - GET /kb-admin/chat-stats - Chat usage statistics
    - GET /kb-admin/costs - Cost breakdown
    - GET /kb-admin/errors - Recent errors
    - GET /kb-admin/stats - Combined statistics
    - GET /kb-admin/activity-logs - Activity logs
    """
    # Handle CORS preflight
    if event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
        return options_response()
    
    try:
        # Get user from API Gateway authorizer context (admin role enforced by authorizer)
        try:
            user = get_user_from_authorizer(event)
        except Exception as e:
            return unauthorized_response(str(e))
        
        # Determine route
        path = get_route_path(event)
        
        if 'chat-stats' in path:
            return get_chat_stats_handler(event)
        elif 'costs' in path:
            return get_costs_handler(event)
        elif 'errors' in path:
            return get_errors_handler(event)
        elif 'activity-logs' in path:
            return get_activity_logs_handler(event)
        elif 'stats' in path:
            return get_combined_stats_handler(event)
        else:
            return error_response("Unknown endpoint", 404)
        
    except Exception as e:
        print(f"Error in admin stats: {e}")
        import traceback
        traceback.print_exc()
        return server_error_response(str(e))


def parse_period(period_str: str) -> timedelta:
    """Parse period string to timedelta."""
    period_map = {
        '1h': timedelta(hours=1),
        '6h': timedelta(hours=6),
        '24h': timedelta(hours=24),
        '7d': timedelta(days=7),
        '30d': timedelta(days=30)
    }
    return period_map.get(period_str, timedelta(hours=24))


def get_chat_stats_handler(event):
    """Get chat usage statistics (aggregated, no PII)."""
    period = get_query_parameter(event, 'period', '24h')
    delta = parse_period(period)
    start_time = (datetime.now(timezone.utc) - delta).isoformat()
    
    stats = get_chat_stats(start_time)
    stats['period'] = period
    
    return success_response(stats)


def get_costs_handler(event):
    """Get cost breakdown by operation."""
    days = int(get_query_parameter(event, 'days', '30'))
    days = max(1, min(365, days))  # Clamp between 1-365
    
    start_time = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    # Get logs for cost calculation
    doc_logs = get_logs('document', start_time, limit=1000)
    chat_logs = get_logs('chat', start_time, limit=1000)
    
    # For document costs, only count parse logs (ai_parse_async/parse) which have tokens/cost.
    # Upload logs have cost_usd=0 so they won't add anything, but filtering avoids
    # future bugs if upload logs ever carry cost data.
    # NOTE: No deduplication by file_name — each parse is a real cost event,
    # including re-uploads/version updates of the same file.
    parse_ops = ('parse', 'ai_parse_async')
    parse_doc_logs = [log for log in doc_logs if log.get('operation') in parse_ops]
    
    doc_cost = sum(log.get('cost_usd', 0) or 0 for log in parse_doc_logs)
    doc_tokens = sum(log.get('tokens_used', 0) or 0 for log in parse_doc_logs)
    
    chat_cost = sum(log.get('cost_usd', 0) for log in chat_logs)
    chat_tokens = sum(log.get('tokens_used', 0) for log in chat_logs)
    
    return success_response({
        'period_days': days,
        'document_processing': {
            'total_tokens': doc_tokens,
            'total_cost_usd': doc_cost
        },
        'chat': {
            'total_tokens': chat_tokens,
            'total_cost_usd': chat_cost
        },
        'total': {
            'tokens': doc_tokens + chat_tokens,
            'cost_usd': doc_cost + chat_cost
        }
    })


def get_errors_handler(event):
    """Get recent errors."""
    hours = int(get_query_parameter(event, 'hours', '1'))
    hours = max(1, min(24, hours))
    limit = int(get_query_parameter(event, 'limit', '50'))
    limit = max(1, min(200, limit))
    
    start_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    
    # Get error logs
    all_logs = get_logs(None, start_time, limit * 2)
    
    # Filter for errors
    errors = []
    for log in all_logs:
        if log.get('success') == False or log.get('error'):
            errors.append({
                'timestamp': log.get('timestamp'),
                'log_type': log.get('log_type'),
                'operation': log.get('operation'),
                'error': log.get('error'),
                'document_id': log.get('document_id'),
                'file_name': log.get('file_name')
            })
    
    errors = errors[:limit]
    
    return success_response({
        'errors': errors,
        'total': len(errors),
        'period_hours': hours
    })


def get_combined_stats_handler(event):
    """Get combined statistics for dashboard."""
    period = get_query_parameter(event, 'period', '24h')
    delta = parse_period(period)
    start_time = (datetime.now(timezone.utc) - delta).isoformat()
    
    doc_stats = get_document_stats(start_time)
    chat_stats = get_chat_stats(start_time)
    
    # Calculate totals
    total_tokens = (doc_stats.get('total_tokens', 0) or 0) + (chat_stats.get('total_tokens', 0) or 0)
    total_cost = (doc_stats.get('total_cost_usd', 0) or 0) + (chat_stats.get('total_cost_usd', 0) or 0)
    
    return success_response({
        'period': period,
        'documents': {
            'processed': doc_stats.get('documents_processed', 0),
            'chunks_created': doc_stats.get('total_chunks', 0),
            'tokens': doc_stats.get('total_tokens', 0) or 0,
            'cost_usd': doc_stats.get('total_cost_usd', 0) or 0,
            'success_rate': doc_stats.get('success_rate', 100),
            'successful': doc_stats.get('successful', 0),
            'failed': doc_stats.get('failed', 0),
            'avg_processing_time_ms': doc_stats.get('avg_processing_time_ms', 0)
        },
        'chat': {
            'sessions': chat_stats.get('total_sessions', 0),
            'messages': chat_stats.get('total_messages', 0),
            'tokens': chat_stats.get('total_tokens', 0) or 0,
            'cost_usd': chat_stats.get('total_cost_usd', 0) or 0,
            'avg_response_time_ms': chat_stats.get('avg_response_time_ms', 0)
        },
        'totals': {
            'tokens': total_tokens,
            'cost_usd': total_cost
        }
    })


def get_activity_logs_handler(event):
    """Get recent activity logs for admin monitoring."""
    hours = int(get_query_parameter(event, 'hours', '24'))
    hours = max(1, min(168, hours))  # Max 7 days
    limit = int(get_query_parameter(event, 'limit', '50'))
    limit = max(1, min(200, limit))
    log_type = get_query_parameter(event, 'log_type', 'all')
    
    start_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    
    logs = []
    
    if log_type in ['all', 'documents']:
        doc_logs = get_logs('document', start_time, limit)
        logs.extend([{**log, 'log_type': 'document'} for log in doc_logs])
    
    if log_type in ['all', 'chat']:
        chat_logs = get_logs('chat', start_time, limit)
        logs.extend([{**log, 'log_type': 'chat'} for log in chat_logs])
    
    # Sort by timestamp descending
    logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    logs = logs[:limit]
    
    # Sanitize logs (remove sensitive info)
    sanitized = []
    for log in logs:
        operation = log.get('operation', '')
        
        # Build human-readable action label
        if operation == 'ai_parse_async':
            action = 'AI Parse'
        elif operation == 'parse':
            action = 'Parse'
        elif operation == 'upload':
            action = 'Upload to KB'
        elif operation == 'delete':
            action = 'Delete'
        else:
            action = operation.replace('_', ' ').title() if operation else 'Unknown'
        
        safe_log = {
            'timestamp': log.get('timestamp'),
            'type': log.get('log_type', 'document'),
            'log_type': log.get('log_type'),
            'action': action,
            'operation': operation,
            'target': log.get('file_name'),
            'success': log.get('success'),
            'document_id': log.get('document_id'),
            'file_name': log.get('file_name'),
            'details': {
                'tokens': log.get('tokens_used', 0) or 0,
                'cost_usd': log.get('cost_usd', 0) or 0,
                'chunks_created': log.get('chunks_created', 0) or 0,
                'duration_ms': log.get('duration_ms', 0) or 0,
                'uploaded_by': log.get('uploaded_by') or log.get('parsed_by') or '',
                'page_count': log.get('page_count', 0) or 0,
                'job_id': log.get('job_id', ''),
                'version': log.get('version', 0) or 0
            }
        }
        if not log.get('success'):
            safe_log['error'] = log.get('error')
        sanitized.append(safe_log)
    
    return success_response({
        'logs': sanitized,
        'total': len(sanitized),
        'period_hours': hours,
        'filter': log_type
    })
