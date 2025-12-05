"""
Token Tracker - OpenAI Token and Cost Tracking

Provides utilities to track token usage and estimate costs for OpenAI API calls.
"""

from typing import Optional, Dict, Any
from functools import wraps
import time


# Token pricing per 1K tokens (as of late 2024)
MODEL_PRICING = {
    "gpt-4o": {"input": 0.0025, "output": 0.01},          # $2.50/1M input, $10/1M output
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},  # $0.15/1M input, $0.60/1M output
    "gpt-4": {"input": 0.03, "output": 0.06},             # $30/1M input, $60/1M output
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},       # $10/1M input, $30/1M output
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015}, # $0.50/1M input, $1.50/1M output
    "text-embedding-3-small": {"input": 0.00002, "output": 0},  # $0.02/1M tokens
    "text-embedding-3-large": {"input": 0.00013, "output": 0},  # $0.13/1M tokens
    "default": {"input": 0.01, "output": 0.03}            # Fallback pricing
}


def estimate_cost(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0
) -> float:
    """
    Estimate the cost of an API call based on token usage.
    
    Args:
        model: Model name
        input_tokens: Number of input tokens (if known)
        output_tokens: Number of output tokens (if known)
        total_tokens: Total tokens (used if input/output not provided)
    
    Returns:
        Estimated cost in USD
    """
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
    
    # If input/output are provided, use them
    if input_tokens > 0 or output_tokens > 0:
        input_cost = (input_tokens / 1000) * pricing["input"]
        output_cost = (output_tokens / 1000) * pricing["output"]
        return input_cost + output_cost
    
    # If only total_tokens is provided, estimate 60% input / 40% output split
    if total_tokens > 0:
        estimated_input = int(total_tokens * 0.6)
        estimated_output = total_tokens - estimated_input
        input_cost = (estimated_input / 1000) * pricing["input"]
        output_cost = (estimated_output / 1000) * pricing["output"]
        return input_cost + output_cost
    
    return 0.0


def extract_token_usage(response) -> Dict[str, Any]:
    """
    Extract token usage from an OpenAI API response.
    
    Args:
        response: OpenAI API response object
    
    Returns:
        Dict with input_tokens, output_tokens, total_tokens, estimated_cost_usd
    """
    try:
        usage = response.usage
        model = response.model if hasattr(response, 'model') else 'gpt-4o'
        
        input_tokens = usage.prompt_tokens if hasattr(usage, 'prompt_tokens') else 0
        output_tokens = usage.completion_tokens if hasattr(usage, 'completion_tokens') else 0
        total_tokens = usage.total_tokens if hasattr(usage, 'total_tokens') else input_tokens + output_tokens
        
        return {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": estimate_cost(model, input_tokens, output_tokens)
        }
    except Exception as e:
        print(f"[TokenTracker] Error extracting token usage: {e}")
        return {
            "model": "unknown",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0
        }


class TokenTracker:
    """
    Tracks token usage across multiple API calls.
    """
    
    def __init__(self):
        self.calls = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_tokens = 0
        self.total_cost_usd = 0.0
    
    def track(self, response, model: Optional[str] = None) -> Dict[str, Any]:
        """
        Track token usage from an API response.
        
        Args:
            response: OpenAI API response
            model: Override model name if not in response
        
        Returns:
            Token usage dict for this call
        """
        usage = extract_token_usage(response)
        
        if model:
            usage["model"] = model
            usage["estimated_cost_usd"] = estimate_cost(
                model, 
                usage["input_tokens"], 
                usage["output_tokens"]
            )
        
        self.calls.append(usage)
        self.total_input_tokens += usage["input_tokens"]
        self.total_output_tokens += usage["output_tokens"]
        self.total_tokens += usage["total_tokens"]
        self.total_cost_usd += usage["estimated_cost_usd"]
        
        return usage
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all tracked calls."""
        return {
            "call_count": len(self.calls),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "calls": self.calls
        }
    
    def reset(self):
        """Reset the tracker."""
        self.calls = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_tokens = 0
        self.total_cost_usd = 0.0


def track_openai_call(model: str = "gpt-4o"):
    """
    Decorator to track token usage for OpenAI API calls.
    
    Usage:
        @track_openai_call("gpt-4o")
        def my_function():
            response = openai.chat.completions.create(...)
            return response
    
    The decorated function should return the OpenAI response object.
    Token usage will be printed to console.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            response = func(*args, **kwargs)
            duration_ms = (time.time() - start_time) * 1000
            
            if response:
                usage = extract_token_usage(response)
                print(f"[TokenTracker] {model}: {usage['total_tokens']} tokens, ${usage['estimated_cost_usd']:.6f}, {duration_ms:.0f}ms")
            
            return response
        return wrapper
    return decorator
