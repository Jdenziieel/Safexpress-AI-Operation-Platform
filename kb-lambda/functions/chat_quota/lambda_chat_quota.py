"""
Lambda function for chat quota endpoint.
GET /chat/quota - Get user's quota balance

Matches original knowledge-base/api/chat_routes.py quota endpoint.
"""
import sys
import os
import httpx

# Add shared modules to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.response_utils import (
    success_response, error_response, unauthorized_response, 
    server_error_response, options_response, get_user_from_authorizer
)
from shared.service_jwt import service_auth_headers

# Quota service configuration
QUOTA_SERVICE_URL = os.environ.get('QUOTA_SERVICE_URL', '')
QUOTA_ENABLED = os.environ.get('QUOTA_ENABLED', 'true').lower() == 'true'


def lambda_handler(event, context):
    """
    Get user's quota balance from quota service.
    
    Returns quota information including:
    - remaining_tokens: Tokens left in monthly quota
    - monthly_limit: Total monthly limit
    - current_usage: Tokens used this month
    - percentage_used: Percentage of quota consumed
    - tier: User's quota tier (free, pro, enterprise)
    - resets_at: When the quota resets
    """
    # Handle CORS preflight
    if event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
        return options_response()
    
    try:
        # Get user from API Gateway authorizer context
        try:
            user = get_user_from_authorizer(event)
            user_id = user['user_id']
        except Exception as e:
            return unauthorized_response(str(e))
        
        # If quota not enabled, return disabled message
        if not QUOTA_ENABLED:
            return success_response({
                'success': True,
                'quota_enabled': False,
                'message': 'Quota tracking is disabled'
            })
        
        # If no quota service configured, return unlimited
        if not QUOTA_SERVICE_URL:
            return success_response({
                'success': True,
                'quota_enabled': True,
                'quota_service_available': False,
                'user_id': user_id,
                'message': 'Quota service not configured'
            })
        
        # Call quota service
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(
                    f"{QUOTA_SERVICE_URL.rstrip('/')}/quota/balance/{user_id}",
                    headers=service_auth_headers('kb-chat-quota'),
                )
                
                if response.status_code == 404:
                    return error_response(
                        "User not found. Please contact an administrator to set up your account.",
                        404
                    )
                
                response.raise_for_status()
                data = response.json()
                
                return success_response({
                    'success': True,
                    'quota_enabled': True,
                    'quota_service_available': True,
                    'user_id': user_id,
                    'remaining_tokens': data.get('remaining_tokens', 0),
                    'monthly_limit': data.get('monthly_limit', 0),
                    'current_usage': data.get('current_usage', 0),
                    'percentage_used': data.get('percentage_used', 0),
                    'tier': data.get('tier', 'free'),
                    'resets_at': data.get('resets_at'),
                    'warning': data.get('warning', False),
                    'warning_message': data.get('warning_message')
                })
                
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return error_response(
                    "User not found. Please contact an administrator.",
                    404
                )
            raise
        except Exception as e:
            # Quota service unavailable - still return success but indicate issue
            return success_response({
                'success': True,
                'quota_enabled': True,
                'quota_service_available': False,
                'user_id': user_id,
                'message': f'Quota service unavailable: {str(e)}'
            })
            
    except Exception as e:
        print(f"Error getting quota: {e}")
        import traceback
        traceback.print_exc()
        return server_error_response(str(e))
