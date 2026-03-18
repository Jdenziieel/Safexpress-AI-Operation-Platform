#THIS IS THE SUPERVISOR.py
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel
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
import hashlib
import agent_capabilities_v2

# Import models
from models.models import *

# Import configuration
from config import (
    AGENT_ENDPOINTS,
    OUTPUT_DIR,
    PLAN_SCHEMA,
    GOOGLE_ACCESS_TOKEN,
    GOOGLE_REFRESH_TOKEN,
    OPENAI_API_KEY,
    LLM_MODEL,
    LLM_TEMPERATURE,
    SERVER_PORT,
    SERVER_HOST,
)

# Import agent capabilities
from agent_capabilities_v2 import agent_capabilities

# Import utility functions
from utils import (
    identify_relevant_agents,
    get_filtered_capabilities,
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
        # Skip noisy health/docs endpoints
        if request.url.path in ("/health", "/docs", "/openapi.json", "/favicon.ico"):
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


# Pydantic models for API
class UserRequest(BaseModel):
    input: str
    memory: Optional[Dict[str, Any]] = {}
    policies: Optional[List[Dict[str, Any]]] = [{"rule": "allow all for demo"}]


class CreateThreadRequest(BaseModel):
    """Request to create a new conversation thread"""
    user_id: str
    message: Optional[str] = None


class WorkflowResponse(BaseModel):
    status: str
    final_context: Dict[str, Any]
    plan: Dict[str, Any]
    message: str


# SharedState TypedDict for workflow
class SharedState(TypedDict):
    input: str
    plan: dict
    context: dict
    memory: dict
    policy: list
    final_context: dict


# NOTE: PENDING_ACTIONS_CACHE is defined below (around line 450) and is used with SQLite integration.
# The in-memory cache stores execution callbacks while SQLite persists action metadata.


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


# NOTE: The main PendingAction class is defined below (around line 484) with SQLite integration support.
# It includes thread_id, conversation_id, and request_id fields.


def generate_action_id() -> str:
    """Generate unique action ID"""
    return f"action_{uuid.uuid4().hex[:8]}"


# NOTE: The main store_pending_action, get_pending_action, and remove_pending_action
# functions are defined below (lines ~570-680) with SQLite integration.
# The PENDING_ACTIONS_CACHE is used for in-memory caching of execution callbacks.




def supervisor_node(state: SharedState) -> SharedState:
    """
    STEP 1: Supervisor generates a plan based on user input
    Enhanced to support multi-step workflows with data dependencies
    
    TOKEN OPTIMIZATION: Uses two-level filtering:
    1. Agent filtering (identify_relevant_agents)
    2. Tool filtering within agents (identify_relevant_tools_fast)
    3. Compact mode (removes verbose metadata)
    4. Dynamic workflow hints (only when needed)
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
    yesterday_date = context.get("yesterday_date", "")
    print(f"📅 Context dates: today={today_date}, yesterday={yesterday_date}")

    # OPTIMIZATION V2: Two-level filtering (agents + tools)
    # ✅ FIX: Force inclusion of drive_agent for template+data workflows
    needs_template_data = any(word in user_input.lower() for word in ['template', 'data', 'mom'])
    
    filtered_capabilities, tool_filter = get_optimized_capabilities(
        user_input,
        use_llm_filter=False,  # Use fast keyword matching (0 tokens)
        compact_mode=True       # Remove verbose metadata
    )
    relevant_agents = list(filtered_capabilities.keys())
    
    # Force add drive_agent if template+data detected and not already included
    if needs_template_data and 'drive_agent' not in relevant_agents:
        print("⚠️ WARNING: drive_agent missing for template+data workflow, force adding...")
        relevant_agents.append('drive_agent')
        # Add drive_agent from the globally imported capabilities
        filtered_capabilities['drive_agent'] = agent_capabilities_v2.agent_capabilities['drive_agent']
    
    print(f"📌 Relevant agents: {relevant_agents}")
    print(f"🔧 Filtered tools: {tool_filter}")

    # ===================================================================
    # 🚀 DYNAMIC WORKFLOW HINT INJECTION (ONLY WHEN NEEDED)
    # ===================================================================
    
    def detect_template_data_workflow(user_msg: str) -> bool:
        """Detect if user wants template+data document creation"""
        msg_lower = user_msg.lower()
        
        # Check for both template AND data mentions
        has_template = any(word in msg_lower for word in ['template', 'format', 'mom'])
        has_data = any(word in msg_lower for word in ['data', 'use ', 'document', 'file', 'content'])
        
        # Check for explicit file references (like 'TestData123' or 'MOMtemplate')
        has_specific_files = any(char.isupper() for char in user_msg) or 'found within' in msg_lower
        
        # Must have: template keyword + data keyword + specific file mentions
        return has_template and has_data and has_specific_files
    
    # Detect workflow pattern
    needs_template_data_hint = detect_template_data_workflow(user_input)
    
    # Build dynamic hint (only if pattern detected) - SIMPLIFIED VERSION
    workflow_hint = ""
    if needs_template_data_hint:
        print("🎯 Detected: TEMPLATE+DATA workflow pattern")
        workflow_hint = """
🚨 TEMPLATE+DATA WORKFLOW DETECTED 🚨

USER WANTS: Create document using template + data files from Google Drive

YOU MUST GENERATE EXACTLY THIS 2-STEP PLAN:

Step 1 - Search for both files:
{
  "step_id": 1,
  "agent": "drive_agent",
  "tool": "search_template_and_data",
  "description": "Search Google Drive for template and data files",
  "inputs": {
    "template_name": "<EXTRACT: look for 'MOMtemplate', 'Board Meeting Template', etc.>",
    "data_name": "<EXTRACT: look for 'TestData123', 'January Data', etc.>"
  },
  "output_variables": {
    "template_file_id": "template_file_id",
    "data_file_id": "data_file_id"
  }
}

Step 2 - Create document from template and data:
{
  "step_id": 2,
  "agent": "docs_agent",
  "tool": "create_from_template_and_data_ids",
  "description": "Create document from template and data files",
  "inputs": {
    "template_file_id": "{{ template_file_id }}",
    "data_file_id": "{{ data_file_id }}",
    "new_title": "<EXTRACT: look for 'January Reports', 'Q4 Summary', etc.>",
    "output_format": "google_docs"
  },
  "output_variables": {
    "document_id": "document_id",
    "document_url": "document_url"
  }
}

EXTRACTION INSTRUCTIONS:
- template_name: Find file name for structure/formatting (e.g., "MOMtemplate")
- data_name: Find file name for content/values (e.g., "TestData123")
- new_title: Find desired document name (e.g., "January Reports")

CRITICAL: Your JSON response MUST have "steps" array with exactly these 2 steps.

Example Response Format:
{
  "steps": [
    { "step_id": 1, "agent": "drive_agent", "tool": "search_template_and_data", ... },
    { "step_id": 2, "agent": "docs_agent", "tool": "create_from_template_and_data_ids", ... }
  ]
}
"""
    
    # ===================================================================
    # BUILD SYSTEM PROMPT (with optional hint)
    # ===================================================================
    
    capability_summary = json.dumps(filtered_capabilities, indent=2)
    schema_text = json.dumps(PLAN_SCHEMA, indent=2)

    system_prompt = f"""You are the Supervisor agent creating multi-step execution plans.

CURRENT DATE CONTEXT:
- Today's date: {today_date}
- Yesterday's date: {yesterday_date}

{workflow_hint}

PLANNING RULES:
1. Reference previous outputs using {{{{ variable_name }}}} syntax
2. Declare output_variables as {{"new_name": "source_field"}} to rename fields from tool's "returns"
3. Break tasks into sequential steps with clear data flow
4. Use date context variables: {{{{ today_date }}}}, {{{{ yesterday_date }}}} (format: YYYY-MM-DD)
5. For ANY email sending: create_draft_email first, then optionally send_draft_email if explicitly requested
6. IMPORTANT: read_recent_emails and search_emails return an "emails" array. Access items using array syntax:
   - {{{{ emails[0].message_id }}}} for first email's message_id
   - {{{{ emails[0].from }}}} for first email's sender
   - {{{{ emails[0].subject }}}} for first email's subject
   - Store array in variable: {{"recent_emails": "emails"}}, then use {{{{ recent_emails[0].from }}}}
7. For template uploads: ALWAYS do upload → analyze → create (3 steps minimum)
8. Follow tool-specific instructions in the capabilities (especially for templates and content generation)
9. When file is uploaded: uploaded_file context contains temp_path, filename, size, mime_type

Available agents and tools:
{capability_summary}

Schema:
{schema_text}

CRITICAL: Return ONLY valid JSON matching the schema above. NO explanations, NO text before or after the JSON.
Your response must be a valid JSON object with a "steps" array."""

    # Calculate token stats
    total_tools = sum(len(tools) for tools in tool_filter.values())
    all_tools_count = sum(len(agent_capabilities[a]["tools"]) for a in agent_capabilities)
    
    print("🤖 Calling LLM to generate multi-step plan...")
    print(f"💰 Token optimization:")
    print(f"   Agents: {len(relevant_agents)}/{len(agent_capabilities)}")
    print(f"   Tools: {total_tools}/{all_tools_count}")
    print(f"   Context size: {len(capability_summary):,} chars (~{len(capability_summary)//4:,} tokens)")
    if needs_template_data_hint:
        print(f"   ⚡ Dynamic hint: +{len(workflow_hint)//4:,} tokens (workflow-specific)")

    # ===================================================================
    # RETRY LOGIC FOR ROBUST PLAN GENERATION
    # ===================================================================
    max_retries = 2
    retry_count = 0
    plan = None
    last_error = None

    while retry_count <= max_retries:
        try:
            # === TOKEN TRACKING: Plan Generation ===
            start_time = time.time()
            llm_response = llm.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input},
                ]
            )
            duration_ms = (time.time() - start_time) * 1000
            
            # Extract token usage from response
            input_tokens = 0
            output_tokens = 0
            if hasattr(llm_response, 'response_metadata'):
                token_usage = llm_response.response_metadata.get('token_usage', {})
                input_tokens = token_usage.get('prompt_tokens', (len(system_prompt) + len(user_input)) // 4)
                output_tokens = token_usage.get('completion_tokens', len(llm_response.content) // 4)
            else:
                input_tokens = (len(system_prompt) + len(user_input)) // 4
                output_tokens = len(llm_response.content) // 4
            
            # Log the LLM call with token tracking
            logger.llm_call(
                model=LLM_MODEL,
                operation="plan_generation",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
                tier="supervisor",
                prompt_summary=f"Planning: {user_input[:50]}...",
                success=True
            )

            # Extract JSON from response (handle text before JSON block)
            response_text = llm_response.content.strip()
            
            # Check if response contains markdown code block
            if "```json" in response_text:
                # Extract content between ```json and ```
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()
            elif "```" in response_text:
                # Extract content between ``` and ```
                start = response_text.find("```") + 3
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()
            
            # If still no valid JSON, try to find JSON object directly
            if not response_text.startswith("{"):
                # Try to find JSON object in the text
                json_start = response_text.find("{")
                if json_start != -1:
                    response_text = response_text[json_start:]

            plan = json.loads(response_text)
            
            # ===================================================================
            # ✅ VALIDATE BASIC PLAN STRUCTURE FIRST
            # ===================================================================
            if not isinstance(plan, dict):
                raise ValueError("Plan must be a dictionary object")
            
            if "steps" not in plan and "plan" in plan:
                print("⚠️ LLM returned 'plan' key instead of 'steps' — normalizing...")
                plan["steps"] = plan.pop("plan")
                
            if "steps" not in plan:
                raise ValueError("Plan must contain 'steps' array. Got keys: " + str(list(plan.keys())))
            
            steps = plan.get("steps", [])
            
            if not isinstance(steps, list):
                raise ValueError(f"'steps' must be an array, got {type(steps).__name__}")
            
            if len(steps) == 0:
                raise ValueError("'steps' array is empty - plan must contain at least one step")
            
            # ===================================================================
            # ✅ VALIDATE: Template+Data Workflow Correctness
            # ===================================================================
            if needs_template_data_hint:
                
                if len(steps) < 2:
                    raise ValueError(
                        f"❌ WORKFLOW ERROR: Template+data workflow requires at least 2 steps, "
                        f"but only {len(steps)} step(s) found. "
                        f"Required workflow:\n"
                        f"  Step 1: drive_agent.search_template_and_data\n"
                        f"  Step 2: docs_agent.create_from_template_and_data_ids"
                    )
                
                first_step = steps[0]
                second_step = steps[1]
                
                # Check if first step is search_template_and_data
                if first_step.get("tool") != "search_template_and_data":
                    raise ValueError(
                        f"❌ WORKFLOW ERROR: Template+data creation must start with "
                        f"'search_template_and_data', not '{first_step.get('tool')}'. "
                        f"Please regenerate the plan following the workflow hint."
                    )
                
                # Check if second step is create_from_template_and_data_ids
                if second_step.get("tool") != "create_from_template_and_data_ids":
                    raise ValueError(
                        f"❌ WORKFLOW ERROR: After search_template_and_data, must use "
                        f"'create_from_template_and_data_ids', not '{second_step.get('tool')}'. "
                        f"Please regenerate the plan following the workflow hint."
                    )
                
                # Check if template_file_id and data_file_id are passed correctly
                second_step_inputs = str(second_step.get("inputs", {}))
                if "{{ template_file_id }}" not in second_step_inputs:
                    raise ValueError(
                        "❌ WORKFLOW ERROR: Step 2 must reference {{ template_file_id }} "
                        "from Step 1's output_variables"
                    )
                
                if "{{ data_file_id }}" not in second_step_inputs:
                    raise ValueError(
                        "❌ WORKFLOW ERROR: Step 2 must reference {{ data_file_id }} "
                        "from Step 1's output_variables"
                    )
                
                print("✅ Workflow validation passed: search → create sequence correct")

            # If we got here, plan is valid!
            print("✅ Plan generated successfully!")
            print(f"\n📋 Generated Plan:\n{json.dumps(plan, indent=2)}")
            break  # Exit retry loop

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            retry_count += 1
            
            if retry_count > max_retries:
                # All retries exhausted
                error_msg = (
                    f"Failed to generate valid plan after {max_retries} attempts.\n"
                    f"Last error: {str(last_error)}\n"
                    f"Last LLM response:\n{llm_response.content[:500]}..."
                )
                print(f"❌ {error_msg}")
                raise ValueError(error_msg)
            
            print(f"⚠️ Plan generation failed (attempt {retry_count}/{max_retries}), retrying...")
            print(f"Error: {str(e)}")
            
            # Add error feedback to system prompt for retry
            system_prompt += f"\n\n⚠️ PREVIOUS ATTEMPT FAILED: {str(e)}\n"
            system_prompt += "Please generate a valid JSON plan with a 'steps' array containing all required steps."

    # Save the plan to a file for inspection
    plan_file = os.path.join(OUTPUT_DIR, "supervisor_plan.json")
    with open(plan_file, "w") as f:
        json.dump(plan, f, indent=2)
    print(f"\n💾 Plan saved to: {plan_file}")
    print("=" * 60 + "\n")

    return {"plan": plan, "context": state.get("context", {})}
# ============================================================================
# PENDING ACTIONS - SQLite Storage with Runtime Cache
# ============================================================================
# Runtime cache for execution callbacks (callbacks can't be stored in DB)
PENDING_ACTIONS_CACHE = {}


def recover_pending_actions_from_sqlite():
    """
    Recover pending actions from SQLite on startup.
    Callbacks will be None but step_info is preserved for execution.
    """
    try:
        storage = LogStorage()
        
        pending_records = storage.get_pending_actions(status="pending")
        recovered_count = 0
        
        for record in pending_records:
            action_id = record.get("action_id")
            if action_id and action_id not in PENDING_ACTIONS_CACHE:
                # Rebuild PendingAction from SQLite data
                step_info = {
                    "step_number": record.get("step_number"),
                    "agent": record.get("agent_name"),
                    "tool": record.get("tool_name"),
                    "description": record.get("description"),
                    "inputs": record.get("inputs"),
                    "output_variables": record.get("output_variables"),
                    "risk_level": record.get("risk_level"),
                }
                
                action = PendingAction(
                    action_id=action_id,
                    step_info=step_info,
                    execution_callback=None,  # Callback lost - use execute_single_action instead
                    thread_id=record.get("thread_id"),
                    conversation_id=record.get("conversation_id"),
                    request_id=record.get("request_id")
                )
                
                # Restore metadata
                if record.get("created_at"):
                    try:
                        action.created_at = datetime.fromisoformat(record["created_at"])
                    except:
                        pass
                
                PENDING_ACTIONS_CACHE[action_id] = action
                recovered_count += 1
        
        if recovered_count > 0:
            print(f"🔄 Recovered {recovered_count} pending actions from SQLite")
    except Exception as e:
        print(f"⚠️ Error recovering pending actions: {e}")


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
    """Store action waiting for approval in SQLite and cache callback"""
    storage = LogStorage()
    
    # Get context IDs
    thread_id = action.thread_id or get_current_thread_id()
    conversation_id = action.conversation_id or get_current_conversation_id()
    request_id = action.request_id or get_current_request_id()
    
    risk_level = get_action_risk_level(action.step_info.get("tool"))
    
    # Store in SQLite
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
    
    # Cache the callback for later execution
    PENDING_ACTIONS_CACHE[action.action_id] = action
    
    # Log the pending action
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
    """Retrieve pending action from cache or rebuild from SQLite"""
    # Check cache first
    if action_id in PENDING_ACTIONS_CACHE:
        return PENDING_ACTIONS_CACHE[action_id]
    
    # Fallback to SQLite (won't have callback, but will have step_info)
    storage = LogStorage()
    
    action_data = storage.get_pending_action(action_id)
    if not action_data:
        return None
    
    # Rebuild PendingAction from SQLite data
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
        execution_callback=None,  # Callback lost after restart
        thread_id=action_data.get("thread_id"),
        conversation_id=action_data.get("conversation_id"),
        request_id=action_data.get("request_id")
    )
    action.status = action_data.get("status", "pending")
    action.created_at = datetime.fromisoformat(action_data.get("created_at")) if action_data.get("created_at") else datetime.now()
    
    return action


def remove_pending_action(action_id: str):
    """Remove completed action from SQLite and cache"""
    storage = LogStorage()
    
    # Remove from SQLite
    storage.delete_pending_action(action_id)
    
    # Remove from cache
    if action_id in PENDING_ACTIONS_CACHE:
        del PENDING_ACTIONS_CACHE[action_id]
    
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
    # 🔍 DEBUG: Validate Google credentials at startup
    # ===================================================================
    print("\n🔑 CREDENTIALS VALIDATION AT STARTUP:")
    print("─" * 60)
    google_creds_available = {
        "GOOGLE_ACCESS_TOKEN": bool(os.getenv("GOOGLE_ACCESS_TOKEN")),
        "GOOGLE_REFRESH_TOKEN": bool(os.getenv("GOOGLE_REFRESH_TOKEN")),
        "GOOGLE_CLIENT_ID": bool(os.getenv("GOOGLE_CLIENT_ID")),
        "GOOGLE_CLIENT_SECRET": bool(os.getenv("GOOGLE_CLIENT_SECRET")),
        "OAUTH_CLIENT_ID": bool(os.getenv("OAUTH_CLIENT_ID")),
        "OAUTH_CLIENT_SECRET": bool(os.getenv("OAUTH_CLIENT_SECRET")),
    }
    for cred_name, is_available in google_creds_available.items():
        status = "✅" if is_available else "❌"
        print(f"   {status} {cred_name}: {'SET' if is_available else 'MISSING'}")
    print("─" * 60)

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
            print(f"   Endpoint: POST /action/approve/{action_id}")
            print(f"   Details: {json.dumps(step_info, indent=4)}")

        # If no approval needed, execute normally
        print(f"✅ Auto-executing (safe action)")

        # STEP 1: Variable Substitution
        print(f"\n🔄 Substituting variables in inputs...")
        print(f"   Original inputs: {json.dumps(inputs, indent=6)}")

        substituted_inputs = {}
        for key, value in inputs.items():
            if isinstance(value, str):
                # Use Jinja2 to substitute {{ variables }}
                template = Template(value)
                substituted_inputs[key] = template.render(**variable_context)
            # ✅ FIX: Handle file uploads
            elif key == "file_path" and "uploaded_file" in variable_context:
                # Use the temp_path from uploaded_file
                uploaded_file = variable_context["uploaded_file"]
                substituted_inputs[key] = uploaded_file.get("temp_path")
            else:
                substituted_inputs[key] = value

        print(f"   Substituted inputs: {json.dumps(substituted_inputs, indent=6)}")
        print(f"   Available context variables: {list(variable_context.keys())}")

        # STEP 2: Call Agent Microservice
        agent_url = AGENT_ENDPOINTS.get(agent_name)
        if not agent_url:
            error_msg = f"No endpoint configured for agent: {agent_name}"
            print(f"❌ {error_msg}")
            results.append({
                "step": step_num,
                "agent": agent_name,
                "tool": tool_name,
                "status": "error",
                "error": error_msg,
            })
            continue

        print(f"\n🌐 Calling agent microservice: {agent_url}")

        # ===================================================================
        # 🔍 DEBUG + FIX: Build and validate credentials properly
        # ===================================================================
        print(f"\n🔑 Building credentials dictionary...")
        
        # Build credentials dict - ALL VALUES MUST BE STRINGS for Pydantic validation
        credentials_dict = {
            "access_token": os.getenv("GOOGLE_ACCESS_TOKEN"),
            "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN"),
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": os.getenv("GOOGLE_CLIENT_ID") or os.getenv("OAUTH_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET") or os.getenv("OAUTH_CLIENT_SECRET"),
        }

        # Remove None values and empty strings (Google rejects these)
        credentials_dict = {k: v for k, v in credentials_dict.items() if v}

        # 🔍 DEBUG: Print credential validation status
        print(f"\n🔍 CREDENTIAL VALIDATION:")
        print("─" * 60)
        print(f"   Has access_token: {bool(credentials_dict.get('access_token'))}")
        print(f"   Has refresh_token: {bool(credentials_dict.get('refresh_token'))}")
        print(f"   Has client_id: {bool(credentials_dict.get('client_id'))}")
        print(f"   Has client_secret: {bool(credentials_dict.get('client_secret'))}")
        print(f"   Has token_uri: {bool(credentials_dict.get('token_uri'))}")
        print(f"   Total fields: {len(credentials_dict)}")
        print("─" * 60)

        # Validate that we have the minimum required credentials
        required_fields = ["access_token", "refresh_token", "client_id", "client_secret"]
        missing_fields = [field for field in required_fields if not credentials_dict.get(field)]

        if missing_fields:
            error_msg = f"Missing required Google credentials: {', '.join(missing_fields)}"
            print(f"❌ {error_msg}")
            print(f"🛑 Cannot proceed with this step - credentials incomplete")
            
            results.append({
                "step": step_num,
                "agent": agent_name,
                "tool": tool_name,
                "status": "error",
                "error": error_msg,
            })
            
            # Stop workflow due to credential error
            print(f"\n{'='*60}")
            print("🛑 ORCHESTRATOR STOPPED - CREDENTIAL ERROR")
            print(f"{'='*60}")
            
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

        print(f"✅ Credentials validation passed - all required fields present")

        # ⚠️ CRITICAL FIX: Don't add expiry or scopes - agent expects only strings
        # The agent's Pydantic model is: credentials_dict: Dict[str, str]
        # Adding datetime objects or lists will cause 422 validation error

        # Prepare request payload (tool-based format) - FIXED STRUCTURE
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

    print(f"\n{'='*60}")
    print("✅ ORCHESTRATOR COMPLETED")
    print(f"{'='*60}")
    print(f"📊 Total steps: {len(plan)}")
    print(f"✓ Successful: {sum(1 for r in results if r.get('status') == 'success')}")
    print(f"ℹ️ No Results: {sum(1 for r in results if r.get('status') == 'no_results')}")
    print(f"✗ Failed: {sum(1 for r in results if r.get('status') == 'error')}")
    print(f"{'='*60}\n")

    # Include results in final_context for summary generation
    variable_context["results"] = results

    return {
        "final_context": variable_context,
        "context": variable_context,
        "results": results,
    }
    
    # === WEBSOCKET BROADCAST: Completion ===
    broadcast_ws_progress(len(plan), len(plan), "All steps completed", None, "completed")

    print(f"\n📦 FINAL CONTEXT (All Available Variables):")
    print("─" * 60)
    for key, value in variable_context.items():
        if isinstance(value, list):
            if len(value) > 0 and isinstance(value[0], dict):
                # Array of objects (like emails)
                print(f"   {key}: Array[{len(value)} items]")
                if len(value) > 0:
                    print(f"      └─ Sample keys: {list(value[0].keys())}")
                    # Show first item's key values for reference
                    if "message_id" in value[0]:
                        print(f"      └─ [0].message_id: {value[0].get('message_id')}")
                    if "from" in value[0]:
                        print(f"      └─ [0].from: {value[0].get('from')}")
                    if "subject" in value[0]:
                        print(f"      └─ [0].subject: {value[0].get('subject')}")
            else:
                print(f"   {key}: {value}")
        elif isinstance(value, dict):
            print(f"   {key}: Dict with keys: {list(value.keys())}")
        else:
            print(f"   {key}: {value}")
    print("─" * 60)
    print(f"{'='*60}\n")

    # Include results in final_context for summary generation
    variable_context["results"] = results

    return {
        "final_context": variable_context,
        # Note: "context" key removed - use final_context instead (they were identical)
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



# =============================================================================
# ALL ROUTE ENDPOINTS -> Moved to routes/ package
#   routes/workflow.py  - POST /workflow
#   routes/actions.py   - /actions/pending, /action/{id}, /action/approve/{id}, /actions/cleanup
#   routes/logs.py      - /logs, /logs/search, /logs/stats, /logs/requests/{id}, /agents/metrics
#   routes/realtime.py  - WebSocket /ws/threads/{id}/progress, GET /threads/{id}/progress
#   routes/health.py    - /health, /
#   routes/threads.py   - /threads (all CRUD)
#   routes/admin.py     - /admin/* (dashboard)
# =============================================================================
