"""
Lambda function for chat sessions management.
GET /chat/sessions - List user's sessions
GET /chat/session/{session_id} - Get session details
GET /chat/session/{session_id}/history - Get session message history
PATCH /chat/session/{session_id}/title - Update session title
DELETE /chat/session/{session_id} - Delete session

Matches original knowledge-base/api/chat_routes.py session endpoints.
"""
import sys
import os

# Add shared modules to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.response_utils import (
    success_response, error_response, unauthorized_response, 
    server_error_response, options_response, get_path_parameter,
    get_route_path, forbidden_response, get_user_from_authorizer,
    get_http_method, parse_body, get_query_parameter
)
from shared.db_utils import (
    get_session, get_user_sessions, get_session_messages,
    update_session, delete_session
)


def lambda_handler(event, context):
    """
    Handle session list, details, update, and delete requests.
    
    Routes:
    - GET /chat/sessions - List all sessions for user
    - GET /chat/session/{session_id} - Get session details
    - GET /chat/session/{session_id}/history - Get session messages
    - PATCH /chat/session/{session_id}/title - Update session title
    - DELETE /chat/session/{session_id} - Delete session
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
        
        # Determine which route
        path = get_route_path(event)
        method = get_http_method(event)
        session_id = get_path_parameter(event, 'session_id')
        
        print(f"[Chat Sessions] {method} {path} session_id={session_id}")
        
        # Route: DELETE /chat/session/{id} - Delete session
        if method == 'DELETE' and session_id:
            return handle_delete_session(session_id, user_id)
        
        # Route: PATCH /chat/session/{id}/title - Update title
        if method == 'PATCH' and session_id and '/title' in path:
            body = parse_body(event)
            return handle_update_title(session_id, user_id, body.get('title', ''))
        
        # Route: GET /chat/sessions - List all sessions
        if '/sessions' in path and not session_id:
            limit = int(get_query_parameter(event, 'limit', '20'))
            offset = int(get_query_parameter(event, 'offset', '0'))
            return list_sessions(user_id, limit, offset)
        
        # Route: GET /chat/session/{id}/history - Get session messages
        if session_id and '/history' in path:
            return get_session_history(session_id, user_id)
        
        # Route: GET /chat/session/{id} - Get session details
        if session_id:
            return get_session_details(session_id, user_id)
        
        return error_response("Invalid route", 400)
        
    except Exception as e:
        print(f"Error in chat sessions: {e}")
        import traceback
        traceback.print_exc()
        return server_error_response(str(e))


def list_sessions(user_id: str, limit: int = 20, offset: int = 0):
    """List all chat sessions for a user with pagination."""
    sessions = get_user_sessions(user_id)
    
    # Sort by updated_at descending
    sessions.sort(key=lambda x: x.get('updated_at') or x.get('created_at', ''), reverse=True)
    
    # Apply pagination
    total = len(sessions)
    sessions = sessions[offset:offset + limit]
    
    # Format for response
    formatted = []
    for session in sessions:
        formatted.append({
            'session_id': session['session_id'],
            'title': session.get('title', 'New Chat'),
            'created_at': session.get('created_at'),
            'updated_at': session.get('updated_at'),
            'message_count': session.get('message_count', 0)
        })
    
    return success_response({
        'success': True,
        'sessions': formatted,
        'total': total,
        'count': len(formatted),
        'limit': limit,
        'offset': offset
    })


def get_session_details(session_id: str, user_id: str):
    """Get session details."""
    session = get_session(session_id)
    
    if not session:
        return error_response("Session not found", 404)
    
    if session.get('user_id') != user_id:
        return forbidden_response("Access denied - you don't own this session")
    
    return success_response({
        'success': True,
        'session_id': session['session_id'],
        'title': session.get('title', 'New Chat'),
        'created_at': session.get('created_at'),
        'updated_at': session.get('updated_at'),
        'message_count': session.get('message_count', 0),
        'total_tokens_used': session.get('total_tokens_used', 0),
        'total_cost_usd': session.get('total_cost_usd', 0),
        'metadata': session.get('metadata', {})
    })


def get_session_history(session_id: str, user_id: str):
    """Get session message history."""
    session = get_session(session_id)
    
    if not session:
        return error_response("Session not found", 404)
    
    if session.get('user_id') != user_id:
        return forbidden_response("Access denied - you don't own this session")
    
    messages = get_session_messages(session_id)
    
    # Format messages for response
    formatted = []
    for msg in messages:
        formatted.append({
            'message_id': msg['message_id'],
            'role': msg['role'],
            'content': msg['content'],
            'timestamp': msg['timestamp'],
            'sources': msg.get('sources', [])
        })
    
    return success_response({
        'success': True,
        'session_id': session_id,
        'title': session.get('title', 'New Chat'),
        'messages': formatted,
        'total': len(formatted)
    })


def handle_update_title(session_id: str, user_id: str, title: str):
    """Update session title."""
    if not title or not title.strip():
        return error_response("Title is required", 400)
    
    title = title.strip()[:200]  # Max 200 chars
    
    session = get_session(session_id)
    
    if not session:
        return error_response("Session not found", 404)
    
    if session.get('user_id') != user_id:
        return forbidden_response("Access denied - you don't own this session")
    
    result = update_session(session_id, {'title': title})
    
    if not result:
        return server_error_response("Failed to update session title")
    
    return success_response({
        'success': True,
        'message': 'Session title updated successfully',
        'session_id': session_id,
        'title': title
    })


def handle_delete_session(session_id: str, user_id: str):
    """Delete a session."""
    session = get_session(session_id)
    
    if not session:
        return error_response("Session not found or already deleted", 404)
    
    if session.get('user_id') != user_id:
        return forbidden_response("Access denied - you don't own this session")
    
    success = delete_session(session_id)
    
    if not success:
        return server_error_response("Failed to delete session")
    
    return success_response({
        'success': True,
        'message': 'Session deleted successfully',
        'session_id': session_id
    })
