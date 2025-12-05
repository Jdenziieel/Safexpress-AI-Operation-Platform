"""
Quota Client - HTTP client for services to interact with Token Quota Service

This module provides a simple async client for:
1. Checking quota before LLM operations
2. Reporting usage after LLM operations

Usage in other services:
    from quota_client import QuotaClient
    
    quota = QuotaClient()
    
    # Before LLM call
    if not await quota.check(user_id, estimated_tokens=1000):
        raise QuotaExceededException()
    
    # Make LLM call...
    
    # After LLM call
    await quota.report(
        user_id=user_id,
        service="knowledge-base",
        model="gpt-4o",
        input_tokens=500,
        output_tokens=200,
        operation="chat"
    )
"""

import httpx
from typing import Optional, Dict, Any
import os


class QuotaExceededException(Exception):
    """Raised when user has exceeded their token quota."""
    def __init__(self, message: str = "Token quota exceeded", remaining: int = 0, limit: int = 0):
        self.message = message
        self.remaining = remaining
        self.limit = limit
        super().__init__(self.message)


class QuotaClient:
    """
    Async HTTP client for Token Quota Service.
    
    Can be configured via environment variable QUOTA_SERVICE_URL
    or by passing url to constructor.
    """
    
    def __init__(self, url: str = None, timeout: float = 5.0):
        self.base_url = url or os.getenv("QUOTA_SERVICE_URL", "http://localhost:8011")
        self.timeout = timeout
        self._client = None
    
    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client
    
    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def check(
        self,
        user_id: str,
        estimated_tokens: int = 0,
        service: str = None,
        operation: str = None,
        raise_on_exceed: bool = True
    ) -> bool:
        """
        Check if user has sufficient quota for an operation.
        
        Args:
            user_id: Unique user identifier
            estimated_tokens: Estimated tokens for the operation
            service: Service making the request (for logging)
            operation: Type of operation (for logging)
            raise_on_exceed: If True, raises QuotaExceededException when quota exceeded
        
        Returns:
            True if quota is available, False otherwise
        
        Raises:
            QuotaExceededException: If quota exceeded and raise_on_exceed=True
        """
        try:
            response = await self.client.post(
                f"{self.base_url}/quota/check",
                json={
                    "user_id": user_id,
                    "estimated_tokens": estimated_tokens,
                    "service": service,
                    "operation": operation
                }
            )
            response.raise_for_status()
            data = response.json()
            
            if not data["allowed"] and raise_on_exceed:
                raise QuotaExceededException(
                    message=f"Token quota exceeded. {data['remaining_tokens']} tokens remaining of {data['monthly_limit']} monthly limit.",
                    remaining=data["remaining_tokens"],
                    limit=data["monthly_limit"]
                )
            
            return data["allowed"]
            
        except httpx.RequestError as e:
            # If quota service is unavailable, fail open (allow operation)
            # In production, you might want to fail closed instead
            print(f"⚠️ Quota service unavailable: {e}. Allowing operation.")
            return True
    
    async def report(
        self,
        user_id: str,
        service: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        operation: str = "unknown",
        cost_usd: float = None,
        request_id: str = None,
        session_id: str = None,
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Report token usage after an LLM operation.
        
        Args:
            user_id: Unique user identifier
            service: Service that used tokens (supervisor, knowledge-base, etc.)
            model: LLM model used (gpt-4o, gpt-4o-mini, etc.)
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            operation: Type of operation (chat, embedding, planning, etc.)
            cost_usd: Estimated cost (calculated if not provided)
            request_id: Request correlation ID
            session_id: Session ID (should be hashed for privacy)
            metadata: Additional metadata
        
        Returns:
            Response with new_usage and remaining tokens
        """
        try:
            response = await self.client.post(
                f"{self.base_url}/quota/report",
                json={
                    "user_id": user_id,
                    "service": service,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "operation": operation,
                    "cost_usd": cost_usd,
                    "request_id": request_id,
                    "session_id": session_id,
                    "metadata": metadata
                }
            )
            response.raise_for_status()
            return response.json()
            
        except httpx.RequestError as e:
            # Log error but don't fail the operation
            print(f"⚠️ Failed to report usage: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_balance(self, user_id: str) -> Dict[str, Any]:
        """
        Get current quota balance for a user.
        
        Returns:
            Quota balance info including remaining tokens, limit, percentage used
        """
        try:
            response = await self.client.get(
                f"{self.base_url}/quota/balance/{user_id}"
            )
            response.raise_for_status()
            return response.json()
            
        except httpx.RequestError as e:
            print(f"⚠️ Failed to get balance: {e}")
            return {"error": str(e)}


# ==============================================================================
# SYNCHRONOUS WRAPPER (for non-async contexts)
# ==============================================================================

class QuotaClientSync:
    """
    Synchronous wrapper for QuotaClient.
    
    Use this in non-async contexts like traditional Flask apps.
    """
    
    def __init__(self, url: str = None, timeout: float = 5.0):
        self.base_url = url or os.getenv("QUOTA_SERVICE_URL", "http://localhost:8011")
        self.timeout = timeout
    
    def check(
        self,
        user_id: str,
        estimated_tokens: int = 0,
        raise_on_exceed: bool = True
    ) -> bool:
        """Synchronous quota check."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/quota/check",
                    json={
                        "user_id": user_id,
                        "estimated_tokens": estimated_tokens
                    }
                )
                response.raise_for_status()
                data = response.json()
                
                if not data["allowed"] and raise_on_exceed:
                    raise QuotaExceededException(
                        remaining=data["remaining_tokens"],
                        limit=data["monthly_limit"]
                    )
                
                return data["allowed"]
                
        except httpx.RequestError:
            return True  # Fail open
    
    def report(
        self,
        user_id: str,
        service: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        operation: str = "unknown"
    ) -> Dict[str, Any]:
        """Synchronous usage report."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/quota/report",
                    json={
                        "user_id": user_id,
                        "service": service,
                        "model": model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "operation": operation
                    }
                )
                response.raise_for_status()
                return response.json()
                
        except httpx.RequestError as e:
            return {"success": False, "error": str(e)}


# ==============================================================================
# DECORATOR FOR EASY INTEGRATION
# ==============================================================================

def with_quota_check(
    service: str,
    operation: str,
    estimate_tokens_fn=None
):
    """
    Decorator to add quota check to LLM-calling functions.
    
    Usage:
        @with_quota_check("knowledge-base", "chat")
        async def process_chat(user_id: str, query: str):
            # LLM call here
            return response
    
    The decorated function MUST have 'user_id' as first argument.
    """
    def decorator(func):
        async def wrapper(user_id: str, *args, **kwargs):
            client = QuotaClient()
            
            # Estimate tokens if function provided
            estimated = 1000  # Default estimate
            if estimate_tokens_fn:
                estimated = estimate_tokens_fn(*args, **kwargs)
            
            # Check quota
            await client.check(
                user_id=user_id,
                estimated_tokens=estimated,
                service=service,
                operation=operation,
                raise_on_exceed=True
            )
            
            # Call the actual function
            result = await func(user_id, *args, **kwargs)
            
            # If result has usage info, report it
            if hasattr(result, 'usage'):
                await client.report(
                    user_id=user_id,
                    service=service,
                    operation=operation,
                    model=getattr(result, 'model', 'unknown'),
                    input_tokens=result.usage.prompt_tokens,
                    output_tokens=result.usage.completion_tokens
                )
            
            await client.close()
            return result
        
        return wrapper
    return decorator
