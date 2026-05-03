"""
Configuration settings for the Supervisor Agent

This file contains environment variables, endpoint URLs,
and other configuration constants.

AA-lambda MODIFY: AGENT_ENDPOINTS is now populated by `_load_agent_targets()`.
When `AGENT_LAMBDA_NAMES_JSON` env var is set (Lambda mode), values are bare
function names like `agent-gmail`. The `call_agent_with_retry` adapter in
`utils.py` detects strings without `://` and routes via `boto3.lambda.invoke`
instead of `httpx.post`. Local-dev fallback preserves the `/execute_task`
suffix to match the original `supervisor-agent/config.py:14-27`.
"""

import os
import json

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _load_agent_targets() -> dict:
    """Pick Lambda function names (Lambda mode) or local URLs (dev mode)."""
    raw = os.getenv("AGENT_LAMBDA_NAMES_JSON")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {
        "gmail_agent": os.getenv("GMAIL_AGENT_URL", "http://localhost:8000/execute_task"),
        "docs_agent": os.getenv("DOCS_AGENT_URL", "http://localhost:8002/execute_task"),
        "sheets_agent": os.getenv("SHEETS_AGENT_URL", "http://localhost:8003/execute_task"),
        "mapping_agent": os.getenv("MAPPING_AGENT_URL", "http://localhost:8004/execute_task"),
        "calendar_agent": os.getenv("CALENDAR_AGENT_URL", "http://localhost:8005/execute_task"),
        "drive_agent": os.getenv("DRIVE_AGENT_URL", "http://localhost:8006/execute_task"),
    }


AGENT_ENDPOINTS = _load_agent_targets()

# Output directory for saved JSON files (plans, logs, etc.).
# In AWS Lambda, /var/task (where this module lives) is read-only — only
# /tmp is writable. AWS sets ``AWS_LAMBDA_FUNCTION_NAME`` for us so we can
# detect the runtime cheaply. CloudWatch already captures every print/log
# statement and Sup_RequestSummaries / Sup_LLMCalls hold the structured
# analytics, so the on-disk supervisor_plan.json is a developer convenience
# only — losing it across cold starts is not a failure mode. Without this
# branch every workflow crashed at supervisor_agent.py:704 with
# `[Errno 30] Read-only file system: '/var/task/shared/agent_outputs/supervisor_plan.json'`
# the moment the planner tried to dump its plan.
if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    OUTPUT_DIR = "/tmp/agent_outputs"
else:
    OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "agent_outputs")
try:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
except OSError:
    # Even /tmp can fail (full disk, ENOSPC). The actual writes inside
    # supervisor_agent.py / etc. are wrapped in their own try/except, so a
    # missing directory becomes a silent no-op instead of a cold-start crash.
    pass

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

# Google OAuth app credentials (client_id / client_secret) are app-wide and
# stay in env vars — populated by the deploy scripts from the
# ``prod/app/google-oauth`` Secrets Manager secret. Per-user access /
# refresh tokens have moved out of env into DynamoDB ``SocialTokens`` (see
# ``google_creds.py``); the GOOGLE_ACCESS_TOKEN / GOOGLE_REFRESH_TOKEN env
# vars below are kept ONLY as a single-user dev/test fallback when no
# user_email is propagated through the request context.
GOOGLE_ACCESS_TOKEN = os.getenv("GOOGLE_ACCESS_TOKEN")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")


def get_google_credentials(user_email: str = None) -> dict:
    """Build a complete Google OAuth credentials dict for agent calls.

    AA-lambda SocialTokens phase: in production, the per-user access &
    refresh tokens live in the deployed ``SocialTokens`` DynamoDB table
    (PK ``gmail``, SK ``provider``), written by ``auth-google-login`` at
    OAuth callback. This function resolves them in two distinct paths:

      Path A — Authenticated request (production):
        1. ``user_email`` arg → ``logging_config._user_email_var``
           contextvar (set by ``set_request_context_lambda`` from the JWT
           authorizer claims).
        2. Query ``SocialTokens(gmail, "google")``; the helper refreshes
           the access_token in-place when ``expires_at`` is past.
        3. If lookup fails (no row, refresh broken, etc.) → return an
           **empty** creds dict. The orchestrator's pre-flight check
           (``supervisor_agent.py:1170-1186``) sees the missing fields,
           emits a clear "Missing required Google credentials" error, and
           refuses to run the workflow.

           Critically: we do NOT silently fall back to the env-var creds
           in this case. In production those env vars hold whatever single
           account the deploy scripts seeded; using them on behalf of an
           authenticated user would be a privilege-escalation / data-leak
           vector. Fail closed instead.

      Path B — Unauthenticated context (dev / smoke tests / cron):
        ``user_email`` is None (no JWT, no contextvar). Read the legacy
        ``GOOGLE_*`` env vars so single-user developer laptops keep
        working unchanged. Production Lambda invocations always have a
        JWT, so this path never fires there.

    The output shape is identical in both paths (the ``credentials_dict``
    every sub-agent's ``_build_google_credentials()`` already consumes),
    so no brain or sub-agent code has to change.
    """
    # Resolve user_email: explicit arg > request contextvar > None
    if not user_email:
        try:
            from logging_config import get_current_user_email  # type: ignore
            user_email = get_current_user_email()
        except Exception:
            user_email = None

    if user_email:
        # Path A — authenticated request. Fail closed on lookup failure.
        try:
            from google_creds import get_google_credentials_for_user  # type: ignore
            ddb_creds = get_google_credentials_for_user(user_email)
        except Exception as e:
            print(f"[config.get_google_credentials] SocialTokens lookup raised: {e}")
            ddb_creds = None
        if ddb_creds:
            return {k: v for k, v in ddb_creds.items() if v}
        print(
            f"[config.get_google_credentials] SocialTokens lookup returned"
            f" no row for {user_email!r}; refusing to fall back to env-var"
            " creds (would leak the seed account's tokens). The orchestrator"
            " will surface 'Missing required Google credentials' to the user."
        )
        return {}

    # Path B — unauthenticated context (no user_email anywhere). Use env.
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
