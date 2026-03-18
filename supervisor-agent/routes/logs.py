"""
Log query routes.

Handles all /logs/* and /agents/metrics endpoints for
querying, searching, and managing system logs.
"""

from fastapi import APIRouter, HTTPException
from typing import Optional
from log_storage import LogStorage

router = APIRouter(tags=["logs"])


@router.get("/logs")
async def get_logs(
    level: Optional[str] = None,
    component: Optional[str] = None,
    request_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """
    Get logs with filtering and pagination.
    
    Query Parameters:
        - level: Filter by log level (DEBUG, INFO, PROGRESS, WARNING, ERROR, CRITICAL)
        - component: Filter by component (llm, orchestrator, api, etc.)
        - request_id: Filter by request ID
        - conversation_id: Filter by conversation ID
        - thread_id: Filter by thread ID
        - start_time: Filter logs after this time (ISO format)
        - end_time: Filter logs before this time (ISO format)
        - limit: Number of logs to return (default 100, max 1000)
        - offset: Offset for pagination
    
    Returns:
        - logs: List of log entries
        - total: Total count of matching logs
        - limit: Current limit
        - offset: Current offset
    """
    try:
        storage = LogStorage()
        
        # Validate limit
        limit = min(limit, 1000)
        
        logs, total = storage.get_logs(
            level=level.upper() if level else None,
            component=component,
            request_id=request_id,
            conversation_id=conversation_id,
            thread_id=thread_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset
        )
        
        return {
            "logs": logs,
            "total": total,
            "limit": limit,
            "offset": offset
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving logs: {str(e)}")


@router.get("/logs/search")
async def search_logs(
    q: str,
    level: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """
    Full-text search across log messages.
    
    Query Parameters:
        - q: Search query (required)
        - level: Filter by log level
        - start_time: Filter logs after this time (ISO format)
        - end_time: Filter logs before this time (ISO format)
        - limit: Number of results (default 100, max 1000)
        - offset: Offset for pagination
    
    Returns:
        - logs: List of matching log entries
        - total: Total count of matches
        - query: The search query used
    """
    try:
        storage = LogStorage()
        
        limit = min(limit, 1000)
        
        logs, total = storage.search_logs(
            query=q,
            level=level.upper() if level else None,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset
        )
        
        return {
            "logs": logs,
            "total": total,
            "query": q,
            "limit": limit,
            "offset": offset
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error searching logs: {str(e)}")


@router.get("/logs/stats")
async def get_log_stats(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None
):
    """
    Get log statistics including token usage and cost summary.
    
    Query Parameters:
        - start_time: Start of time range (ISO format)
        - end_time: End of time range (ISO format)
    
    Returns:
        - token_summary: Total tokens and costs
        - request_analytics: Per-request analytics
        - log_level_counts: Count of logs by level
    """
    try:
        storage = LogStorage()
        
        token_summary = storage.get_token_summary(start_time, end_time)
        request_analytics = storage.get_request_analytics(start_time, end_time)
        
        return {
            "token_summary": token_summary,
            "request_analytics": request_analytics,
            "time_range": {
                "start": start_time,
                "end": end_time
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving stats: {str(e)}")


@router.get("/logs/requests/{request_id}")
async def get_request_logs(request_id: str):
    """
    Get all logs for a specific request ID.
    Useful for tracing a complete request through the system.
    
    Returns all log entries associated with the given request_id,
    ordered chronologically.
    """
    try:
        storage = LogStorage()
        
        logs, total = storage.get_logs(
            request_id=request_id,
            limit=1000
        )
        
        # Calculate summary for this request
        token_total = 0
        cost_total = 0.0
        llm_calls = []
        agent_calls = []
        
        for log in logs:
            data = log.get("data", {})
            if log.get("component") == "llm" and "input_tokens" in data:
                token_total += data.get("total_tokens", 0)
                cost_total += data.get("estimated_cost_usd", 0)
                llm_calls.append({
                    "operation": log.get("operation"),
                    "model": data.get("model"),
                    "tokens": data.get("total_tokens"),
                    "cost_usd": data.get("estimated_cost_usd"),
                    "duration_ms": data.get("duration_ms")
                })
            elif log.get("component") == "orchestrator" and "agent" in data:
                agent_calls.append({
                    "agent": data.get("agent"),
                    "tool": data.get("tool"),
                    "success": data.get("success"),
                    "duration_ms": data.get("duration_ms")
                })
        
        return {
            "request_id": request_id,
            "logs": logs,
            "total_logs": total,
            "summary": {
                "total_tokens": token_total,
                "total_cost_usd": round(cost_total, 6),
                "llm_calls": len(llm_calls),
                "agent_calls": len(agent_calls),
                "llm_details": llm_calls,
                "agent_details": agent_calls
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving request logs: {str(e)}")


@router.delete("/logs")
async def clear_logs(
    before_time: Optional[str] = None,
    confirm: bool = False
):
    """
    Clear logs from the database.
    
    Query Parameters:
        - before_time: Delete logs before this time (ISO format)
        - confirm: Must be true to actually delete (safety measure)
    
    Returns:
        - deleted_count: Number of logs deleted
    """
    if not confirm:
        raise HTTPException(
            status_code=400, 
            detail="Set confirm=true to actually delete logs"
        )
    
    try:
        storage = LogStorage()
        
        deleted_count = storage.clear_logs(before_time)
        
        return {
            "deleted_count": deleted_count,
            "before_time": before_time or "all"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error clearing logs: {str(e)}")


@router.get("/agents/metrics")
async def get_agent_metrics(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None
):
    """
    Get performance metrics for all agents.
    
    Returns metrics including:
    - Accuracy (task success rate)
    - Speed/Latency scores
    - Reliability
    - Resource efficiency
    - Overall performance score
    
    Query Parameters:
        - start_time: Filter from this time (ISO format)
        - end_time: Filter until this time (ISO format)
    """
    try:
        storage = LogStorage()
        
        # Get agent calls data
        agent_calls = storage.get_agent_calls(
            start_time=start_time,
            end_time=end_time,
            limit=10000
        )
        
        # Aggregate metrics per agent
        agent_stats = {}
        for call in agent_calls:
            agent = call.get("agent_name", "unknown")
            if agent not in agent_stats:
                agent_stats[agent] = {
                    "total_calls": 0,
                    "successful_calls": 0,
                    "total_duration_ms": 0,
                    "durations": []
                }
            
            stats = agent_stats[agent]
            stats["total_calls"] += 1
            if call.get("success"):
                stats["successful_calls"] += 1
            duration = call.get("duration_ms", 0)
            stats["total_duration_ms"] += duration
            stats["durations"].append(duration)
        
        # Calculate performance scores
        metrics = {}
        for agent, stats in agent_stats.items():
            total = stats["total_calls"]
            successful = stats["successful_calls"]
            
            # Accuracy/Reliability (task success rate)
            accuracy = (successful / total * 100) if total > 0 else 0
            reliability = accuracy  # Same metric for now
            
            # Speed score
            avg_duration = stats["total_duration_ms"] / total if total > 0 else 0
            if avg_duration < 3000:
                speed_score = 100
            elif avg_duration < 10000:
                speed_score = 75
            else:
                speed_score = 50
            
            # Efficiency (placeholder - would need token data linked to agents)
            efficiency = 70  # Default
            
            # User feedback (placeholder - needs user_feedback table)
            user_feedback = 70  # Default neutral
            
            # Overall score using the formula
            overall_score = (
                accuracy * 0.35 +
                speed_score * 0.25 +
                reliability * 0.15 +
                efficiency * 0.10 +
                user_feedback * 0.15
            )
            
            # Determine tier
            if overall_score >= 85:
                tier = "Excellent"
            elif overall_score >= 70:
                tier = "Good"
            elif overall_score >= 50:
                tier = "Fair"
            else:
                tier = "Poor"
            
            metrics[agent] = {
                "accuracy": round(accuracy, 1),
                "speed": round(speed_score, 1),
                "reliability": round(reliability, 1),
                "efficiency": round(efficiency, 1),
                "user_feedback": round(user_feedback, 1),
                "overall_score": round(overall_score, 1),
                "tier": tier,
                "total_calls": total,
                "successful_calls": successful,
                "success_rate": round(accuracy, 1),
                "avg_latency_ms": round(avg_duration, 0),
            }
        
        return {
            "metrics": metrics,
            "time_range": {
                "start": start_time,
                "end": end_time
            },
            "agent_count": len(metrics)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving agent metrics: {str(e)}")
