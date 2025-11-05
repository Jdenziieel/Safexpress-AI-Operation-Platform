# Token Quota System - Implementation Guide

## Overview

This document outlines a comprehensive token quota and rate limiting system for the Supervisor Agent API. The system is designed for **internal use with a small user base** (client + management team), providing generous limits while preventing runaway costs and abuse.

---

## 1. System Architecture

### Three-Layer Protection

```
┌─────────────────────────────────────────────────────────┐
│              Layer 1: Per-Request Limits                │
│  • Prevents individual requests from consuming too much │
│  • Catches bugs/infinite loops in planning              │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│           Layer 2: Per-User Daily Quotas                │
│  • Tracks daily usage per user                          │
│  • Resets at midnight                                   │
│  • Generous limits for power users                      │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│          Layer 3: System-Wide Safety Limits             │
│  • Prevents server overload                             │
│  • Caps concurrent workflows                            │
│  • Hourly system-wide token cap                         │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Quota Limits Configuration

### Environment Variables (.env)

```bash
# Per-Request Limits
MAX_TOKENS_PER_PLANNING=8000           # Supervisor planning with GPT-4
MAX_TOKENS_PER_AGENT_CALL=4000         # Individual agent LLM calls
MAX_STEPS_PER_WORKFLOW=20              # Prevent infinite loops

# Per-User Daily Limits
MAX_TOKENS_PER_USER_PER_DAY=500000     # ~$10/day at GPT-4 rates
MAX_REQUESTS_PER_USER_PER_DAY=100      # ~1 request every 15 min (8hr day)

# System-Wide Limits
MAX_TOKENS_PER_HOUR_SYSTEM_WIDE=1000000   # Entire system cap
MAX_CONCURRENT_WORKFLOWS=10               # Prevent server overload

# Usage Logging
USAGE_LOG_FILE=usage_logs.csv          # CSV file for usage tracking
ENABLE_USAGE_LOGGING=true              # Enable/disable logging
```

### Default Values (Hardcoded Fallbacks)

```python
# If env vars not set, use these defaults
DEFAULT_LIMITS = {
    "max_tokens_per_planning": 8000,
    "max_tokens_per_agent_call": 4000,
    "max_steps_per_workflow": 20,
    "max_tokens_per_user_per_day": 500_000,
    "max_requests_per_user_per_day": 100,
    "max_tokens_per_hour_system_wide": 1_000_000,
    "max_concurrent_workflows": 10
}
```

---

## 3. Limit Rationale

### Per-Request Planning Limit: **8,000 tokens**

**Why 8K?**
- Complex multi-step workflows with full agent capabilities = ~3-5K tokens
- Agent capability JSON (filtered) = ~2-3K tokens
- User input + context = ~500-1K tokens
- 8K provides comfortable headroom for complex requests

**What happens at limit:**
- Request rejected with clear error message
- User notified of token count and limit
- Suggested: simplify request or break into smaller workflows

### Per-Request Agent Call Limit: **4,000 tokens**

**Why 4K?**
- Gmail agents processing full email bodies = ~1-2K tokens
- Docs agents reading/writing documents = ~1-3K tokens
- 4K handles most real-world scenarios comfortably

**What happens at limit:**
- Agent call rejected before execution
- User notified which specific agent/tool exceeded limit
- Suggested: reduce max_results, use pagination, or filter data

### Max Workflow Steps: **20 steps**

**Why 20?**
- Most real workflows = 3-10 steps
- 20 catches infinite loops from planning errors
- Still allows complex multi-agent orchestrations

**What happens at limit:**
- Workflow execution stops at step 20
- Partial results returned (steps 1-20)
- User notified of step limit reached

### Per-User Daily Token Limit: **500,000 tokens (~$10/day)**

**Why 500K?**
- Power user scenario: 50 complex workflows/day × 10K tokens = 500K
- Cost: ~$10-15/day at GPT-4 Turbo rates ($0.01 input, $0.03 output)
- For 5 users: ~$50-75/day = **$1,500-2,250/month** max

**What happens at limit:**
- New requests rejected with quota exceeded message
- Shows tokens used, limit, and reset time (midnight)
- User can request quota increase from admin

### Per-User Daily Request Limit: **100 requests/day**

**Why 100?**
- 8-hour workday: 100 requests = ~1 request every 5 minutes
- Prevents accidental spam from scripts/bugs
- Comfortable for manual usage

**What happens at limit:**
- New requests rejected with request count exceeded
- Shows requests made, limit, and reset time
- Prevents infinite loops from external scripts

### System-Wide Hourly Limit: **1,000,000 tokens/hour**

**Why 1M/hour?**
- 5 users × 500K daily ÷ 8 hours = ~312K tokens/hour normal usage
- 1M provides 3x headroom for burst usage
- Protects against coordinated heavy usage

**What happens at limit:**
- New requests queued or rejected (configurable)
- Admin notified of unusual usage spike
- Auto-resets every hour

### Concurrent Workflow Limit: **10 workflows**

**Why 10?**
- Server capacity protection (CPU, memory, network)
- 2 workflows per user × 5 users = comfortable
- Prevents resource exhaustion

**What happens at limit:**
- New requests return 503 Service Temporarily Unavailable
- Includes retry-after header with estimated wait time
- Auto-retries when slot available

---

## 4. Token Counting Method

### Using `tiktoken` Library

```python
import tiktoken

def count_tokens(text: str, model: str = "gpt-4") -> int:
    """
    Count tokens in text using tiktoken.
    
    Args:
        text: The text to count tokens for
        model: OpenAI model name (e.g., "gpt-4", "gpt-3.5-turbo")
    
    Returns:
        Number of tokens
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        # Fallback for unknown models
        encoding = tiktoken.get_encoding("cl100k_base")
    
    return len(encoding.encode(text))
```

### Token Counting Points

1. **Planning Phase (supervisor_node)**
   - System prompt (agent capabilities)
   - User input
   - LLM response (generated plan)

2. **Agent Classification Phase (identify_relevant_agents)**
   - Classification prompt
   - User input
   - LLM response (agent list)

3. **Agent Execution Phase (orchestrator_node)**
   - Each agent's LLM calls (if applicable)
   - Email body processing, doc content, etc.

---

## 5. Data Storage

### In-Memory Storage (Development/Small Scale)

```python
# User quota tracking
USER_DAILY_QUOTAS = {
    "user_id_123": {
        "date": "2025-10-20",
        "tokens_used": 125000,
        "requests_made": 45,
        "last_reset": "2025-10-20T00:00:00Z"
    }
}

# System-wide tracking
SYSTEM_HOURLY_USAGE = {
    "2025-10-20T14:00": {
        "tokens_used": 450000,
        "requests_made": 87,
        "active_workflows": 3
    }
}

# Active workflow tracking
ACTIVE_WORKFLOWS = {
    "workflow_abc123": {
        "user_id": "user_id_123",
        "started_at": "2025-10-20T14:35:22Z",
        "status": "running"
    }
}
```

### CSV Logging (Usage Analytics)

```csv
timestamp,user_id,workflow_id,operation,tokens_used,cost_estimate,status,error
2025-10-20T14:35:22Z,user_123,wf_abc,planning,3500,0.035,success,
2025-10-20T14:35:25Z,user_123,wf_abc,agent_gmail,1200,0.012,success,
2025-10-20T14:35:28Z,user_123,wf_abc,agent_docs,2100,0.021,success,
2025-10-20T14:40:11Z,user_456,wf_def,planning,4200,0.042,quota_exceeded,Daily limit reached
```

### Future: Database Migration

For production with more users, migrate to:
- **PostgreSQL/MySQL**: Persistent storage, better querying
- **Redis**: Fast in-memory cache for real-time quota checks
- **InfluxDB/TimescaleDB**: Time-series data for analytics

---

## 6. Error Messages

### Per-Request Token Limit Exceeded

```json
{
  "status": "error",
  "error_code": "REQUEST_TOKEN_LIMIT_EXCEEDED",
  "message": "This request would use 9,500 tokens, exceeding the limit of 8,000 tokens per planning request.",
  "details": {
    "tokens_required": 9500,
    "tokens_limit": 8000,
    "tokens_over": 1500
  },
  "suggestions": [
    "Simplify your request",
    "Break into smaller workflows",
    "Reduce the number of agents involved"
  ]
}
```

### Daily User Quota Exceeded

```json
{
  "status": "error",
  "error_code": "DAILY_QUOTA_EXCEEDED",
  "message": "You have exceeded your daily token quota.",
  "details": {
    "tokens_used_today": 505000,
    "daily_limit": 500000,
    "requests_made_today": 87,
    "requests_limit": 100,
    "quota_resets_at": "2025-10-21T00:00:00Z",
    "hours_until_reset": 9.5
  },
  "suggestions": [
    "Wait until midnight for quota reset",
    "Contact admin to request quota increase"
  ]
}
```

### System-Wide Limit Exceeded

```json
{
  "status": "error",
  "error_code": "SYSTEM_CAPACITY_EXCEEDED",
  "message": "System is at capacity. Please try again shortly.",
  "details": {
    "reason": "hourly_token_limit",
    "system_tokens_this_hour": 1050000,
    "hourly_limit": 1000000,
    "retry_after_seconds": 1200
  },
  "suggestions": [
    "Retry in 20 minutes when hourly limit resets",
    "Use simpler workflows to reduce token usage"
  ]
}
```

### Concurrent Workflow Limit

```json
{
  "status": "error",
  "error_code": "TOO_MANY_CONCURRENT_WORKFLOWS",
  "message": "Maximum concurrent workflows reached. Please wait.",
  "details": {
    "active_workflows": 10,
    "max_concurrent": 10,
    "estimated_wait_seconds": 45
  },
  "suggestions": [
    "Wait for one of your current workflows to complete",
    "Check /workflows/active endpoint to see running workflows"
  ]
}
```

---

## 7. Implementation Steps

### Step 1: Install Dependencies

```bash
pip install tiktoken
```

### Step 2: Create Quota Manager Module

**File: `supervisor-agent/quota_manager.py`**

```python
"""
Token quota and rate limiting system for Supervisor Agent.
Tracks per-user daily limits and system-wide capacity.
"""

import os
import tiktoken
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import csv
from pathlib import Path

class QuotaManager:
    """Manages token quotas and rate limiting"""
    
    def __init__(self):
        # Load limits from environment or use defaults
        self.max_tokens_per_planning = int(os.getenv("MAX_TOKENS_PER_PLANNING", 8000))
        self.max_tokens_per_agent_call = int(os.getenv("MAX_TOKENS_PER_AGENT_CALL", 4000))
        self.max_steps_per_workflow = int(os.getenv("MAX_STEPS_PER_WORKFLOW", 20))
        self.max_tokens_per_user_per_day = int(os.getenv("MAX_TOKENS_PER_USER_PER_DAY", 500000))
        self.max_requests_per_user_per_day = int(os.getenv("MAX_REQUESTS_PER_USER_PER_DAY", 100))
        self.max_tokens_per_hour_system_wide = int(os.getenv("MAX_TOKENS_PER_HOUR_SYSTEM_WIDE", 1000000))
        self.max_concurrent_workflows = int(os.getenv("MAX_CONCURRENT_WORKFLOWS", 10))
        
        # Storage
        self.user_daily_quotas: Dict = {}
        self.system_hourly_usage: Dict = {}
        self.active_workflows: Dict = {}
        
        # Logging
        self.enable_logging = os.getenv("ENABLE_USAGE_LOGGING", "true").lower() == "true"
        self.log_file = os.getenv("USAGE_LOG_FILE", "usage_logs.csv")
        self._init_log_file()
    
    def count_tokens(self, text: str, model: str = "gpt-4") -> int:
        """Count tokens using tiktoken"""
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    
    def check_request_limit(self, user_id: str, estimated_tokens: int) -> Tuple[bool, Optional[str]]:
        """
        Check if request is within all limits.
        Returns (allowed, error_message)
        """
        # Implementation details...
        pass
    
    def record_usage(self, user_id: str, workflow_id: str, operation: str, tokens: int, status: str):
        """Record token usage for analytics"""
        # Implementation details...
        pass
```

### Step 3: Integrate into supervisor_agent.py

Add quota checks at key points:
1. Before planning (supervisor_node)
2. Before agent execution (orchestrator_node)
3. Track concurrent workflows

### Step 4: Add Monitoring Endpoints

```python
@app.get("/quota/status")
async def get_quota_status(user_id: str):
    """Get current quota usage for a user"""
    pass

@app.get("/quota/system")
async def get_system_quota():
    """Get system-wide quota status"""
    pass
```

### Step 5: Add Admin Endpoints

```python
@app.post("/admin/quota/reset")
async def reset_user_quota(user_id: str, admin_key: str):
    """Admin: Reset user's daily quota"""
    pass

@app.post("/admin/quota/increase")
async def increase_user_quota(user_id: str, new_limit: int, admin_key: str):
    """Admin: Increase user's quota limit"""
    pass
```

---

## 8. Cost Estimates

### Per-User Monthly Cost (assuming 50% quota usage)

```
Base calculation:
- Daily limit: 500,000 tokens
- Average daily usage: 250,000 tokens (50% of limit)
- Working days per month: 22 days
- Monthly tokens: 250,000 × 22 = 5,500,000 tokens

Cost breakdown:
- GPT-4 Turbo: ~$0.01 input + ~$0.03 output = ~$0.02 average/1K tokens
- Monthly cost per user: 5,500K tokens × $0.02/1K = $110/user

For 5 users:
- Total monthly cost: $110 × 5 = $550/month
```

### Peak Monthly Cost (100% quota usage)

```
- Daily limit fully used: 500,000 tokens
- Working days: 22 days
- Monthly tokens: 500,000 × 22 = 11,000,000 tokens
- Monthly cost per user: 11M × $0.02/1K = $220/user

For 5 users:
- Total monthly cost: $220 × 5 = $1,100/month
```

### Recommended Budget

**Set monthly budget: $1,500**
- Covers 100% quota usage for 5 users
- Includes 36% buffer for spikes/overages
- Alert at $1,200 (80% of budget)

---

## 9. Monitoring & Alerts

### Daily Monitoring

```python
# Check at end of each day
def daily_summary():
    """Generate daily usage summary"""
    return {
        "date": "2025-10-20",
        "total_tokens": 2_500_000,
        "total_cost": 50.00,
        "total_requests": 245,
        "unique_users": 5,
        "peak_hour": "14:00-15:00",
        "peak_hour_tokens": 450_000
    }
```

### Alert Thresholds

1. **User approaching daily limit** (80% = 400K tokens)
   - Email notification to user
   - Suggest optimizing workflows

2. **System approaching hourly limit** (80% = 800K tokens)
   - Alert admin
   - Consider temporary rate limiting

3. **Unusual spike detected** (2x normal usage)
   - Alert admin immediately
   - Check for bugs or abuse

4. **Monthly budget at 80%** ($1,200)
   - Alert finance/management
   - Review quota allocations

---

## 10. User Communication

### Email Template: Approaching Daily Limit

```
Subject: Token Usage Alert - 80% of Daily Quota Used

Hi [User Name],

You've used 400,000 of your 500,000 daily token quota (80%).

Your quota resets in: 6 hours (at midnight)

Tips to reduce token usage:
• Use more specific search queries
• Limit max_results in email searches
• Break complex workflows into smaller steps

Need more quota? Contact: admin@company.com

Best regards,
Supervisor Agent System
```

---

## 11. Future Enhancements

### Phase 2 (3-6 months)

1. **User-specific quota customization**
   - Different limits for different roles (admin, manager, staff)
   - Project-based quota allocation

2. **Quota sharing**
   - Team quotas shared across multiple users
   - Department-level budgets

3. **Advanced analytics dashboard**
   - Real-time usage visualization
   - Cost breakdown by user/project
   - Trend analysis and forecasting

### Phase 3 (6-12 months)

1. **Machine learning optimization**
   - Predict token usage before execution
   - Suggest more efficient workflow alternatives

2. **Dynamic pricing tiers**
   - Pay-per-use option for burst capacity
   - Reserved capacity pricing

3. **Integration with billing systems**
   - Automatic chargeback to departments
   - Invoice generation

---

## Summary

This quota system provides:

✅ **Cost Control**: Predictable monthly costs (~$550-1,100 for 5 users)  
✅ **Performance**: Prevents server overload with concurrent limits  
✅ **User Experience**: Generous limits for internal power users  
✅ **Monitoring**: CSV logging for usage analytics  
✅ **Scalability**: Easy to adjust limits via environment variables  
✅ **Safety**: Three-layer protection against abuse/bugs  

**Ready for implementation in supervisor_agent.py**
