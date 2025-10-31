"""
Configuration settings for the Supervisor Agent

This file contains environment variables, endpoint URLs,
and other configuration constants.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Microservice URLs for specialized agents
AGENT_ENDPOINTS = {
    "gmail_agent": os.getenv("GMAIL_AGENT_URL", "http://localhost:8001/execute_task"),
    "docs_agent": os.getenv("DOCS_AGENT_URL", "http://localhost:8002/execute_task"),
    "sheets_agent": os.getenv(
        "SHEETS_AGENT_URL", "http://localhost:8003/execute_task"
    ),  # ✅ FIXED
    "mapping_agent": os.getenv(
        "MAPPING_AGENT_URL", "http://localhost:8004/execute_task"
    ),  # ✅ Already correct
    "calendar_agent": os.getenv(
        "CALENDAR_AGENT_URL", "http://localhost:8005/execute_task"
    ),
    "drive_agent": os.getenv("DRIVE_AGENT_URL", "http://localhost:8006/execute_task"),
}

# Output directory for saved JSON files (plans, logs, etc.)
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "agent_outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Retry configuration for agent calls
DEFAULT_MAX_RETRIES = 5
DEFAULT_TIMEOUT = 320.0  # seconds
DEFAULT_BACKOFF_FACTOR = 2.0

# Plan schema for LLM
PLAN_SCHEMA = """
{
  "plan": [
    {
      "agent": "string - name of the agent to use (e.g., 'gmail_agent', 'docs_agent')",
      "tool": "string - exact tool name from agent's tools list (e.g., 'create_draft_email', 'search_emails', 'create_doc')",
      "inputs": {
        "param_name": "value or {{ variable_from_previous_step }}"
      },
      "output_variables": {
        "new_variable_name": "source_field_name - create 'new_variable_name' by copying value from 'source_field_name' in the tool's result"
      },
      "description": "string - summary of what this step does"
    }
  ]
}
"""

# Google OAuth credentials
GOOGLE_ACCESS_TOKEN = os.getenv("GOOGLE_ACCESS_TOKEN")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")

# OpenAI API configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))

# Classifier LLM for agent identification (cheaper model)
CLASSIFIER_MODEL = os.getenv("CLASSIFIER_MODEL", "gpt-3.5-turbo")

# Server configuration
SERVER_PORT = int(os.getenv("PORT", "8000"))
SERVER_HOST = os.getenv("HOST", "0.0.0.0")
