"""JWT middleware for authentication using external authentication server tokens."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from config import Config
from typing import Optional

security = HTTPBearer()

def decode_jwt(token: str) -> dict:
    """
    Decode JWT token without raising exceptions.
    Useful for optional authentication scenarios.
    
    Args:
        token: JWT token string
        
    Returns:
        dict: Decoded token payload, or empty dict if invalid
    """
    try:
        payload = jwt.decode(
            token,
            Config.JWT_SECRET_KEY,
            algorithms=["HS256"]
        )
        return payload
    except Exception as e:
        print(f"[JWT] Failed to decode token: {str(e)}")
        return {}

def verify_jwt_token(token: str) -> dict:
    """
    Verify JWT token from external authentication server using shared secret key.
    
    Args:
        token: JWT token string
        
    Returns:
        dict: Decoded token payload containing user information
        
    Raises:
        HTTPException: If token is invalid or verification fails
    """
    try:
        print(f"[JWT DEBUG] Attempting to decode token with HS256 algorithm...")
        
        # Decode and verify the JWT token using the shared secret key
        payload = jwt.decode(
            token,
            Config.JWT_SECRET_KEY,
            algorithms=["HS256"]  # Most common algorithm for JWT
        )
        
        print(f"[JWT DEBUG] Token decoded successfully. Payload keys: {list(payload.keys())}")
        print(f"[JWT DEBUG] Full payload: {payload}")
        
        # Extract user_id from 'sub' claim (standard JWT) or 'user_id' claim (Django SimpleJWT)
        user_id = payload.get("sub") or payload.get("user_id")
        if not user_id:
            print(f"[JWT DEBUG] ERROR: Token missing 'sub' or 'user_id' claim. Available claims: {list(payload.keys())}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing user ID in token (sub or user_id claim)"
            )
        
        print(f"[JWT] Authenticated user: {user_id}")
        return payload
        
    except JWTError as e:
        print(f"[JWT] Authentication failed: {e}")
        print(f"[JWT DEBUG] Error type: {type(e).__name__}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    FastAPI dependency to extract and verify JWT token from request headers.
    
    Usage:
        @router.get("/protected")
        async def protected_route(current_user: dict = Depends(get_current_user)):
            user_id = current_user["sub"]
            ...
    
    Args:
        credentials: HTTP Bearer token from Authorization header
        
    Returns:
        dict: Decoded token payload with user information
    """
    token = credentials.credentials
    print(f"[JWT DEBUG] Received token: {token[:50]}..." if len(token) > 50 else f"[JWT DEBUG] Received token: {token}")
    print(f"[JWT DEBUG] Using secret key: {Config.JWT_SECRET_KEY[:10]}..." if Config.JWT_SECRET_KEY else "[JWT DEBUG] NO SECRET KEY!")
    return verify_jwt_token(token)

async def get_user_id(current_user: dict = Depends(get_current_user)) -> str:
    """
    Helper dependency to extract just the user_id from the token.
    Uses 'user_id' claim which contains the unique UUID from auth_user table.
    Falls back to 'sub' for backwards compatibility.
    
    Usage:
        @router.get("/protected")
        async def protected_route(user_id: str = Depends(get_user_id)):
            ...
    """
    user_id = current_user.get("user_id") or current_user.get("sub")
    return str(user_id) if user_id is not None else None
