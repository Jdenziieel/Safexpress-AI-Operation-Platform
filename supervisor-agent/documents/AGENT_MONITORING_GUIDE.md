# Agent Monitoring Guide

## Overview

This document outlines the Agent Performance Scoring Matrix used to monitor and evaluate AI agents in the system. The matrix provides administrators with comprehensive information regarding agent effectiveness, usability, and sustainability.

---

## Agent Performance Scoring Matrix

The Agent Performance Scoring Matrix comprises **five key performance variables** that collectively measure each agent's quality, responsiveness, and impact during real-world use. These variables help:

- Diagnose agent issues
- Inform improvements
- Optimize system resource allocation

---

## Performance Variables

### 1. Accuracy (Weight: 35%)

**Definition:** Measures whether the agent returns relevant and correct results. Critical when processing user queries, extracting data, or generating outputs based on predefined constraints.

**Implementation:**
- Log agent outputs and compare them to expected results or benchmarks
- For tasks with known answers, accuracy can be directly measured
- For open-ended queries, accuracy is approximated via:
  - User validation
  - Post-task correction rates

**Scoring Range:** 0-100

**Proposed Measurement:** % of responses that matched user question

---

### 2. Speed / Latency (Weight: 25%)

**Definition:** Evaluates how quickly the agent can complete its assigned task or response. Essential in user-facing workflows where delays can hinder or reduce trust in the system.

**Implementation:**
- System logs timestamp the start and end of tasks/API interactions
- Measure round-trip time per agent task
- Trigger alerts when latency exceeds defined thresholds

**Scoring Range:** 0-100

**Proposed Measurement:**
| Response Time | Score |
|---------------|-------|
| < 3 seconds | 100 |
| 4-10 seconds | 75 |
| > 11 seconds | 50 |

---

### 3. Reliability (Weight: 15%)

**Definition:** Assesses the agent's ability to complete its task successfully without system errors, crashes, or repeated failures. A reliable agent should not need frequent retries.

**Implementation:**
- Track failed executions, retries, and timeout rates over time
- Flag agents with high retry frequency or frequent escalation to fallback logic for review

**Scoring Range:** 0-100

**Proposed Measurement:** Successful tasks / total requests (as percentage)

---

### 4. Resource Efficiency (Weight: 10%)

**Definition:** Measures how optimally the agent uses computing resources such as memory, LLM tokens, and API tokens. Efficient agents consume fewer resources to deliver the same quality output.

**Implementation:**
- Integrate with monitoring tools to track memory and token usage per agent execution
- Track token consumption in LLM environments
- Cache reusable prompts or outputs

**Scoring Range:** 0-100

**Proposed Measurement:** Lower token consumption, lower memory or API quota usage scores higher

---

### 5. User Feedback (Weight: 15%)

**Definition:** Evaluates whether the user was satisfied with the agent's performance. Inferred through feedback mechanisms like ratings or comments.

**Implementation:**
- Log explicit feedback submitted through the UI
- Infer satisfaction scores via surveys or integrated feedback modules

**Scoring Range:** 1-5 (converted to 0-100 scale for calculation)

**Proposed Measurement:** 5-star rating or feedback click-through/abandon rate

---

## Performance Scoring Matrix Summary

| Metric | Scoring Range | Weight (%) | Proposed Measurement |
|--------|---------------|------------|----------------------|
| Accuracy | 0-100 | 35% | % of responses that matched user question |
| Speed/Latency | 0-100 | 25% | Response in <3 sec = 100, 4–10 sec = 75, >11 sec = 50 |
| Reliability | 0-100 | 15% | Successful tasks / total requests |
| Resource Efficiency | 0-100 | 10% | Lower token/memory/API usage scores higher |
| User Feedback Score | 1-5 | 15% | 5-star rating or feedback click-through/abandon rate |

---

## Agent Score Calculation

The overall agent score is calculated using the following formula:

```
Agent Score = (A × 0.35) + (S × 0.25) + (R × 0.15) + (E × 0.10) + (U × 0.15)
```

**Where:**
- **A** = Accuracy score (0-100)
- **S** = Speed/Latency time score (0-100)
- **R** = Reliability score (0-100)
- **E** = Resource efficiency score (0-100)
- **U** = User feedback score (normalized to 0-100 scale)

---

## Performance Tiers

| Score Range | Tier | Meaning |
|-------------|------|---------|
| **85-100** | 🟢 Excellent | Agent is highly effective and consistent |
| **70-84** | 🔵 Good | Agent performs well but may need optimization |
| **50-69** | 🟡 Fair | Agent needs improvement in key areas |
| **Below 50** | 🔴 Poor | Agent is underperforming and may need redesign |

---

## Implementation Recommendations

### Data Collection Points

For each agent execution, collect the following data:

```json
{
  "agent_id": "string",
  "agent_name": "string",
  "task_id": "string",
  "timestamp_start": "ISO8601",
  "timestamp_end": "ISO8601",
  "latency_ms": "number",
  "status": "success | failure | timeout | retry",
  "retry_count": "number",
  "tokens_used": "number",
  "memory_usage_mb": "number",
  "api_calls_count": "number",
  "accuracy_score": "number (0-100)",
  "user_feedback": {
    "rating": "number (1-5)",
    "comment": "string (optional)"
  }
}
```

### Logging Architecture

1. **Agent Wrapper/Middleware**
   - Wrap each agent execution to capture start/end timestamps
   - Log all inputs and outputs for accuracy validation

2. **Database Schema**
   - Store execution logs in a dedicated metrics table
   - Aggregate daily/weekly/monthly scores per agent

3. **Admin Dashboard Integration**
   - Real-time metrics visualization
   - Historical trend analysis
   - Alert configuration for threshold breaches

### Recommended Thresholds for Alerts

| Metric | Warning Threshold | Critical Threshold |
|--------|-------------------|-------------------|
| Latency | > 5 seconds | > 15 seconds |
| Reliability | < 90% | < 75% |
| Accuracy | < 80% | < 60% |
| Resource Usage | > 80% of quota | > 95% of quota |

---

## Example Score Calculation

**Scenario:** Gmail Agent Performance

| Metric | Raw Value | Score |
|--------|-----------|-------|
| Accuracy | 92% correct responses | 92 |
| Speed | Average 2.5 seconds | 100 |
| Reliability | 95% success rate | 95 |
| Resource Efficiency | 70% efficient | 70 |
| User Feedback | 4.2 stars | 84 |

**Calculation:**
```
Agent Score = (92 × 0.35) + (100 × 0.25) + (95 × 0.15) + (70 × 0.10) + (84 × 0.15)
            = 32.2 + 25 + 14.25 + 7 + 12.6
            = 91.05
```

**Result:** 🟢 **Excellent** tier (91.05)

---

## Admin Interface Requirements

The admin monitoring interface should include:

1. **Dashboard View**
   - Overall system health score
   - Individual agent performance cards
   - Real-time status indicators

2. **Detailed Agent View**
   - Historical performance graphs
   - Breakdown by metric
   - Recent execution logs

3. **Alerts & Notifications**
   - Configurable threshold alerts
   - Email/Slack notifications for critical issues

4. **Reports**
   - Daily/weekly/monthly performance reports
   - Comparative analysis between agents
   - Trend identification

---

## Next Steps

1. [ ] Implement logging middleware for all agents
2. [ ] Create database schema for metrics storage
3. [ ] Build admin dashboard components
4. [ ] Set up alerting system
5. [ ] Create automated reporting pipeline
6. [ ] Integrate user feedback collection in UI

---

## Detailed Implementation Analysis

### Current System Capabilities

Based on the existing codebase, **you already have significant infrastructure** that can be leveraged:

#### ✅ What Already Exists

| Component | Location | Current Capability |
|-----------|----------|-------------------|
| **SQLite Log Storage** | `supervisor-agent/log_storage.py` | Full logging with timestamps, request tracking |
| **LLM Call Tracking** | `llm_calls` table | Token usage, duration, success/failure |
| **Agent Call Tracking** | `agent_calls` table | Agent name, tool, duration, success |
| **Request Summaries** | `request_summaries` table | Aggregated stats per request |
| **Token Statistics** | `get_token_usage_stats()` | Already calculates totals, by model, by tier |

---

## How to Measure Each Metric - Detailed Implementation

### 1. ACCURACY (35%) - The Challenging One

**The Problem:** This is the hardest metric because "correct" depends on the task type.

**Realistic Implementation Options:**

#### Option A: User Validation Approach (Recommended)
```
Accuracy = (Tasks marked as correct by user) / (Total completed tasks) × 100
```

**Implementation:**
1. After each agent response, show user: "Was this helpful? 👍 👎"
2. Store in database:
   ```sql
   CREATE TABLE user_validations (
       id INTEGER PRIMARY KEY,
       request_id TEXT,
       agent_name TEXT,
       task_type TEXT,
       user_validated INTEGER,  -- 1 = thumbs up, 0 = thumbs down, NULL = no response
       timestamp TEXT
   );
   ```
3. Calculate accuracy per agent over time window

**Pros:** Real feedback from users
**Cons:** Not all users will respond, bias toward negative feedback

#### Option B: Task Completion Proxy
```
Accuracy = (Tasks completed without errors or retries) / (Total tasks) × 100
```

**Logic:** If the agent completes a task without errors, we assume it was accurate.

**Implementation:**
- Already tracked! Your `agent_calls` table has `success` field
- Query: 
  ```sql
  SELECT agent_name,
         (SUM(success) * 100.0 / COUNT(*)) as accuracy_score
  FROM agent_calls
  GROUP BY agent_name;
  ```

#### Option C: Hybrid Approach (Best)
```
Accuracy = (0.6 × Task Success Rate) + (0.4 × User Validation Rate)
```

**Recommendation:** Start with **Option B** (already available), then add **Option A** as enhancement.

---

### 2. SPEED / LATENCY (25%) - ✅ Already Measurable

**You already have this data!**

**Current Data Available:**
- `agent_calls.duration_ms` - Time per agent execution
- `llm_calls.duration_ms` - Time per LLM call
- `request_summaries.total_duration_ms` - Total request time

**Implementation:**
```sql
-- Get average latency per agent
SELECT 
    agent_name,
    AVG(duration_ms) as avg_latency_ms,
    CASE 
        WHEN AVG(duration_ms) < 3000 THEN 100
        WHEN AVG(duration_ms) BETWEEN 3000 AND 10000 THEN 75
        ELSE 50
    END as latency_score
FROM agent_calls
WHERE timestamp > datetime('now', '-7 days')
GROUP BY agent_name;
```

**Score Calculation:**
| Response Time | Score |
|---------------|-------|
| < 3 seconds (3000ms) | 100 |
| 3-10 seconds | 75 |
| > 10 seconds | 50 |

---

### 3. RELIABILITY (15%) - ✅ Already Measurable

**You already have this data!**

**Current Data Available:**
- `agent_calls.success` - 1 or 0 per execution
- Retry tracking in supervisor logs

**Implementation:**
```sql
-- Reliability score per agent
SELECT 
    agent_name,
    COUNT(*) as total_requests,
    SUM(success) as successful_requests,
    (SUM(success) * 100.0 / COUNT(*)) as reliability_score
FROM agent_calls
WHERE timestamp > datetime('now', '-7 days')
GROUP BY agent_name;
```

**What counts as failure:**
- HTTP errors from agent APIs
- Timeout exceeded
- Exception thrown
- Retry required

---

### 4. RESOURCE EFFICIENCY (10%) - ✅ Partially Available

**Current Data Available:**
- `llm_calls.input_tokens`, `output_tokens`, `total_tokens`
- `llm_calls.estimated_cost_usd`

**Implementation Challenge:** 
- Token usage is tracked, but we need a **baseline** to compare against
- Memory usage is NOT currently tracked

**Implementation:**

```sql
-- Token efficiency per agent (lower is better)
SELECT 
    ac.agent_name,
    AVG(lc.total_tokens) as avg_tokens_per_task,
    AVG(lc.estimated_cost_usd) as avg_cost_per_task
FROM agent_calls ac
JOIN llm_calls lc ON ac.request_id = lc.request_id
WHERE ac.timestamp > datetime('now', '-7 days')
GROUP BY ac.agent_name;
```

**Scoring Logic:**
```python
def calculate_efficiency_score(agent_name, avg_tokens):
    # Define baseline tokens per agent type
    baselines = {
        'gmail': 1500,
        'gdocs': 2000,
        'calendar': 1000,
        'sheets': 2500,
        'gdrive': 1200
    }
    
    baseline = baselines.get(agent_name.lower(), 1500)
    
    # Score: 100 if at/below baseline, decreases as usage increases
    if avg_tokens <= baseline:
        return 100
    elif avg_tokens <= baseline * 1.5:
        return 80
    elif avg_tokens <= baseline * 2:
        return 60
    else:
        return 40
```

---

### 5. USER FEEDBACK (15%) - ❌ Needs Implementation

**What's Needed:**

#### Database Schema Addition
```sql
CREATE TABLE user_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT,
    thread_id TEXT,
    conversation_id TEXT,
    agent_name TEXT,
    rating INTEGER CHECK(rating >= 1 AND rating <= 5),
    feedback_text TEXT,
    feedback_type TEXT,  -- 'thumbs', 'stars', 'comment'
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### Frontend Component
Add to chat interface after each response:
```jsx
// Rating component
<div className="feedback-prompt">
  <span>Was this helpful?</span>
  <button onClick={() => submitFeedback(5)}>👍</button>
  <button onClick={() => submitFeedback(1)}>👎</button>
  {/* Or 5-star rating */}
  <StarRating onChange={submitFeedback} />
</div>
```

#### API Endpoint
```python
@app.post("/feedback")
async def submit_feedback(request: FeedbackRequest):
    log_storage.insert_user_feedback(
        request_id=request.request_id,
        agent_name=request.agent_name,
        rating=request.rating
    )
```

**Score Calculation:**
```sql
SELECT 
    agent_name,
    AVG(rating) as avg_rating,
    (AVG(rating) * 20) as feedback_score  -- Convert 1-5 to 0-100
FROM user_feedback
WHERE timestamp > datetime('now', '-30 days')
GROUP BY agent_name;
```

---

## Complete Agent Score Calculation

### SQL Query for Full Agent Performance
```sql
WITH 
accuracy_cte AS (
    SELECT agent_name, 
           (SUM(success) * 100.0 / COUNT(*)) as accuracy_score
    FROM agent_calls
    WHERE timestamp > datetime('now', '-7 days')
    GROUP BY agent_name
),
latency_cte AS (
    SELECT agent_name,
           CASE 
               WHEN AVG(duration_ms) < 3000 THEN 100
               WHEN AVG(duration_ms) < 10000 THEN 75
               ELSE 50
           END as latency_score
    FROM agent_calls
    WHERE timestamp > datetime('now', '-7 days')
    GROUP BY agent_name
),
reliability_cte AS (
    SELECT agent_name,
           (SUM(success) * 100.0 / COUNT(*)) as reliability_score
    FROM agent_calls
    WHERE timestamp > datetime('now', '-7 days')
    GROUP BY agent_name
),
feedback_cte AS (
    SELECT agent_name,
           COALESCE(AVG(rating) * 20, 70) as feedback_score  -- Default 70 if no feedback
    FROM user_feedback
    WHERE timestamp > datetime('now', '-30 days')
    GROUP BY agent_name
)

SELECT 
    a.agent_name,
    ROUND(a.accuracy_score, 1) as accuracy,
    ROUND(l.latency_score, 1) as speed,
    ROUND(r.reliability_score, 1) as reliability,
    70 as efficiency,  -- Placeholder until baseline established
    ROUND(COALESCE(f.feedback_score, 70), 1) as user_feedback,
    ROUND(
        (a.accuracy_score * 0.35) +
        (l.latency_score * 0.25) +
        (r.reliability_score * 0.15) +
        (70 * 0.10) +  -- Efficiency placeholder
        (COALESCE(f.feedback_score, 70) * 0.15),
        1
    ) as overall_score,
    CASE 
        WHEN (a.accuracy_score * 0.35) + (l.latency_score * 0.25) + 
             (r.reliability_score * 0.15) + (70 * 0.10) + 
             (COALESCE(f.feedback_score, 70) * 0.15) >= 85 THEN 'Excellent'
        WHEN (a.accuracy_score * 0.35) + (l.latency_score * 0.25) + 
             (r.reliability_score * 0.15) + (70 * 0.10) + 
             (COALESCE(f.feedback_score, 70) * 0.15) >= 70 THEN 'Good'
        WHEN (a.accuracy_score * 0.35) + (l.latency_score * 0.25) + 
             (r.reliability_score * 0.15) + (70 * 0.10) + 
             (COALESCE(f.feedback_score, 70) * 0.15) >= 50 THEN 'Fair'
        ELSE 'Poor'
    END as tier
FROM accuracy_cte a
LEFT JOIN latency_cte l ON a.agent_name = l.agent_name
LEFT JOIN reliability_cte r ON a.agent_name = r.agent_name
LEFT JOIN feedback_cte f ON a.agent_name = f.agent_name;
```

---

## Implementation Roadmap

### Phase 1: Quick Wins (Use Existing Data) - 1-2 Days
- [x] Speed/Latency - Already in `agent_calls.duration_ms`
- [x] Reliability - Already in `agent_calls.success`
- [ ] Create API endpoint to aggregate metrics
- [ ] Add "Agent Performance" section to admin dashboard

### Phase 2: Accuracy Enhancement - 2-3 Days
- [ ] Add thumbs up/down UI after each response
- [ ] Create `user_validations` table
- [ ] Implement hybrid accuracy calculation

### Phase 3: User Feedback System - 2-3 Days
- [ ] Create `user_feedback` table
- [ ] Add rating component to frontend
- [ ] Build feedback API endpoint

### Phase 4: Resource Efficiency - 3-4 Days
- [ ] Establish baseline token usage per agent
- [ ] Create efficiency scoring algorithm
- [ ] Link LLM calls to specific agents

### Phase 5: Admin Dashboard - 3-5 Days
- [ ] Agent performance cards with all 5 metrics
- [ ] Historical trend charts
- [ ] Alert configuration UI
- [ ] Export/reporting features

---

## Summary: What's Achievable Now vs. Later

| Metric | Status | Data Source | Effort |
|--------|--------|-------------|--------|
| **Accuracy** | 🟡 Partial | Task success + user validation | Medium |
| **Speed/Latency** | ✅ Ready | `agent_calls.duration_ms` | Low |
| **Reliability** | ✅ Ready | `agent_calls.success` | Low |
| **Resource Efficiency** | 🟡 Partial | `llm_calls.total_tokens` | Medium |
| **User Feedback** | ❌ Needs Work | New table + UI | High |

**Bottom Line:** You can implement **3 out of 5 metrics immediately** using existing data. The other 2 require new data collection mechanisms.
