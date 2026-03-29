#THIS IS THE SUPERVISOR.py
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
import json
import httpx
import traceback
import tempfile
import shutil
from jinja2 import Template
from typing import TypedDict, List, Optional, Dict, Any, Callable, Awaitable
from datetime import datetime, timedelta, timezone
from fastapi.middleware.cors import CORSMiddleware
import os
import uvicorn
import asyncio
import uuid
import time

# Import models
from models.models import *

# Import configuration
from config import (
    AGENT_ENDPOINTS,
    OUTPUT_DIR,
    GOOGLE_ACCESS_TOKEN,
    GOOGLE_REFRESH_TOKEN,
    OPENAI_API_KEY,
    LLM_MODEL,
    LLM_TEMPERATURE,
    QUICK_MODEL,
    SERVER_PORT,
    SERVER_HOST,
)  

# Import agent capabilities
from agent_capabilities_v3 import agent_capabilities

# Import utility functions
from utils import (
    call_agent_with_retry,
    generate_action_summary,
)

# Import conversational agent
from conversational_agent import ConversationalAgent

# Import LLM error handler for unified error handling
from llm_error_handler import handle_llm_error, LLMServiceException, is_llm_error

# Import execution trace logger
from execution_logger import trace

# Import logging module
from logging_config import (
    supervisor_logger as logger,
    orchestrator_logger,
    set_request_context,
    clear_request_context,
    get_current_request_id,
    get_current_thread_id,
    get_current_conversation_id,
    get_token_summary,
    generate_request_id,
    check_user_quota
)

# Import tool filter for optimized capability filtering
from tool_filter import get_optimized_capabilities

# Import log storage for SQLite persistence
from log_storage import LogStorage

# Initialize FastAPI app
app = FastAPI(title="Supervisor Agent API")

# Add CORS middleware (configured for all services)
ALLOWED_ORIGINS = [
    "http://localhost:5173",  # Frontend
    "http://localhost:5174",  # Alternative frontend
    "http://localhost:8000",  # Gmail Agent
    "http://localhost:8001",  # Auth Server
    "http://localhost:8002",  # Docs Agent
    "http://localhost:8003",  # Sheets Agent
    "http://localhost:8004",  # Mapping Agent
    "http://localhost:8005",  # Calendar Agent
    "http://localhost:8006",  # Drive Agent
    "http://localhost:8009",  # Knowledge Base
    "http://localhost:8011",  # Token Quota Service
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── HTTP Request/Response Trace Middleware ──────────────────────────────
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class TraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        method_path = f"{request.method} {request.url.path}"
        # Skip noisy/read-only endpoints: health, docs, OPTIONS preflight, GET polling
        if request.url.path in ("/health", "/docs", "/openapi.json", "/favicon.ico"):
            return await call_next(request)
        if request.method in ("OPTIONS", "GET"):
            return await call_next(request)
        trace.request_start(method_path, {"query": str(request.query_params) or None})
        try:
            response = await call_next(request)
            duration_ms = (time.time() - start) * 1000
            trace.request_end(f"{response.status_code}", duration_ms)
            return response
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            trace.error(f"{method_path} failed", exception=e)
            trace.request_end("500 ERROR", duration_ms)
            raise

app.add_middleware(TraceMiddleware)


# ============================================================================
# WEBSOCKET CONNECTION MANAGER FOR REAL-TIME PROGRESS
# ============================================================================

class ProgressConnectionManager:
    """Manages WebSocket connections for real-time progress updates."""
    
    def __init__(self):
        # Map of thread_id -> list of WebSocket connections
        self.active_connections: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, thread_id: str):
        """Accept a new WebSocket connection for a thread."""
        await websocket.accept()
        if thread_id not in self.active_connections:
            self.active_connections[thread_id] = []
        self.active_connections[thread_id].append(websocket)
        print(f"📡 WebSocket connected for thread: {thread_id}")
    
    def disconnect(self, websocket: WebSocket, thread_id: str):
        """Remove a WebSocket connection."""
        if thread_id in self.active_connections:
            if websocket in self.active_connections[thread_id]:
                self.active_connections[thread_id].remove(websocket)
            if not self.active_connections[thread_id]:
                del self.active_connections[thread_id]
        print(f"📡 WebSocket disconnected for thread: {thread_id}")
    
    async def send_progress(self, thread_id: str, progress_data: dict):
        """Send progress update to all connections for a thread."""
        if thread_id not in self.active_connections:
            return
        
        disconnected = []
        for connection in self.active_connections[thread_id]:
            try:
                await connection.send_json(progress_data)
            except Exception as e:
                print(f"Error sending to WebSocket: {e}")
                disconnected.append(connection)
        
        # Clean up disconnected sockets
        for conn in disconnected:
            self.disconnect(conn, thread_id)
    
    async def broadcast_to_thread(self, thread_id: str, message_type: str, data: dict):
        """Broadcast a typed message to all connections for a thread."""
        await self.send_progress(thread_id, {
            "type": message_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

# Global WebSocket manager instance
progress_manager = ProgressConnectionManager()

# Helper function to send progress updates (can be called from anywhere)
async def broadcast_progress(thread_id: str, current_step: int, total_steps: int, 
                             step_name: str, agent: str = None, status: str = "executing"):
    """Helper to broadcast progress updates to connected clients."""
    await progress_manager.broadcast_to_thread(thread_id, "progress", {
        "current_step": current_step,
        "total_steps": total_steps,
        "step_name": step_name,
        "agent": agent,
        "status": status
    })

# Initialize LLM
llm = ChatOpenAI(
    model=LLM_MODEL, temperature=LLM_TEMPERATURE, openai_api_key=OPENAI_API_KEY
)

# Initialize Conversational Agent
conversational_agent = ConversationalAgent(
    openai_api_key=OPENAI_API_KEY,
    model=LLM_MODEL,
    quick_model=QUICK_MODEL,
    temperature=0.2,  # Lower temperature for more consistent clarifications
)

# ============================================================
# CONVERSATION STATE MANAGEMENT (SQLite-backed with in-memory cache)
# ============================================================
# In-memory cache for active conversations (fast access during session)
# SQLite persistence via ThreadManager for durability across restarts
CONVERSATIONS = {}


def get_conversation_state(conversation_id: str) -> Optional[Any]:
    """
    Get conversation state from cache or SQLite.
    Provides fast access with persistence fallback.
    """
    # Check in-memory cache first
    if conversation_id in CONVERSATIONS:
        return CONVERSATIONS[conversation_id]
    
    # Try to load from SQLite via ThreadManager (standalone table)
    try:
        state_dict = conversational_agent.thread_manager.load_conversation_state_standalone(conversation_id)
        if state_dict:
            # Reconstruct ConversationState from dict
            # Handle intent enum conversion
            if state_dict.get("intent") and isinstance(state_dict["intent"], str):
                try:
                    state_dict["intent"] = ConversationIntent(state_dict["intent"])
                except ValueError:
                    state_dict["intent"] = None
            
            state = ConversationState(**state_dict)
            # Cache it for future access
            CONVERSATIONS[conversation_id] = state
            print(f"📂 Loaded conversation state from SQLite: {conversation_id}")
            return state
    except Exception as e:
        print(f"⚠️ Error loading conversation state: {e}")
    
    return None


def save_conversation_state(conversation_id: str, state: Any):
    """
    Save conversation state to both cache and SQLite.
    Ensures durability across server restarts.
    """
    # Update in-memory cache
    CONVERSATIONS[conversation_id] = state
    
    # Persist to SQLite (standalone table, no FK constraint)
    try:
        conversational_agent.thread_manager.save_conversation_state_standalone(conversation_id, state)
        print(f"💾 Saved conversation state to SQLite: {conversation_id}")
    except Exception as e:
        print(f"⚠️ Error saving conversation state: {e}")


def remove_conversation_state(conversation_id: str):
    """Remove conversation state from both cache and SQLite."""
    # Remove from cache
    if conversation_id in CONVERSATIONS:
        del CONVERSATIONS[conversation_id]
    
    # Note: SQLite cleanup handled by thread deletion


# Pydantic models for API (defined in models/models.py, available via `from models.models import *`)
# UserRequest, CreateThreadRequest, WorkflowResponse, SharedState


# NOTE: The main get_action_risk_level, requires_approval, generate_action_id,
# PendingAction class, and store/get/remove_pending_action functions are defined
# below (around line 700+) with SQLite integration support.


# ===================================================================
# STRUCTURED OUTPUT MODELS for Plan Generation
# ===================================================================
class PlanStep(BaseModel):
    agent: str = Field(description="Agent name, e.g. gmail_agent, docs_agent")
    tool: str = Field(description="Tool name from the agent's available tools")
    inputs: Dict[str, Any] = Field(description="Input parameters; use {{ variable }} for references to previous step outputs")
    output_variables: Dict[str, str] = Field(default_factory=dict, description='Map of new_var_name to source_field from tool response, e.g. {"email_id": "emails[0].message_id"}')
    description: str = Field(description="Human-readable description of what this step does")

class ExecutionPlan(BaseModel):
    steps: List[PlanStep] = Field(description="Ordered list of execution steps")


def supervisor_node(state: SharedState) -> SharedState:
    """
    STEP 1: Supervisor generates a plan based on user input
    Enhanced to support multi-step workflows with data dependencies
    
    TOKEN OPTIMIZATION: Single LLM call identifies agents + tools together.
    Dynamic workflow hints injected only when template+data pattern detected.
    """
    print(">>> RUNNING SUPERVISOR NODE VERSION 2 <<<")
    print("\n" + "=" * 60)
    print("🧠 SUPERVISOR NODE - Planning Phase")
    print("=" * 60)

    user_input = state["input"]
    context = state.get("context", {})
    print(f"📥 User Input: {user_input}\n")
    trace.step("supervisor_node", f"Planning for: {user_input[:80]}")

    # Extract date info from context
    today_date = context.get("today_date", "")
    print(f"📅 Context dates: today={today_date}")

    # Reuse the tool filter from Tier 1 if available (avoids a redundant LLM call)
    cached_tool_filter = context.get("_cached_tool_filter")
    if cached_tool_filter:
        from tool_filter import get_filtered_capabilities_v2
        filtered_capabilities = get_filtered_capabilities_v2(cached_tool_filter)
        tool_filter = cached_tool_filter
        print(f"📌 Reusing cached tool filter from Tier 1 (saved 1 LLM call)")
        trace.step("agent_filtering", f"reused cached filter, agents={list(filtered_capabilities.keys())}")
    else:
        filtered_capabilities, tool_filter = get_optimized_capabilities(user_input)
        trace.step("agent_filtering", f"fresh classification")
    relevant_agents = list(filtered_capabilities.keys())
    
    print(f"📌 Relevant agents: {relevant_agents}")
    print(f"🔧 Filtered tools: {tool_filter}")
    
    # ===================================================================
    # BUILD SYSTEM PROMPT
    # ===================================================================
    
    capability_summary = json.dumps(filtered_capabilities, indent=2)

    # Build dynamic context variables list (exclude internal keys starting with _)
    context_keys = [k for k in context.keys() if k != "today_date" and not k.startswith("_")]
    context_vars_note = ""
    if context_keys:
        context_vars_note = f"\n\nAVAILABLE CONTEXT VARIABLES: {', '.join(context_keys)}"
        if "uploaded_file" in context:
            uf = context["uploaded_file"]
            context_vars_note += f"\n- uploaded_file: {{{{ uploaded_file.temp_path }}}} (file: {uf.get('filename', 'unknown')})"
        if "extracted_file_text" in context:
            context_vars_note += f"\n- extracted_file_text: {{{{ extracted_file_text }}}} (text content extracted from uploaded file)"

    # System prompt: fixed rules + example first (cacheable prefix),
    # dynamic date/context/capabilities appended at the end
    system_prompt = f"""You are the Supervisor agent creating multi-step execution plans.

PLANNING RULES:
1. Reference previous outputs using {{{{ variable_name }}}} syntax
2. Declare output_variables as {{"new_name": "source_field"}} to rename fields from tool's "returns"
3. Break tasks into sequential steps with clear data flow
4. Use {{{{ today_date }}}} for date references (format: YYYY-MM-DD). For relative dates (yesterday, last week, etc.), compute from today_date.
5. For ANY email sending: create_draft_email first, then optionally send_draft_email if explicitly requested
6. Follow tool-specific instructions in the capabilities (array_access hints, workflow definitions, can_be_derived_from)
7. When uploaded_file is present in context: use {{{{ uploaded_file.temp_path }}}} for file_path inputs and {{{{ uploaded_file.filename }}}} for filename inputs.

EXAMPLE:
User: "Find the latest email from john@example.com and reply saying thanks"
{{{{
  "steps": [
    {{{{
      "agent": "gmail_agent",
      "tool": "search_emails",
      "inputs": {{"query": "from:john@example.com", "max_results": 1}},
      "output_variables": {{"latest_email_id": "emails[0].message_id"}},
      "description": "Search for latest email from john@example.com"
    }}}},
    {{{{
      "agent": "gmail_agent",
      "tool": "reply_to_email",
      "inputs": {{"message_id": "{{{{{{ latest_email_id }}}}}}", "reply_body": "Thanks!"}},
      "output_variables": {{}},
      "description": "Reply to the email saying thanks"
    }}}}
  ]
}}}}

CURRENT DATE CONTEXT:
- Today's date: {today_date}
{context_vars_note}

Available agents and tools:
{capability_summary}"""

    # Calculate token stats
    total_tools = sum(len(tools) for tools in tool_filter.values())
    all_tools_count = sum(len(agent_capabilities[a]["tools"]) for a in agent_capabilities)
    
    print("🤖 Calling LLM to generate multi-step plan...")
    print(f"💰 Token optimization:")
    print(f"   Agents: {len(relevant_agents)}/{len(agent_capabilities)}")
    print(f"   Tools: {total_tools}/{all_tools_count}")
    print(f"   Context size: {len(capability_summary):,} chars (~{len(capability_summary)//4:,} tokens)")
    trace.step("plan_generation_start", f"agents={len(relevant_agents)}/{len(agent_capabilities)}, tools={total_tools}/{all_tools_count}, context_tokens~{len(capability_summary)//4}")

    # ===================================================================
    # STRUCTURED OUTPUT: Plan generation via function calling
    # Eliminates JSON parsing, code-fence extraction, and retry-for-format
    # ===================================================================
    try:
        structured_llm = llm.with_structured_output(
            ExecutionPlan, method="function_calling", include_raw=True
        )

        start_time = time.time()
        result = structured_llm.invoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ]
        )
        duration_ms = (time.time() - start_time) * 1000

        # include_raw=True returns {"raw": AIMessage, "parsed": ExecutionPlan, "parsing_error": ...}
        raw_message = result["raw"]
        execution_plan = result["parsed"]
        parsing_error = result.get("parsing_error")

        if parsing_error:
            raise ValueError(f"Plan parsing failed: {parsing_error}")
        if execution_plan is None:
            raise ValueError("Structured output returned None — LLM did not produce a valid plan")

        # Real token tracking from the raw AIMessage
        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        if hasattr(raw_message, 'response_metadata'):
            token_usage = raw_message.response_metadata.get('token_usage', {})
            input_tokens = token_usage.get('prompt_tokens', 0)
            output_tokens = token_usage.get('completion_tokens', 0)
            cached_tokens = token_usage.get('prompt_tokens_details', {}).get('cached_tokens', 0)

        logger.llm_call(
            model=LLM_MODEL,
            operation="plan_generation",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
            tier="supervisor",
            prompt_summary=f"Planning: {user_input[:50]}...",
            success=True,
            cached_tokens=cached_tokens
        )

        # Convert Pydantic model → dict for downstream compatibility
        plan = execution_plan.model_dump()

        if not plan.get("steps"):
            raise ValueError("Plan has no steps")

        steps = plan["steps"]
        print("✅ Plan generated successfully!")
        print(f"\n📋 Generated Plan:\n{json.dumps(plan, indent=2)}")
        trace.step("plan_generated", f"{len(steps)} steps: {', '.join(s.get('agent','?')+'.'+s.get('tool','?') for s in steps)}")

    except Exception as e:
        if is_llm_error(e):
            raise LLMServiceException(handle_llm_error(e))
        error_msg = f"Failed to generate plan: {str(e)}"
        print(f"❌ {error_msg}")
        trace.error(f"Plan generation failed: {e}")
        raise ValueError(error_msg)

    # Save the plan to a file for inspection
    plan_file = os.path.join(OUTPUT_DIR, "supervisor_plan.json")
    with open(plan_file, "w") as f:
        json.dump(plan, f, indent=2)
    print(f"\n💾 Plan saved to: {plan_file}")
    print("=" * 60 + "\n")

    return {"plan": plan, "context": state.get("context", {})}
# ============================================================================
# PENDING ACTIONS - SQLite Storage (stateless, Lambda-ready)
# ============================================================================


def get_action_risk_level(tool_name: str) -> ActionRiskLevel:
    """Get risk level for a tool"""
    return ACTION_RISK_LEVELS.get(tool_name, ActionRiskLevel.MODERATE)


def requires_approval(tool_name: str, auto_approve_moderate: bool = True) -> bool:
    """Check if action requires approval based on risk level"""
    risk = get_action_risk_level(tool_name)

    if risk == ActionRiskLevel.SAFE:
        return False
    elif risk == ActionRiskLevel.MODERATE:
        return not auto_approve_moderate  # Configurable
    elif risk in [ActionRiskLevel.DANGEROUS, ActionRiskLevel.CRITICAL]:
        return True

    return True  # Default to requiring approval


class PendingAction:
    """Represents an action waiting for approval - stored in SQLite"""

    def __init__(self, action_id: str, step_info: dict, execution_callback: Callable = None,
                 thread_id: str = None, conversation_id: str = None, request_id: str = None):
        self.action_id = action_id
        self.step_info = step_info
        self.execution_callback = execution_callback
        self.status = "pending"
        self.result = None
        self.created_at = datetime.now()
        self.thread_id = thread_id
        self.conversation_id = conversation_id
        self.request_id = request_id

    def to_dict(self):
        risk_level = get_action_risk_level(self.step_info.get("tool"))
        return {
            "action_id": self.action_id,
            "step_number": self.step_info.get("step_number"),
            "agent": self.step_info.get("agent"),
            "tool": self.step_info.get("tool"),
            "description": self.step_info.get("description"),
            "inputs": self.step_info.get("inputs"),
            "risk_level": risk_level.value if hasattr(risk_level, 'value') else str(risk_level),
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "thread_id": self.thread_id,
            "conversation_id": self.conversation_id,
        }


def generate_action_id() -> str:
    """Generate unique action ID"""
    return f"action_{uuid.uuid4().hex[:8]}"


def extract_nested_value(data: dict, path: str):
    """
    Extract value from nested dictionary/list using path notation.

    Examples:
        path="drafts[0].id" -> data["drafts"][0]["id"]
        path="messages[-1].body" -> data["messages"][-1]["body"]
        path="user.name" -> data["user"]["name"]
        path="emails[2].subject" -> data["emails"][2]["subject"]

    Returns:
        The extracted value, or None if path not found
    """
    import re

    # Split path by dots, but preserve array indices
    # Example: "drafts[0].id" -> ["drafts[0]", "id"]
    parts = path.split(".")

    current = data
    for part in parts:
        # Check if this part has array index notation: "field[index]" or "field[-index]"
        match = re.match(r"(\w+)\[(-?\d+)\]", part)
        if match:
            field_name = match.group(1)
            index = int(match.group(2))

            # First access the field
            if isinstance(current, dict) and field_name in current:
                current = current[field_name]
            else:
                return None

            # Then access the array index (supports negative indexing)
            if isinstance(current, list):
                try:
                    current = current[index]
                except IndexError:
                    return None
            else:
                return None
        else:
            # Simple field access
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None

    return current


def store_pending_action(action: PendingAction):
    """Store action waiting for approval in SQLite"""
    storage = LogStorage()
    
    thread_id = action.thread_id or get_current_thread_id()
    conversation_id = action.conversation_id or get_current_conversation_id()
    request_id = action.request_id or get_current_request_id()
    
    risk_level = get_action_risk_level(action.step_info.get("tool"))
    
    storage.insert_pending_action(
        action_id=action.action_id,
        agent_name=action.step_info.get("agent", "unknown"),
        tool_name=action.step_info.get("tool", "unknown"),
        step_number=action.step_info.get("step_number"),
        description=action.step_info.get("description"),
        inputs=action.step_info.get("inputs"),
        output_variables=action.step_info.get("output_variables"),
        risk_level=risk_level.value if hasattr(risk_level, 'value') else str(risk_level),
        thread_id=thread_id,
        conversation_id=conversation_id,
        request_id=request_id,
        expires_in_minutes=30
    )
    
    logger.info(
        f"Pending action stored: {action.action_id}",
        component="approval",
        operation="store_pending_action",
        extra={
            "action_id": action.action_id,
            "agent": action.step_info.get("agent"),
            "tool": action.step_info.get("tool"),
            "risk_level": risk_level.value if hasattr(risk_level, 'value') else str(risk_level),
            "thread_id": thread_id
        }
    )


def get_pending_action(action_id: str) -> Optional[PendingAction]:
    """Retrieve pending action from the database"""
    storage = LogStorage()
    
    action_data = storage.get_pending_action(action_id)
    if not action_data:
        return None
    
    step_info = {
        "step_number": action_data.get("step_number"),
        "agent": action_data.get("agent_name"),
        "tool": action_data.get("tool_name"),
        "description": action_data.get("description"),
        "inputs": action_data.get("inputs"),
        "output_variables": action_data.get("output_variables"),
        "risk_level": action_data.get("risk_level"),
    }
    
    action = PendingAction(
        action_id=action_id,
        step_info=step_info,
        execution_callback=None,
        thread_id=action_data.get("thread_id"),
        conversation_id=action_data.get("conversation_id"),
        request_id=action_data.get("request_id")
    )
    action.status = action_data.get("status", "pending")
    action.created_at = datetime.fromisoformat(action_data.get("created_at")) if action_data.get("created_at") else datetime.now()
    
    return action


def remove_pending_action(action_id: str):
    """Remove completed action from the database"""
    storage = LogStorage()
    storage.delete_pending_action(action_id)
    
    logger.info(
        f"Pending action removed: {action_id}",
        component="approval",
        operation="remove_pending_action",
        extra={"action_id": action_id}
    )


def get_all_pending_actions(thread_id: str = None) -> List[Dict]:
    """Get all pending actions from SQLite"""
    storage = LogStorage()
    
    return storage.get_pending_actions(thread_id=thread_id, status="pending")


def orchestrator_node(state: SharedState) -> SharedState:
    """
    Executes the plan by calling specialized agent microservices via HTTP.
    Supports both tool-based and task-based execution formats.
    Manages variable substitution and context flow between steps.
    """
    print("\n" + "=" * 60)
    print("⚙️ ORCHESTRATOR NODE - Execution Phase")
    print("=" * 60)

    # ===================================================================
    # 🔍 DEBUG: Print incoming state structure
    # ===================================================================

    plan_dict = state.get("plan", {})
    plan = plan_dict.get("steps", [])
    variable_context = state.get("context", {})
    results = []

    if not plan:
        print("❌ ERROR: No steps found in plan!")
        print(f"📋 Plan structure: {json.dumps(plan_dict, indent=2)}")
        trace.error("No steps found in plan", data={"plan_keys": list(plan_dict.keys())})
        return {
            "final_context": variable_context,
            "context": variable_context,
            "results": [],
            "error": "No steps to execute in plan"
        }
    
    print(f"✅ Found {len(plan)} steps to execute")
    trace.step("orchestrator_node", f"{len(plan)} steps to execute")
        
    
    # Get thread_id from logging context for WebSocket broadcasting
    thread_id = get_current_thread_id()
    
    # Helper to broadcast progress via WebSocket (handles sync context)
    def broadcast_ws_progress(step: int, total: int, step_name: str, agent: str = None, status: str = "executing"):
        if thread_id:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If we're in an async context, create a task
                    asyncio.create_task(broadcast_progress(thread_id, step, total, step_name, agent, status))
                else:
                    # If no event loop is running, run synchronously
                    loop.run_until_complete(broadcast_progress(thread_id, step, total, step_name, agent, status))
            except RuntimeError:
                # Create new event loop if none exists
                asyncio.run(broadcast_progress(thread_id, step, total, step_name, agent, status))
            except Exception as e:
                print(f"⚠️ WebSocket broadcast error: {e}")

    # Print initial context
    print("\n📦 INITIAL CONTEXT:")
    print("─" * 60)
    for key, value in variable_context.items():
        if isinstance(value, (list, dict)):
            print(f"   {key}: {type(value).__name__} (length: {len(value)})")
        else:
            print(f"   {key}: {value}")
    print("─" * 60)

    # Jinja2 for variable substitution

    # ===================================================================
    # PRE-FLIGHT: Build and validate Google credentials ONCE before loop
    # ===================================================================
    credentials_dict = {
        "access_token": os.getenv("GOOGLE_ACCESS_TOKEN"),
        "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN"),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": os.getenv("GOOGLE_CLIENT_ID") or os.getenv("OAUTH_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET") or os.getenv("OAUTH_CLIENT_SECRET"),
    }
    # Remove None/empty values (Google rejects these)
    credentials_dict = {k: v for k, v in credentials_dict.items() if v}

    required_cred_fields = ["access_token", "refresh_token", "client_id", "client_secret"]
    missing_cred_fields = [f for f in required_cred_fields if not credentials_dict.get(f)]

    if missing_cred_fields:
        error_msg = f"Missing required Google credentials: {', '.join(missing_cred_fields)}. Cannot execute plan."
        print(f"❌ {error_msg}")
        trace.error(error_msg, data={"missing": missing_cred_fields})
        variable_context["error"] = error_msg
        return {
            "final_context": variable_context,
            "context": variable_context,
            "results": [],
            "stopped_at_step": 0,
            "error": error_msg,
        }

    print(f"✅ Pre-flight credential check passed ({len(credentials_dict)} fields)")

    for step_num, step in enumerate(plan, 1):
        agent_name = step["agent"]
        tool_name = step.get("tool")
        description = step.get("description", "No description")
        inputs = step.get("inputs", {})
        output_variables = step.get("output_variables", {})

        print(f"\n{'='*60}")
        print(f"📍 Step {step_num}/{len(plan)}: {agent_name}.{tool_name}")
        print(f"📝 Description: {description}")
        print(f"{'='*60}")
        
        # === PROGRESS LOGGING (step-based, no percentage) ===
        orchestrator_logger.progress(
            f"Executing step: {agent_name}.{tool_name}",
            current_step=step_num,
            total_steps=len(plan),
            step_name=f"{agent_name}.{tool_name}",
            extra={"description": description}
        )
        
        # === WEBSOCKET BROADCAST ===
        broadcast_ws_progress(step_num, len(plan), description or f"{agent_name}.{tool_name}", agent_name, "executing")

        # Check if this action requires approval
        risk_level = get_action_risk_level(tool_name)
        needs_approval = requires_approval(tool_name)

        print(f"⚠️ Risk Level: {risk_level.value}")
        if needs_approval:
            print(f"⏸️ PAUSED - Action requires approval!")
            # Substitute variables first so user sees actual values
            substituted_inputs = {}
            for key, value in inputs.items():
                if isinstance(value, str) and "{{" in value and "}}" in value:
                    template = Template(value)
                    rendered = template.render(**variable_context)
                    try:
                        if rendered.startswith("[") or rendered.startswith("{"):
                            substituted_inputs[key] = json.loads(rendered.replace("'", '"'))
                        else:
                            substituted_inputs[key] = rendered
                    except (json.JSONDecodeError, ValueError):
                        substituted_inputs[key] = rendered
                else:
                    substituted_inputs[key] = value

            # Create action approval request
            action_id = generate_action_id()

            step_info = {
                "step_number": step_num,
                "total_steps": len(plan),
                "agent": agent_name,
                "tool": tool_name,
                "description": description,
                "inputs": substituted_inputs,
                "output_variables": output_variables,
                "risk_level": risk_level.value,
            }

            pending_action = PendingAction(
                action_id=action_id,
                step_info=step_info,
                execution_callback=None,
            )
            store_pending_action(pending_action)

            print(f"🔔 Approval required for action: {action_id}")
            print(f"   Details: {json.dumps(step_info, indent=4)}")

            # Collect remaining steps (after the current one)
            remaining_steps = []
            for future_step_num, future_step in enumerate(plan[step_num:], step_num + 1):
                remaining_steps.append({
                    "step_number": future_step_num,
                    "agent": future_step.get("agent"),
                    "tool": future_step.get("tool"),
                    "description": future_step.get("description", ""),
                    "inputs": future_step.get("inputs", {}),
                    "output_variables": future_step.get("output_variables", {}),
                })

            # Record this step as pending
            results.append({
                "step": step_num,
                "agent": agent_name,
                "tool": tool_name,
                "status": "pending_approval",
                "action_id": action_id,
                "description": description,
            })

            # STOP the loop — return with pending info so threads.py can pause workflow
            print(f"⏸️ WORKFLOW PAUSED — waiting for chat-based approval")
            variable_context["results"] = results
            
            # Include approval metadata in final_context so it flows to WorkflowResponse
            variable_context["paused_for_approval"] = True
            variable_context["pending_action"] = step_info
            variable_context["pending_action_id"] = action_id
            variable_context["remaining_steps"] = remaining_steps
            
            # Preserve ReAct state for resumption (if in react mode) — DISABLED
            # if state.get("react_history") is not None:
            #     variable_context["react_history"] = state.get("react_history", [])
            #     variable_context["react_iteration"] = state.get("react_iteration", 0)

            # === WEBSOCKET BROADCAST: Paused for approval ===
            broadcast_ws_progress(step_num, len(plan), f"Awaiting approval: {description}", agent_name, "paused")

            return {
                "final_context": variable_context,
                "context": variable_context,
                "results": results,
            }

        # No approval needed — execute normally

        # STEP 1: Variable Substitution
        print(f"\n🔄 Substituting variables in inputs...")
        print(f"   Original inputs: {json.dumps(inputs, indent=6)}")

        substituted_inputs = {}
        for key, value in inputs.items():
            if isinstance(value, str):
                # Use Jinja2 to substitute {{ variables }}
                template = Template(value)
                rendered = template.render(**variable_context)
                # If the rendered value is a file_path and it came from uploaded_file,
                # ensure the file is available locally (downloads from S3 if needed)
                if key == "file_path" and rendered and "uploaded_file" in variable_context:
                    from s3_temp_storage import resolve_file_to_local_path
                    rendered = resolve_file_to_local_path(variable_context["uploaded_file"])
                substituted_inputs[key] = rendered
            elif key == "file_path" and "uploaded_file" in variable_context:
                # Non-string file_path — resolve from uploaded_file context
                from s3_temp_storage import resolve_file_to_local_path
                substituted_inputs[key] = resolve_file_to_local_path(variable_context["uploaded_file"])
            else:
                substituted_inputs[key] = value

        print(f"   Substituted inputs: {json.dumps(substituted_inputs, indent=6)}")
        print(f"   Available context variables: {list(variable_context.keys())}")
        trace.step("variable_substitution", f"step {step_num}: {agent_name}.{tool_name}", data={"inputs": substituted_inputs, "context_keys": list(variable_context.keys())})

        # STEP 2: Call Agent Microservice
        agent_url = AGENT_ENDPOINTS.get(agent_name)
        if not agent_url:
            error_msg = f"No endpoint configured for agent: {agent_name}"
            print(f"❌ {error_msg}")
            trace.error(f"No endpoint for {agent_name}", data={"step": step_num})
            results.append({
                "step": step_num,
                "agent": agent_name,
                "tool": tool_name,
                "status": "error",
                "error": error_msg,
            })
            continue

        print(f"\n🌐 Calling agent microservice: {agent_url}")

        # Prepare request payload (tool-based format)
        request_payload = {
            "tool": tool_name,
            "inputs": substituted_inputs,
            "credentials_dict": credentials_dict  # Only string values, no expiry/scopes
        }

        # 🔍 DEBUG: Print request payload structure (without sensitive data)
        print(f"\n🔍 REQUEST PAYLOAD STRUCTURE:")
        print("─" * 60)
        print(f"   Tool: {request_payload['tool']}")
        print(f"   Inputs keys: {list(request_payload['inputs'].keys())}")
        print(f"   Credentials keys: {list(request_payload['credentials_dict'].keys())}")
        print(f"   Credentials types: {{{', '.join([f'{k}: {type(v).__name__}' for k, v in request_payload['credentials_dict'].items()])}}}")
        print(f"   Payload size: {len(json.dumps(request_payload, default=str))} bytes")
        print("─" * 60)

        try:
            # === AGENT CALL TIMING ===
            agent_start_time = time.time()
            
            print(f"\n🚀 Sending request to agent...")
            print(f"   URL: {agent_url}")
            print(f"   Timeout: 320 seconds")
            print(f"   Max retries: 3")
            
            # Use retry logic with longer timeout (320 seconds) and exponential backoff
            result = call_agent_with_retry(
                agent_url=agent_url,
                request_payload=request_payload,
                max_retries=3,
                timeout=320.0,
            )
            
            agent_duration_ms = (time.time() - agent_start_time) * 1000
            print(f"⏱️ Agent call completed in {agent_duration_ms:.2f}ms")

            if not result:
                raise ValueError("Agent call failed after retries")

            print(f"✅ Agent response received")
            trace.agent_call(agent_name, tool_name, substituted_inputs,
                             success=result.get("success", False), duration_ms=agent_duration_ms)
            print(f"\n{'─'*60}")
            print(f"📦 FULL AGENT RESPONSE DATA:")
            print(f"{'─'*60}")
            print(json.dumps(result, indent=2))
            print(f"{'─'*60}\n")

            # STEP 3: Extract variables from result
            if result.get("success"):
                # The agent response can be in two formats:
                # 1. Direct format: {"success": true, "drafts": [...], ...}
                # 2. Wrapped format: {"success": true, "result": {"drafts": [...]}, ...}
                # Try wrapped format first, fall back to direct format
                agent_result = result.get("result", result)

                # First, add ALL fields from the result to context (for backward compatibility)
                # But exclude common wrapper fields
                fields_to_add = {
                    k: v
                    for k, v in agent_result.items()
                    if k not in ["success", "error"]
                }
                variable_context.update(fields_to_add)

                # Namespace the full result under step_{N}_{agent} to prevent collisions
                namespace_key = f"step_{step_num}_{agent_name}"
                variable_context[namespace_key] = fields_to_add

                # Then, create renamed variables based on output_variables mapping
                # Format: "new_variable_name": "source_field_name" or "nested.path[0].field"
                print(f"\n📦 Variables added to context:")
                for new_var_name, source_field_name in output_variables.items():
                    # Try nested path extraction first (handles "drafts[0].id")
                    value = extract_nested_value(agent_result, source_field_name)

                    if value is not None:
                        variable_context[new_var_name] = value
                        print(
                            f"   ✓ {new_var_name} = {value} (from {source_field_name})"
                        )
                    # Fallback to simple field access for backward compatibility
                    elif source_field_name in agent_result:
                        variable_context[new_var_name] = agent_result[source_field_name]
                        print(
                            f"   ✓ {new_var_name} = {agent_result[source_field_name]} (from {source_field_name})"
                        )
                    else:
                        print(
                            f"   ⚠️ {new_var_name} = NOT FOUND (looking for {source_field_name} in result)"
                        )

                # Print updated context after this step
                print(f"\n📊 CONTEXT AFTER STEP {step_num}:")
                print("─" * 60)
                for key, value in variable_context.items():
                    if isinstance(value, list):
                        if len(value) > 0 and isinstance(value[0], dict):
                            # Array of objects (like emails)
                            print(f"   {key}: Array[{len(value)} items]")
                            if len(value) > 0:
                                print(
                                    f"      └─ First item keys: {list(value[0].keys())}"
                                )
                        else:
                            print(f"   {key}: {value}")
                    elif isinstance(value, dict):
                        print(f"   {key}: Dict with keys: {list(value.keys())}")
                    else:
                        print(f"   {key}: {value}")
                print("─" * 60)

                # Store step result
                results.append(
                    {
                        "step": step_num,
                        "agent": agent_name,
                        "tool": tool_name,
                        "description": description,
                        "inputs": substituted_inputs,
                        "output": agent_result,
                        "status": "success",
                    }
                )
                
                # === AGENT CALL LOGGING (success) ===
                orchestrator_logger.agent_call(
                    agent_name=agent_name,
                    tool_name=tool_name,
                    step_number=step_num,
                    total_steps=len(plan),
                    inputs=substituted_inputs,
                    success=True,
                    duration_ms=agent_duration_ms,
                    output_summary=f"Fields returned: {list(agent_result.keys())}"
                )
            else:
                # Handle failure - distinguish between no_results and actual errors
                error_msg = result.get("error", "Unknown error")
                is_no_results = result.get("no_results", False)

                # 🔍 DEBUG: Print error details
                print(f"\n🔍 ERROR RESPONSE DETAILS:")
                print("─" * 60)
                print(f"   Error message: {error_msg}")
                print(f"   Is no_results: {is_no_results}")
                print(f"   Full response: {json.dumps(result, indent=2)}")
                print("─" * 60)

                if is_no_results:
                    # Graceful handling for empty results
                    print(f"ℹ️ No results found: {error_msg}")
                    print(
                        f"   This step returned no data, but the operation was valid."
                    )
                    print(f"   Continuing to next step (if any)...")

                    # Store as a special status for tracking
                    results.append(
                        {
                            "step": step_num,
                            "agent": agent_name,
                            "tool": tool_name,
                            "description": description,
                            "inputs": substituted_inputs,
                            "status": "no_results",
                            "message": error_msg,
                            "output": result,
                        }
                    )
                    
                    # === AGENT CALL LOGGING (no results) ===
                    orchestrator_logger.agent_call(
                        agent_name=agent_name,
                        tool_name=tool_name,
                        step_number=step_num,
                        total_steps=len(plan),
                        inputs=substituted_inputs,
                        success=True,  # No results is not a failure
                        duration_ms=agent_duration_ms,
                        output_summary="No results found (valid operation)"
                    )

                    # Add empty result context to prevent downstream failures
                    # Extract the result format to add empty defaults
                    agent_result = result.get("result", result)
                    fields_to_add = {
                        k: v
                        for k, v in agent_result.items()
                        if k not in ["success", "error", "no_results"]
                    }
                    variable_context.update(fields_to_add)

                    print(
                        f"   Added empty context fields: {list(fields_to_add.keys())}"
                    )
                else:
                    # Actual error occurred - STOP EXECUTION
                    print(f"❌ Agent reported error: {error_msg}")
                    print(f"🛑 STOPPING WORKFLOW - Error in step {step_num}")

                    results.append(
                        {
                            "step": step_num,
                            "agent": agent_name,
                            "tool": tool_name,
                            "description": description,
                            "inputs": substituted_inputs,
                            "status": "error",
                            "error": error_msg,
                        }
                    )
                    
                    # === AGENT CALL LOGGING (error) ===
                    orchestrator_logger.agent_call(
                        agent_name=agent_name,
                        tool_name=tool_name,
                        step_number=step_num,
                        total_steps=len(plan),
                        inputs=substituted_inputs,
                        success=False,
                        duration_ms=agent_duration_ms,
                        error=error_msg
                    )

                    # Stop workflow and return early
                    print(f"\n{'='*60}")
                    print("🛑 ORCHESTRATOR STOPPED DUE TO ERROR")
                    print(f"{'='*60}")
                    print(f"📊 Completed steps: {step_num}/{len(plan)}")
                    print(
                        f"✓ Successful: {sum(1 for r in results if r.get('status') == 'success')}"
                    )
                    print(
                        f"ℹ️ No Results: {sum(1 for r in results if r.get('status') == 'no_results')}"
                    )
                    print(f"✗ Failed at step: {step_num}")
                    print(f"{'='*60}\n")

                    # Include results in final_context for summary generation
                    variable_context["results"] = results
                    variable_context["stopped_at_step"] = step_num
                    variable_context["error"] = error_msg

                    return {
                        "final_context": variable_context,
                        "context": variable_context,
                        "results": results,
                        "stopped_at_step": step_num,
                        "error": error_msg,
                    }

        except httpx.HTTPError as e:
            error_msg = f"HTTP error calling {agent_name}: {str(e)}"
            print(f"❌ {error_msg}")
            print(f"🛑 STOPPING WORKFLOW - HTTP Error in step {step_num}")
            trace.error(f"HTTP error step {step_num}: {agent_name}.{tool_name}", data={"error": str(e), "type": type(e).__name__})
            
            # 🔍 DEBUG: Print HTTP error details
            print(f"\n🔍 HTTP ERROR DETAILS:")
            print("─" * 60)
            print(f"   Error type: {type(e).__name__}")
            print(f"   Error message: {str(e)}")
            if hasattr(e, 'response'):
                print(f"   Status code: {getattr(e.response, 'status_code', 'N/A')}")
                print(f"   Response text: {getattr(e.response, 'text', 'N/A')[:500]}")
            print("─" * 60)

            results.append(
                {
                    "step": step_num,
                    "agent": agent_name,
                    "tool": tool_name,
                    "status": "error",
                    "error": error_msg,
                }
            )

            # Stop workflow and return early
            print(f"\n{'='*60}")
            print("🛑 ORCHESTRATOR STOPPED DUE TO HTTP ERROR")
            print(f"{'='*60}")
            print(f"📊 Completed steps: {step_num}/{len(plan)}")
            print(
                f"✓ Successful: {sum(1 for r in results if r.get('status') == 'success')}"
            )
            print(
                f"ℹ️ No Results: {sum(1 for r in results if r.get('status') == 'no_results')}"
            )
            print(f"✗ Failed at step: {step_num}")
            print(f"{'='*60}\n")

            # Include results in final_context for summary generation
            variable_context["results"] = results
            variable_context["stopped_at_step"] = step_num
            variable_context["error"] = error_msg

            return {
                "final_context": variable_context,
                "context": variable_context,
                "results": results,
                "stopped_at_step": step_num,
                "error": error_msg,
            }

        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            print(f"❌ {error_msg}")
            print(f"🛑 STOPPING WORKFLOW - Unexpected Error in step {step_num}")
            trace.error(f"Unexpected error step {step_num}: {agent_name}.{tool_name}", exception=e)
            
            # 🔍 DEBUG: Print full traceback
            print(f"\n🔍 FULL TRACEBACK:")
            print("─" * 60)
            traceback.print_exc()
            print("─" * 60)

            results.append(
                {
                    "step": step_num,
                    "agent": agent_name,
                    "tool": tool_name,
                    "status": "error",
                    "error": error_msg,
                }
            )

            # Stop workflow and return early
            print(f"\n{'='*60}")
            print("🛑 ORCHESTRATOR STOPPED DUE TO UNEXPECTED ERROR")
            print(f"{'='*60}")
            print(f"📊 Completed steps: {step_num}/{len(plan)}")
            print(
                f"✓ Successful: {sum(1 for r in results if r.get('status') == 'success')}"
            )
            print(
                f"ℹ️ No Results: {sum(1 for r in results if r.get('status') == 'no_results')}"
            )
            print(f"✗ Failed at step: {step_num}")
            print(f"{'='*60}\n")

            # Include results in final_context for summary generation
            variable_context["results"] = results
            variable_context["stopped_at_step"] = step_num
            variable_context["error"] = error_msg

            return {
                "final_context": variable_context,
                "context": variable_context,
                "results": results,
                "stopped_at_step": step_num,
                "error": error_msg,
            }

    success_count = sum(1 for r in results if r.get('status') == 'success')
    no_results_count = sum(1 for r in results if r.get('status') == 'no_results')
    error_count = sum(1 for r in results if r.get('status') == 'error')

    print(f"\n{'='*60}")
    print("✅ ORCHESTRATOR COMPLETED")
    print(f"{'='*60}")
    print(f"📊 Total steps: {len(plan)}")
    print(f"✓ Successful: {success_count}")
    print(f"ℹ️ No Results: {no_results_count}")
    print(f"✗ Failed: {error_count}")
    print(f"{'='*60}\n")
    trace.step("orchestrator_complete", f"steps={len(plan)}, success={success_count}, no_results={no_results_count}, errors={error_count}")

    # Include results in final_context for summary generation
    variable_context["results"] = results

    # === WEBSOCKET BROADCAST: Completion ===
    broadcast_ws_progress(len(plan), len(plan), "All steps completed", None, "completed")

    return {
        "final_context": variable_context,
        "context": variable_context,
        "results": results,
    }


# Build langraph workflow
graph = StateGraph(SharedState)
graph.add_node("supervisor", supervisor_node)
graph.add_node("orchestrator", orchestrator_node)

graph.set_entry_point("supervisor")
graph.add_edge("supervisor", "orchestrator")
graph.add_edge("orchestrator", END)

workflow = graph.compile()

print("✅ Workflow graph compiled (FULL WORKFLOW)")
print("   Flow: supervisor → orchestrator → END")
print(f"   Plans saved to: {OUTPUT_DIR}/supervisor_plan.json")
print(f"   Agent endpoints: {list(AGENT_ENDPOINTS.keys())}")


# ============================================================================
# REACT WORKFLOW — Iterative Reason-Act-Observe Loop (COMMENTED OUT)
# ============================================================================
# To re-enable ReAct: uncomment the block below and set react_workflow = react_graph.compile()
#
# Instead of planning all steps upfront (standard), the ReAct workflow:
#   1. react_planner: observes previous results → thinks → generates ONE next step
#   2. orchestrator: executes that single step (reuses existing orchestrator_node)
#   3. route_react_plan: checks if planner said done → END, else → orchestrator
#   4. After execution, loops back to planner with new observations
#
# Graph: react_planner → [route_react_plan] → orchestrator → react_planner → ...
# ============================================================================

# --- REACT FLOW DISABLED — uncomment to re-enable ---
react_workflow = None  # Stub so imports don't break

# MAX_REACT_ITERATIONS = 10
#
#
# class ReactStep(BaseModel):
#     """Structured output for a single ReAct iteration."""
#     thought: str = Field(description="Reasoning about what to do next based on observations so far")
#     next_step: Optional[PlanStep] = Field(default=None, description="Next step to execute, or null if task is done")
#     done: bool = Field(description="True if the task is fully complete, False if more steps are needed")
#     summary: Optional[str] = Field(default=None, description="Final summary of what was accomplished (set when done=True)")
#
#
# def _summarize_react_observation(output: dict) -> str:
#     """Create a compact summary of a step's output for the react history prompt."""
#     if not output:
#         return "No output"
#     summary_parts = []
#     for key, value in output.items():
#         if key in ("success", "error"):
#             continue
#         if isinstance(value, list):
#             summary_parts.append(f"{key}: [{len(value)} items]")
#         elif isinstance(value, dict):
#             summary_parts.append(f"{key}: {{{', '.join(list(value.keys())[:5])}}}")
#         elif isinstance(value, str) and len(value) > 100:
#             summary_parts.append(f"{key}: {value[:100]}...")
#         else:
#             summary_parts.append(f"{key}: {value}")
#     return "; ".join(summary_parts) if summary_parts else "Empty result"
#
#
# def react_planner_node(state: SharedState) -> SharedState:
#     """
#     ReAct planner node: observe → think → plan ONE next step (or declare done).
#
#     On first call react_history is empty — generates the first step.
#     On subsequent calls it sees accumulated observations and decides the next
#     action or declares the task complete.
#     """
#     print("\n" + "=" * 60)
#     print("🧠 REACT PLANNER — Reason + Act")
#     print("=" * 60)
#
#     user_input = state["input"]
#     context = state.get("context", {})
#     react_history = list(state.get("react_history", []))  # copy to avoid mutation
#     react_iteration = state.get("react_iteration", 0)
#
#     trace.step("react_planner", f"Iteration {react_iteration + 1}, prior observations: {len(react_history)}")
#
#     # ------------------------------------------------------------------
#     # Capture results from the previous orchestrator run (if any)
#     # ------------------------------------------------------------------
#     prev_results = state.get("results", [])
#     for r in prev_results:
#         react_history.append({
#             "agent": r.get("agent", "unknown"),
#             "tool": r.get("tool", "unknown"),
#             "description": r.get("description", ""),
#             "status": r.get("status", "unknown"),
#             "output_summary": _summarize_react_observation(r.get("output", {})),
#             "error": r.get("error"),
#         })
#
#     # ------------------------------------------------------------------
#     # Safety: max iterations
#     # ------------------------------------------------------------------
#     if react_iteration >= MAX_REACT_ITERATIONS:
#         print(f"⚠️ Max iterations reached ({MAX_REACT_ITERATIONS}) — forcing completion")
#         trace.warning(f"React loop hit max iterations ({MAX_REACT_ITERATIONS})")
#         return {
#             "plan": {"steps": []},
#             "react_done": True,
#             "react_iteration": react_iteration,
#             "react_history": react_history,
#         }
#
#     # ------------------------------------------------------------------
#     # Build observation context for the LLM
#     # ------------------------------------------------------------------
#     observation_text = ""
#     if react_history:
#         observation_text = "\n\nPREVIOUS STEPS AND OBSERVATIONS:"
#         for i, obs in enumerate(react_history, 1):
#             observation_text += f"\n\nStep {i}: {obs['agent']}.{obs['tool']} — {obs['description']}"
#             observation_text += f"\n  Status: {obs['status']}"
#             if obs.get("output_summary"):
#                 observation_text += f"\n  Result: {obs['output_summary']}"
#             if obs.get("error"):
#                 observation_text += f"\n  Error: {obs['error']}"
#
#     # ------------------------------------------------------------------
#     # Capabilities & context
#     # ------------------------------------------------------------------
#     filtered_capabilities, tool_filter = get_optimized_capabilities(user_input)
#     capability_summary = json.dumps(filtered_capabilities, indent=2)
#     today_date = context.get("today_date", "")
#
#     context_keys = [k for k in context.keys() if k != "today_date"]
#     context_vars_note = ""
#     if context_keys:
#         context_vars_note = f"\n\nAVAILABLE CONTEXT VARIABLES: {', '.join(context_keys)}"
#         if "uploaded_file" in context:
#             uf = context["uploaded_file"]
#             context_vars_note += f"\n- uploaded_file: {{{{ uploaded_file.temp_path }}}} (file: {uf.get('filename', 'unknown')})"
#
#     total_tools = sum(len(tools) for tools in tool_filter.values())
#     print(f"📌 Relevant agents: {list(filtered_capabilities.keys())}")
#     print(f"🔧 Tools: {total_tools}")
#
#     # ------------------------------------------------------------------
#     # System prompt (ReAct-specific)
#     # ------------------------------------------------------------------
#     system_prompt = f"""You are a ReAct (Reason + Act) agent that solves tasks step-by-step.
#
# CURRENT DATE: {today_date}
#
# APPROACH:
# 1. THINK: Analyse what you have observed so far and what needs to happen next.
# 2. DECIDE: Either plan exactly ONE next step, or declare the task done.
#
# PLANNING RULES:
# 1. Reference previous step outputs using {{{{ variable_name }}}} syntax.
# 2. Declare output_variables as {{"new_name": "source_field"}} to rename fields from the tool response.
# 3. Use {{{{ today_date }}}} for date references (format: YYYY-MM-DD). Compute relative dates from today_date.
# 4. For ANY email sending: create_draft_email first, then optionally send_draft_email.
# 5. Follow tool-specific instructions in the capabilities (array_access hints, workflow definitions, can_be_derived_from).
# 6. When uploaded_file is present in context: use {{{{ uploaded_file.temp_path }}}} for file_path inputs.
# {context_vars_note}
# {observation_text}
#
# Available agents and tools:
# {capability_summary}
#
# Generate your thought process and EXACTLY ONE next step to execute,
# OR set done=true with a summary if the task is fully complete."""
#
#     # ------------------------------------------------------------------
#     # LLM call (structured output — ReactStep)
#     # ------------------------------------------------------------------
#     print("🤖 Calling LLM for next ReAct step...")
#     try:
#         structured_llm = llm.with_structured_output(
#             ReactStep, method="function_calling", include_raw=True
#         )
#
#         start_time = time.time()
#         result = structured_llm.invoke([
#             {"role": "system", "content": system_prompt},
#             {"role": "user", "content": user_input},
#         ])
#         duration_ms = (time.time() - start_time) * 1000
#
#         raw_message = result["raw"]
#         react_step = result["parsed"]
#         parsing_error = result.get("parsing_error")
#
#         if parsing_error:
#             raise ValueError(f"ReactStep parsing failed: {parsing_error}")
#         if react_step is None:
#             raise ValueError("Structured output returned None")
#
#         # Token tracking
#         input_tokens = 0
#         output_tokens = 0
#         if hasattr(raw_message, "response_metadata"):
#             token_usage = raw_message.response_metadata.get("token_usage", {})
#             input_tokens = token_usage.get("prompt_tokens", 0)
#             output_tokens = token_usage.get("completion_tokens", 0)
#
#         logger.llm_call(
#             model=LLM_MODEL,
#             operation=f"react_plan_iter_{react_iteration + 1}",
#             input_tokens=input_tokens,
#             output_tokens=output_tokens,
#             duration_ms=duration_ms,
#             tier="react_planner",
#             prompt_summary=f"React iteration {react_iteration + 1}: {user_input[:50]}...",
#             success=True,
#         )
#
#         print(f"💭 Thought: {react_step.thought}")
#         trace.step("react_thought", react_step.thought[:200])
#
#         # ------------------------------------------------------------------
#         # Done? Return empty plan so route_react_plan sends us to END
#         # ------------------------------------------------------------------
#         if react_step.done or react_step.next_step is None:
#             summary = react_step.summary or "Task completed."
#             print(f"✅ React planner declares DONE: {summary}")
#             trace.step(
#                 "react_done",
#                 f"Complete after {react_iteration} iterations: {summary}",
#             )
#             # Build final_context from accumulated context so downstream summary works
#             # Clean stale error markers from earlier iterations that may have recovered
#             context.pop("stopped_at_step", None)
#             context.pop("error", None)
#             context["react_summary"] = summary
#             context["results"] = [
#                 {"step": i + 1, "agent": h["agent"], "tool": h["tool"],
#                  "description": h["description"], "status": h["status"]}
#                 for i, h in enumerate(react_history)
#             ]
#             return {
#                 "plan": {"steps": []},
#                 "react_done": True,
#                 "react_iteration": react_iteration,
#                 "react_history": react_history,
#                 "final_context": context,
#                 "context": context,
#             }
#
#         # ------------------------------------------------------------------
#         # Not done — wrap the single step as a 1-step plan for orchestrator
#         # ------------------------------------------------------------------
#         step_dict = react_step.next_step.model_dump()
#         plan = {"steps": [step_dict]}
#
#         print(f"📋 Next step: {step_dict['agent']}.{step_dict['tool']}: {step_dict['description']}")
#         trace.step(
#             "react_next_step",
#             f"iter {react_iteration + 1}: {step_dict['agent']}.{step_dict['tool']}",
#         )
#
#         return {
#             "plan": plan,
#             "react_done": False,
#             "react_iteration": react_iteration + 1,
#             "react_history": react_history,
#             "context": context,
#         }
#
#     except Exception as e:
#         if is_llm_error(e):
#             raise LLMServiceException(handle_llm_error(e))
#         trace.error(f"React planning failed: {e}")
#         raise ValueError(f"React planning failed: {str(e)}")
#
#
# def route_react_plan(state: SharedState) -> str:
#     """
#     Conditional routing after react_planner_node.
#     Returns "execute" to run the orchestrator, or "done" to finish.
#     """
#     if state.get("react_done", False):
#         return "done"
#     plan = state.get("plan", {})
#     if not plan.get("steps"):
#         return "done"
#     return "execute"
#
#
# def route_after_orchestrator(state: SharedState) -> str:
#     """
#     Conditional routing after orchestrator_node in ReAct mode.
#     If orchestrator paused for approval, stop the loop (→ END).
#     Otherwise, loop back to react_planner for next step.
#     """
#     final_context = state.get("final_context", {})
#     if final_context.get("paused_for_approval"):
#         print("⏸️ ReAct orchestrator paused for approval — exiting loop")
#         return "paused"
#     return "continue"
#
#
# # Build ReAct workflow graph
# react_graph = StateGraph(SharedState)
# react_graph.add_node("react_planner", react_planner_node)
# react_graph.add_node("orchestrator", orchestrator_node)
#
# react_graph.set_entry_point("react_planner")
# react_graph.add_conditional_edges(
#     "react_planner",
#     route_react_plan,
#     {"execute": "orchestrator", "done": END},
# )
# # After orchestrator: check if paused for approval → END, otherwise → react_planner
# react_graph.add_conditional_edges(
#     "orchestrator",
#     route_after_orchestrator,
#     {"continue": "react_planner", "paused": END},
# )
#
# react_workflow = react_graph.compile()
#
# print("✅ ReAct workflow graph compiled")
# print("   Flow: react_planner → [route] → orchestrator → [paused?] → END or ↺ react_planner")
# print(f"   Max iterations: {MAX_REACT_ITERATIONS}")
# --- END REACT FLOW DISABLED ---

