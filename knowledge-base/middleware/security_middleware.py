"""
Security middleware for rate limiting and request validation.
"""
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from typing import Optional, Dict
import time
from collections import defaultdict
import threading

class RateLimiter:
    """
    Simple in-memory rate limiter using sliding window algorithm.
    For production, consider using Redis-backed rate limiter.
    """
    
    def __init__(self):
        self.requests: Dict[str, list] = defaultdict(list)
        self.lock = threading.Lock()
        
    def is_allowed(
        self, 
        identifier: str, 
        max_requests: int, 
        window_seconds: int
    ) -> tuple[bool, Optional[int]]:
        """
        Check if request is allowed based on rate limit.
        
        Args:
            identifier: Unique identifier (IP address or user ID)
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds
            
        Returns:
            Tuple of (is_allowed, retry_after_seconds)
        """
        with self.lock:
            current_time = time.time()
            window_start = current_time - window_seconds
            
            # Clean old requests outside the window
            self.requests[identifier] = [
                req_time for req_time in self.requests[identifier]
                if req_time > window_start
            ]
            
            # Check if limit exceeded
            if len(self.requests[identifier]) >= max_requests:
                # Calculate retry after time
                oldest_request = min(self.requests[identifier])
                retry_after = int(oldest_request + window_seconds - current_time) + 1
                return False, retry_after
            
            # Add current request
            self.requests[identifier].append(current_time)
            return True, None
    
    def cleanup_old_entries(self, max_age_seconds: int = 3600):
        """Periodically cleanup old entries to prevent memory leak"""
        with self.lock:
            current_time = time.time()
            keys_to_delete = []
            
            for identifier, timestamps in self.requests.items():
                # Remove entries older than max_age
                recent = [t for t in timestamps if current_time - t < max_age_seconds]
                
                if recent:
                    self.requests[identifier] = recent
                else:
                    keys_to_delete.append(identifier)
            
            # Delete empty entries
            for key in keys_to_delete:
                del self.requests[key]


# Global rate limiter instance
rate_limiter = RateLimiter()


# Rate limit configurations
RATE_LIMITS = {
    "default": {"requests": 100, "window": 60},        # 100 req/minute
    "auth": {"requests": 5, "window": 60},             # 5 req/minute (login)
    "chat": {"requests": 60, "window": 60},            # 60 req/minute (thread switching + queries)
    "upload": {"requests": 20, "window": 3600},        # 20 req/hour (storage protection)
    "query": {"requests": 30, "window": 60},           # 30 req/minute (KB queries)
}


async def rate_limit_middleware(request: Request, call_next):
    """
    Middleware to enforce rate limiting on all endpoints.
    """
    # Get client identifier (IP address or user ID from token)
    client_ip = request.client.host if request.client else "unknown"
    user_id = None
    
    # Try to get user_id from request state (set by JWT middleware)
    if hasattr(request.state, "user"):
        user_id = request.state.user.get("user_id") or request.state.user.get("sub")
    
    # Use user_id if authenticated, otherwise use IP
    identifier = f"user:{user_id}" if user_id else f"ip:{client_ip}"
    
    # Determine rate limit based on path
    path = request.url.path
    limit_config = RATE_LIMITS["default"]
    
    if "/chat/" in path:
        limit_config = RATE_LIMITS["chat"]
    elif "/upload" in path or "/parse-pdf" in path:
        limit_config = RATE_LIMITS["upload"]
    elif "/query" in path:
        limit_config = RATE_LIMITS["query"]
    
    # Check rate limit
    is_allowed, retry_after = rate_limiter.is_allowed(
        identifier,
        limit_config["requests"],
        limit_config["window"]
    )
    
    if not is_allowed:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error": "Rate limit exceeded",
                "message": f"Too many requests. Please try again in {retry_after} seconds.",
                "retry_after": retry_after
            },
            headers={"Retry-After": str(retry_after)}
        )
    
    # Add rate limit info to response headers
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(limit_config["requests"])
    response.headers["X-RateLimit-Window"] = str(limit_config["window"])
    
    return response


async def security_headers_middleware(request: Request, call_next):
    """
    Add security headers to all responses.
    These headers protect against common web vulnerabilities and are safe to use with JWT authentication.
    They operate at the browser level and don't interfere with API authentication.
    """
    response = await call_next(request)
    
    # Basic security headers (safe for all environments)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    # HSTS - only in production with HTTPS
    # response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    
    # CSP - Permissive for development (allows connections to any origin)
    # This won't block your frontend or API calls
    # For production, tighten this based on your actual needs
    response.headers["Content-Security-Policy"] = "default-src * 'unsafe-inline' 'unsafe-eval'; img-src * data: blob:; connect-src *"
    
    return response


def validate_string_length(value: str, max_length: int, field_name: str) -> str:
    """
    Validate string length to prevent abuse.
    
    Args:
        value: String to validate
        max_length: Maximum allowed length
        field_name: Name of field for error message
        
    Returns:
        Validated string
        
    Raises:
        HTTPException: If validation fails
    """
    if len(value) > max_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} exceeds maximum length of {max_length} characters"
        )
    return value


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to prevent directory traversal attacks.
    
    Args:
        filename: Original filename
        
    Returns:
        Sanitized filename
    """
    import re
    import os
    
    # Remove path components
    filename = os.path.basename(filename)
    
    # Remove dangerous characters
    filename = re.sub(r'[^\w\s\-\.]', '', filename)
    
    # Limit length
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:250] + ext
    
    return filename


def validate_file_type(filename: str, allowed_types: list[str]) -> bool:
    """
    Validate file type based on extension.
    
    Args:
        filename: File name
        allowed_types: List of allowed extensions (e.g., ['.pdf', '.docx'])
        
    Returns:
        True if valid, False otherwise
    """
    import os
    _, ext = os.path.splitext(filename.lower())
    return ext in allowed_types


# Input validation constants
MAX_MESSAGE_LENGTH = 10000        # 10K characters for chat messages
MAX_SESSION_TITLE_LENGTH = 200    # 200 characters for session titles
MAX_FILENAME_LENGTH = 255         # 255 characters for filenames
MAX_QUERY_LENGTH = 5000           # 5K characters for search queries
MAX_FILE_SIZE_MB = 10             # 10 MB for file uploads
ALLOWED_FILE_TYPES = ['.pdf']     # Only PDF files allowed
