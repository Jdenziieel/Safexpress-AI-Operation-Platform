"""API routes for the application."""
from fastapi import FastAPI
from api.pdf_routes import pdf_router
from api.kb_routes import kb_router


def register_routes(app: FastAPI):
    """Register all route routers with the FastAPI app."""
    
    # Register routers
    app.include_router(pdf_router)
    app.include_router(kb_router)
    
    # Health check endpoint
    @app.get('/', tags=['health'])
    async def health_check():
        return {"status": "ok", "message": "PDF Processing API is running"}
    
    print("✅ All routes registered successfully")
