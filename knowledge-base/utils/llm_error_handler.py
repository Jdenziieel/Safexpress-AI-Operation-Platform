"""
LLM Error Handler - Universal error handling for OpenAI/LangChain calls

This module provides standardized error classification and user-friendly messages
for LLM-related errors including:
- Rate limits (429)
- Quota/billing exceeded
- API outages/connection errors
- Authentication errors

Usage:
    from utils.llm_error_handler import handle_llm_error, LLMError, LLMErrorType
    
    try:
        response = client.chat.completions.create(...)
    except Exception as e:
        llm_error = handle_llm_error(e)
        raise HTTPException(status_code=llm_error.status_code, detail=llm_error.to_dict())
"""

from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass
import traceback


class LLMErrorType(str, Enum):
    """Types of LLM errors for frontend display"""
    RATE_LIMIT = "rate_limit"
    QUOTA_EXCEEDED = "quota_exceeded"
    SERVICE_UNAVAILABLE = "service_unavailable"
    AUTHENTICATION = "authentication"
    INVALID_REQUEST = "invalid_request"
    CONTEXT_LENGTH = "context_length"
    UNKNOWN = "unknown"


@dataclass
class LLMError:
    """Structured LLM error for consistent API responses"""
    error_type: LLMErrorType
    title: str
    message: str
    user_message: str
    status_code: int
    retry_after: Optional[int] = None
    details: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response"""
        return {
            "error": True,
            "error_type": self.error_type.value,
            "title": self.title,
            "message": self.message,
            "user_message": self.user_message,
            "status_code": self.status_code,
            "retry_after": self.retry_after,
            "details": self.details,
            "is_llm_error": True  # Flag for frontend to show LLM error modal
        }


# Error messages for each type
ERROR_MESSAGES = {
    LLMErrorType.RATE_LIMIT: {
        "title": "Too Many Requests",
        "message": "Our AI service is receiving too many requests right now.",
        "user_message": "Please wait a moment and try again. The AI service is experiencing high demand."
    },
    LLMErrorType.QUOTA_EXCEEDED: {
        "title": "AI Service Quota Exceeded",
        "message": "The AI service billing quota has been reached.",
        "user_message": "The AI service is temporarily unavailable due to quota limits. Please contact your administrator or try again later."
    },
    LLMErrorType.SERVICE_UNAVAILABLE: {
        "title": "AI Service Unavailable",
        "message": "Our AI service provider is experiencing issues.",
        "user_message": "The AI service is temporarily unavailable. Please try again in a few minutes. If the issue persists, contact support."
    },
    LLMErrorType.AUTHENTICATION: {
        "title": "AI Service Authentication Error",
        "message": "There was an issue authenticating with the AI service.",
        "user_message": "Unable to connect to the AI service. Please contact your administrator."
    },
    LLMErrorType.INVALID_REQUEST: {
        "title": "Invalid Request",
        "message": "The request to the AI service was invalid.",
        "user_message": "There was an issue processing your request. Please try rephrasing your message."
    },
    LLMErrorType.CONTEXT_LENGTH: {
        "title": "Message Too Long",
        "message": "The conversation context exceeded the AI model's limit.",
        "user_message": "Your conversation has become too long. Please start a new chat session."
    },
    LLMErrorType.UNKNOWN: {
        "title": "AI Service Error",
        "message": "An unexpected error occurred with the AI service.",
        "user_message": "Something went wrong with the AI service. Please try again later."
    }
}


def handle_llm_error(exception: Exception, context: str = None) -> LLMError:
    """
    Handle and classify LLM-related exceptions.
    
    Args:
        exception: The exception that was raised
        context: Optional context about where the error occurred
        
    Returns:
        LLMError with structured error information
    """
    error_str = str(exception).lower()
    error_type_str = type(exception).__name__
    
    print(f"🔴 LLM Error: {error_type_str}: {exception}")
    if context:
        print(f"   Context: {context}")
    
    # Check for OpenAI-specific errors
    # openai.RateLimitError
    if "ratelimiterror" in error_type_str.lower() or "rate_limit" in error_str or "rate limit" in error_str:
        error_type = LLMErrorType.RATE_LIMIT
        status_code = 429
        retry_after = _extract_retry_after(exception)
        
    # openai.InsufficientQuotaError or billing issues
    elif ("insufficientquotaerror" in error_type_str.lower() or 
          "insufficient_quota" in error_str or 
          "quota" in error_str and "exceeded" in error_str or
          "billing" in error_str or
          "exceeded your current quota" in error_str or
          "you exceeded" in error_str):
        error_type = LLMErrorType.QUOTA_EXCEEDED
        status_code = 402  # Payment Required
        retry_after = None
        
    # openai.APIConnectionError or service unavailable
    elif ("apiconnectionerror" in error_type_str.lower() or 
          "connection" in error_str and ("error" in error_str or "refused" in error_str or "timeout" in error_str) or
          "service unavailable" in error_str or
          "502" in error_str or "503" in error_str or "504" in error_str or
          "bad gateway" in error_str or
          "temporarily unavailable" in error_str):
        error_type = LLMErrorType.SERVICE_UNAVAILABLE
        status_code = 503
        retry_after = 60  # Suggest retry in 1 minute
        
    # openai.AuthenticationError
    elif ("authenticationerror" in error_type_str.lower() or 
          "authentication" in error_str or 
          "api key" in error_str or
          "invalid api" in error_str or
          "401" in error_str or
          "unauthorized" in error_str):
        error_type = LLMErrorType.AUTHENTICATION
        status_code = 401
        retry_after = None
        
    # openai.BadRequestError (invalid request)
    elif ("badrequesterror" in error_type_str.lower() or 
          "invalid_request" in error_str or
          "400" in error_str and "bad request" in error_str):
        error_type = LLMErrorType.INVALID_REQUEST
        status_code = 400
        retry_after = None
        
    # Context length exceeded
    elif ("context_length" in error_str or 
          "maximum context length" in error_str or
          "token limit" in error_str or
          "tokens. this is more than" in error_str):
        error_type = LLMErrorType.CONTEXT_LENGTH
        status_code = 400
        retry_after = None
        
    else:
        error_type = LLMErrorType.UNKNOWN
        status_code = 500
        retry_after = None
    
    # Get error messages for this type
    messages = ERROR_MESSAGES[error_type]
    
    # Build detailed message for logging
    details = f"{error_type_str}: {exception}"
    if context:
        details = f"{context} - {details}"
    
    return LLMError(
        error_type=error_type,
        title=messages["title"],
        message=messages["message"],
        user_message=messages["user_message"],
        status_code=status_code,
        retry_after=retry_after,
        details=details
    )


def _extract_retry_after(exception: Exception) -> Optional[int]:
    """Extract retry-after time from rate limit exceptions."""
    error_str = str(exception)
    
    # Try to find retry time in the error message
    import re
    
    # Look for patterns like "try again in 20s" or "retry after 20 seconds"
    patterns = [
        r'try again in (\d+)\s*(?:s|sec|second)',
        r'retry after (\d+)\s*(?:s|sec|second)',
        r'wait (\d+)\s*(?:s|sec|second)',
        r'in (\d+)s',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, error_str.lower())
        if match:
            return int(match.group(1))
    
    # Default retry time for rate limits
    return 30


def is_llm_error(exception: Exception) -> bool:
    """
    Check if an exception is an LLM-related error.
    
    Args:
        exception: The exception to check
        
    Returns:
        True if it's an LLM error that should be handled specially
    """
    error_type_str = type(exception).__name__.lower()
    error_str = str(exception).lower()
    
    llm_indicators = [
        "openai",
        "ratelimit",
        "quota",
        "apiconnection",
        "authentication",
        "badrequesterror",
        "context_length",
        "gpt",
        "chatcompletion",
        "langchain"
    ]
    
    return any(indicator in error_type_str or indicator in error_str for indicator in llm_indicators)


# Convenience decorator for LLM operations
def handle_llm_errors(context: str = None):
    """
    Decorator to wrap LLM operations with error handling.
    
    Usage:
        @handle_llm_errors(context="chat completion")
        def generate_response(prompt):
            return client.chat.completions.create(...)
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                llm_error = handle_llm_error(e, context)
                # Re-raise as a structured exception
                raise LLMServiceException(llm_error)
        return wrapper
    return decorator


class LLMServiceException(Exception):
    """Exception wrapper for LLM errors with structured data."""
    def __init__(self, llm_error: LLMError):
        self.llm_error = llm_error
        super().__init__(llm_error.user_message)
    
    def to_dict(self) -> Dict[str, Any]:
        return self.llm_error.to_dict()
    
    @property
    def status_code(self) -> int:
        return self.llm_error.status_code
