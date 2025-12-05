"""
FastAPI application entry point for PDF processing and knowledge base system.
This file initializes the FastAPI app and registers all routes.
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from api.routes import register_routes
from api.chat_routes import chat_router
from api.admin_routes import admin_router
from config import Config
from database.weaviate_client import get_weaviate_client
from middleware.security_middleware import (
    rate_limit_middleware, 
    security_headers_middleware
)
import atexit

def create_app():
    """Create and configure the FastAPI application"""
    # Validate configuration at startup
    Config.validate()
    
    # Initialize FastAPI
    app = FastAPI(
        title="PDF Processing and Knowledge Base API",
        description="API for PDF processing, knowledge base management, and chat functionality",
        version="1.0.0",
        # Limit request body size to 10MB (10 * 1024 * 1024 bytes)
        max_request_size=10 * 1024 * 1024
    )
    
    # Security Middleware (Applied in order - only if rate limiting enabled)
    # 1. Security headers
    app.middleware("http")(security_headers_middleware)
    
    # 2. Rate limiting
    if Config.RATE_LIMIT_ENABLED:
        app.middleware("http")(rate_limit_middleware)
        print(f"✓ Rate limiting enabled (Environment: {Config.ENVIRONMENT})")
    else:
        print("⚠ Rate limiting disabled")
    
    # CORS Configuration - This is the ONLY place where CORS is configured
    # To add your frontend port:
    #   1. For development: Add it to the list below
    #   2. For production: Add it to ALLOWED_ORIGINS in .env file
    
    allowed_origins = Config.ALLOWED_ORIGINS if Config.ENVIRONMENT == "production" else [
        "http://localhost:5173",      # Vite dev server (default)
        "http://localhost:5174",      # Alternative Vite port
        "http://localhost:3000",      # Alternative dev port
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        # Agent service ports
        "http://localhost:8000",
        "http://localhost:8001",
        "http://localhost:8002",
        "http://localhost:8003",
        "http://localhost:8004",
        "http://localhost:8005",
        "http://localhost:8006",
        "http://localhost:8007",
        "http://localhost:8008",
        "http://localhost:8009",
        "http://localhost:8010",
        "http://localhost:8011",
    ]
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],  # Allows Authorization header for JWT tokens
    )
    
    print(f"✓ CORS configured for origins: {allowed_origins}")
    
    # Register all routes (PDF processing, KB management)
    register_routes(app)
    
    # Register chat routes
    app.include_router(chat_router)
    
    # Register admin routes for monitoring
    app.include_router(admin_router)
    
    return app

def cleanup_on_exit():
    """Cleanup function to run when script exits"""
    try:
        client = get_weaviate_client()
        if client.is_connected():
            client.close()
            print("✓ Weaviate connection closed")
    except:
        pass

# Create app instance
app = create_app()

# Register cleanup on exit
atexit.register(cleanup_on_exit)

if __name__ == '__main__':
    import uvicorn
    
    print("\n" + "="*70)
    print("Starting FastAPI Server...")
    print(f"Environment: {Config.ENVIRONMENT}")
    print(f"Debug Mode: {Config.DEBUG}")
    print(f"Port: {Config.PORT}")
    print(f"Rate Limiting: {'Enabled' if Config.RATE_LIMIT_ENABLED else 'Disabled'}")
    
    # HTTPS/TLS Configuration
    ssl_config = {}
    if Config.USE_HTTPS and Config.SSL_CERTFILE and Config.SSL_KEYFILE:
        ssl_config = {
            "ssl_certfile": Config.SSL_CERTFILE,
            "ssl_keyfile": Config.SSL_KEYFILE
        }
        print(f"HTTPS Enabled: Using cert {Config.SSL_CERTFILE}")
        print("⚠ For production, use a reverse proxy (Nginx/Caddy) for HTTPS")
    else:
        print("HTTP Mode (Development)")
        print("⚠ For production deployment, enable HTTPS via reverse proxy")
    
    print("="*70 + "\n")
    
    try:
        uvicorn.run(
            "app:app",
            host="0.0.0.0",
            port=Config.PORT,
            reload=Config.DEBUG,
            **ssl_config
        )
    finally:
        # Ensure cleanup on normal exit
        cleanup_on_exit()
