"""
Lambda function for chat session creation.
POST /chat/session/new - Create new chat session

Matches original knowledge-base/api/chat_routes.py session creation.
Includes quota check for deactivated users.
"""
import sys
import os

# Add shared modules to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.response_utils import (
    success_response, error_response, unauthorized_response, 
    server_error_response, options_response, parse_body,
    get_user_from_authorizer, forbidden_response
)
from shared.db_utils import create_session
from shared.service_jwt import service_auth_headers

# Quota service configuration
QUOTA_SERVICE_URL = os.environ.get('QUOTA_SERVICE_URL', '')
QUOTA_ENABLED = os.environ.get('QUOTA_ENABLED', 'true').lower() == 'true'


def check_user_active(user_id: str) -> tuple[bool, str]:
    """
    Check if user is active via quota service.
    
    Returns:
        (is_active: bool, error_message: str)
    """
    if not QUOTA_ENABLED or not QUOTA_SERVICE_URL:
        print("[Chat] Quota check disabled or not configured")
        return True, ""
    
    try:
        import httpx
        
        # No trailing slash — API Gateway treats `/quota/check` and
        # `/quota/check/` as different routes; only the former is wired up.
        url = f"{QUOTA_SERVICE_URL.rstrip('/')}/quota/check"
        print(f"[Chat] Checking user status at: {url}")
        
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                url,
                json={
                    "user_id": user_id,
                    "estimated_tokens": 0,
                    "service": "knowledge-base",
                    "operation": "create_session"
                },
                headers=service_auth_headers('kb-chat-session-create'),
            )
            
            if response.status_code == 200:
                data = response.json()
                # Check if user is deactivated
                if data.get('is_deactivated', False):
                    return False, data.get('message', 'User account is deactivated')
                return True, ""
            elif response.status_code == 403:
                data = response.json()
                return False, data.get('message', 'Access denied')
            else:
                print(f"[Chat] Quota check returned {response.status_code} - allowing operation")
                return True, ""
                
    except Exception as e:
        print(f"[Chat] Quota check error: {e} - allowing operation")
        return True, ""


def lambda_handler(event, context):
    """
    Create a new chat session.
    
    Request body:
    {
        "title": "Optional session title",
        "initial_message": "Optional first message"
    }
    
    Returns:
    - session_id: New session ID
    - created_at: Creation timestamp
    - message: Success message
    """
    # Handle CORS preflight
    if event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
        return options_response()
    
    try:
        # Get user from API Gateway authorizer context
        try:
            user = get_user_from_authorizer(event)
            user_id = user['user_id']
            user_email = user.get('email') or user_id
        except Exception as e:
            return unauthorized_response(str(e))
        
        print(f"[Chat] Creating session for user: {user_email}")
        
        # Check if user is active before creating session
        is_active, error_message = check_user_active(user_id)
        if not is_active:
            print(f"[Chat] ❌ User {user_email} is DEACTIVATED: {error_message}")
            return error_response(
                f"Access denied: {error_message}",
                403,
                error_code='ACCOUNT_DEACTIVATED'
            )
        
        print(f"[Chat] ✅ User {user_email} is active")
        
        # Parse request body
        body = parse_body(event)
        title = body.get('title', 'New Chat')
        initial_message = body.get('initial_message', '')
        
        # Create session
        session = create_session(user_id=user_id, title=title)
        session_id = session['session_id']
        
        print(f"[Chat] Created session {session_id} for user {user_email}")
        
        # If initial message provided, we could invoke chat_message Lambda
        # but for now just note it - the frontend typically sends messages separately
        if initial_message:
            print(f"[Chat] Initial message provided (length: {len(initial_message)})")
            # Could invoke chat_message Lambda here if needed
        
        return success_response({
            'success': True,
            'session_id': session_id,
            'title': title,
            'created_at': session.get('created_at'),
            'user_id': user_id,
            'message': 'Session created successfully'
        }, status_code=201)
        
    except Exception as e:
        print(f"Error creating chat session: {e}")
        import traceback
        traceback.print_exc()
        
        error_msg = str(e)
        # Check if this is an access denied error
        if "Access denied" in error_msg or "deactivated" in error_msg.lower():
            return forbidden_response(error_msg)
        
        return server_error_response(error_msg)
