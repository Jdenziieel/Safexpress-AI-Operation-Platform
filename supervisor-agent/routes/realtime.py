"""
Real-time progress routes.

Handles WebSocket endpoint for live progress streaming
and HTTP endpoint for polling thread execution progress.
"""

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from datetime import datetime, timezone
import asyncio

from log_storage import LogStorage
from supervisor_agent import progress_manager

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/threads/{thread_id}/progress")
async def websocket_progress(websocket: WebSocket, thread_id: str):
    """
    WebSocket endpoint for real-time progress updates.
    
    Connect to this endpoint to receive instant progress updates during execution.
    Messages are JSON objects with type: "progress", "status", "token_usage", "complete"
    
    Example message:
    {
        "type": "progress",
        "data": {
            "current_step": 2,
            "total_steps": 5,
            "step_name": "Sending email",
            "agent": "gmail-agent",
            "status": "executing"
        },
        "timestamp": "2025-11-29T10:30:00Z"
    }
    """
    await progress_manager.connect(websocket, thread_id)
    try:
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connected",
            "data": {"thread_id": thread_id, "message": "Connected to progress stream"},
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        # Keep connection alive and listen for any client messages
        while True:
            try:
                # Wait for messages (ping/pong or close)
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Echo back pings
                if data == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # Send keepalive ping
                try:
                    await websocket.send_json({"type": "ping"})
                except:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        progress_manager.disconnect(websocket, thread_id)


@router.get("/threads/{thread_id}/progress")
async def get_thread_progress(thread_id: str):
    """
    Get the current execution progress for a thread.
    
    This endpoint returns the latest progress logs for a thread,
    useful for real-time progress display in the frontend.
    
    Returns:
        - status: Current status (idle, executing, completed, failed)
        - current_step: Current step number
        - total_steps: Total number of steps
        - step_name: Current step name/description
        - agent: Current agent being used
        - message: Progress message
        - request_id: Current request ID
        - token_usage: Current token usage for this request
    """
    try:
        storage = LogStorage()
        
        # Get recent logs for this thread, ordered by timestamp DESC
        logs, total = storage.get_logs(
            thread_id=thread_id,
            limit=50,
            offset=0
        )
        
        if not logs:
            return {
                "status": "idle",
                "current_step": 0,
                "total_steps": 0,
                "step_name": None,
                "agent": None,
                "message": None,
                "request_id": None,
                "token_usage": None
            }
        
        # Find the most recent progress or status log
        latest_progress = None
        latest_llm = None
        latest_agent = None
        latest_request_id = None
        current_status = "idle"
        
        for log in logs:
            level = log.get("level", "")
            component = log.get("component", "")
            operation = log.get("operation", "")
            data = log.get("data", {}) or {}
            
            # Track request_id
            if log.get("request_id") and not latest_request_id:
                latest_request_id = log.get("request_id")
            
            # Check for progress logs
            if level == "PROGRESS" and not latest_progress:
                latest_progress = {
                    "current_step": data.get("current_step", 0),
                    "total_steps": data.get("total_steps", 0),
                    "step_name": data.get("step_name", ""),
                    "message": log.get("message", "")
                }
                current_status = "executing"
            
            # Check for LLM calls
            if component == "llm" and not latest_llm:
                latest_llm = {
                    "operation": operation,
                    "model": data.get("model", ""),
                    "tokens": data.get("total_tokens", 0),
                    "tier": data.get("tier", "")
                }
                if current_status == "idle":
                    current_status = "processing"
            
            # Check for agent calls
            if component == "orchestrator" and operation == "agent_call" and not latest_agent:
                latest_agent = {
                    "agent": data.get("agent", ""),
                    "tool": data.get("tool", ""),
                    "step": data.get("step", 0),
                    "total_steps": data.get("total_steps", 0),
                    "success": data.get("success", True)
                }
                current_status = "executing"
            
            # Check for completion
            if operation == "request_complete":
                current_status = "completed"
                break
        
        # Build response
        response = {
            "status": current_status,
            "current_step": 0,
            "total_steps": 0,
            "step_name": None,
            "agent": None,
            "message": None,
            "request_id": latest_request_id,
            "token_usage": None
        }
        
        # Add progress info
        if latest_progress:
            response["current_step"] = latest_progress["current_step"]
            response["total_steps"] = latest_progress["total_steps"]
            response["step_name"] = latest_progress["step_name"]
            response["message"] = latest_progress["message"]
        
        # Add agent info
        if latest_agent:
            response["agent"] = latest_agent["agent"]
            response["tool"] = latest_agent["tool"]
            if not latest_progress:
                response["current_step"] = latest_agent["step"]
                response["total_steps"] = latest_agent["total_steps"]
                response["step_name"] = f"{latest_agent['agent']}.{latest_agent['tool']}"
        
        # Add LLM info if processing
        if latest_llm and current_status == "processing":
            response["step_name"] = latest_llm["operation"]
            response["message"] = f"Processing with {latest_llm['model']}..."
        
        # Get token usage for this request
        if latest_request_id:
            request_logs, _ = storage.get_logs(
                request_id=latest_request_id,
                component="llm",
                limit=100
            )
            
            total_tokens = 0
            total_cost = 0.0
            llm_calls = 0
            
            for log in request_logs:
                data = log.get("data", {}) or {}
                if "total_tokens" in data:
                    total_tokens += data.get("total_tokens", 0)
                    # Prefer aligned `cost_usd`; fall back to legacy key for old logs
                    total_cost += data.get("cost_usd", data.get("estimated_cost_usd", 0)) or 0
                    llm_calls += 1
            
            if llm_calls > 0:
                response["token_usage"] = {
                    "total_tokens": total_tokens,
                    "total_cost_usd": round(total_cost, 6),
                    "llm_calls": llm_calls
                }
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving progress: {str(e)}")
