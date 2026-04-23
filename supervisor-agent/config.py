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
    "gmail_agent": os.getenv("GMAIL_AGENT_URL", "http://localhost:8000/execute_task"),
    "docs_agent": os.getenv("DOCS_AGENT_URL", "http://localhost:8002/execute_task"),
    "sheets_agent": os.getenv(
        "SHEETS_AGENT_URL", "http://localhost:8003/execute_task"
    ), # FIXED
    "mapping_agent": os.getenv(
        "MAPPING_AGENT_URL", "http://localhost:8004/execute_task"
    ), # Already correct
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
PLAN_SCHEMA = {
    "steps": [
        {
            "agent": "agent_name",
            "tool": "tool_name",
            "inputs": {"param": "value or {{ variable }}"},
            "output_variables": {"new_name": "source_field"},
            "description": "what this step does"
        }
    ]
}

# Google OAuth credentials
GOOGLE_ACCESS_TOKEN = os.getenv("GOOGLE_ACCESS_TOKEN")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")


def get_google_credentials() -> dict:
    """Build a complete Google OAuth credentials dict for agent calls.

    Used by both the orchestrator loop and execute_single_action so
    the credential set is always identical and supports token refresh.
    """
    creds = {
        "access_token": os.getenv("GOOGLE_ACCESS_TOKEN"),
        "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN"),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": os.getenv("GOOGLE_CLIENT_ID") or os.getenv("OAUTH_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET") or os.getenv("OAUTH_CLIENT_SECRET"),
    }
    return {k: v for k, v in creds.items() if v}

# OpenAI API configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# Planner / primary reasoning model. Flipped from gpt-5 to gpt-4.1 after
# DEMO8.9 exposed two problems with gpt-5 as a structured-output planner:
#   1. gpt-5 emitted PlanSteps WITHOUT the required `inputs` field when it
#      "reasoned" the field would come from prior step outputs — Pydantic
#      rejected the whole ExecutionPlan (5/5 steps invalid). gpt-4 / gpt-4.1
#      do not exhibit this; they populate every declared field.
#   2. gpt-5's reasoning tokens are billed as output ($10/M). For this workload
#      the planner emits ~2-3x more output than a non-reasoning model for the
#      same task, so gpt-5's input-price advantage ($1.25/M vs $2/M + 90% vs
#      75% cache discount) is erased by output-token inflation. See DEMO8.9
#      analysis: a single failed planner call cost $0.0339 and took 35.7s.
#
# gpt-4.1 still supports automatic prompt caching at 75% discount (cached
# input $0.50/M), so the ~3k-token static planner system prompt stays cheap
# on cache hits. Env override preserved for experimentation with gpt-5 /
# gpt-4o / gpt-4 once the `inputs`-default-dict + `method=json_schema` fixes
# ship.
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4.1")

# Tier 1 conversational analysis model. Flipped from gpt-5-mini to gpt-4.1-mini
# for the same two reasons as the planner: gpt-5-mini burned 2398-3006 output
# tokens per Tier 1 call in DEMO8.9 (28-34s each) because of reasoning-token
# inflation, versus ~800-1200 expected for the same classification /
# parameter-extraction work. gpt-4.1-mini input is $0.40/M (vs $0.25/M on
# gpt-5-mini) but output is $1.60/M (vs $2/M), and with 60% fewer output
# tokens the per-call cost drops ~45% AND latency drops from ~30s to ~5s.
# Env override preserved.
TIER1_MODEL = os.getenv("TIER1_MODEL", "gpt-4.1-mini")

LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))

# Classifier LLM for agent identification (cheaper AND smarter model).
# Flipped from gpt-3.5-turbo to gpt-4o-mini in Phase 0 of the
# fix-sheets-crash-cascade plan: gpt-4o-mini is ~3x cheaper per input
# token ($0.15 vs $0.50 per 1M) AND measurably better at classification
# tasks. Env-var override preserved for instant rollback.
CLASSIFIER_MODEL = os.getenv("CLASSIFIER_MODEL", "gpt-4o-mini")

# Lightweight model for quick checks, memory summarization, result summarization
QUICK_MODEL = os.getenv("QUICK_MODEL", "gpt-4o-mini")

# Transform layer (llm_tool.transform_text) — cheaper model with large context window
TRANSFORM_MODEL = os.getenv("TRANSFORM_MODEL", "gpt-4o")
TRANSFORM_MAX_INPUT_TOKENS = int(os.getenv("TRANSFORM_MAX_INPUT_TOKENS", "20000"))

# Server configuration
SERVER_PORT = int(os.getenv("PORT", "8010"))
SERVER_HOST = os.getenv("HOST", "0.0.0.0")
