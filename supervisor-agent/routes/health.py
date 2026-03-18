"""
Health and root information routes.

Handles GET /health and GET / endpoints.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "supervisor-agent"}


@router.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "service": "Supervisor Agent API",
        "version": "1.0.0",
        "endpoints": {
            "workflow": "/workflow (POST) - Execute a workflow with user input",
            "chat": "/chat (POST) - Send a chat message",
            "threads": "/threads (GET/POST) - Manage conversation threads",
            "logs": "/logs (GET) - Query system logs with filtering",
            "logs_search": "/logs/search (GET) - Full-text search in logs",
            "logs_stats": "/logs/stats (GET) - Token usage and cost statistics",
            "logs_request": "/logs/requests/{request_id} (GET) - Get all logs for a request",
            "admin_logs": "/admin/logs (GET) - Privacy-safe logs for admin dashboard",
            "admin_activity": "/admin/activity (GET) - Privacy-safe activity feed",
            "admin_health": "/admin/health (GET) - System health status",
            "admin_alerts": "/admin/alerts (GET) - Active alerts and warnings",
            "admin_metrics": "/admin/metrics (GET) - Agent performance metrics",
            "health": "/health (GET) - Health check",
            "docs": "/docs (GET) - Swagger documentation",
        },
    }
