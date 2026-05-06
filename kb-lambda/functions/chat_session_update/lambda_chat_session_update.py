"""
Lambda function for chat session update/delete.
PATCH /chat/session/{session_id}/title - Update session title
DELETE /chat/session/{session_id} - Delete session
"""
import sys
import os

# Add shared modules to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.response_utils import (
    success_response, error_response, unauthorized_response, 
    server_error_response, options_response, get_path_parameter,
    get_http_method, parse_body, forbidden_response, validation_error_response,
    get_user_from_authorizer
)
from shared.db_utils import get_session, update_session, delete_session


def lambda_handler(event, context):
    """
    Handle session update and delete requests.
    
    Routes:
    - PATCH /chat/session/{session_id}/title - Update title
    - DELETE /chat/session/{session_id} - Delete session
    """
    # Handle CORS preflight
    method = get_http_method(event)
    if method == 'OPTIONS':
        return options_response()
    
    try:
        # Get user from API Gateway authorizer context
        try:
            user = get_user_from_authorizer(event)
            user_id = user['user_id']
        except Exception as e:
            return unauthorized_response(str(e))
        
        # Get session ID
        session_id = get_path_parameter(event, 'session_id')
        if not session_id:
            return validation_error_response("session_id is required")
        
        # Verify session ownership
        session = get_session(session_id)
        if not session:
            return error_response("Session not found", 404)
        
        if session.get('user_id') != user_id:
            return forbidden_response("Access denied - you don't own this session")
        
        # Handle by method
        if method == 'PATCH':
            return update_session_title(session_id, event)
        elif method == 'DELETE':
            return delete_session_handler(session_id)
        else:
            return error_response(f"Method {method} not allowed", 405)
        
    except Exception as e:
        print(f"Error in session update: {e}")
        import traceback
        traceback.print_exc()
        return server_error_response(str(e))


def update_session_title(session_id: str, event: dict):
    """Update session title."""
    body = parse_body(event)
    title = body.get('title', '').strip()
    
    if not title:
        return validation_error_response("title is required")
    
    updated = update_session(session_id, {'title': title})
    
    if updated:
        return success_response({
            'session_id': session_id,
            'title': title,
            'updated': True
        })
    else:
        return error_response("Failed to update session", 500)


def delete_session_handler(session_id: str):
    """Delete session and all its messages."""
    success = delete_session(session_id)
    
    if success:
        return success_response({
            'session_id': session_id,
            'deleted': True
        })
    else:
        return error_response("Failed to delete session", 500)
