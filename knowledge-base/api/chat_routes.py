# api/chat_routes.py
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any, List
from services.chat_service import ChatService
from middleware.jwt_middleware import get_current_user
from middleware.security_middleware import (
    validate_string_length,
    MAX_MESSAGE_LENGTH,
    MAX_SESSION_TITLE_LENGTH
)
from utils.llm_error_handler import LLMServiceException

chat_router = APIRouter(prefix='/chat', tags=['chat'])
chat_service = ChatService()


def extract_user_id(current_user: dict) -> Optional[str]:
    """
    Extract user_id from JWT payload.
    Prioritizes 'uuid' (the UUID from auth_user table) for quota/tracking,
    falls back to 'user_id' or 'sub' for backwards compatibility.
    """
    # Prefer uuid for quota service (matches Django User model UUID)
    user_id = current_user.get("uuid") or current_user.get("user_id") or current_user.get("sub")
    return str(user_id) if user_id is not None else None

# Request models with validation
class CreateSessionRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=MAX_SESSION_TITLE_LENGTH)
    initial_message: Optional[str] = Field(None, max_length=MAX_MESSAGE_LENGTH)
    options: Optional[Dict[str, Any]] = Field(default_factory=dict)
    
    @field_validator('title')
    @classmethod
    def validate_title(cls, v):
        if v is not None and v.strip():
            return validate_string_length(v.strip(), MAX_SESSION_TITLE_LENGTH, "title")
        return v
    
    @field_validator('initial_message')
    @classmethod
    def validate_message(cls, v):
        if v is not None and v.strip():
            return validate_string_length(v.strip(), MAX_MESSAGE_LENGTH, "message")
        return v

class SendMessageRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)
    options: Optional[Dict[str, Any]] = Field(default_factory=dict)
    
    @field_validator('message')
    @classmethod
    def validate_message(cls, v):
        if not v or not v.strip():
            raise ValueError("Message cannot be empty")
        return validate_string_length(v.strip(), MAX_MESSAGE_LENGTH, "message")
    
    @field_validator('session_id')
    @classmethod
    def validate_session_id(cls, v):
        if not v or not v.strip():
            raise ValueError("Session ID cannot be empty")
        return v.strip()

class UpdateSessionTitleRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=MAX_SESSION_TITLE_LENGTH)
    
    @field_validator('title')
    @classmethod
    def validate_title(cls, v):
        if not v or not v.strip():
            raise ValueError("Title cannot be empty")
        return validate_string_length(v.strip(), MAX_SESSION_TITLE_LENGTH, "title")

@chat_router.post('/session/new')
async def create_session(
    request: CreateSessionRequest,
    current_user: dict = Depends(get_current_user)
):
    """Create a new chat session"""
    try:
        user_id = extract_user_id(current_user)
        print(f"[ChatRoutes] Creating session for user_id: {user_id}")
        
        # Check if user is active before creating session
        import os
        from utils.quota_client import QuotaClientSync, UserDeactivatedException
        quota_enabled = os.getenv("QUOTA_ENABLED", "true").lower() == "true"
        if quota_enabled and user_id:
            try:
                quota_client = QuotaClientSync()
                print(f"[ChatRoutes] Checking quota for user_id: {user_id}")
                quota_client.check(user_id=user_id, estimated_tokens=0, raise_on_exceed=False)
                print(f"[ChatRoutes] ✅ User {user_id} is active")
            except UserDeactivatedException as e:
                print(f"[ChatRoutes] ❌ User {user_id} is DEACTIVATED")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: {e.message}"
                )
            except Exception as e:
                print(f"[ChatRoutes] ⚠️ Quota check error: {e} - allowing operation")
                pass  # Allow if quota service is unavailable
        
        # Create session
        session = chat_service.create_session(user_id, request.title)
        
        # Process initial message if provided
        if request.initial_message:
            chat_service.process_message(
                session_id=session['session_id'],
                user_message=request.initial_message,
                options=request.options or {},
                user_id=user_id
            )
        
        return {
            'success': True,
            'session_id': session['session_id'],
            'created_at': session['created_at'],
            'message': 'Session created successfully'
        }
        
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        print(f"Error creating session: {e}")
        import traceback
        traceback.print_exc()
        
        # Check if this is an access denied error (deactivated user)
        if "Access denied" in error_msg or "deactivated" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=error_msg
            )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_msg
        )


@chat_router.post('/message')
async def send_message(
    request: SendMessageRequest,
    current_user: dict = Depends(get_current_user)
):
    """Send a message in a chat session"""
    try:
        user_id = extract_user_id(current_user)
        
        if not request.session_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='session_id is required'
            )
        
        if not request.message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='message is required'
            )
        
        # Process message
        response = chat_service.process_message(
            session_id=request.session_id,
            user_message=request.message,
            options=request.options or {},
            user_id=user_id
        )
        
        return {
            'success': True,
            **response
        }
        
    except HTTPException:
        raise
    except LLMServiceException as llm_ex:
        # Return LLM error with structured response for frontend popup
        print(f"🔴 LLM Error in chat: {llm_ex}")
        return JSONResponse(
            status_code=llm_ex.status_code,
            content={
                'success': False,
                **llm_ex.to_dict()
            }
        )
    except Exception as e:
        error_msg = str(e)
        print(f"Error processing message: {e}")
        import traceback
        traceback.print_exc()
        
        # Check if this is an access denied error (deactivated user)
        if "Access denied" in error_msg or "deactivated" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=error_msg
            )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_msg
        )


@chat_router.get('/session/{session_id}/history')
async def get_session_history(
    session_id: str,
    limit: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get session history with messages"""
    try:
        user_id = extract_user_id(current_user)
        
        result = chat_service.get_session_history(session_id, limit, user_id)
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Session not found or access denied'
            )
        
        return {
            'success': True,
            'session_id': session_id,
            'session': result['session'],
            'messages': result['messages'],
            'total_messages': len(result['messages'])
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting session history: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@chat_router.get('/sessions')
async def get_user_sessions(
    limit: int = 20,
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    """Get all sessions for a user"""
    try:
        user_id = extract_user_id(current_user)
        
        result = chat_service.get_user_sessions(user_id, limit, offset)
        
        return {
            'success': True,
            **result
        }
        
    except Exception as e:
        print(f"Error getting user sessions: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@chat_router.get('/session/{session_id}')
async def get_session(
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get session details"""
    try:
        user_id = extract_user_id(current_user)
        result = chat_service.get_session_history(session_id, limit=0, user_id=user_id)
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Session not found or access denied'
            )
        
        return {
            'success': True,
            **result['session']
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@chat_router.patch('/session/{session_id}/title')
async def update_session_title(
    session_id: str,
    request: UpdateSessionTitleRequest,
    current_user: dict = Depends(get_current_user)
):
    """Update session title"""
    try:
        user_id = extract_user_id(current_user)
        
        # Validate ownership
        session = chat_service.chat_db.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        if session.get('user_id') != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied - you don't own this session"
            )
        
        # Update title
        success = chat_service.chat_db.update_session_title(session_id, request.title)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update session title"
            )
        
        return {
            'success': True,
            'message': 'Session title updated successfully',
            'title': request.title
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating session title: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@chat_router.delete('/session/{session_id}')
async def delete_session(
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a session"""
    try:
        user_id = extract_user_id(current_user)
        success = chat_service.delete_session(session_id, user_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Session not found, already deleted, or access denied'
            )
        
        return {
            'success': True,
            'message': 'Session deleted successfully'
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@chat_router.get('/quota')
async def get_user_quota(
    current_user: dict = Depends(get_current_user)
):
    """
    Get current user's token quota balance.
    
    Returns quota information including:
    - remaining_tokens: Tokens left in monthly quota
    - monthly_limit: Total monthly limit
    - current_usage: Tokens used this month
    - percentage_used: Percentage of quota consumed
    - tier: User's quota tier (free, pro, enterprise)
    - resets_at: When the quota resets
    """
    try:
        from utils.quota_client import QuotaClientSync
        import os
        
        user_id = extract_user_id(current_user)
        
        # Check if quota service is enabled
        quota_enabled = os.getenv("QUOTA_ENABLED", "true").lower() == "true"
        if not quota_enabled:
            return {
                'success': True,
                'quota_enabled': False,
                'message': 'Quota tracking is disabled'
            }
        
        quota_client = QuotaClientSync()
        
        try:
            import httpx
            with httpx.Client(timeout=5.0) as client:
                response = client.get(
                    f"{quota_client.base_url}/quota/balance/{user_id}"
                )
                response.raise_for_status()
                data = response.json()
                
                return {
                    'success': True,
                    'quota_enabled': True,
                    'user_id': user_id,
                    'remaining_tokens': data.get('remaining_tokens', 0),
                    'monthly_limit': data.get('monthly_limit', 0),
                    'current_usage': data.get('current_usage', 0),
                    'percentage_used': data.get('percentage_used', 0),
                    'tier': data.get('tier', 'free'),
                    'resets_at': data.get('resets_at'),
                    'warning': data.get('warning', False),
                    'warning_message': data.get('warning_message')
                }
        except Exception as e:
            # Quota service unavailable
            return {
                'success': True,
                'quota_enabled': True,
                'quota_service_available': False,
                'message': f'Quota service unavailable: {str(e)}'
            }
            
    except Exception as e:
        print(f"Error getting quota: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@chat_router.websocket('/ws/{session_id}/stream')
async def websocket_stream_endpoint(
    websocket,
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    WebSocket endpoint for streaming chat responses.
    
    Message should be passed as query parameter: ws://localhost:9009/chat/ws/session123/stream?message=hello
    
    Receives:
        - Streaming tokens as JSON: {"type": "token", "content": "..."}
        - Completion as JSON: {"type": "done", "content": "...", "tokens": 150}
        - Errors as JSON: {"type": "error", "content": "..."}
    """
    from fastapi import WebSocketException
    
    try:
        # Check JWT authentication
        user_id = extract_user_id(current_user)
        print(f"[WebSocket] Stream connection from user_id: {user_id}, session: {session_id}")
        
        # The message comes from the frontend via the query parameter
        # We need to handle the connection first
        await websocket.accept()
        
        # Get the message from the query parameter sent in the first message or from URL
        # Actually, in WebSocket, we need to receive the message after connection
        message_data = await websocket.receive_json()
        user_message = message_data.get('message')
        options = message_data.get('options', {})
        
        if not user_message:
            await websocket.send_json({"type": "error", "content": "No message provided"})
            await websocket.close(code=1000)
            return
        
        print(f"[WebSocket] Streaming response for user_message: {user_message[:50]}...")
        
        # Stream response from chat service
        for json_chunk in chat_service.stream_response(
            session_id=session_id,
            user_message=user_message,
            options=options,
            user_id=user_id
        ):
            try:
                await websocket.send_text(json_chunk)
            except Exception as send_error:
                print(f"[WebSocket] Error sending chunk: {send_error}")
                break
        
        print(f"[WebSocket] Streaming complete for session: {session_id}")
        await websocket.close(code=1000)
        
    except HTTPException as http_ex:
        print(f"[WebSocket] HTTP Exception: {http_ex}")
        try:
            await websocket.send_json({"type": "error", "content": http_ex.detail})
            await websocket.close(code=1008)
        except:
            pass
    except Exception as e:
        print(f"[WebSocket] Error in stream endpoint: {e}")
        import traceback
        traceback.print_exc()
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
            await websocket.close(code=1011)
        except:
            pass
