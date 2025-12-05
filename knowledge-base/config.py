"""Configuration management for the application."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Get the directory where this config.py file is located (knowledge-base folder)
BASE_DIR = Path(__file__).resolve().parent

load_dotenv(override=True)


class Config:
    """Application configuration class."""
    
    # OpenAI Configuration
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE")
    OPENAI_MODEL = "gpt-4o"
    OPENAI_MINI_MODEL = "gpt-4o-mini"
    EMBEDDING_MODEL = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS = 1536
    
    # Weaviate Configuration
    WEAVIATE_URL = os.environ.get("WEAVIATE_URL")
    WEAVIATE_API_KEY = os.environ.get("WEAVIATE_API_KEY")
    
    # JWT Configuration
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
    
    # Security Configuration
    ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")  # development, staging, production
    ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
    
    # Rate Limiting (can be overridden via environment)
    RATE_LIMIT_ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "true").lower() == "true"
    
    # HTTPS/TLS (Production only)
    USE_HTTPS = os.environ.get("USE_HTTPS", "false").lower() == "true"
    SSL_CERTFILE = os.environ.get("SSL_CERTFILE")  # Path to SSL certificate
    SSL_KEYFILE = os.environ.get("SSL_KEYFILE")    # Path to SSL private key
    
    # Processing Configuration
    BATCH_SIZE = 100
    MAX_TOKENS = 1000
    TEMPERATURE = 0.0
    TOP_M_RERANK = 10
    HYBRID_SEARCH_ALPHA = 0.5
    HYBRID_SEARCH_LIMIT = 20
    
    # PDF Processing Configuration
    LINE_TOLERANCE = 5
    WORD_TOLERANCE_MULTIPLIER = 0.4
    GAP_MULTIPLIER = 1.5
    MATCH_SCORE_THRESHOLD = 80
    CROSS_PAGE_LINE_WINDOW = 20
    
    # FastAPI Configuration
    DEBUG = True
    PORT = 8009
    
    # File paths (absolute paths based on this file's location)
    OUTPUT_DIR = str(BASE_DIR / "outputs")
    DATABASE_DIR = BASE_DIR / "database"
    DOCUMENTS_DB_PATH = str(DATABASE_DIR / "documents.db")
    CHAT_SESSIONS_DB_PATH = str(DATABASE_DIR / "chat_sessions.db")
    KB_LOGS_DB_PATH = str(DATABASE_DIR / "kb_logs.db")
    
    @classmethod
    def validate(cls):
        """Validate required configuration."""
        if not cls.OPENAI_API_KEY:
            # Fallback to dotenv
            from dotenv import dotenv_values
            env_vars = dotenv_values(".env")
            cls.OPENAI_API_KEY = env_vars.get("OPENAI_APIKEY")
            
        if not cls.OPENAI_API_KEY:
            raise RuntimeError("❌ OPENAI_API_KEY environment variable is not set!")
        
        if not cls.WEAVIATE_URL or not cls.WEAVIATE_API_KEY:
            raise RuntimeError("❌ Weaviate configuration is missing!")
        
        return True
