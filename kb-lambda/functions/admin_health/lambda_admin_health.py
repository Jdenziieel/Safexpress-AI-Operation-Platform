"""
Lambda function for admin health check.
GET /kb-admin/health - Get system health status

Matches original knowledge-base/api/admin_routes.py health endpoint
with traffic light indicator and service status.
"""
import sys
import os

# Add shared modules to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.response_utils import success_response, options_response
from shared.weaviate_utils import check_weaviate_connection, get_weaviate_chunk_count, close_weaviate_client
from shared.openai_utils import check_openai_connection


def lambda_handler(event, context):
    """
    Check system health status.
    
    Returns traffic light indicator:
    - 🟢 All Systems Operational
    - 🟡 Minor Issues Detected
    - 🔴 System Issues Detected
    """
    # Handle CORS preflight
    if event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
        return options_response()
    
    try:
        health_issues = []
        
        # Check Weaviate
        weaviate_ok = False
        weaviate_chunks = 0
        weaviate_status = "unknown"
        try:
            weaviate_ok = check_weaviate_connection()
            if weaviate_ok:
                weaviate_status = "connected"
                weaviate_chunks = get_weaviate_chunk_count()
            else:
                weaviate_status = "disconnected"
                health_issues.append("Weaviate vector database not connected")
        except Exception as e:
            weaviate_status = f"error: {str(e)[:50]}"
            health_issues.append(f"Weaviate error: {str(e)[:50]}")
        
        # Check OpenAI
        openai_ok = False
        openai_status = "unknown"
        try:
            openai_ok = check_openai_connection()
            openai_status = "configured" if openai_ok else "not configured"
            if not openai_ok:
                health_issues.append("OpenAI API not configured")
        except Exception as e:
            openai_status = f"error: {str(e)[:50]}"
            health_issues.append(f"OpenAI error: {str(e)[:50]}")
        
        # Check DynamoDB (environment variables are set)
        dynamodb_ok = bool(os.environ.get('DOCUMENTS_TABLE'))
        dynamodb_status = "connected" if dynamodb_ok else "not configured"
        if not dynamodb_ok:
            health_issues.append("DynamoDB tables not configured")
        
        # Check S3
        s3_ok = bool(os.environ.get('KB_FILES_BUCKET'))
        s3_status = "configured" if s3_ok else "not configured"
        
        # Determine overall status and indicator
        critical_ok = weaviate_ok and openai_ok and dynamodb_ok
        all_ok = critical_ok and s3_ok
        
        if all_ok:
            status = "All Systems Operational"
            indicator = "🟢"
        elif critical_ok:
            status = "Minor Issues Detected"
            indicator = "🟡"
        else:
            status = "System Issues Detected"
            indicator = "🔴"
        
        return success_response({
            'status': status,
            'indicator': indicator,
            'services': {
                'weaviate': {
                    'status': weaviate_status,
                    'chunks_stored': weaviate_chunks,
                    'url': os.environ.get('WEAVIATE_URL', 'not configured')[:50] if os.environ.get('WEAVIATE_URL') else 'not configured'
                },
                'openai': {
                    'status': openai_status
                },
                'dynamodb': {
                    'status': dynamodb_status,
                    'tables': {
                        'documents': os.environ.get('DOCUMENTS_TABLE', 'not configured'),
                        'sessions': os.environ.get('SESSIONS_TABLE', 'not configured'),
                        'messages': os.environ.get('MESSAGES_TABLE', 'not configured'),
                        'logs': os.environ.get('LOGS_TABLE', 'not configured')
                    }
                },
                's3': {
                    'status': s3_status,
                    'bucket': os.environ.get('KB_FILES_BUCKET', 'not configured')
                }
            },
            'recent_errors': health_issues[-5:] if health_issues else []
        })
        
    except Exception as e:
        print(f"Health check error: {e}")
        return success_response({
            'status': 'Unable to determine status',
            'indicator': '🟡',
            'services': {
                'weaviate': {'status': 'unknown'},
                'openai': {'status': 'unknown'},
                'dynamodb': {'status': 'unknown'},
                's3': {'status': 'unknown'}
            },
            'error': str(e)
        })
    
    finally:
        try:
            close_weaviate_client()
        except:
            pass
