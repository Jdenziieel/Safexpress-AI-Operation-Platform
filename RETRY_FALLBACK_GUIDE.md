# Retry & Fallback Strategy Guide

## 🎯 Where to Add Retries in Your Architecture

Your system has **3 layers** where retry logic should be implemented:

```
User Request → Supervisor Agent → Gmail/Docs Agent → Google API
     ↓              ↓                    ↓               ↓
  Layer 1       Layer 2             Layer 3         Layer 4
```

---

## 📍 Layer 1: Supervisor HTTP Calls to Agents (RECOMMENDED)

**Location:** `supervisor-agent/supervisor_agent.py` (orchestrator_node function, ~line 517)

**Why here?**
- ✅ Single point of retry for all agent calls
- ✅ Can implement circuit breaker pattern
- ✅ Can fallback to alternative agents
- ✅ Centralized logging and monitoring

### Implementation:

```python
# Add this at the top of supervisor_agent.py
import time
from typing import Optional

def call_agent_with_retry(
    agent_url: str,
    request_payload: dict,
    max_retries: int = 5,
    timeout: float = 180.0,
    backoff_factor: float = 2.0
) -> Optional[dict]:
    """
    Call an agent with exponential backoff retry logic.
    
    Args:
        agent_url: URL of the agent endpoint
        request_payload: JSON payload to send
        max_retries: Maximum number of retry attempts
        timeout: Request timeout in seconds
        backoff_factor: Multiplier for exponential backoff (2.0 = double each time)
    
    Returns:
        Response JSON or None if all retries failed
    """
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            print(f"🔄 Attempt {attempt + 1}/{max_retries} calling {agent_url}")
            
            with httpx.Client(timeout=timeout) as client:
                response = client.post(agent_url, json=request_payload)
                response.raise_for_status()
                result = response.json()
                
                # Check if the agent actually succeeded
                if result.get("success"):
                    print(f"✅ Agent call succeeded on attempt {attempt + 1}")
                    return result
                else:
                    # Agent returned error but HTTP was successful
                    print(f"⚠️ Agent reported error: {result.get('error')}")
                    if attempt < max_retries - 1:
                        wait_time = backoff_factor ** attempt
                        print(f"   Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    return result  # Return the error result on last attempt
                    
        except httpx.TimeoutException as e:
            last_exception = e
            print(f"⏱️ Timeout on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = backoff_factor ** attempt
                print(f"   Retrying in {wait_time}s...")
                time.sleep(wait_time)
                
        except httpx.HTTPStatusError as e:
            last_exception = e
            print(f"❌ HTTP {e.response.status_code} on attempt {attempt + 1}")
            
            # Don't retry on 4xx client errors (except 429 rate limit)
            if 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                print(f"   Client error - not retrying")
                return None
                
            if attempt < max_retries - 1:
                wait_time = backoff_factor ** attempt
                print(f"   Retrying in {wait_time}s...")
                time.sleep(wait_time)
                
        except httpx.HTTPError as e:
            last_exception = e
            print(f"❌ HTTP error on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = backoff_factor ** attempt
                print(f"   Retrying in {wait_time}s...")
                time.sleep(wait_time)
                
        except Exception as e:
            last_exception = e
            print(f"❌ Unexpected error on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = backoff_factor ** attempt
                print(f"   Retrying in {wait_time}s...")
                time.sleep(wait_time)
    
    # All retries exhausted
    print(f"💀 All {max_retries} attempts failed. Last error: {last_exception}")
    return None


# Then replace the try block in orchestrator_node (~line 517) with:
def orchestrator_node(state: SharedState) -> SharedState:
    # ... existing code ...
    
    for step_num, step in enumerate(plan_steps, start=1):
        # ... existing code to build request_payload ...
        
        # Replace the existing try block with:
        result = call_agent_with_retry(
            agent_url=agent_url,
            request_payload=request_payload,
            max_retries=3,
            timeout=180.0,
            backoff_factor=2.0
        )
        
        if result is None:
            # All retries failed
            error_msg = f"Failed to call {agent_name} after 3 attempts"
            print(f"❌ {error_msg}")
            results.append({
                "step": step_num,
                "agent": agent_name,
                "tool": tool_name,
                "status": "error",
                "error": error_msg
            })
            # Optional: break here to stop workflow, or continue to next step
            continue
        
        # Handle successful or error response
        if result.get("success"):
            # ... existing success handling code ...
            pass
        else:
            # ... existing error handling code ...
            pass
```

---

## 📍 Layer 2: Gmail Agent LangGraph Invocation (OPTIONAL)

**Location:** `gmail-agent/api.py` (execute_task function, ~line 167)

**Why here?**
- ✅ Handles LLM/LangGraph specific failures
- ✅ Can retry on LLM rate limits
- ✅ Can fallback to simpler prompts

### Implementation:

```python
# Add to gmail-agent/api.py

def invoke_agent_with_retry(
    agent,
    agent_prompt: str,
    max_retries: int = 2,
    recursion_limit: int = 10
) -> Optional[dict]:
    """
    Invoke LangGraph agent with retry logic for LLM failures.
    """
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            print(f"🤖 Invoking agent (attempt {attempt + 1}/{max_retries})")
            
            result = agent.invoke(
                {"messages": [("user", agent_prompt)]},
                config={"recursion_limit": recursion_limit}
            )
            
            print(f"✅ Agent invocation succeeded")
            return result
            
        except Exception as e:
            last_exception = e
            print(f"❌ Agent invocation failed on attempt {attempt + 1}: {str(e)}")
            
            # Check if it's a rate limit error
            if "rate limit" in str(e).lower() or "429" in str(e):
                if attempt < max_retries - 1:
                    wait_time = 5 * (attempt + 1)  # 5s, 10s
                    print(f"   Rate limited - waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    continue
            
            # Check if it's a timeout/recursion error
            elif "recursion" in str(e).lower() or "timeout" in str(e).lower():
                print(f"   Recursion/timeout error - not retrying")
                raise
            
            # Generic retry
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 1s, 2s
                print(f"   Retrying in {wait_time}s...")
                time.sleep(wait_time)
    
    print(f"💀 All agent invocation attempts failed")
    raise last_exception


# Then in execute_task function, replace the agent.invoke call:
@app.post("/execute_task", response_model=AgentTaskResponse)
async def execute_task(request: AgentTaskRequest):
    try:
        agent = create_email_agent(request.credentials_dict)
        
        # ... build agent_prompt ...
        
        # Replace direct agent.invoke with retry wrapper
        result = invoke_agent_with_retry(
            agent=agent,
            agent_prompt=agent_prompt,
            max_retries=2,
            recursion_limit=10
        )
        
        # ... rest of the code ...
```

---

## 📍 Layer 3: Gmail API Calls (CRITICAL)

**Location:** `gmail-agent/tools.py` (individual tool functions)

**Why here?**
- ✅ Handles Google API rate limits (429 errors)
- ✅ Handles transient network errors
- ✅ Most important layer for reliability

### Implementation:

```python
# Add this to gmail-agent/tools.py at the top

import time
from typing import Callable, Any
from googleapiclient.errors import HttpError

def gmail_api_call_with_retry(
    api_call: Callable,
    max_retries: int = 3,
    backoff_factor: float = 2.0
) -> Any:
    """
    Execute a Gmail API call with exponential backoff retry.
    
    Args:
        api_call: Lambda or function that executes the API call
        max_retries: Maximum retry attempts
        backoff_factor: Exponential backoff multiplier
    
    Returns:
        API call result
    """
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return api_call()
            
        except HttpError as error:
            last_exception = error
            error_code = error.resp.status
            
            # Rate limit (429) or server errors (5xx) - retry
            if error_code == 429 or error_code >= 500:
                if attempt < max_retries - 1:
                    wait_time = backoff_factor ** attempt
                    print(f"⚠️ Gmail API error {error_code}, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
            
            # Client errors (4xx except 429) - don't retry
            else:
                print(f"❌ Gmail API client error {error_code}: {error}")
                raise
                
        except Exception as e:
            last_exception = e
            print(f"❌ Unexpected error: {e}")
            if attempt < max_retries - 1:
                wait_time = backoff_factor ** attempt
                time.sleep(wait_time)
                continue
            raise
    
    # All retries exhausted
    raise last_exception


# Then wrap API calls in your tools:
def _search_emails_impl(query: str, max_results: int, credentials_dict: Dict) -> str:
    """Search emails in Gmail matching a query"""
    try:
        gmail_service = get_google_service("gmail", "v1", credentials_dict)
        
        # Wrap the API call with retry logic
        results = gmail_api_call_with_retry(
            lambda: gmail_service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
        )

        messages = results.get("messages", [])
        
        if not messages:
            return "No emails found matching query"

        # For each message, also wrap the detailed fetch
        email_list = []
        for msg in messages:
            message = gmail_api_call_with_retry(
                lambda: gmail_service.users()
                    .messages()
                    .get(userId="me", id=msg["id"])
                    .execute()
            )
            # ... rest of the code ...
```

---

## 📍 Layer 4: Advanced Patterns

### Circuit Breaker Pattern

Prevent cascading failures by temporarily stopping calls to failing services:

```python
# Add to supervisor_agent.py

from datetime import datetime, timedelta

class CircuitBreaker:
    """Circuit breaker to prevent cascading failures"""
    
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures = {}
        self.last_failure_time = {}
        self.open_circuits = set()
    
    def is_open(self, agent_name: str) -> bool:
        """Check if circuit is open for an agent"""
        if agent_name in self.open_circuits:
            # Check if timeout has passed
            if datetime.now() - self.last_failure_time[agent_name] > timedelta(seconds=self.timeout):
                print(f"🔄 Circuit breaker timeout expired for {agent_name}, trying again")
                self.open_circuits.remove(agent_name)
                self.failures[agent_name] = 0
                return False
            print(f"🚫 Circuit breaker OPEN for {agent_name}")
            return True
        return False
    
    def record_success(self, agent_name: str):
        """Record successful call"""
        self.failures[agent_name] = 0
        if agent_name in self.open_circuits:
            self.open_circuits.remove(agent_name)
            print(f"✅ Circuit breaker CLOSED for {agent_name}")
    
    def record_failure(self, agent_name: str):
        """Record failed call"""
        self.failures[agent_name] = self.failures.get(agent_name, 0) + 1
        self.last_failure_time[agent_name] = datetime.now()
        
        if self.failures[agent_name] >= self.failure_threshold:
            self.open_circuits.add(agent_name)
            print(f"⚠️ Circuit breaker OPENED for {agent_name} ({self.failures[agent_name]} failures)")

# Initialize circuit breaker
circuit_breaker = CircuitBreaker(failure_threshold=5, timeout=60)

# Use in orchestrator_node:
def orchestrator_node(state: SharedState) -> SharedState:
    for step in plan_steps:
        agent_name = step["agent"]
        
        # Check circuit breaker
        if circuit_breaker.is_open(agent_name):
            error_msg = f"{agent_name} circuit breaker is open"
            results.append({"status": "error", "error": error_msg})
            continue
        
        result = call_agent_with_retry(agent_url, request_payload)
        
        if result and result.get("success"):
            circuit_breaker.record_success(agent_name)
        else:
            circuit_breaker.record_failure(agent_name)
```

### Fallback Strategies

```python
# Add fallback options in supervisor_agent.py

def call_agent_with_fallback(
    primary_agent: str,
    fallback_agents: list,
    request_payload: dict
) -> Optional[dict]:
    """
    Try primary agent, fallback to alternatives if it fails.
    """
    agents_to_try = [primary_agent] + fallback_agents
    
    for agent_name in agents_to_try:
        print(f"🎯 Trying agent: {agent_name}")
        
        agent_url = AGENT_ENDPOINTS.get(agent_name)
        if not agent_url:
            continue
        
        result = call_agent_with_retry(agent_url, request_payload)
        
        if result and result.get("success"):
            if agent_name != primary_agent:
                print(f"✅ Fallback successful using {agent_name}")
            return result
    
    print(f"❌ All agents failed (tried {agents_to_try})")
    return None

# Usage:
# result = call_agent_with_fallback(
#     primary_agent="gmail_agent",
#     fallback_agents=["gmail_agent_backup"],  # If you have alternatives
#     request_payload=request_payload
# )
```

---

## 🎯 Recommended Implementation Priority

### Phase 1: Essential (Do First)
1. ✅ **Layer 1: Supervisor HTTP retries** - Catches most failures
2. ✅ **Layer 3: Gmail API retries** - Handles Google API issues

### Phase 2: Enhanced Reliability
3. ⭐ **Circuit Breaker** - Prevents cascading failures
4. ⭐ **Better error logging** - Track patterns

### Phase 3: Advanced
5. 🔄 **Layer 2: LangGraph retries** - For LLM rate limits
6. 🔄 **Fallback agents** - If you have redundant services

---

## 📊 Configuration Recommendations

### For Development:
```python
max_retries = 2
timeout = 60.0
backoff_factor = 2.0
circuit_breaker_threshold = 3
```

### For Production:
```python
max_retries = 3
timeout = 180.0
backoff_factor = 2.0
circuit_breaker_threshold = 5
```

### For High-Load Production:
```python
max_retries = 5
timeout = 300.0
backoff_factor = 1.5
circuit_breaker_threshold = 10
```

---

## 🧪 Testing Your Retries

```python
# Test script: test_retries.py

import httpx
import time

def test_retry_logic():
    """Test retry mechanism"""
    
    # Test 1: Normal success
    print("\n1️⃣ Testing normal success...")
    response = httpx.post(
        "http://localhost:8000/workflow",
        json={"input": "Show me my last email"}
    )
    print(f"   Result: {response.status_code}")
    
    # Test 2: Timeout recovery
    print("\n2️⃣ Testing timeout recovery...")
    # Artificially cause timeout by killing agent temporarily
    
    # Test 3: Rate limit handling
    print("\n3️⃣ Testing rate limit...")
    for i in range(10):
        response = httpx.post(
            "http://localhost:8000/workflow",
            json={"input": f"Search email {i}"}
        )
        time.sleep(0.1)

if __name__ == "__main__":
    test_retry_logic()
```

---

## 📝 Summary

**Best Practice Implementation Order:**

1. **Start with Layer 1** (Supervisor HTTP retries) - Quick win, big impact
2. **Add Layer 3** (Gmail API retries) - Handles Google API issues
3. **Add Circuit Breaker** - Prevent cascading failures
4. **Monitor and tune** - Adjust based on actual failure patterns

This gives you production-grade reliability! 🚀
