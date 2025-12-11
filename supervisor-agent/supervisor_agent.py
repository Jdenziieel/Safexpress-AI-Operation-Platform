#THIS IS THE SUPERVISOR.py
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
import json
import httpx
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
from conversational_agent import ConversationalAgent, ConversationState

# Import LLM error handler for unified error handling
from llm_error_handler import handle_llm_error, LLMServiceException, is_llm_error

# Import logging module
from logging_config import (
    supervisor_logger as logger,
    orchestrator_logger,
    set_request_context,
    clear_request_context,
    get_current_request_id,
    get_token_summary,
    generate_request_id,
    check_user_quota
)

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


@app.on_event("startup")
async def startup_event():
    """Run on application startup - recover state from SQLite."""
    print("🔄 Running startup recovery...")
    # Recover pending actions from SQLite
    recover_pending_actions_from_sqlite()
    print("✅ Startup recovery complete")


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
            from conversational_agent import ConversationState, ConversationIntent
            
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


class ConversationRequest(BaseModel):
    """Request for conversational endpoint"""

    message: str
    conversation_id: Optional[str] = None  # For continuing conversations
    auto_execute: bool = False  # If true, auto-execute when ready
    user_id: Optional[str] = None  # Optional: auto-create persistent thread
    persist: bool = False  # If true with user_id, create persistent thread
    file: Optional[UploadFile] = File(None)


class ConversationResponse(BaseModel):
    """Response from conversational endpoint"""

    response: str
    conversation_id: str
    ready_for_execution: bool
    intent: str
    extracted_info: Dict[str, Any] = {}
    execution_summary: Optional[str] = None


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

    # Extract date info from context
    today_date = context.get("today_date", "")
    yesterday_date = context.get("yesterday_date", "")
    print(f"📅 Context dates: today={today_date}, yesterday={yesterday_date}")

    # OPTIMIZATION V2: Two-level filtering (agents + tools)
    from tool_filter import get_optimized_capabilities
    
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
        # Re-fetch capabilities with drive_agent included
        from agent_capabilities import agent_capabilities
        if 'drive_agent' in agent_capabilities:
            filtered_capabilities['drive_agent'] = agent_capabilities['drive_agent']
    
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
        from log_storage import LogStorage
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
    from log_storage import LogStorage
    from logging_config import get_current_thread_id, get_current_conversation_id, get_current_request_id
    
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
    from log_storage import LogStorage
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
    from log_storage import LogStorage
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
    from log_storage import LogStorage
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
        
    
    # Get thread_id from logging context for WebSocket broadcasting
    from logging_config import get_current_thread_id
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
    from jinja2 import Template

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
            import traceback
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


# ============================================================
# CONVERSATIONAL ENDPOINTS (NEW)
# ============================================================


# @app.post("/chat", response_model=ConversationResponse)
# async def chat(request: ConversationRequest):
#     """
#     Conversational endpoint that validates and clarifies user requests.
#     Use this BEFORE /workflow for interactive conversations.

#     Args:
#         request: ConversationRequest containing:
#             - message: User's message
#             - conversation_id: Optional ID to continue a conversation
#             - auto_execute: If true, auto-execute when ready

#     Returns:
#         ConversationResponse with bot response and execution readiness
#     """
#     # === QUOTA CHECK: Verify user has quota before processing ===
#     if request.user_id:
#         quota_result = check_user_quota(request.user_id, estimated_tokens=2000)
#         if not quota_result.allowed:
#             error_message = quota_result.error or "Quota check failed"
#             if quota_result.user_deactivated:
#                 raise HTTPException(
#                     status_code=403,
#                     detail={
#                         "error": "account_deactivated",
#                         "message": error_message,
#                         "user_message": "Your account has been deactivated. Please contact an administrator."
#                     }
#                 )
#             else:
#                 raise HTTPException(
#                     status_code=429,
#                     detail={
#                         "error": "quota_exceeded",
#                         "message": error_message,
#                         "user_message": error_message
#                     }
#                 )
    
#     # === REQUEST CONTEXT: Initialize logging context ===
#     request_id = set_request_context(
#         request_id=generate_request_id(),
#         conversation_id=request.conversation_id,
#         thread_id=None,  # Will be set if persist mode
#         user_id=request.user_id  # Pass user_id for quota tracking
#     )
    
#     logger.info(
#         f"Chat request received",
#         component="api",
#         operation="chat",
#         extra={
#             "message_preview": request.message[:50] + "..." if len(request.message) > 50 else request.message,
#             "has_conversation_id": request.conversation_id is not None,
#             "auto_execute": request.auto_execute,
#             "persist": request.persist,
#             "user_id": request.user_id
#         }
#     )
    
#     try:
#         print(f"\n💬 Chat request: {request.message}")

#         # Handle persistent thread creation if user_id and persist are provided
#         if request.persist and request.user_id and not request.conversation_id:
#             print(f"🔄 Creating persistent thread for user {request.user_id}")
#             # Create new thread
#             thread_id, conversation_state, bot_response = conversational_agent.create_new_thread(
#                 user_id=request.user_id,
#                 initial_message=request.message,
#                 title=None,  # Will auto-generate
#                 tags=[]
#             )
            
#             # Store in both cache and SQLite for persistence
#             save_conversation_state(thread_id, conversation_state)
            
#             # Get thread metadata
#             metadata = conversational_agent.get_thread_metadata(thread_id)
            
#             return ConversationResponse(
#                 response=bot_response or "Thread created",
#                 conversation_id=thread_id,
#                 ready_for_execution=conversation_state.ready_for_execution,
#                 intent=conversation_state.intent.value if conversation_state.intent else "unknown",
#                 extracted_info=conversation_state.extracted_info,
#                 execution_summary=conversation_state.execution_summary,
#             )

#         # Get or create conversation (checks cache then SQLite)
#         conversation_id = request.conversation_id or f"conv_{uuid.uuid4().hex[:8]}"
#         conversation_state = get_conversation_state(conversation_id)
        
#         # Check if this conversation has a corresponding thread in database
#         thread_exists = False
#         if conversation_id.startswith("conv_"):
#             # Legacy conversation ID format - check if thread exists
#             thread_metadata = conversational_agent.get_thread_metadata(conversation_id)
#             thread_exists = thread_metadata is not None

#         # If a conversation is currently executing, reject further inputs to avoid conflicts.
#         if conversation_state and conversation_state.executing:
#             print(
#                 f"⏳ Conversation {conversation_id} is executing — rejecting new input"
#             )
#             raise HTTPException(
#                 status_code=409,
#                 detail="Conversation is currently executing. Please wait until the operation completes.",
#             )

#         # Process message through conversational agent
#         # Use auto_save=True if this is a persistent thread conversation
#         response_text, updated_state = conversational_agent.process_message(
#             user_message=request.message, 
#             conversation_state=conversation_state,
#             state_id=conversation_id,
#             auto_save=thread_exists  # Auto-save if thread exists in DB
#         )

#         print(f"🤖 Bot response: {response_text}")
#         print(f"✅ Ready to execute: {updated_state.ready_for_execution}")

#         # If the conversation is ready for execution, run it immediately but KEEP the conversation.
#         if updated_state.ready_for_execution:
#             print(
#                 "🚀 Conversation ready — executing workflow (conversation will be kept)..."
#             )

#             # Mark as executing BEFORE any async operations to prevent race conditions
#             updated_state.executing = True
#             save_conversation_state(conversation_id, updated_state)

#             try:
#                 supervisor_input = conversational_agent.build_supervisor_input(
#                     updated_state
#                 )

#                 # Execute workflow first to get the actual plan
#                 workflow_request = UserRequest(input=supervisor_input)
#                 now_iso = datetime.now(timezone.utc).isoformat()

#                 status = "unknown"
#                 message = ""
#                 final_context = {}
#                 plan_dict = {}

#                 try:
#                     workflow_result = await execute_workflow(workflow_request)
#                     status = workflow_result.status
#                     message = workflow_result.message
#                     final_context = workflow_result.final_context or {}
#                     plan_dict = workflow_result.plan or {}
#                 except HTTPException as he:
#                     # ApprovalRequired and other HTTPExceptions
#                     status = "approval_required" if he.status_code == 202 else "error"
#                     message = str(he.detail) if hasattr(he, "detail") else str(he)
#                 except Exception as e:
#                     status = "error"
#                     message = str(e)
#                     import traceback

#                     traceback.print_exc()

#                 # Compute plan hash from actual structured plan (more stable than string)
#                 try:
#                     plan_json = json.dumps(plan_dict, sort_keys=True)
#                 except Exception:
#                     plan_json = json.dumps({"input": supervisor_input}, sort_keys=True)

#                 plan_hash = hashlib.sha256(plan_json.encode("utf-8")).hexdigest()

#                 # Build history entry
#                 history_item = {
#                     "executed_at": now_iso,
#                     "plan_hash": plan_hash,
#                     "status": status,
#                     "message": message,
#                     "final_context_snapshot": final_context,
#                 }

#                 # Append to history (limit to last 50 entries to prevent unbounded growth)
#                 updated_state.execution_history.append(history_item)
#                 if len(updated_state.execution_history) > 50:
#                     updated_state.execution_history = updated_state.execution_history[
#                         -50:
#                     ]

#                 updated_state.executed_count += 1
#                 updated_state.last_plan_hash = plan_hash
#                 updated_state.last_executed_at = now_iso
#                 updated_state.execution_summary = message

#                 # Prevent immediate re-execution until the agent sets ready_for_execution again
#                 updated_state.ready_for_execution = False

#                 # Generate user-friendly summary using conversational agent
#                 print("📝 Generating user-friendly summary...")
#                 friendly_summary = conversational_agent.summarize_execution(
#                     conversation_state=updated_state,
#                     final_context=final_context,
#                     execution_status=status,
#                     execution_message=message,
#                 )

#                 # Return response with execution summary
#                 return ConversationResponse(
#                     response=friendly_summary,
#                     conversation_id=conversation_id,
#                     ready_for_execution=updated_state.ready_for_execution,
#                     intent=(
#                         updated_state.intent.value
#                         if updated_state.intent
#                         else "unknown"
#                     ),
#                     extracted_info=updated_state.extracted_info,
#                     execution_summary=updated_state.execution_summary,
#                 )

#             finally:
#                 # CRITICAL: Always clear executing flag, even on error
#                 updated_state.executing = False
#                 save_conversation_state(conversation_id, updated_state)

#         # Otherwise, return current conversational response and state (not ready yet)
#         # Store the updated state before returning (both cache and SQLite)
#         save_conversation_state(conversation_id, updated_state)

#         # === REQUEST SUMMARY: Log token usage and complete request ===
#         logger.request_summary()
#         clear_request_context()
        
#         return ConversationResponse(
#             response=response_text,
#             conversation_id=conversation_id,
#             ready_for_execution=updated_state.ready_for_execution,
#             intent=updated_state.intent.value if updated_state.intent else "unknown",
#             extracted_info=updated_state.extracted_info,
#             execution_summary=updated_state.execution_summary,
#         )

#     except LLMServiceException as llm_ex:
#         # Handle LLM-specific errors with structured response
#         logger.error(
#             f"LLM service error in chat",
#             error=llm_ex,
#             component="api",
#             operation="chat"
#         )
#         logger.request_summary()
#         clear_request_context()
        
#         print(f"\n🔴 LLM Error in chat: {llm_ex}")
#         return JSONResponse(
#             status_code=llm_ex.status_code,
#             content=llm_ex.to_dict()
#         )
        
#     except Exception as e:
#         # Check if this is an LLM error that wasn't wrapped
#         if is_llm_error(e):
#             llm_error = handle_llm_error(e, context="Supervisor Chat")
#             logger.error(
#                 f"LLM error in chat (unwrapped)",
#                 error=e,
#                 component="api",
#                 operation="chat"
#             )
#             logger.request_summary()
#             clear_request_context()
            
#             print(f"\n🔴 LLM Error in chat: {llm_error.user_message}")
#             return JSONResponse(
#                 status_code=llm_error.status_code,
#                 content=llm_error.to_dict()
#             )
        
#         # === ERROR LOGGING ===
#         logger.error(
#             f"Chat processing failed",
#             error=e,
#             component="api",
#             operation="chat"
#         )
#         logger.request_summary()
#         clear_request_context()
        
#         print(f"\n❌ Error in chat: {str(e)}")
#         import traceback

#         traceback.print_exc()
#         raise HTTPException(status_code=500, detail=f"Chat processing failed: {str(e)}")

# Add after /chat endpoint (around line 800)

# @app.post("/chat/upload")
# async def chat_with_upload(
#     message: str = Form(...),
#     conversation_id: Optional[str] = Form(None),
#     auto_execute: bool = Form(False),
#     file: UploadFile = File(...)
# ):
#     """
#     Chat endpoint with file upload support for template workflows.
#     """
#     import tempfile
#     import shutil
    
#     try:
#         print(f"\n📎 File upload received: {file.filename}")
        
#         # Save file to temp location
#         with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp_file:
#             shutil.copyfileobj(file.file, tmp_file)
#             temp_path = tmp_file.name
        
#         # Get file size
#         file_size = os.path.getsize(temp_path)
        
#         # Build file metadata
#         uploaded_file = {
#             "filename": file.filename,
#             "temp_path": temp_path,
#             "size": file_size,
#             "mime_type": file.content_type or "application/octet-stream"
#         }
        
#         print(f"  → Saved to: {temp_path}")
#         print(f"  → Size: {file_size} bytes")
        
#         # Get or create conversation
#         conversation_id = conversation_id or f"conv_{uuid.uuid4().hex[:8]}"
#         conversation_state = CONVERSATIONS.get(conversation_id)
        
#         # ✅ FIX: Initialize conversation_state if None
#         if conversation_state is None:
#             conversation_state = ConversationState()
        
#         # Check if executing
#         if conversation_state.executing:
#             os.unlink(temp_path)  # Clean up
#             raise HTTPException(
#                 status_code=409,
#                 detail="Conversation is currently executing."
#             )
        
#         # Process message with file
#         response_text, updated_state = conversational_agent.process_message(
#             user_message=message,
#             conversation_state=conversation_state,  # Now guaranteed to not be None
#             state_id=conversation_id,
#             uploaded_file=uploaded_file
#         )
        
#         print(f"🤖 Bot response: {response_text}")
#         print(f"✅ Ready to execute: {updated_state.ready_for_execution}")
        
#         # Auto-execute if ready
#         if updated_state.ready_for_execution and auto_execute:
#             print("🚀 Auto-executing template upload workflow...")
            
#             updated_state.executing = True
#             CONVERSATIONS[conversation_id] = updated_state
            
#             try:
#                 supervisor_input = conversational_agent.build_supervisor_input(updated_state)
#                 workflow_request = UserRequest(input=supervisor_input)
                
#                 now_iso = datetime.now(timezone.utc).isoformat()
                
#                 status = "unknown"
#                 message_result = ""
#                 final_context = {}
#                 plan_dict = {}
                
#                 try:
#                     workflow_result = await execute_workflow(workflow_request)
#                     status = workflow_result.status
#                     message_result = workflow_result.message
#                     final_context = workflow_result.final_context or {}
#                     plan_dict = workflow_result.plan or {}
#                 except HTTPException as he:
#                     status = "approval_required" if he.status_code == 202 else "error"
#                     message_result = str(he.detail) if hasattr(he, "detail") else str(he)
#                 except Exception as e:
#                     status = "error"
#                     message_result = str(e)
#                     import traceback
#                     traceback.print_exc()
                
#                 # Compute plan hash
#                 try:
#                     plan_json = json.dumps(plan_dict, sort_keys=True)
#                 except Exception:
#                     plan_json = json.dumps({"input": supervisor_input}, sort_keys=True)
                
#                 plan_hash = hashlib.sha256(plan_json.encode("utf-8")).hexdigest()
                
#                 # Build history
#                 history_item = {
#                     "executed_at": now_iso,
#                     "plan_hash": plan_hash,
#                     "status": status,
#                     "message": message_result,
#                     "final_context_snapshot": final_context,
#                 }
                
#                 updated_state.execution_history.append(history_item)
#                 if len(updated_state.execution_history) > 50:
#                     updated_state.execution_history = updated_state.execution_history[-50:]
                
#                 updated_state.executed_count += 1
#                 updated_state.last_plan_hash = plan_hash
#                 updated_state.last_executed_at = now_iso
#                 updated_state.execution_summary = message_result
#                 updated_state.ready_for_execution = False
                
#                 # Generate summary
#                 print("📝 Generating summary...")
#                 friendly_summary = conversational_agent.summarize_execution(
#                     conversation_state=updated_state,
#                     final_context=final_context,
#                     execution_status=status,
#                     execution_message=message_result,
#                 )
                
#                 response_text = friendly_summary
                
#             finally:
#                 updated_state.executing = False
#                 CONVERSATIONS[conversation_id] = updated_state
                
#                 # Clean up temp file
#                 try:
#                     os.unlink(temp_path)
#                     print(f"🗑️ Cleaned up temp file: {temp_path}")
#                 except:
#                     pass
        
#         # Store updated state
#         CONVERSATIONS[conversation_id] = updated_state
        
#         return ConversationResponse(
#             response=response_text,
#             conversation_id=conversation_id,
#             ready_for_execution=updated_state.ready_for_execution,
#             intent=updated_state.intent.value if updated_state.intent else "unknown",
#             extracted_info=updated_state.extracted_info,
#             execution_summary=updated_state.execution_summary,
#         )
        
#     except Exception as e:
#         print(f"\n❌ Error in chat with upload: {str(e)}")
#         import traceback
#         traceback.print_exc()
        
#         # Clean up temp file on error
#         try:
#             if 'temp_path' in locals():
#                 os.unlink(temp_path)
#         except:
#             pass
        
#         raise HTTPException(status_code=500, detail=f"Upload processing failed: {str(e)}")

# @app.post("/chat/{conversation_id}/execute")
# async def execute_conversation(conversation_id: str):
#     """
#     Execute a conversation that's ready for execution.

#     Args:
#         conversation_id: ID of the conversation to execute

#     Returns:
#         WorkflowResponse with execution results
#     """
#     try:
#         # Get conversation
#         conversation_state = CONVERSATIONS.get(conversation_id)

#         if not conversation_state:
#             raise HTTPException(
#                 status_code=404, detail=f"Conversation {conversation_id} not found"
#             )

#         if not conversation_state.ready_for_execution:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Conversation is not ready for execution. Missing required information.",
#             )

#         print(f"\n🚀 Executing conversation: {conversation_id}")

#         # Build supervisor input from conversation
#         supervisor_input = conversational_agent.build_supervisor_input(
#             conversation_state
#         )
#         print(f"📝 Supervisor input: {supervisor_input}")

#         # Execute workflow
#         workflow_request = UserRequest(input=supervisor_input)
#         result = await execute_workflow(workflow_request)

#         # Clear conversation after successful execution
#         del CONVERSATIONS[conversation_id]

#         return result

#     except HTTPException:
#         raise
#     except Exception as e:
#         print(f"\n❌ Error executing conversation: {str(e)}")
#         import traceback

#         traceback.print_exc()
#         raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


# @app.get("/chat/{conversation_id}")
# async def get_conversation(conversation_id: str):
#     """Get conversation state and history"""
#     conversation_state = CONVERSATIONS.get(conversation_id)

#     if not conversation_state:
#         raise HTTPException(
#             status_code=404, detail=f"Conversation {conversation_id} not found"
#         )

#     return {
#         "conversation_id": conversation_id,
#         "ready_for_execution": conversation_state.ready_for_execution,
#         "intent": (
#             conversation_state.intent.value if conversation_state.intent else None
#         ),
#         "extracted_info": conversation_state.extracted_info,
#         "missing_fields": conversation_state.missing_fields,
#         "execution_summary": conversation_state.execution_summary,
#         "conversation_history": conversation_state.conversation_history,
#         # New metadata fields
#         "execution_history": conversation_state.execution_history,
#         "executed_count": conversation_state.executed_count,
#         "last_plan_hash": conversation_state.last_plan_hash,
#         "last_executed_at": conversation_state.last_executed_at,
#         "executing": conversation_state.executing,
#     }


# @app.delete("/chat/{conversation_id}")
# async def clear_conversation(conversation_id: str):
#     """Clear/reset a conversation"""
#     if conversation_id in CONVERSATIONS:
#         del CONVERSATIONS[conversation_id]
#         return {
#             "status": "success",
#             "message": f"Conversation {conversation_id} cleared",
#         }
#     else:
#         raise HTTPException(
#             status_code=404, detail=f"Conversation {conversation_id} not found"
#         )


# @app.get("/conversations")
# async def list_conversations():
#     """List all active conversations"""
#     conversations = []
#     for conv_id, state in CONVERSATIONS.items():
#         conversations.append(
#             {
#                 "conversation_id": conv_id,
#                 "ready_for_execution": state.ready_for_execution,
#                 "intent": state.intent.value if state.intent else None,
#                 "message_count": len(state.conversation_history),
#             }
#         )

#     return {"conversations": conversations, "count": len(conversations)}


# @app.post("/chat/{conversation_id}/persist")
# async def persist_conversation_to_thread(conversation_id: str, request: dict):
#     """
#     Convert a legacy in-memory conversation to a persistent thread.
    
#     Args:
#         conversation_id: Existing conversation ID
#         request: {"user_id": str (required), "title": str (optional), "tags": List[str] (optional)}
    
#     Returns:
#         Thread metadata with new thread_id
#     """
#     try:
#         user_id = request.get("user_id")
#         if not user_id:
#             raise HTTPException(status_code=400, detail="user_id is required")
        
#         # Get conversation from memory
#         conversation_state = CONVERSATIONS.get(conversation_id)
#         if not conversation_state:
#             raise HTTPException(
#                 status_code=404, 
#                 detail=f"Conversation {conversation_id} not found"
#             )
        
#         # Create thread with existing state
#         title = request.get("title") or f"Chat {conversation_id}"
#         tags = request.get("tags", [])
        
#         # Create thread in database
#         thread_metadata = conversational_agent.thread_manager.create_thread(
#             user_id=user_id,
#             title=title,
#             tags=tags
#         )
#         thread_id = thread_metadata.thread_id
        
#         # Save existing state to thread
#         conversational_agent._save_thread_to_db(thread_id, conversation_state)
        
#         # Migrate messages from memory to messages table
#         if thread_id in conversational_agent.memory_managers:
#             memory_manager = conversational_agent.memory_managers[thread_id]
#             messages = memory_manager.get_recent_messages(n=1000)  # Get all messages
            
#             for msg in messages:
#                 conversational_agent.thread_manager.add_message(
#                     thread_id=thread_id,
#                     role=msg["role"],
#                     content=msg["content"]
#                 )
        
#         # Keep conversation in memory but also return thread_id
#         print(f"✅ Persisted conversation {conversation_id} to thread {thread_id}")
        
#         return {
#             "conversation_id": conversation_id,
#             "thread_id": thread_id,
#             "user_id": user_id,
#             "message": "Conversation persisted to thread successfully",
#             "note": "You can now use either the conversation_id or thread_id"
#         }
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         print(f"❌ Error persisting conversation: {str(e)}")
#         raise HTTPException(status_code=500, detail=str(e))

#     return {"conversations": conversations, "count": len(conversations)}


# ============================================================
# ORIGINAL WORKFLOW ENDPOINT (Direct execution, no conversation)
# ============================================================


# FastAPI Endpoint
@app.post("/workflow", response_model=WorkflowResponse)
async def execute_workflow(request: UserRequest):
    """
    Main endpoint to accept user input and execute the workflow.

    Args:
        request: UserRequest containing:
            - input: The user's natural language request
            - memory: Optional context from previous interactions
            - policies: Optional access control policies

    Returns:
        WorkflowResponse with status, final context, plan, and message
    """
    try:
        print(f"\n📥 Received request: {request.input}")

        # Get current date for date-aware queries (Gmail-compatible format)
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        # Prepare initial state with date context
        initial_state: SharedState = {
            "input": request.input,
            "plan": {},
            "context": {
                "today_date": today,
                "yesterday_date": yesterday,
                "current_year": datetime.now().year,
                "current_month": datetime.now().month,
                "current_day": datetime.now().day,
            },
            "memory": request.memory,
            "policy": request.policies,
            "final_context": {},
        }

        print(f"📅 Date context: today={today}, yesterday={yesterday}")

        # Execute workflow
        print("🚀 Starting workflow execution...")
        result_state = workflow.invoke(initial_state)

        print("\n✅ Workflow completed successfully")

        # Also print to console for immediate viewing
        print(
            f"\n📋 Generated Plan:\n{json.dumps(result_state.get('plan', {}), indent=2)}"
        )
        print(
            f"\n📊 Final Context: {json.dumps(result_state.get('final_context', {}), indent=2)}"
        )

        return WorkflowResponse(
            status="success",
            final_context=result_state.get("final_context", {}),
            plan=result_state.get("plan", {}),
            message="Workflow executed successfully",
        )

    # except ApprovalRequiredException as approval_ex:
    #     # Handle approval requirement gracefully
    #     print(
    #         f"\n⏸️ Workflow paused - approval required for action: {approval_ex.action_id}"
    #     )

        # Return structured response for approval
        raise HTTPException(
            status_code=202,  # 202 Accepted - request received but not completed
            detail={
                "status": "approval_required",
                "action_id": approval_ex.action_id,
                "step_info": approval_ex.step_info,
                "message": str(approval_ex),
                "approval_endpoint": f"/action/approve/{approval_ex.action_id}",
                "next_steps": [
                    f"Review the action details at GET /action/{approval_ex.action_id}",
                    f"Approve with POST /action/approve/{approval_ex.action_id}",
                    "Include decision: 'approve', 'reject', or 'skip'",
                ],
            },
        )
    
    except LLMServiceException as llm_ex:
        # Handle LLM-specific errors with structured response
        print(f"\n🔴 LLM Error in workflow: {llm_ex}")
        return JSONResponse(
            status_code=llm_ex.status_code,
            content=llm_ex.to_dict()
        )

    except Exception as e:
        # Check if this is an LLM error that wasn't wrapped
        if is_llm_error(e):
            llm_error = handle_llm_error(e, context="Workflow Execution")
            print(f"\n🔴 LLM Error in workflow: {llm_error.user_message}")
            return JSONResponse(
                status_code=llm_error.status_code,
                content=llm_error.to_dict()
            )
        
        print(f"\n❌ Error executing workflow: {str(e)}")
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Workflow execution failed: {str(e)}"
        )


@app.get("/actions/pending")
async def list_pending_actions(thread_id: str = None):
    """List all actions waiting for approval (with automatic cleanup from SQLite)"""
    from log_storage import LogStorage
    storage = LogStorage()
    
    # First cleanup expired actions
    cleaned_count = storage.cleanup_expired_pending_actions(expire_minutes=5)
    if cleaned_count > 0:
        print(f"🧹 Cleaned up {cleaned_count} expired actions from SQLite")
    
    # Get pending actions from SQLite
    pending_records = storage.get_pending_actions(status="pending", thread_id=thread_id)
    
    # Also sync with in-memory cache (PENDING_ACTIONS_CACHE used for execution callbacks)
    for record in pending_records:
        if record["action_id"] not in PENDING_ACTIONS_CACHE:
            # Reload into cache if missing (note: execution_callback will be None after restart)
            action = PendingAction(
                action_id=record["action_id"],
                step_info={
                    "agent": record["agent_name"],
                    "tool": record["tool_name"],
                    "description": record["description"],
                    "inputs": json.loads(record["inputs"]) if record["inputs"] else {},
                    "output_variables": json.loads(record["output_variables"]) if record["output_variables"] else [],
                    "risk_level": record["risk_level"]
                },
                thread_id=record.get("thread_id"),
                conversation_id=record.get("conversation_id"),
                request_id=record.get("request_id")
            )
            PENDING_ACTIONS_CACHE[record["action_id"]] = action
    
    return {"pending_actions": pending_records, "count": len(pending_records)}


@app.get("/action/{action_id}")
async def get_action_details(action_id: str):
    """Get detailed information about a pending action"""
    action = get_pending_action(action_id)

    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    # Add helpful context
    step_info = action.step_info
    tool = step_info.get("tool")
    inputs = step_info.get("inputs", {})

    # Generate human-readable summary
    summary = generate_action_summary(tool, inputs)

    return {
        "action_id": action_id,
        "step_info": step_info,
        "summary": summary,
        "status": action.status,
        "created_at": action.created_at.isoformat(),
        "expires_at": (action.created_at + timedelta(minutes=5)).isoformat(),
    }


@app.post("/action/approve/{action_id}")
async def approve_action(action_id: str, approval: ActionApprovalRequest):
    """
    Approve or reject a specific action.
    After approval, the workflow continues from where it paused.
    Also updates status in SQLite database.
    """
    from log_storage import LogStorage
    storage = LogStorage()
    
    action = get_pending_action(action_id)

    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    if action.status != "pending":
        raise HTTPException(status_code=400, detail=f"Action already {action.status}")

    # Check timeout
    if datetime.now() - action.created_at > timedelta(minutes=360):
        action.status = "expired"
        storage.update_pending_action_status(action_id, "expired", decided_by="system_timeout")
        raise HTTPException(status_code=400, detail="Action approval expired")

    # Handle rejection
    if approval.decision == "reject":
        action.status = "rejected"
        storage.update_pending_action_status(
            action_id, "rejected", 
            decided_by="user",
            error=approval.rejection_reason
        )
        print(f"❌ Action {action_id} rejected: {approval.rejection_reason}")
        return {
            "status": "rejected",
            "action_id": action_id,
            "message": f"Action rejected: {approval.rejection_reason}",
        }

    # Handle skip
    if approval.decision == "skip":
        action.status = "skipped"
        storage.update_pending_action_status(action_id, "skipped", decided_by="user")
        print(f"⏭️ Action {action_id} skipped")
        return {
            "status": "skipped",
            "action_id": action_id,
            "message": "Action skipped, workflow will continue to next step",
        }

    # Handle approval (with optional modifications)
    action.status = "approved"
    storage.update_pending_action_status(action_id, "approved", decided_by="user")

    # Apply modified inputs if provided
    if approval.modified_inputs:
        print(f"📝 Inputs modified by user")
        action.step_info["inputs"] = approval.modified_inputs

    print(f"✅ Action {action_id} approved, executing now...")

    # Execute the approved action
    try:
        result = execute_single_action(action.step_info)
        action.result = result
        action.status = "completed"

        # Update status in SQLite with execution result
        storage.update_pending_action_status(
            action_id, "completed", 
            decided_by="user",
            execution_result=json.dumps(result) if isinstance(result, dict) else str(result)
        )

        # Clean up from cache
        remove_pending_action(action_id)

        return {
            "status": "completed",
            "action_id": action_id,
            "result": result,
            "message": "Action executed successfully",
        }

    except Exception as e:
        action.status = "failed"
        action.result = {"error": str(e)}
        
        # Update status in SQLite with error
        storage.update_pending_action_status(
            action_id, "failed", 
            decided_by="user",
            error=str(e)
        )

        return {
            "status": "failed",
            "action_id": action_id,
            "error": str(e),
            "message": f"Action execution failed: {str(e)}",
        }
    
@app.post("/actions/cleanup")
async def cleanup_expired_actions(expire_minutes: int = 5):
    """Clean up expired or completed pending actions from both cache and SQLite"""
    from log_storage import LogStorage
    storage = LogStorage()
    
    # Clean up from SQLite
    cleaned_from_db = storage.cleanup_expired_pending_actions(expire_minutes=expire_minutes)
    
    # Also clean up from in-memory cache (PENDING_ACTIONS_CACHE)
    cleaned_from_cache = []
    now = datetime.now()
    
    # Create a list of actions to remove (can't modify dict during iteration)
    actions_to_remove = []
    
    for action_id, action in PENDING_ACTIONS_CACHE.items():
        # Remove if expired (older than specified minutes)
        if now - action.created_at > timedelta(minutes=expire_minutes):
            actions_to_remove.append(action_id)
            cleaned_from_cache.append({
                "action_id": action_id,
                "reason": "expired",
                "age_seconds": (now - action.created_at).total_seconds()
            })
        # Remove if already processed (not pending)
        elif action.status != "pending":
            actions_to_remove.append(action_id)
            cleaned_from_cache.append({
                "action_id": action_id,
                "reason": f"already_{action.status}",
                "status": action.status
            })
    
    # Remove from cache
    for action_id in actions_to_remove:
        PENDING_ACTIONS_CACHE.pop(action_id, None)
    
    # Get remaining pending count from SQLite
    remaining = storage.get_pending_actions(status="pending")
    
    return {
        "cleaned_from_db": cleaned_from_db,
        "cleaned_from_cache": len(cleaned_from_cache),
        "cleaned_cache_details": cleaned_from_cache,
        "remaining_pending": len(remaining)
    }


def execute_single_action(step_info: dict) -> dict:
    """Execute a single approved action"""
    agent_name = step_info["agent"]
    tool_name = step_info["tool"]
    inputs = step_info["inputs"]

    agent_url = AGENT_ENDPOINTS.get(agent_name)
    if not agent_url:
        raise ValueError(f"No endpoint for agent: {agent_name}")

    request_payload = {
        "tool": tool_name,
        "inputs": inputs,
        "credentials_dict": {
            "access_token": os.getenv("GOOGLE_ACCESS_TOKEN"),
            "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN"),
        },
    }

    # Use retry logic
    result = call_agent_with_retry(
        agent_url=agent_url, request_payload=request_payload, max_retries=3
    )

    if not result:
        raise ValueError("Agent call failed after retries")

    return result


# ============================================================
# THREAD MANAGEMENT ENDPOINTS (NEW)
# ============================================================


@app.post("/threads")
async def create_thread(request: dict):
    """
    Create a new conversation thread.
    
    Args:
        request: {
            "user_id": str (required),
            "message": str (optional - first message),
            "title": str (optional - custom title),
            "tags": List[str] (optional)
        }
    
    Returns:
        Thread metadata with thread_id
    """
    # Generate a preliminary conversation_id (will get actual thread_id after creation)
    preliminary_conv_id = generate_request_id()
    
    # Extract user_id first for context
    user_id = request.get("user_id")
    
    # === REQUEST CONTEXT: Initialize logging context ===
    request_id = set_request_context(
        request_id=generate_request_id(),
        conversation_id=preliminary_conv_id,
        thread_id=None,  # Will be set after thread creation
        user_id=user_id
    )
    
    logger.info(
        f"Create thread request",
        component="api",
        operation="create_thread",
        extra={
            "user_id": user_id,
            "has_initial_message": request.get("message") is not None
        }
    )
    
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="No user_id detected")
        
        initial_message = request.get("message")
        title = request.get("title")
        tags = request.get("tags", [])
        
        # Create thread using conversational agent
        thread_id, conversation_state, bot_response = conversational_agent.create_new_thread(
            user_id=user_id,
            initial_message=initial_message,
            title=title,
            tags=tags
        )
        
        # If ready for execution after initial message, execute immediately
        if initial_message and conversation_state.ready_for_execution:
            print(f"🚀 Thread {thread_id} ready - executing workflow...")
            
            # Mark as executing to prevent conflicts
            conversation_state.executing = True
            conversational_agent._save_thread_to_db(thread_id, conversation_state)
            
            try:
                supervisor_input = conversational_agent.build_supervisor_input(conversation_state)
                print("HERE IS THE SUPERVISOR INPUT")
                print(supervisor_input)
                workflow_request = UserRequest(input=supervisor_input)
                now_iso = datetime.now(timezone.utc).isoformat()
                
                status = "unknown"
                message = ""
                final_context = {}
                plan_dict = {}
                
                try:
                    workflow_result = await execute_workflow(workflow_request)
                    status = workflow_result.status
                    message = workflow_result.message
                    final_context = workflow_result.final_context or {}
                    plan_dict = workflow_result.plan or {}
                except HTTPException as he:
                    status = "approval_required" if he.status_code == 202 else "error"
                    message = str(he.detail) if hasattr(he, "detail") else str(he)
                except Exception as e:
                    status = "error"
                    message = str(e)
                    import traceback
                    traceback.print_exc()
                
                # Compute plan hash
                try:
                    plan_json = json.dumps(plan_dict, sort_keys=True)
                except Exception:
                    plan_json = json.dumps({"input": supervisor_input}, sort_keys=True)
                plan_hash = hashlib.sha256(plan_json.encode("utf-8")).hexdigest()
                
                # Build history entry
                history_item = {
                    "executed_at": now_iso,
                    "plan_hash": plan_hash,
                    "status": status,
                    "message": message,
                    "final_context_snapshot": final_context,
                }
                
                # Update execution history
                conversation_state.execution_history.append(history_item)
                if len(conversation_state.execution_history) > 50:
                    conversation_state.execution_history = conversation_state.execution_history[-50:]
                
                conversation_state.executed_count += 1
                conversation_state.last_plan_hash = plan_hash
                conversation_state.last_executed_at = now_iso
                conversation_state.execution_summary = message
                conversation_state.ready_for_execution = False
                
                # Generate user-friendly summary
                print("📝 Generating user-friendly summary...")
                print("\n" + "=" * 60)
                print("📊 INPUTS TO summarize_execution:")
                print("=" * 60)
                print(f"conversation_state.execution_summary: {conversation_state.execution_summary}")
                print(f"conversation_state.extracted_info: {json.dumps(conversation_state.extracted_info, indent=2)}")
                print(f"execution_status: {status}")
                print(f"execution_message: {message}")
                print(f"\nfinal_context keys: {list(final_context.keys())}")
                print(f"final_context: {json.dumps(final_context, indent=2)}")
                print("=" * 60 + "\n")
                
                friendly_summary = conversational_agent.summarize_execution(
                    conversation_state=conversation_state,
                    final_context=final_context,
                    execution_status=status,
                    execution_message=message,
                )
                
                bot_response = friendly_summary
                
            finally:
                # Clear executing flag and save
                conversation_state.executing = False
                conversational_agent._save_thread_to_db(thread_id, conversation_state)
        
        # Get thread metadata
        thread_metadata = conversational_agent.get_thread_metadata(thread_id)
        
        response = {
            "thread_id": thread_id,
            "user_id": user_id,
            "metadata": thread_metadata,
            "message": "Thread created successfully"
        }
        
        # If there was an initial message, include the bot's response
        if initial_message and bot_response:
            response["bot_response"] = bot_response
            response["ready_for_execution"] = conversation_state.ready_for_execution
            
            # Simple check: if not ready for execution, it needs clarification
            if not conversation_state.ready_for_execution:
                response["needs_clarification"] = True
                response["clarification_question"] = conversation_state.clarification_question
            else:
                response["needs_clarification"] = False
        
        # Log request summary before returning
        logger.request_summary()
        clear_request_context()
        
        return response
        
    except Exception as e:
        print(f"❌ Error creating thread: {str(e)}")
        clear_request_context()
        raise HTTPException(status_code=500, detail=str(e))
@app.post("/threads/create-with-upload")
async def create_thread_with_upload(
    message: str = Form(...),
    user_id: str = Form(...),
    file: UploadFile = File(...),
):
    """
    Create a new thread with initial message AND file upload in one request.
    This prevents the "📎 Uploading file..." secondary message issue.
    """
    import tempfile
    import shutil
    
    # === REQUEST CONTEXT: Initialize logging context ===
    preliminary_conv_id = generate_request_id()
    request_id = set_request_context(
        request_id=generate_request_id(),
        conversation_id=preliminary_conv_id,
        thread_id=None,  # Will be set after thread creation
        user_id=user_id
    )
    
    logger.info(
        f"Create thread with upload request",
        component="api",
        operation="create_thread_upload",
        extra={
            "user_id": user_id,
            "filename": file.filename,
            "message_preview": message[:50] + "..." if len(message) > 50 else message
        }
    )
    
    try:
        print(f"\n📎 Creating thread with file upload for user {user_id}")
        print(f"📎 File: {file.filename}")
        print(f"💬 Message: {message}")
        
        # Save file to temp location
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp_file:
            shutil.copyfileobj(file.file, tmp_file)
            temp_path = tmp_file.name
        
        # Get file size
        file_size = os.path.getsize(temp_path)
        
        # Build file metadata
        uploaded_file = {
            "filename": file.filename,
            "temp_path": temp_path,
            "size": file_size,
            "mime_type": file.content_type or "application/octet-stream"
        }
        
        print(f"  → Saved to: {temp_path}")
        print(f"  → Size: {file_size} bytes")
        
        # Create thread with initial message AND file
        thread_id, conversation_state, bot_response = conversational_agent.create_new_thread(
            user_id=user_id,
            initial_message=message,
            title=None,  # Will auto-generate
            tags=[]
        )
        
        # Store in both cache and SQLite for persistence
        save_conversation_state(thread_id, conversation_state)
        
        print(f"✅ Created thread: {thread_id}")
        
        # Process message with file
        response_text, updated_state = conversational_agent.process_message(
            user_message=message,
            conversation_state=conversation_state,
            state_id=thread_id,
            auto_save=True,
            uploaded_file=uploaded_file
        )
        
        print(f"🤖 Bot response: {response_text}")
        print(f"✅ Ready to execute: {updated_state.ready_for_execution}")
        
        # If ready for execution, execute immediately
        if updated_state.ready_for_execution:
            print(f"🚀 Thread {thread_id} ready - executing workflow...")
            
            updated_state.executing = True
            conversational_agent._save_thread_to_db(thread_id, updated_state)
            
            try:
                supervisor_input = conversational_agent.build_supervisor_input(updated_state)
                workflow_request = UserRequest(input=supervisor_input)
                now_iso = datetime.now(timezone.utc).isoformat()
                
                status = "unknown"
                message_text = ""
                final_context = {}
                plan_dict = {}
                
                try:
                    workflow_result = await execute_workflow(workflow_request)
                    status = workflow_result.status
                    message_text = workflow_result.message
                    final_context = workflow_result.final_context or {}
                    plan_dict = workflow_result.plan or {}
                except HTTPException as he:
                    status = "approval_required" if he.status_code == 202 else "error"
                    message_text = str(he.detail) if hasattr(he, "detail") else str(he)
                except Exception as e:
                    status = "error"
                    message_text = str(e)
                    import traceback
                    traceback.print_exc()
                
                # Compute plan hash
                try:
                    plan_json = json.dumps(plan_dict, sort_keys=True)
                except Exception:
                    plan_json = json.dumps({"input": supervisor_input}, sort_keys=True)
                plan_hash = hashlib.sha256(plan_json.encode("utf-8")).hexdigest()
                
                # Build history entry
                history_item = {
                    "executed_at": now_iso,
                    "plan_hash": plan_hash,
                    "status": status,
                    "message": message_text,
                    "final_context_snapshot": final_context,
                }
                
                updated_state.execution_history.append(history_item)
                if len(updated_state.execution_history) > 50:
                    updated_state.execution_history = updated_state.execution_history[-50:]
                
                updated_state.executed_count += 1
                updated_state.last_plan_hash = plan_hash
                updated_state.last_executed_at = now_iso
                updated_state.execution_summary = message_text
                updated_state.ready_for_execution = False
                
                # Generate user-friendly summary
                print("📝 Generating user-friendly summary...")
                friendly_summary = conversational_agent.summarize_execution(
                    conversation_state=updated_state,
                    final_context=final_context,
                    execution_status=status,
                    execution_message=message_text,
                )
                
                response_text = friendly_summary
                
            finally:
                updated_state.executing = False
                conversational_agent._save_thread_to_db(thread_id, updated_state)
                
                # Clean up temp file
                try:
                    os.unlink(temp_path)
                    print(f"🗑️ Cleaned up temp file: {temp_path}")
                except:
                    pass
        else:
            # Not ready yet, clean up temp file
            try:
                os.unlink(temp_path)
                print(f"🗑️ Cleaned up temp file: {temp_path}")
            except:
                pass
        
        # Get thread metadata
        metadata = conversational_agent.get_thread_metadata(thread_id)
        
        # Log request summary before returning
        logger.request_summary()
        clear_request_context()
        
        return {
            "thread_id": thread_id,
            "bot_response": response_text,
            "ready_for_execution": updated_state.ready_for_execution,
            "metadata": metadata
        }
        
    except Exception as e:
        print(f"\n❌ Error creating thread with upload: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Clean up temp file on error
        try:
            if 'temp_path' in locals():
                os.unlink(temp_path)
                print(f"🗑️ Cleaned up temp file on error: {temp_path}")
        except:
            pass
        
        clear_request_context()
        raise HTTPException(status_code=500, detail=f"Failed to create thread with file: {str(e)}")


@app.get("/threads")
async def list_threads(user_id: str, status: str = "active", limit: int = 50, offset: int = 0):
    """
    List all threads for a user.
    
    Args:
        user_id: User identifier (required)
        status: Filter by status (active, archived, all) - default: active
        limit: Maximum results - default: 50
        offset: Pagination offset - default: 0
    
    Returns:
        List of thread metadata
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")
        
        threads = conversational_agent.list_user_threads(
            user_id=user_id,
            status=status,
            limit=limit,
            offset=offset
        )
        
        return {
            "user_id": user_id,
            "threads": threads,
            "count": len(threads),
            "limit": limit,
            "offset": offset
        }
        
    except Exception as e:
        print(f"❌ Error listing threads: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/threads/{thread_id}")
async def get_thread(thread_id: str):
    """
    Get metadata for a specific thread.
    
    Args:
        thread_id: Thread identifier
    
    Returns:
        Thread metadata
    """
    try:
        metadata = conversational_agent.get_thread_metadata(thread_id)
        
        if not metadata:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        
        return {
            "thread_id": thread_id,
            "metadata": metadata
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error getting thread: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/threads/{thread_id}/messages")
async def get_thread_messages(thread_id: str, limit: int = 50, offset: int = 0):
    """
    Get full conversation history for a thread from messages table.
    
    Args:
        thread_id: Thread identifier
        limit: Maximum messages to return (default: 50)
        offset: Pagination offset (default: 0)
    
    Returns:
        List of messages with role, content, and created_at
    """
    try:
        messages = conversational_agent.get_thread_messages(
            thread_id=thread_id,
            limit=limit,
            offset=offset
        )
        
        if messages is None:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        
        return {
            "thread_id": thread_id,
            "messages": messages,
            "count": len(messages),
            "limit": limit,
            "offset": offset
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error getting thread messages: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/threads/{thread_id}/messages")
async def send_message_to_thread(thread_id: str, request: dict):
    """
    Continue a thread by sending a new message.
    
    Args:
        thread_id: Thread identifier
        request: {"message": str (required)}
    
    Returns:
        Bot response and updated thread metadata
    """
    # === QUOTA CHECK: Extract user_id from thread_id and verify quota ===
    # Thread ID format: {user_id}_{conv_id}
    user_id = thread_id.split('_')[0] if '_' in thread_id else None
    if user_id:
        quota_result = check_user_quota(user_id, estimated_tokens=2000)
        if not quota_result.allowed:
            error_message = quota_result.error or "Quota check failed"
            if quota_result.user_deactivated:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "account_deactivated",
                        "message": error_message,
                        "user_message": "Your account has been deactivated. Please contact an administrator."
                    }
                )
            else:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "quota_exceeded",
                        "message": error_message,
                        "user_message": error_message
                    }
                )
    
    # === REQUEST CONTEXT: Initialize logging context for this thread ===
    # Extract conversation_id from thread_id (format: {user_id}_{conv_id})
    conversation_id = thread_id.split('_')[-1] if '_' in thread_id else thread_id
    request_id = set_request_context(
        request_id=generate_request_id(),
        conversation_id=conversation_id,
        thread_id=thread_id,
        user_id=user_id
    )
    
    logger.info(
        f"Thread message received",
        component="api",
        operation="thread_message",
        extra={
            "thread_id": thread_id,
            "message_preview": request.get("message", "")[:50] + "..." if len(request.get("message", "")) > 50 else request.get("message", "")
        }
    )
    
    try:
        message = request.get("message")
        if not message:
            raise HTTPException(status_code=400, detail="message is required")
        
        # Load current conversation state
        conversation_state = conversational_agent._load_thread_from_db(thread_id)
        
        if conversation_state is None:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        
        # Check if conversation is currently executing - reject to avoid conflicts
        if conversation_state.executing:
            print(f"⏳ Thread {thread_id} is executing — rejecting new input")
            raise HTTPException(
                status_code=409,
                detail="Thread is currently executing. Please wait until the operation completes.",
            )
        
        # Continue the thread
        response_text, conversation_state = conversational_agent.continue_thread(
            thread_id=thread_id,
            new_message=message
        )
        
        # If ready for execution, execute immediately
        if conversation_state.ready_for_execution:
            print(f"🚀 Thread {thread_id} ready - executing workflow...")
            
            # Mark as executing to prevent conflicts
            conversation_state.executing = True
            conversational_agent._save_thread_to_db(thread_id, conversation_state)
            
            try:
                supervisor_input = conversational_agent.build_supervisor_input(conversation_state)
                workflow_request = UserRequest(input=supervisor_input)
                now_iso = datetime.now(timezone.utc).isoformat()
                
                status = "unknown"
                message_text = ""
                final_context = {}
                plan_dict = {}
                
                try:
                    workflow_result = await execute_workflow(workflow_request)
                    status = workflow_result.status
                    message_text = workflow_result.message
                    final_context = workflow_result.final_context or {}
                    plan_dict = workflow_result.plan or {}
                except HTTPException as he:
                    status = "approval_required" if he.status_code == 202 else "error"
                    message_text = str(he.detail) if hasattr(he, "detail") else str(he)
                except Exception as e:
                    status = "error"
                    message_text = str(e)
                    import traceback
                    traceback.print_exc()
                
                # Compute plan hash
                try:
                    plan_json = json.dumps(plan_dict, sort_keys=True)
                except Exception:
                    plan_json = json.dumps({"input": supervisor_input}, sort_keys=True)
                plan_hash = hashlib.sha256(plan_json.encode("utf-8")).hexdigest()
                
                # Build history entry
                history_item = {
                    "executed_at": now_iso,
                    "plan_hash": plan_hash,
                    "status": status,
                    "message": message_text,
                    "final_context_snapshot": final_context,
                }
                
                # Update execution history
                conversation_state.execution_history.append(history_item)
                if len(conversation_state.execution_history) > 50:
                    conversation_state.execution_history = conversation_state.execution_history[-50:]
                
                conversation_state.executed_count += 1
                conversation_state.last_plan_hash = plan_hash
                conversation_state.last_executed_at = now_iso
                conversation_state.execution_summary = message_text
                conversation_state.ready_for_execution = False
                
                # Generate user-friendly summary
                print("📝 Generating user-friendly summary...")
                print("\n" + "=" * 60)
                print("📊 INPUTS TO summarize_execution:")
                print("=" * 60)
                print(f"conversation_state.execution_summary: {conversation_state.execution_summary}")
                print(f"conversation_state.extracted_info: {json.dumps(conversation_state.extracted_info, indent=2)}")
                print(f"execution_status: {status}")
                print(f"execution_message: {message_text}")
                print(f"\nfinal_context keys: {list(final_context.keys())}")
                print(f"final_context: {json.dumps(final_context, indent=2)}")
                print("=" * 60 + "\n")
                
                friendly_summary = conversational_agent.summarize_execution(
                    conversation_state=conversation_state,
                    final_context=final_context,
                    execution_status=status,
                    execution_message=message_text,
                )
                
                response_text = friendly_summary
                
            finally:
                # Clear executing flag and save
                conversation_state.executing = False
                conversational_agent._save_thread_to_db(thread_id, conversation_state)
        
        # Get updated metadata
        metadata = conversational_agent.get_thread_metadata(thread_id)
        
        # Log request summary before returning
        logger.request_summary()
        clear_request_context()
        
        return {
            "thread_id": thread_id,
            "bot_response": response_text,
            "ready_for_execution": conversation_state.ready_for_execution,
            "metadata": metadata
        }
        
    except HTTPException:
        clear_request_context()
        raise
    except ValueError as e:
        clear_request_context()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"❌ Error sending message to thread: {str(e)}")
        clear_request_context()
        raise HTTPException(status_code=500, detail=str(e))
@app.post("/threads/{thread_id}/messages/upload")
async def send_message_to_thread_with_upload(
    thread_id: str,
    message: str = Form(...),
    file: UploadFile = File(...)
):
    """
    Continue a thread by sending a new message with file upload.
    
    Args:
        thread_id: Thread identifier
        message: User's message (required)
        file: File upload (required)
    
    Returns:
        Bot response and updated thread metadata
    """
    import tempfile
    import shutil
    
    # === REQUEST CONTEXT: Initialize logging context for this thread ===
    conversation_id = thread_id.split('_')[-1] if '_' in thread_id else thread_id
    user_id = thread_id.split('_')[0] if '_' in thread_id else None
    request_id = set_request_context(
        request_id=generate_request_id(),
        conversation_id=conversation_id,
        thread_id=thread_id,
        user_id=user_id
    )
    
    logger.info(
        f"Thread message with upload received",
        component="api",
        operation="thread_message_upload",
        extra={
            "thread_id": thread_id,
            "filename": file.filename,
            "message_preview": message[:50] + "..." if len(message) > 50 else message
        }
    )
    
    try:
        print(f"\n📎 File upload to thread {thread_id}: {file.filename}")
        
        # Save file to temp location
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp_file:
            shutil.copyfileobj(file.file, tmp_file)
            temp_path = tmp_file.name
        
        # Get file size
        file_size = os.path.getsize(temp_path)
        
        # Build file metadata
        uploaded_file = {
            "filename": file.filename,
            "temp_path": temp_path,
            "size": file_size,
            "mime_type": file.content_type or "application/octet-stream"
        }
        
        print(f"  → Saved to: {temp_path}")
        print(f"  → Size: {file_size} bytes")
        
        # Load current conversation state
        conversation_state = conversational_agent._load_thread_from_db(thread_id)
        
        if conversation_state is None:
            # Clean up temp file
            os.unlink(temp_path)
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        
        # Check if conversation is currently executing
        if conversation_state.executing:
            print(f"⏳ Thread {thread_id} is executing — rejecting new input")
            # Clean up temp file
            os.unlink(temp_path)
            raise HTTPException(
                status_code=409,
                detail="Thread is currently executing. Please wait until the operation completes.",
            )
        
        # Process message with file
        response_text, updated_state = conversational_agent.process_message(
            user_message=message,
            conversation_state=conversation_state,
            state_id=thread_id,
            auto_save=True,  # Always auto-save for threads
            uploaded_file=uploaded_file
        )
        
        print(f"🤖 Bot response: {response_text}")
        print(f"✅ Ready to execute: {updated_state.ready_for_execution}")
        
        # If ready for execution, execute immediately
        if updated_state.ready_for_execution:
            print(f"🚀 Thread {thread_id} ready - executing workflow...")
            
            # Mark as executing to prevent conflicts
            updated_state.executing = True
            conversational_agent._save_thread_to_db(thread_id, updated_state)
            
            try:
                supervisor_input = conversational_agent.build_supervisor_input(updated_state)
                workflow_request = UserRequest(input=supervisor_input)
                now_iso = datetime.now(timezone.utc).isoformat()
                
                status = "unknown"
                message_text = ""
                final_context = {}
                plan_dict = {}
                
                try:
                    workflow_result = await execute_workflow(workflow_request)
                    status = workflow_result.status
                    message_text = workflow_result.message
                    final_context = workflow_result.final_context or {}
                    plan_dict = workflow_result.plan or {}
                except HTTPException as he:
                    status = "approval_required" if he.status_code == 202 else "error"
                    message_text = str(he.detail) if hasattr(he, "detail") else str(he)
                except Exception as e:
                    status = "error"
                    message_text = str(e)
                    import traceback
                    traceback.print_exc()
                
                # Compute plan hash
                try:
                    plan_json = json.dumps(plan_dict, sort_keys=True)
                except Exception:
                    plan_json = json.dumps({"input": supervisor_input}, sort_keys=True)
                plan_hash = hashlib.sha256(plan_json.encode("utf-8")).hexdigest()
                
                # Build history entry
                history_item = {
                    "executed_at": now_iso,
                    "plan_hash": plan_hash,
                    "status": status,
                    "message": message_text,
                    "final_context_snapshot": final_context,
                }
                
                # Update execution history
                updated_state.execution_history.append(history_item)
                if len(updated_state.execution_history) > 50:
                    updated_state.execution_history = updated_state.execution_history[-50:]
                
                updated_state.executed_count += 1
                updated_state.last_plan_hash = plan_hash
                updated_state.last_executed_at = now_iso
                updated_state.execution_summary = message_text
                updated_state.ready_for_execution = False
                
                # Generate user-friendly summary
                print("📝 Generating user-friendly summary...")
                friendly_summary = conversational_agent.summarize_execution(
                    conversation_state=updated_state,
                    final_context=final_context,
                    execution_status=status,
                    execution_message=message_text,
                )
                
                response_text = friendly_summary
                
            finally:
                # Clear executing flag and save
                updated_state.executing = False
                conversational_agent._save_thread_to_db(thread_id, updated_state)
                
                # Clean up temp file
                try:
                    os.unlink(temp_path)
                    print(f"🗑️ Cleaned up temp file: {temp_path}")
                except:
                    pass
        else:
            # Not ready for execution yet, just clean up temp file
            try:
                os.unlink(temp_path)
                print(f"🗑️ Cleaned up temp file: {temp_path}")
            except:
                pass
        
        # Get updated metadata
        metadata = conversational_agent.get_thread_metadata(thread_id)
        
        # Log request summary before returning
        logger.request_summary()
        clear_request_context()
        
        return {
            "thread_id": thread_id,
            "bot_response": response_text,
            "ready_for_execution": updated_state.ready_for_execution,
            "metadata": metadata
        }
        
    except HTTPException:
        clear_request_context()
        raise
    except Exception as e:
        print(f"\n❌ Error sending message with upload to thread: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Clean up temp file on error
        try:
            if 'temp_path' in locals():
                os.unlink(temp_path)
                print(f"🗑️ Cleaned up temp file on error: {temp_path}")
        except:
            pass
        
        clear_request_context()
        raise HTTPException(status_code=500, detail=f"Upload processing failed: {str(e)}")


@app.put("/threads/{thread_id}")
async def update_thread(thread_id: str, request: dict):
    """
    Update thread metadata.
    
    Args:
        thread_id: Thread identifier
        request: {
            "title": str (optional),
            "tags": List[str] (optional),
            "status": str (optional)
        }
    
    Returns:
        Updated thread metadata
    """
    try:
        title = request.get("title")
        tags = request.get("tags")
        status = request.get("status")
        
        success = conversational_agent.update_thread_metadata(
            thread_id=thread_id,
            title=title,
            tags=tags,
            status=status
        )
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        
        # Get updated metadata
        metadata = conversational_agent.get_thread_metadata(thread_id)
        
        return {
            "thread_id": thread_id,
            "metadata": metadata,
            "message": "Thread updated successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error updating thread: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/threads/{thread_id}")
async def delete_thread(thread_id: str, hard_delete: bool = False):
    """
    Delete a thread (archive by default, hard delete if specified).
    
    Args:
        thread_id: Thread identifier
        hard_delete: If true, permanently delete. Otherwise, archive.
    
    Returns:
        Success message
    """
    try:
        success = conversational_agent.delete_thread(
            thread_id=thread_id,
            hard_delete=hard_delete
        )
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        
        action = "deleted permanently" if hard_delete else "archived"
        
        return {
            "thread_id": thread_id,
            "message": f"Thread {action} successfully",
            "hard_delete": hard_delete
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error deleting thread: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/threads/search")
async def search_threads(user_id: str, q: str, limit: int = 20):
    """
    Search user's threads by title.
    
    Args:
        user_id: User identifier (required)
        q: Search query (required)
        limit: Maximum results - default: 20
    
    Returns:
        List of matching threads
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")
        if not q:
            raise HTTPException(status_code=400, detail="search query (q) is required")
        
        threads = conversational_agent.search_threads(
            user_id=user_id,
            query=q,
            limit=limit
        )
        
        return {
            "user_id": user_id,
            "query": q,
            "threads": threads,
            "count": len(threads)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error searching threads: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# LOG ENDPOINTS
# ============================================================================

@app.websocket("/ws/threads/{thread_id}/progress")
async def websocket_progress(websocket: WebSocket, thread_id: str):
    """
    WebSocket endpoint for real-time progress updates.
    
    Connect to this endpoint to receive instant progress updates during execution.
    Messages are JSON objects with type: "progress", "status", "token_usage", "complete"
    
    Example message:
    {
        "type": "progress",
        "data": {
            "current_step": 2,
            "total_steps": 5,
            "step_name": "Sending email",
            "agent": "gmail-agent",
            "status": "executing"
        },
        "timestamp": "2025-11-29T10:30:00Z"
    }
    """
    await progress_manager.connect(websocket, thread_id)
    try:
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connected",
            "data": {"thread_id": thread_id, "message": "Connected to progress stream"},
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        # Keep connection alive and listen for any client messages
        while True:
            try:
                # Wait for messages (ping/pong or close)
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Echo back pings
                if data == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # Send keepalive ping
                try:
                    await websocket.send_json({"type": "ping"})
                except:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        progress_manager.disconnect(websocket, thread_id)


@app.get("/threads/{thread_id}/progress")
async def get_thread_progress(thread_id: str):
    """
    Get the current execution progress for a thread.
    
    This endpoint returns the latest progress logs for a thread,
    useful for real-time progress display in the frontend.
    
    Returns:
        - status: Current status (idle, executing, completed, failed)
        - current_step: Current step number
        - total_steps: Total number of steps
        - step_name: Current step name/description
        - agent: Current agent being used
        - message: Progress message
        - request_id: Current request ID
        - token_usage: Current token usage for this request
    """
    try:
        from log_storage import LogStorage
        storage = LogStorage()
        
        # Get recent logs for this thread, ordered by timestamp DESC
        logs, total = storage.get_logs(
            thread_id=thread_id,
            limit=50,
            offset=0
        )
        
        if not logs:
            return {
                "status": "idle",
                "current_step": 0,
                "total_steps": 0,
                "step_name": None,
                "agent": None,
                "message": None,
                "request_id": None,
                "token_usage": None
            }
        
        # Find the most recent progress or status log
        latest_progress = None
        latest_llm = None
        latest_agent = None
        latest_request_id = None
        current_status = "idle"
        
        for log in logs:
            level = log.get("level", "")
            component = log.get("component", "")
            operation = log.get("operation", "")
            data = log.get("data", {}) or {}
            
            # Track request_id
            if log.get("request_id") and not latest_request_id:
                latest_request_id = log.get("request_id")
            
            # Check for progress logs
            if level == "PROGRESS" and not latest_progress:
                latest_progress = {
                    "current_step": data.get("current_step", 0),
                    "total_steps": data.get("total_steps", 0),
                    "step_name": data.get("step_name", ""),
                    "message": log.get("message", "")
                }
                current_status = "executing"
            
            # Check for LLM calls
            if component == "llm" and not latest_llm:
                latest_llm = {
                    "operation": operation,
                    "model": data.get("model", ""),
                    "tokens": data.get("total_tokens", 0),
                    "tier": data.get("tier", "")
                }
                if current_status == "idle":
                    current_status = "processing"
            
            # Check for agent calls
            if component == "orchestrator" and operation == "agent_call" and not latest_agent:
                latest_agent = {
                    "agent": data.get("agent", ""),
                    "tool": data.get("tool", ""),
                    "step": data.get("step", 0),
                    "total_steps": data.get("total_steps", 0),
                    "success": data.get("success", True)
                }
                current_status = "executing"
            
            # Check for completion
            if operation == "request_complete":
                current_status = "completed"
                break
        
        # Build response
        response = {
            "status": current_status,
            "current_step": 0,
            "total_steps": 0,
            "step_name": None,
            "agent": None,
            "message": None,
            "request_id": latest_request_id,
            "token_usage": None
        }
        
        # Add progress info
        if latest_progress:
            response["current_step"] = latest_progress["current_step"]
            response["total_steps"] = latest_progress["total_steps"]
            response["step_name"] = latest_progress["step_name"]
            response["message"] = latest_progress["message"]
        
        # Add agent info
        if latest_agent:
            response["agent"] = latest_agent["agent"]
            response["tool"] = latest_agent["tool"]
            if not latest_progress:
                response["current_step"] = latest_agent["step"]
                response["total_steps"] = latest_agent["total_steps"]
                response["step_name"] = f"{latest_agent['agent']}.{latest_agent['tool']}"
        
        # Add LLM info if processing
        if latest_llm and current_status == "processing":
            response["step_name"] = latest_llm["operation"]
            response["message"] = f"Processing with {latest_llm['model']}..."
        
        # Get token usage for this request
        if latest_request_id:
            request_logs, _ = storage.get_logs(
                request_id=latest_request_id,
                component="llm",
                limit=100
            )
            
            total_tokens = 0
            total_cost = 0.0
            llm_calls = 0
            
            for log in request_logs:
                data = log.get("data", {}) or {}
                if "total_tokens" in data:
                    total_tokens += data.get("total_tokens", 0)
                    total_cost += data.get("estimated_cost_usd", 0)
                    llm_calls += 1
            
            if llm_calls > 0:
                response["token_usage"] = {
                    "total_tokens": total_tokens,
                    "total_cost_usd": round(total_cost, 6),
                    "llm_calls": llm_calls
                }
        
        return response
        
    except ImportError:
        raise HTTPException(status_code=500, detail="Log storage module not available")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving progress: {str(e)}")


@app.get("/logs")
async def get_logs(
    level: Optional[str] = None,
    component: Optional[str] = None,
    request_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """
    Get logs with filtering and pagination.
    
    Query Parameters:
        - level: Filter by log level (DEBUG, INFO, PROGRESS, WARNING, ERROR, CRITICAL)
        - component: Filter by component (llm, orchestrator, api, etc.)
        - request_id: Filter by request ID
        - conversation_id: Filter by conversation ID
        - thread_id: Filter by thread ID
        - start_time: Filter logs after this time (ISO format)
        - end_time: Filter logs before this time (ISO format)
        - limit: Number of logs to return (default 100, max 1000)
        - offset: Offset for pagination
    
    Returns:
        - logs: List of log entries
        - total: Total count of matching logs
        - limit: Current limit
        - offset: Current offset
    """
    try:
        from log_storage import LogStorage
        storage = LogStorage()
        
        # Validate limit
        limit = min(limit, 1000)
        
        logs, total = storage.get_logs(
            level=level.upper() if level else None,
            component=component,
            request_id=request_id,
            conversation_id=conversation_id,
            thread_id=thread_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset
        )
        
        return {
            "logs": logs,
            "total": total,
            "limit": limit,
            "offset": offset
        }
        
    except ImportError:
        raise HTTPException(status_code=500, detail="Log storage module not available")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving logs: {str(e)}")


@app.get("/logs/search")
async def search_logs(
    q: str,
    level: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """
    Full-text search across log messages.
    
    Query Parameters:
        - q: Search query (required)
        - level: Filter by log level
        - start_time: Filter logs after this time (ISO format)
        - end_time: Filter logs before this time (ISO format)
        - limit: Number of results (default 100, max 1000)
        - offset: Offset for pagination
    
    Returns:
        - logs: List of matching log entries
        - total: Total count of matches
        - query: The search query used
    """
    try:
        from log_storage import LogStorage
        storage = LogStorage()
        
        limit = min(limit, 1000)
        
        logs, total = storage.search_logs(
            query=q,
            level=level.upper() if level else None,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset
        )
        
        return {
            "logs": logs,
            "total": total,
            "query": q,
            "limit": limit,
            "offset": offset
        }
        
    except ImportError:
        raise HTTPException(status_code=500, detail="Log storage module not available")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error searching logs: {str(e)}")


@app.get("/logs/stats")
async def get_log_stats(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None
):
    """
    Get log statistics including token usage and cost summary.
    
    Query Parameters:
        - start_time: Start of time range (ISO format)
        - end_time: End of time range (ISO format)
    
    Returns:
        - token_summary: Total tokens and costs
        - request_analytics: Per-request analytics
        - log_level_counts: Count of logs by level
    """
    try:
        from log_storage import LogStorage
        storage = LogStorage()
        
        token_summary = storage.get_token_summary(start_time, end_time)
        request_analytics = storage.get_request_analytics(start_time, end_time)
        
        return {
            "token_summary": token_summary,
            "request_analytics": request_analytics,
            "time_range": {
                "start": start_time,
                "end": end_time
            }
        }
        
    except ImportError:
        raise HTTPException(status_code=500, detail="Log storage module not available")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving stats: {str(e)}")


@app.get("/logs/requests/{request_id}")
async def get_request_logs(request_id: str):
    """
    Get all logs for a specific request ID.
    Useful for tracing a complete request through the system.
    
    Returns all log entries associated with the given request_id,
    ordered chronologically.
    """
    try:
        from log_storage import LogStorage
        storage = LogStorage()
        
        logs, total = storage.get_logs(
            request_id=request_id,
            limit=1000
        )
        
        # Calculate summary for this request
        token_total = 0
        cost_total = 0.0
        llm_calls = []
        agent_calls = []
        
        for log in logs:
            data = log.get("data", {})
            if log.get("component") == "llm" and "input_tokens" in data:
                token_total += data.get("total_tokens", 0)
                cost_total += data.get("estimated_cost_usd", 0)
                llm_calls.append({
                    "operation": log.get("operation"),
                    "model": data.get("model"),
                    "tokens": data.get("total_tokens"),
                    "cost_usd": data.get("estimated_cost_usd"),
                    "duration_ms": data.get("duration_ms")
                })
            elif log.get("component") == "orchestrator" and "agent" in data:
                agent_calls.append({
                    "agent": data.get("agent"),
                    "tool": data.get("tool"),
                    "success": data.get("success"),
                    "duration_ms": data.get("duration_ms")
                })
        
        return {
            "request_id": request_id,
            "logs": logs,
            "total_logs": total,
            "summary": {
                "total_tokens": token_total,
                "total_cost_usd": round(cost_total, 6),
                "llm_calls": len(llm_calls),
                "agent_calls": len(agent_calls),
                "llm_details": llm_calls,
                "agent_details": agent_calls
            }
        }
        
    except ImportError:
        raise HTTPException(status_code=500, detail="Log storage module not available")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving request logs: {str(e)}")


@app.delete("/logs")
async def clear_logs(
    before_time: Optional[str] = None,
    confirm: bool = False
):
    """
    Clear logs from the database.
    
    Query Parameters:
        - before_time: Delete logs before this time (ISO format)
        - confirm: Must be true to actually delete (safety measure)
    
    Returns:
        - deleted_count: Number of logs deleted
    """
    if not confirm:
        raise HTTPException(
            status_code=400, 
            detail="Set confirm=true to actually delete logs"
        )
    
    try:
        from log_storage import LogStorage
        storage = LogStorage()
        
        deleted_count = storage.clear_logs(before_time)
        
        return {
            "deleted_count": deleted_count,
            "before_time": before_time or "all"
        }
        
    except ImportError:
        raise HTTPException(status_code=500, detail="Log storage module not available")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error clearing logs: {str(e)}")


@app.get("/agents/metrics")
async def get_agent_metrics(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None
):
    """
    Get performance metrics for all agents.
    
    Returns metrics including:
    - Accuracy (task success rate)
    - Speed/Latency scores
    - Reliability
    - Resource efficiency
    - Overall performance score
    
    Query Parameters:
        - start_time: Filter from this time (ISO format)
        - end_time: Filter until this time (ISO format)
    """
    try:
        from log_storage import LogStorage
        storage = LogStorage()
        
        # Get agent calls data
        agent_calls = storage.get_agent_calls(
            start_time=start_time,
            end_time=end_time,
            limit=10000
        )
        
        # Aggregate metrics per agent
        agent_stats = {}
        for call in agent_calls:
            agent = call.get("agent_name", "unknown")
            if agent not in agent_stats:
                agent_stats[agent] = {
                    "total_calls": 0,
                    "successful_calls": 0,
                    "total_duration_ms": 0,
                    "durations": []
                }
            
            stats = agent_stats[agent]
            stats["total_calls"] += 1
            if call.get("success"):
                stats["successful_calls"] += 1
            duration = call.get("duration_ms", 0)
            stats["total_duration_ms"] += duration
            stats["durations"].append(duration)
        
        # Calculate performance scores
        metrics = {}
        for agent, stats in agent_stats.items():
            total = stats["total_calls"]
            successful = stats["successful_calls"]
            
            # Accuracy/Reliability (task success rate)
            accuracy = (successful / total * 100) if total > 0 else 0
            reliability = accuracy  # Same metric for now
            
            # Speed score
            avg_duration = stats["total_duration_ms"] / total if total > 0 else 0
            if avg_duration < 3000:
                speed_score = 100
            elif avg_duration < 10000:
                speed_score = 75
            else:
                speed_score = 50
            
            # Efficiency (placeholder - would need token data linked to agents)
            efficiency = 70  # Default
            
            # User feedback (placeholder - needs user_feedback table)
            user_feedback = 70  # Default neutral
            
            # Overall score using the formula
            overall_score = (
                accuracy * 0.35 +
                speed_score * 0.25 +
                reliability * 0.15 +
                efficiency * 0.10 +
                user_feedback * 0.15
            )
            
            # Determine tier
            if overall_score >= 85:
                tier = "Excellent"
            elif overall_score >= 70:
                tier = "Good"
            elif overall_score >= 50:
                tier = "Fair"
            else:
                tier = "Poor"
            
            metrics[agent] = {
                "accuracy": round(accuracy, 1),
                "speed": round(speed_score, 1),
                "reliability": round(reliability, 1),
                "efficiency": round(efficiency, 1),
                "user_feedback": round(user_feedback, 1),
                "overall_score": round(overall_score, 1),
                "tier": tier,
                "total_calls": total,
                "successful_calls": successful,
                "success_rate": round(accuracy, 1),
                "avg_latency_ms": round(avg_duration, 0),
            }
        
        return {
            "metrics": metrics,
            "time_range": {
                "start": start_time,
                "end": end_time
            },
            "agent_count": len(metrics)
        }
        
    except ImportError:
        raise HTTPException(status_code=500, detail="Log storage module not available")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving agent metrics: {str(e)}")


# =============================================================================
# ADMIN DASHBOARD ENDPOINTS (Privacy-Safe)
# =============================================================================

@app.get("/admin/logs")
async def get_admin_logs(
    level: Optional[str] = None,
    component: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """
    Get logs with PII redaction for admin dashboard.
    
    This endpoint returns logs with all sensitive information redacted.
    Admins can see system activity without accessing user private data.
    
    Query Parameters:
        - level: Filter by log level (WARNING, ERROR, CRITICAL recommended for admins)
        - component: Filter by component
        - start_time: Filter logs after this time (ISO format)
        - end_time: Filter logs before this time (ISO format)
        - limit: Number of logs to return (default 100, max 500)
        - offset: Offset for pagination
    
    Returns:
        - logs: List of redacted log entries
        - total: Total count of matching logs
        - _privacy: Confirmation that data is redacted
    """
    try:
        from log_storage import LogStorage
        from pii_redactor import PIIRedactor
        
        storage = LogStorage()
        
        # Limit max results for admin dashboard
        limit = min(limit, 500)
        
        logs, total = storage.get_logs(
            level=level.upper() if level else None,
            component=component,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset
        )
        
        # Redact ALL logs before returning
        redacted_logs = [PIIRedactor.redact_log_entry(log, level='admin') for log in logs]
        
        return {
            "logs": redacted_logs,
            "total": total,
            "limit": limit,
            "offset": offset,
            "_privacy": {
                "pii_redacted": True,
                "redaction_level": "admin",
                "safe_for_admin_viewing": True
            }
        }
        
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving admin logs: {str(e)}")


@app.get("/admin/activity")
async def get_admin_activity(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    agent: Optional[str] = None,
    limit: int = 50
):
    """
    Get privacy-safe activity feed for admin dashboard.
    
    Shows WHAT happened (actions) without revealing WHO or WHAT content.
    Example: "Email Service: Sent an email ✅" (no recipient, no subject)
    
    Query Parameters:
        - start_time: Filter after this time (ISO format)
        - end_time: Filter before this time (ISO format)
        - agent: Filter by agent name
        - limit: Number of activities to return (default 50, max 200)
    
    Returns:
        - activities: List of privacy-safe activity summaries
        - total: Total count
    """
    try:
        from log_storage import LogStorage
        from pii_redactor import PIIRedactor
        
        storage = LogStorage()
        limit = min(limit, 200)
        
        agent_calls = storage.get_agent_calls(
            agent_name=agent,
            start_time=start_time,
            end_time=end_time,
            limit=limit
        )
        
        # Create privacy-safe activity summaries
        activities = [
            PIIRedactor.create_admin_activity_summary(call) 
            for call in agent_calls
        ]
        
        return {
            "activities": activities,
            "total": len(activities),
            "_privacy": {
                "pii_redacted": True,
                "content_hidden": True,
                "safe_for_admin_viewing": True
            }
        }
        
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving activity: {str(e)}")


@app.get("/admin/activity/summary")
async def get_admin_activity_summary(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    period: str = "24h"
):
    """
    Get aggregated activity summary for admin dashboard.
    
    Shows counts and statistics without any user data.
    Example: "Email Service: 24 emails sent, 15 read, 0 failed"
    
    Query Parameters:
        - start_time: Filter after this time (ISO format)
        - end_time: Filter before this time (ISO format)  
        - period: Time period shorthand (1h, 24h, 7d, 30d) - used if no start/end
    
    Returns:
        - by_agent: Activity counts per agent
        - totals: Overall totals
    """
    try:
        from log_storage import LogStorage
        from pii_redactor import PIIRedactor
        from datetime import datetime, timedelta
        
        storage = LogStorage()
        
        # Calculate time range from period if not specified
        if not start_time and not end_time:
            now = datetime.utcnow()
            period_map = {
                '1h': timedelta(hours=1),
                '24h': timedelta(hours=24),
                '7d': timedelta(days=7),
                '30d': timedelta(days=30),
            }
            delta = period_map.get(period, timedelta(hours=24))
            start_time = (now - delta).isoformat() + 'Z'
        
        # Get all agent calls for the period
        agent_calls = storage.get_agent_calls(
            start_time=start_time,
            end_time=end_time,
            limit=10000  # Get all for aggregation
        )
        
        # Create aggregated summary
        summary = PIIRedactor.create_activity_aggregation(agent_calls)
        summary['period'] = period
        summary['time_range'] = {
            'start': start_time,
            'end': end_time
        }
        summary['_privacy'] = {
            'pii_redacted': True,
            'aggregated_data_only': True,
            'safe_for_admin_viewing': True
        }
        
        return summary
        
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving summary: {str(e)}")


@app.get("/admin/health")
async def get_system_health(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None
):
    """
    Get system health status for admin dashboard.
    
    Returns overall system health based on success rates and response times.
    Uses traffic light system: healthy (green), degraded (yellow), unhealthy (red)
    
    Returns:
        - status: Overall status (healthy, degraded, unhealthy)
        - score: Health score 0-100
        - indicators: Individual health metrics
    """
    try:
        from log_storage import LogStorage
        from datetime import datetime, timedelta
        
        storage = LogStorage()
        
        # Default to last hour for health check
        if not start_time:
            start_time = (datetime.utcnow() - timedelta(hours=1)).isoformat() + 'Z'
        
        # Get agent calls for health calculation
        agent_calls = storage.get_agent_calls(
            start_time=start_time,
            end_time=end_time,
            limit=10000
        )
        
        # Get log counts for error tracking
        log_counts = storage.get_log_counts(start_time=start_time, end_time=end_time)
        
        # Calculate metrics
        total_calls = len(agent_calls)
        successful_calls = sum(1 for c in agent_calls if c.get('success'))
        failed_calls = total_calls - successful_calls
        
        success_rate = (successful_calls / total_calls * 100) if total_calls > 0 else 100
        
        avg_duration = (
            sum(c.get('duration_ms', 0) for c in agent_calls) / total_calls
            if total_calls > 0 else 0
        )
        
        error_count = log_counts.get('ERROR', 0) + log_counts.get('CRITICAL', 0)
        warning_count = log_counts.get('WARNING', 0)
        
        # Determine health status
        if success_rate >= 95 and avg_duration < 5000 and error_count == 0:
            status = 'healthy'
            score = 100
        elif success_rate >= 90 and avg_duration < 10000 and error_count <= 5:
            status = 'degraded'
            score = 75
        else:
            status = 'unhealthy'
            score = max(0, int(success_rate * 0.5))
        
        # Count healthy agents
        agents_status = {}
        for call in agent_calls:
            agent = call.get('agent_name', 'unknown')
            if agent not in agents_status:
                agents_status[agent] = {'total': 0, 'success': 0}
            agents_status[agent]['total'] += 1
            if call.get('success'):
                agents_status[agent]['success'] += 1
        
        agents_healthy = sum(
            1 for a in agents_status.values() 
            if a['total'] > 0 and (a['success'] / a['total']) >= 0.9
        )
        agents_degraded = len(agents_status) - agents_healthy
        
        return {
            "status": status,
            "score": score,
            "indicators": {
                "success_rate": round(success_rate, 1),
                "avg_response_time_ms": round(avg_duration, 0),
                "error_count_1h": error_count,
                "warning_count_1h": warning_count,
                "total_actions_1h": total_calls,
                "agents_healthy": agents_healthy,
                "agents_degraded": agents_degraded,
            },
            "time_range": {
                "start": start_time,
                "end": end_time or datetime.utcnow().isoformat() + 'Z'
            },
            "last_updated": datetime.utcnow().isoformat() + 'Z'
        }
        
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving health: {str(e)}")


@app.get("/admin/alerts")
async def get_admin_alerts(
    hours: int = 1
):
    """
    Get active alerts for admin dashboard.
    
    Returns recent errors and warnings that need admin attention.
    
    Query Parameters:
        - hours: Look back period in hours (default 1, max 24)
    
    Returns:
        - alerts: List of alerts with severity and recommendations
        - summary: Count of errors and warnings
    """
    try:
        from log_storage import LogStorage
        from pii_redactor import PIIRedactor
        from datetime import datetime, timedelta
        from collections import defaultdict
        
        storage = LogStorage()
        hours = min(hours, 24)
        
        start_time = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + 'Z'
        
        # Get error and warning logs
        error_logs, _ = storage.get_logs(
            level='ERROR',
            start_time=start_time,
            limit=100
        )
        
        critical_logs, _ = storage.get_logs(
            level='CRITICAL',
            start_time=start_time,
            limit=100
        )
        
        warning_logs, _ = storage.get_logs(
            level='WARNING',
            start_time=start_time,
            limit=100
        )
        
        # Aggregate errors by component/agent
        error_groups = defaultdict(list)
        for log in error_logs + critical_logs:
            component = log.get('component', 'system')
            error_groups[component].append(log)
        
        # Create alerts
        alerts = []
        
        for component, logs in error_groups.items():
            agent_info = PIIRedactor.get_agent_friendly_name(component)
            
            # Determine severity
            critical_count = sum(1 for l in logs if l.get('level') == 'CRITICAL')
            severity = 'critical' if critical_count > 0 else 'high'
            
            # Generic alert message (no PII)
            if len(logs) == 1:
                message = f"{agent_info['name']} encountered an error"
            else:
                message = f"{agent_info['name']} encountered {len(logs)} errors"
            
            # Recommendation based on component
            recommendations = {
                'gmail': 'Check Gmail API credentials and quota',
                'calendar': 'Check Calendar API credentials',
                'gdocs': 'Check Google Docs API permissions',
                'sheets': 'Check Sheets API permissions',
                'gdrive': 'Check Drive API permissions',
                'llm': 'Check OpenAI API key and quota',
                'orchestrator': 'Review workflow configuration',
            }
            
            alerts.append({
                'type': 'error',
                'severity': severity,
                'icon': agent_info['icon'],
                'component': component,
                'component_friendly': agent_info['name'],
                'message': message,
                'count': len(logs),
                'first_occurred': logs[-1].get('timestamp') if logs else None,
                'last_occurred': logs[0].get('timestamp') if logs else None,
                'recommendation': recommendations.get(component, 'Review system logs'),
            })
        
        # Sort by severity and count
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        alerts.sort(key=lambda x: (severity_order.get(x['severity'], 99), -x['count']))
        
        return {
            "alerts": alerts,
            "summary": {
                "critical_count": sum(1 for a in alerts if a['severity'] == 'critical'),
                "error_count": len(error_logs) + len(critical_logs),
                "warning_count": len(warning_logs),
                "time_period_hours": hours,
            },
            "time_range": {
                "start": start_time,
                "end": datetime.utcnow().isoformat() + 'Z'
            },
            "_privacy": {
                "pii_redacted": True,
                "error_details_hidden": True,
                "safe_for_admin_viewing": True
            }
        }
        
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving alerts: {str(e)}")


@app.get("/admin/metrics")
async def get_admin_metrics(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    period: str = "24h"
):
    """
    Get agent performance metrics for admin dashboard.
    
    Returns performance scores with plain-language status labels.
    No user data is included.
    
    Query Parameters:
        - start_time: Filter from this time (ISO format)
        - end_time: Filter until this time (ISO format)
        - period: Time period shorthand (1h, 24h, 7d, 30d)
    
    Returns:
        - metrics: Performance metrics per agent with friendly labels
    """
    try:
        from log_storage import LogStorage
        from pii_redactor import PIIRedactor
        from datetime import datetime, timedelta
        
        storage = LogStorage()
        
        # Calculate time range from period if not specified
        if not start_time and not end_time:
            now = datetime.utcnow()
            period_map = {
                '1h': timedelta(hours=1),
                '24h': timedelta(hours=24),
                '7d': timedelta(days=7),
                '30d': timedelta(days=30),
            }
            delta = period_map.get(period, timedelta(hours=24))
            start_time = (now - delta).isoformat() + 'Z'
        
        # Get agent calls data
        agent_calls = storage.get_agent_calls(
            start_time=start_time,
            end_time=end_time,
            limit=10000
        )
        
        # Aggregate metrics per agent
        agent_stats = {}
        for call in agent_calls:
            agent = call.get('agent_name', 'unknown')
            if agent not in agent_stats:
                agent_stats[agent] = {
                    'total_calls': 0,
                    'successful_calls': 0,
                    'total_duration_ms': 0,
                    'durations': []
                }
            
            stats = agent_stats[agent]
            stats['total_calls'] += 1
            if call.get('success'):
                stats['successful_calls'] += 1
            duration = call.get('duration_ms', 0)
            stats['total_duration_ms'] += duration
            stats['durations'].append(duration)
        
        # Calculate performance scores with friendly labels
        metrics = {}
        for agent, stats in agent_stats.items():
            total = stats['total_calls']
            successful = stats['successful_calls']
            
            # Success rate
            success_rate = (successful / total * 100) if total > 0 else 0
            
            # Speed score
            avg_duration = stats['total_duration_ms'] / total if total > 0 else 0
            if avg_duration < 2000:
                speed_score = 100
                speed_label = 'Very Fast'
            elif avg_duration < 5000:
                speed_score = 85
                speed_label = 'Fast'
            elif avg_duration < 10000:
                speed_score = 70
                speed_label = 'Normal'
            else:
                speed_score = 50
                speed_label = 'Slow'
            
            # Overall score
            overall_score = (success_rate * 0.6) + (speed_score * 0.4)
            
            # Status label
            if overall_score >= 90:
                status_label = 'Working Great'
                status_color = 'green'
            elif overall_score >= 75:
                status_label = 'Working Well'
                status_color = 'blue'
            elif overall_score >= 50:
                status_label = 'Needs Attention'
                status_color = 'yellow'
            else:
                status_label = 'Having Issues'
                status_color = 'red'
            
            agent_info = PIIRedactor.get_agent_friendly_name(agent)
            
            metrics[agent] = {
                'agent': agent,
                'friendly_name': agent_info['name'],
                'icon': agent_info['icon'],
                'status_label': status_label,
                'status_color': status_color,
                'overall_score': round(overall_score, 1),
                'success_rate': round(success_rate, 1),
                'speed_score': round(speed_score, 1),
                'speed_label': speed_label,
                'avg_response_time_ms': round(avg_duration, 0),
                'avg_response_time_friendly': PIIRedactor.format_duration(avg_duration),
                'total_actions': total,
                'successful_actions': successful,
                'failed_actions': total - successful,
            }
        
        return {
            'metrics': metrics,
            'period': period,
            'time_range': {
                'start': start_time,
                'end': end_time
            },
            'agent_count': len(metrics),
            '_privacy': {
                'pii_redacted': True,
                'aggregated_metrics_only': True,
                'safe_for_admin_viewing': True
            }
        }
        
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving metrics: {str(e)}")


# =============================================================================
# HEALTH & ROOT ENDPOINTS
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "supervisor-agent"}


@app.get("/")
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


# Run the server
if __name__ == "__main__":
    print(f"🚀 Starting Supervisor Agent on port {SERVER_PORT}")
    print(f"📚 API Documentation: http://localhost:{SERVER_PORT}/docs")
    
    # Recover pending actions from SQLite on startup
    recover_pending_actions_from_sqlite()
    
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
