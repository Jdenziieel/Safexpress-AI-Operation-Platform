"""
Lambda function for admin health check.
GET /kb-admin/health - Get system health status
"""
import sys
import os

# Add shared modules to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.response_utils import success_response, options_response
from shared.weaviate_utils import check_weaviate_connection, close_weaviate_client
from shared.openai_utils import check_openai_connection


def lambda_handler(event, context):
    """
    Check system health status.
    
    Returns:
    {
        "status": "healthy",
        "weaviate": {"connected": true},
        "openai": {"configured": true},
        "dynamodb": {"connected": true}
    }
    """
    # Handle CORS preflight
    if event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
        return options_response()
    
    try:
        # Check Weaviate
        weaviate_ok = False
        try:
            weaviate_ok = check_weaviate_connection()
        except Exception as e:
            print(f"Weaviate check error: {e}")
        
        # Check OpenAI
        openai_ok = False
        try:
            openai_ok = check_openai_connection()
        except Exception as e:
            print(f"OpenAI check error: {e}")
        
        # Check DynamoDB (just check environment variables are set)
        dynamodb_ok = bool(os.environ.get('DOCUMENTS_TABLE'))
        
        # Check S3
        s3_ok = bool(os.environ.get('KB_FILES_BUCKET'))
        
        # Overall status
        all_ok = weaviate_ok and openai_ok and dynamodb_ok
        
        return success_response({
            'status': 'healthy' if all_ok else 'degraded',
            'weaviate': {
                'connected': weaviate_ok,
                'url': os.environ.get('WEAVIATE_URL', 'not configured')[:50] + '...' if os.environ.get('WEAVIATE_URL') else 'not configured'
            },
            'openai': {
                'configured': openai_ok
            },
            'dynamodb': {
                'connected': dynamodb_ok,
                'tables': {
                    'documents': os.environ.get('DOCUMENTS_TABLE', 'not configured'),
                    'sessions': os.environ.get('SESSIONS_TABLE', 'not configured'),
                    'messages': os.environ.get('MESSAGES_TABLE', 'not configured'),
                    'logs': os.environ.get('LOGS_TABLE', 'not configured')
                }
            },
            's3': {
                'configured': s3_ok,
                'bucket': os.environ.get('KB_FILES_BUCKET', 'not configured')
            }
        })
        
    except Exception as e:
        print(f"Health check error: {e}")
        return success_response({
            'status': 'error',
            'error': str(e)
        })
    
    finally:
        try:
            close_weaviate_client()
        except:
            pass
