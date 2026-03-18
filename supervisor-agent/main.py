"""
Main entry point for the Supervisor Agent API.

Run this file to start the server:
    python main.py
"""

import uvicorn

# Import the FastAPI app and shared objects from supervisor_agent
# (this triggers LangGraph compilation, LLM init, etc.)
from supervisor_agent import app, recover_pending_actions_from_sqlite
from config import SERVER_PORT, SERVER_HOST

# Register route modules
from routes.threads import router as threads_router
from routes.admin import router as admin_router
from routes.workflow import router as workflow_router
from routes.actions import router as actions_router
from routes.logs import router as logs_router
from routes.realtime import router as realtime_router
from routes.health import router as health_router

app.include_router(threads_router)
app.include_router(admin_router)
app.include_router(workflow_router)
app.include_router(actions_router)
app.include_router(logs_router)
app.include_router(realtime_router)
app.include_router(health_router)


@app.on_event("startup")
async def startup_event():
    """Run on application startup - recover state from SQLite."""
    print("🔄 Running startup recovery...")
    recover_pending_actions_from_sqlite()
    print("✅ Startup recovery complete")


if __name__ == "__main__":
    print(f"🚀 Starting Supervisor Agent on port {SERVER_PORT}")
    print(f"📚 API Documentation: http://localhost:{SERVER_PORT}/docs")

    # Recover pending actions from SQLite on startup
    recover_pending_actions_from_sqlite()

    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
