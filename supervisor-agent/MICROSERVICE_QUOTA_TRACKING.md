# Microservice Token Quota Tracking - Distributed Architecture

## Overview

This document explains how to track token usage, user consumption, and system-wide limits when the supervisor agent and specialized agents (Gmail, Google Docs, etc.) are deployed as **separate microservices**.

---

## Architecture Strategy

### Centralized vs Distributed Tracking

We use a **CENTRALIZED tracking approach** where:
- ✅ **Supervisor Agent** = Central quota authority (owns the database)
- ✅ **Agent Microservices** = Report usage back to supervisor
- ✅ **Database** = Single source of truth (shared by supervisor only)

```
┌──────────────────────────────────────────────────────────┐
│                     USER REQUEST                          │
└────────────────────────┬─────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│              SUPERVISOR AGENT (Port 8000)                │
│                                                          │
│  ✅ Owns database connection                            │
│  ✅ Checks quotas BEFORE agent calls                    │
│  ✅ Records usage AFTER agent responses                 │
│  ✅ Tracks: planning, classification, orchestration     │
│                                                          │
│  Database: user_daily_quotas, usage_logs, etc.          │
└────────────┬────────────────────────┬───────────────────┘
             │                        │
             ▼                        ▼
┌────────────────────┐    ┌────────────────────┐
│  GMAIL AGENT       │    │  DOCS AGENT        │
│  (Port 8001)       │    │  (Port 8002)       │
│                    │    │                    │
│  ❌ No database    │    │  ❌ No database    │
│  ✅ Returns usage  │    │  ✅ Returns usage  │
│     in response    │    │     in response    │
└────────────────────┘    └────────────────────┘
```

---

## 1. Agent Response Format - Usage Reporting

### Modified Agent Response Schema

All agent microservices return **token usage metadata** in their responses:

**File: `gmail-agent/api.py` (and similar for other agents)**

```python
from pydantic import BaseModel
from typing import Dict, Any, Optional

class TokenUsage(BaseModel):
    """Token usage metadata from agent execution"""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model_used: str  # e.g., "gpt-3.5-turbo", "gpt-4"

class AgentTaskResponse(BaseModel):
    """Response from agent execution WITH token usage"""
    success: bool
    result: Dict[str, Any]
    raw_response: Optional[str] = None
    token_usage: Optional[TokenUsage] = None  # ADD THIS
    error: Optional[str] = None
```

### Update Agent API to Track Tokens

```python
import tiktoken

# Global token encoder
try:
    encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
except KeyError:
    encoding = tiktoken.get_encoding("cl100k_base")

def count_tokens(text: str) -> int:
    """Count tokens in text"""
    return len(encoding.encode(text))

@app.post("/execute_task", response_model=AgentTaskResponse)
async def execute_task(request: AgentTaskRequest):
    """Execute agent task and return token usage"""
    try:
        print(f"\n{'='*60}")
        print(f"🔧 GMAIL AGENT - Tool Execution")
        print(f"{'='*60}")
        print(f"Tool: {request.tool}")
        print(f"Inputs: {json.dumps(request.inputs, indent=2)}")
        
        # Build instruction for the agent
        instruction = build_tool_instruction(request.tool, request.inputs)
        
        # COUNT INPUT TOKENS
        prompt_tokens = count_tokens(instruction)
        
        # Call LLM
        llm_response = agent_llm.invoke(instruction)
        
        # COUNT OUTPUT TOKENS
        completion_tokens = count_tokens(llm_response.content)
        total_tokens = prompt_tokens + completion_tokens
        
        print(f"\n📊 Token Usage:")
        print(f"   Prompt: {prompt_tokens}")
        print(f"   Completion: {completion_tokens}")
        print(f"   Total: {total_tokens}")
        
        # Parse result
        parsed_result = parse_agent_response(llm_response.content)
        
        # Create token usage metadata
        token_usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            model_used="gpt-3.5-turbo"
        )
        
        return AgentTaskResponse(
            success=True,
            result=parsed_result,
            raw_response=llm_response.content,
            token_usage=token_usage  # INCLUDE USAGE
        )
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return AgentTaskResponse(
            success=False,
            result={},
            error=str(e),
            token_usage=None
        )
```

---

## 2. Supervisor Integration - Orchestrator Node

### Update Orchestrator to Track Agent Usage

**File: `supervisor-agent/supervisor_agent.py`**

```python
def orchestrator_node(state: SharedState, db: Session) -> SharedState:
    """
    STEP 2: Orchestrator executes the plan by calling agents
    WITH TOKEN TRACKING FOR EACH AGENT CALL
    """
    print("\n" + "="*60)
    print("⚙️ ORCHESTRATOR NODE - Executing Plan")
    print("="*60)
    
    plan = state.get("plan", {})
    context = state.get("context", {})
    user_id = state.get("user_id", "unknown")
    workflow_id = state.get("workflow_id", "unknown")
    
    steps = plan.get("steps", [])
    print(f"📋 Total steps to execute: {len(steps)}\n")
    
    for idx, step in enumerate(steps, 1):
        step_number = step.get("step_number", idx)
        agent_name = step.get("agent", "unknown")
        tool_name = step.get("tool", "unknown")
        description = step.get("description", "No description")
        inputs = step.get("inputs", {})
        
        print(f"\n{'─'*60}")
        print(f"📍 STEP {step_number}/{len(steps)}: {agent_name}.{tool_name}")
        print(f"📝 {description}")
        print(f"{'─'*60}")
        
        try:
            # STEP 1: ESTIMATE TOKENS FOR THIS AGENT CALL
            inputs_json = json.dumps(inputs)
            estimated_tokens = quota_manager.count_tokens(inputs_json)
            estimated_tokens += 500  # Base overhead for agent processing
            
            print(f"📊 Estimated tokens: {estimated_tokens}")
            
            # STEP 2: CHECK PER-REQUEST LIMIT
            per_request_allowed, per_request_error = quota_manager.check_per_request_limit(
                estimated_tokens,
                "agent_call"
            )
            
            if not per_request_allowed:
                print(f"❌ Per-request limit exceeded for this step!")
                # Record failed attempt
                quota_manager.record_usage(
                    db=db,
                    user_id=user_id,
                    workflow_id=workflow_id,
                    operation="agent_call",
                    agent_name=agent_name,
                    tool_name=tool_name,
                    tokens_used=0,
                    status="quota_exceeded",
                    error_message=per_request_error["message"]
                )
                # Skip this step but continue workflow
                context[f"step_{step_number}_error"] = per_request_error["message"]
                continue
            
            # STEP 3: CHECK USER DAILY QUOTA
            quota_allowed, quota_error = quota_manager.check_user_quota(
                db,
                user_id,
                estimated_tokens
            )
            
            if not quota_allowed:
                print(f"❌ User quota exceeded!")
                # Record failed attempt
                quota_manager.record_usage(
                    db=db,
                    user_id=user_id,
                    workflow_id=workflow_id,
                    operation="agent_call",
                    agent_name=agent_name,
                    tool_name=tool_name,
                    tokens_used=0,
                    status="quota_exceeded",
                    error_message=quota_error["message"]
                )
                # Stop workflow execution
                context["quota_exceeded"] = True
                context["quota_error"] = quota_error
                break
            
            print(f"✅ Quota check passed")
            
            # STEP 4: CALL AGENT MICROSERVICE
            print(f"🔄 Calling {agent_name} microservice...")
            
            agent_url = get_agent_url(agent_name)
            credentials = get_user_credentials(user_id, agent_name)
            
            payload = {
                "tool": tool_name,
                "inputs": inputs,
                "credentials_dict": credentials
            }
            
            response = httpx.post(
                f"{agent_url}/execute_task",
                json=payload,
                timeout=60.0
            )
            response.raise_for_status()
            agent_response = response.json()
            
            # STEP 5: EXTRACT TOKEN USAGE FROM AGENT RESPONSE
            token_usage = agent_response.get("token_usage", {})
            actual_tokens = token_usage.get("total_tokens", estimated_tokens)
            model_used = token_usage.get("model_used", "unknown")
            
            print(f"📊 Actual tokens used: {actual_tokens} (model: {model_used})")
            
            # STEP 6: RECORD USAGE IN DATABASE
            quota_manager.record_usage(
                db=db,
                user_id=user_id,
                workflow_id=workflow_id,
                operation="agent_call",
                agent_name=agent_name,
                tool_name=tool_name,
                tokens_used=actual_tokens,
                status="success"
            )
            
            # Store result in context
            result_data = agent_response.get("result", {})
            context[f"step_{step_number}_result"] = result_data
            
            print(f"✅ Step {step_number} completed successfully")
            print(f"📦 Result stored in context[step_{step_number}_result]")
            
        except httpx.HTTPError as e:
            print(f"❌ HTTP Error calling {agent_name}: {str(e)}")
            # Record error with estimated tokens (since we don't know actual)
            quota_manager.record_usage(
                db=db,
                user_id=user_id,
                workflow_id=workflow_id,
                operation="agent_call",
                agent_name=agent_name,
                tool_name=tool_name,
                tokens_used=estimated_tokens,
                status="error",
                error_message=str(e)
            )
            context[f"step_{step_number}_error"] = str(e)
            
        except Exception as e:
            print(f"❌ Unexpected error: {str(e)}")
            context[f"step_{step_number}_error"] = str(e)
    
    print("\n" + "="*60)
    print("✅ ORCHESTRATOR NODE - Execution Complete")
    print("="*60)
    
    return {"context": context, "final_context": context}


def get_agent_url(agent_name: str) -> str:
    """Get microservice URL for agent"""
    agent_urls = {
        "gmail_agent": os.getenv("GMAIL_AGENT_URL", "http://localhost:8001"),
        "docs_agent": os.getenv("DOCS_AGENT_URL", "http://localhost:8002"),
        # Add more agents here
    }
    return agent_urls.get(agent_name, "http://localhost:8000")
```

---

## 3. Complete Flow with Token Tracking

```
┌──────────────────────────────────────────────────────────┐
│  1. USER REQUEST → Supervisor (/workflow endpoint)       │
│     - user_id: "user123"                                 │
│     - input: "Search my gmail for invoices"              │
└────────────────────────┬─────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────┐
│  2. SUPERVISOR_NODE (Planning Phase)                     │
├──────────────────────────────────────────────────────────┤
│  a. Estimate tokens for planning (GPT-4)                 │
│  b. Check quota (database query)                         │
│  c. Call GPT-4 for planning                              │
│  d. Count actual tokens used                             │
│  e. RECORD in database:                                  │
│     - operation: "planning"                              │
│     - tokens_used: 3500                                  │
│     - agent_name: NULL                                   │
│     - tool_name: NULL                                    │
└────────────────────────┬─────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────┐
│  3. ORCHESTRATOR_NODE (Execution Phase)                  │
│     Plan: [Step 1: gmail_agent.search_emails]            │
└────────────────────────┬─────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────┐
│  4. ORCHESTRATOR - Step 1 Preparation                    │
├──────────────────────────────────────────────────────────┤
│  a. Estimate tokens for agent call                       │
│  b. Check quota (database query)                         │
│  c. Prepare payload for Gmail agent                      │
└────────────────────────┬─────────────────────────────────┘
                         │
                         ▼ HTTP POST
┌──────────────────────────────────────────────────────────┐
│  5. GMAIL AGENT MICROSERVICE (Port 8001)                 │
│     POST /execute_task                                   │
├──────────────────────────────────────────────────────────┤
│  a. Receive: {tool, inputs, credentials}                 │
│  b. Count input tokens                                   │
│  c. Call GPT-3.5-turbo for classification                │
│  d. Execute Gmail API search                             │
│  e. Count output tokens                                  │
│  f. RETURN response with token_usage:                    │
│     {                                                    │
│       "success": true,                                   │
│       "result": {...email data...},                      │
│       "token_usage": {                                   │
│         "prompt_tokens": 450,                            │
│         "completion_tokens": 120,                        │
│         "total_tokens": 570,                             │
│         "model_used": "gpt-3.5-turbo"                    │
│       }                                                  │
│     }                                                    │
└────────────────────────┬─────────────────────────────────┘
                         │
                         ▼ HTTP Response
┌──────────────────────────────────────────────────────────┐
│  6. ORCHESTRATOR - Process Agent Response                │
├──────────────────────────────────────────────────────────┤
│  a. Extract token_usage from response                    │
│  b. actual_tokens = 570                                  │
│  c. RECORD in database:                                  │
│     - operation: "agent_call"                            │
│     - tokens_used: 570                                   │
│     - agent_name: "gmail_agent"                          │
│     - tool_name: "search_emails"                         │
│  d. Store result in context                              │
└────────────────────────┬─────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────┐
│  7. DATABASE UPDATED                                     │
├──────────────────────────────────────────────────────────┤
│  user_daily_quotas:                                      │
│    - tokens_used: 3500 (planning) + 570 (agent) = 4070  │
│    - requests_made: 1                                    │
│                                                          │
│  usage_logs (2 entries):                                 │
│    1. planning | 3500 tokens | NULL agent                │
│    2. agent_call | 570 tokens | gmail_agent              │
│                                                          │
│  system_hourly_usage:                                    │
│    - tokens_used: 4070                                   │
│    - requests_made: 1                                    │
└──────────────────────────────────────────────────────────┘
```

---

## 4. Environment Configuration

### Supervisor Agent (.env)

```bash
# Database
DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/supervisor_db

# Quota Limits
MAX_TOKENS_PER_PLANNING=8000
MAX_TOKENS_PER_AGENT_CALL=4000
MAX_STEPS_PER_WORKFLOW=20
MAX_TOKENS_PER_USER_PER_DAY=500000
MAX_REQUESTS_PER_USER_PER_DAY=100
MAX_TOKENS_PER_HOUR_SYSTEM_WIDE=1000000
MAX_CONCURRENT_WORKFLOWS=10

# Agent Microservice URLs
GMAIL_AGENT_URL=http://localhost:8001
DOCS_AGENT_URL=http://localhost:8002
CALENDAR_AGENT_URL=http://localhost:8003

# OpenAI
OPENAI_API_KEY=sk-...
```

### Agent Microservices (.env)

```bash
# No database needed!
# Only OpenAI for LLM calls
OPENAI_API_KEY=sk-...

# Optional: Service discovery
SUPERVISOR_URL=http://localhost:8000
```

---

## 5. Analytics and Reporting

### Query Examples for Usage Analysis

**Total tokens by user (daily breakdown):**

```sql
SELECT 
    user_id,
    date,
    tokens_used,
    requests_made,
    ROUND((tokens_used / 1000) * 0.02, 4) AS estimated_cost
FROM user_daily_quotas
WHERE date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
ORDER BY user_id, date DESC;
```

**Top agents by token consumption:**

```sql
SELECT 
    agent_name,
    tool_name,
    COUNT(*) AS call_count,
    SUM(tokens_used) AS total_tokens,
    AVG(tokens_used) AS avg_tokens_per_call,
    ROUND(SUM(cost_estimate), 2) AS total_cost
FROM usage_logs
WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
    AND agent_name IS NOT NULL
GROUP BY agent_name, tool_name
ORDER BY total_tokens DESC;
```

**User activity breakdown:**

```sql
SELECT 
    user_id,
    operation,
    COUNT(*) AS operation_count,
    SUM(tokens_used) AS total_tokens,
    ROUND(SUM(cost_estimate), 2) AS total_cost
FROM usage_logs
WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
GROUP BY user_id, operation
ORDER BY user_id, total_tokens DESC;
```

**System hourly load (for capacity planning):**

```sql
SELECT 
    DATE_FORMAT(hour_timestamp, '%Y-%m-%d %H:00') AS hour,
    tokens_used,
    requests_made,
    ROUND((tokens_used / 1000000.0) * 100, 1) AS capacity_percent
FROM system_hourly_usage
WHERE hour_timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
ORDER BY hour_timestamp DESC;
```

**Workflow analysis (end-to-end tracking):**

```sql
SELECT 
    workflow_id,
    user_id,
    operation,
    agent_name,
    tool_name,
    tokens_used,
    status,
    created_at
FROM usage_logs
WHERE workflow_id = 'wf_abc123def456'
ORDER BY created_at ASC;
```

---

## 6. Monitoring Dashboard Endpoint

### Add Analytics Endpoint to Supervisor

```python
from datetime import datetime, timedelta
from sqlalchemy import func

@app.get("/admin/analytics/summary")
async def get_analytics_summary(
    days: int = 7,
    db: Session = Depends(get_db)
):
    """Get system-wide analytics summary"""
    cutoff = datetime.now() - timedelta(days=days)
    
    # Total usage by operation
    operation_stats = db.query(
        UsageLog.operation,
        func.count(UsageLog.id).label('count'),
        func.sum(UsageLog.tokens_used).label('total_tokens'),
        func.avg(UsageLog.tokens_used).label('avg_tokens'),
        func.sum(UsageLog.cost_estimate).label('total_cost')
    ).filter(
        UsageLog.created_at >= cutoff
    ).group_by(UsageLog.operation).all()
    
    # Top agents
    agent_stats = db.query(
        UsageLog.agent_name,
        UsageLog.tool_name,
        func.count(UsageLog.id).label('count'),
        func.sum(UsageLog.tokens_used).label('total_tokens')
    ).filter(
        UsageLog.created_at >= cutoff,
        UsageLog.agent_name.isnot(None)
    ).group_by(
        UsageLog.agent_name,
        UsageLog.tool_name
    ).order_by(func.sum(UsageLog.tokens_used).desc()).limit(10).all()
    
    # User activity
    user_stats = db.query(
        UsageLog.user_id,
        func.count(func.distinct(UsageLog.workflow_id)).label('workflows'),
        func.sum(UsageLog.tokens_used).label('total_tokens'),
        func.sum(UsageLog.cost_estimate).label('total_cost')
    ).filter(
        UsageLog.created_at >= cutoff
    ).group_by(UsageLog.user_id).all()
    
    return {
        "period_days": days,
        "from_date": cutoff.isoformat(),
        "to_date": datetime.now().isoformat(),
        "operations": [
            {
                "operation": op.operation,
                "count": op.count,
                "total_tokens": op.total_tokens,
                "avg_tokens": round(op.avg_tokens, 2),
                "total_cost": float(op.total_cost or 0)
            }
            for op in operation_stats
        ],
        "top_agents": [
            {
                "agent": a.agent_name,
                "tool": a.tool_name,
                "call_count": a.count,
                "total_tokens": a.total_tokens
            }
            for a in agent_stats
        ],
        "users": [
            {
                "user_id": u.user_id,
                "workflows_executed": u.workflows,
                "total_tokens": u.total_tokens,
                "total_cost": float(u.total_cost or 0)
            }
            for u in user_stats
        ]
    }


@app.get("/admin/analytics/agent/{agent_name}")
async def get_agent_analytics(
    agent_name: str,
    days: int = 7,
    db: Session = Depends(get_db)
):
    """Get detailed analytics for specific agent"""
    cutoff = datetime.now() - timedelta(days=days)
    
    # Tool usage breakdown
    tool_stats = db.query(
        UsageLog.tool_name,
        func.count(UsageLog.id).label('count'),
        func.sum(UsageLog.tokens_used).label('total_tokens'),
        func.avg(UsageLog.tokens_used).label('avg_tokens'),
        func.sum(UsageLog.cost_estimate).label('total_cost')
    ).filter(
        UsageLog.agent_name == agent_name,
        UsageLog.created_at >= cutoff
    ).group_by(UsageLog.tool_name).all()
    
    # Error rate
    total_calls = db.query(func.count(UsageLog.id)).filter(
        UsageLog.agent_name == agent_name,
        UsageLog.created_at >= cutoff
    ).scalar()
    
    error_calls = db.query(func.count(UsageLog.id)).filter(
        UsageLog.agent_name == agent_name,
        UsageLog.created_at >= cutoff,
        UsageLog.status == 'error'
    ).scalar()
    
    return {
        "agent_name": agent_name,
        "period_days": days,
        "total_calls": total_calls,
        "error_calls": error_calls,
        "error_rate_percent": round((error_calls / total_calls * 100) if total_calls > 0 else 0, 2),
        "tools": [
            {
                "tool_name": t.tool_name,
                "call_count": t.count,
                "total_tokens": t.total_tokens,
                "avg_tokens": round(t.avg_tokens, 2),
                "total_cost": float(t.total_cost or 0)
            }
            for t in tool_stats
        ]
    }
```

---

## 7. Key Architecture Decisions

### ✅ Why Centralized Tracking?

1. **Single source of truth**: One database eliminates synchronization issues
2. **Simpler agent code**: Agents focus on their domain (Gmail, Docs), not quota logic
3. **Easier quota enforcement**: Supervisor checks before calling agents
4. **Better analytics**: All data in one place for reporting
5. **Scalability**: Agents are stateless and can scale horizontally

### ✅ Why Agents Report Usage?

1. **Accurate counting**: Agents know exactly how many tokens they used
2. **Model flexibility**: Different agents can use different models (GPT-4, GPT-3.5)
3. **No estimation errors**: Actual token counts from tiktoken, not estimates
4. **Transparency**: Supervisor knows which agent/tool consumed tokens

### ✅ What Gets Tracked?

**Planning Phase (Supervisor):**
- Operation: `"planning"`
- Tokens: GPT-4 planning call
- Agent: `NULL`
- Tool: `NULL`

**Classification Phase (Supervisor):**
- Operation: `"classification"`
- Tokens: GPT-3.5 relevance check
- Agent: `NULL`
- Tool: `NULL`

**Agent Execution (Each agent call):**
- Operation: `"agent_call"`
- Tokens: Agent's LLM usage
- Agent: `"gmail_agent"`, `"docs_agent"`, etc.
- Tool: `"search_emails"`, `"add_text"`, etc.

---

## 8. Production Deployment Considerations

### Service Discovery

For production, use service discovery instead of hardcoded URLs:

```python
# Using Kubernetes service DNS
GMAIL_AGENT_URL = "http://gmail-agent-service:8001"
DOCS_AGENT_URL = "http://docs-agent-service:8002"

# Using environment variables (Docker Compose)
GMAIL_AGENT_URL = os.getenv("GMAIL_AGENT_URL", "http://gmail-agent:8001")
```

### Health Checks

Add health check endpoint to all microservices:

```python
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "gmail_agent", "version": "1.0.0"}
```

### Retry Logic

Supervisor should retry failed agent calls:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
def call_agent_with_retry(agent_url, payload):
    response = httpx.post(f"{agent_url}/execute_task", json=payload, timeout=60.0)
    response.raise_for_status()
    return response.json()
```

### Circuit Breaker

Protect against cascading failures:

```python
from circuitbreaker import circuit

@circuit(failure_threshold=5, recovery_timeout=60)
def call_agent(agent_url, payload):
    response = httpx.post(f"{agent_url}/execute_task", json=payload, timeout=60.0)
    response.raise_for_status()
    return response.json()
```

---

## 9. Summary

### ✅ Token Tracking Flow

1. **Supervisor checks quota** before each operation (planning + agent calls)
2. **Agent executes task** and counts its own token usage
3. **Agent returns result** with `token_usage` metadata
4. **Supervisor records usage** in centralized database
5. **Database updated** with detailed tracking (user, agent, tool, tokens, cost)

### ✅ What Each Component Does

**Supervisor Agent:**
- ✅ Owns database connection
- ✅ Checks quotas before operations
- ✅ Records all token usage (planning + agent calls)
- ✅ Provides analytics endpoints

**Agent Microservices:**
- ✅ Count their own token usage
- ✅ Return usage metadata in responses
- ❌ No database connection needed
- ❌ No quota checking needed

**Database:**
- ✅ Single source of truth
- ✅ Tracks per-user daily quotas
- ✅ Logs every operation (planning + agent calls)
- ✅ System-wide hourly tracking

This architecture is **production-ready, scalable, and provides complete visibility** into token consumption across your distributed microservice system! 🚀

