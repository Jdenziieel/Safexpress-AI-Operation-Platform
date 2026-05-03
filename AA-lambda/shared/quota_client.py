"""
Quota Client - HTTP client for Token Quota Service integration

This module provides async and sync clients for:
1. Checking quota before LLM operations
2. Reporting usage after LLM operations

Copied from token-quota-service/quota_client.py
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


class UserDeactivatedException(Exception):
    """Raised when user account has been deactivated."""
    def __init__(self, message: str = "User account is deactivated", user_id: str = None):
        self.message = message
        self.user_id = user_id
        super().__init__(self.message)


class QuotaClient:
    """
    Async HTTP client for Token Quota Service.
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
        
        Returns:
            True if quota is available, False otherwise
        
        Raises:
            QuotaExceededException: If quota exceeded and raise_on_exceed=True
            UserDeactivatedException: If user account is deactivated (404)
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
            
            # Check for 404 - user not found (deactivated)
            if response.status_code == 404:
                raise UserDeactivatedException(
                    message="Your account has been deactivated. Please contact an administrator.",
                    user_id=user_id
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
            print(f" Failed to report usage: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_balance(self, user_id: str) -> Dict[str, Any]:
        """Get current quota balance for a user."""
        try:
            response = await self.client.get(
                f"{self.base_url}/quota/balance/{user_id}"
            )
            response.raise_for_status()
            return response.json()
            
        except httpx.RequestError as e:
            print(f" Failed to get balance: {e}")
            return {"error": str(e)}


# Singleton instance
_quota_client: Optional[QuotaClient] = None


def get_quota_client() -> QuotaClient:
    """Get singleton quota client instance."""
    global _quota_client
    if _quota_client is None:
        _quota_client = QuotaClient()
    return _quota_client
