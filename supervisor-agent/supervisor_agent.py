from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
import json
import httpx
from jinja2 import Template
from typing import TypedDict, List, Optional, Dict, Any, Callable, Awaitable
from datetime import datetime, timedelta
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
    PLAN_SCHEMA,
    GOOGLE_ACCESS_TOKEN,
    GOOGLE_REFRESH_TOKEN,
    OPENAI_API_KEY,
    LLM_MODEL,
    LLM_TEMPERATURE,
    SERVER_PORT,
    SERVER_HOST
)

# Import agent capabilities
from agent_capabilities import agent_capabilities

# Import utility functions
from utils import (
    identify_relevant_agents,
    get_filtered_capabilities,
    call_agent_with_retry,
    generate_action_summary
)

# Initialize FastAPI app
app = FastAPI(title="Supervisor Agent API")

# Initialize LLM
llm = ChatOpenAI(
    model=LLM_MODEL, 
    temperature=LLM_TEMPERATURE, 
    openai_api_key=OPENAI_API_KEY
)

# Pydantic models for API
class UserRequest(BaseModel):
    input: str
    memory: Optional[Dict[str, Any]] = {}
    policies: Optional[List[Dict[str, Any]]] = [{"rule": "allow all for demo"}]

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


# IN MEMORY ONLY (ADJUST THIS LATER ON AND CONNECT TO DB)
PENDING_ACTIONS = {}

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
    """Represents an action waiting for approval"""
    def __init__(self, action_id: str, step_info: dict, execution_callback: Callable):
        self.action_id = action_id
        self.step_info = step_info
        self.execution_callback = execution_callback
        self.status = "pending"
        self.result = None
        self.created_at = datetime.now()
        
    def to_dict(self):
        return {
            "action_id": self.action_id,
            "step_number": self.step_info.get("step_number"),
            "agent": self.step_info.get("agent"),
            "tool": self.step_info.get("tool"),
            "description": self.step_info.get("description"),
            "inputs": self.step_info.get("inputs"),
            "risk_level": get_action_risk_level(self.step_info.get("tool")),
            "status": self.status,
            "created_at": self.created_at.isoformat()
        }
    
def generate_action_id() -> str:
    """Generate unique action ID"""
    return f"action_{uuid.uuid4().hex[:8]}"

def store_pending_action(action: PendingAction):
    """Store action waiting for approval"""
    PENDING_ACTIONS[action.action_id] = action

def get_pending_action(action_id: str) -> Optional[PendingAction]:
    """Retrieve pending action"""
    return PENDING_ACTIONS.get(action_id)

def remove_pending_action(action_id: str):
    """Remove completed action"""
    if action_id in PENDING_ACTIONS:
        del PENDING_ACTIONS[action_id]

# Supervisor Node - Creates the execution plan
def supervisor_node(state: SharedState) -> SharedState:
    """
    STEP 1: Supervisor generates a plan based on user input
    Enhanced to support multi-step workflows with data dependencies
    """
    print("\n" + "="*60)
    print("🧠 SUPERVISOR NODE - Planning Phase")
    print("="*60)
    
    user_input = state["input"]
    context = state.get("context", {})
    print(f"📥 User Input: {user_input}\n")
    
    # Extract date info from context
    today_date = context.get("today_date", "")
    yesterday_date = context.get("yesterday_date", "")
    print(f"📅 Context dates: today={today_date}, yesterday={yesterday_date}")
        
    # OPTIMIZATION: Filter relevant agents first (cheap)
    relevant_agents = identify_relevant_agents(user_input)

    print(f"📌 Relevant agents: {relevant_agents}")

    # Get only the needed capabilities
    filtered_capabilities = get_filtered_capabilities(relevant_agents)
    
    # Now send to LLM with reduced context
    capability_summary = json.dumps(filtered_capabilities, indent=2)
    schema_text = json.dumps(PLAN_SCHEMA, indent=2)

    system_prompt = f"""You are the Supervisor agent creating multi-step execution plans.

    CURRENT DATE CONTEXT:
    - Today's date: {today_date}
    - Yesterday's date: {yesterday_date}

    PLANNING RULES:
    1. Reference previous outputs using capability_summary syntax
    2. Declare output_variables as {{"source_field": "source_field"}} to rename fields from tool's "returns"
    3. Break tasks into sequential steps with clear data flow
    4. Use date context variables: {{{{ today_date }}}}, {{{{ yesterday_date }}}} (format: YYYY-MM-DD)
    5. For ANY email sending: create_draft_email first, then optionally send_draft_email if explicitly requested
    6. IMPORTANT: read_recent_emails and search_emails return an "emails" array. Access items using array syntax:
    - {{{{ emails[0].message_id }}}} for first email's message_id
    - {{{{ emails[0].from }}}} for first email's sender
    - {{{{ emails[0].subject }}}} for first email's subject
    - Store array in variable: {{"recent_emails": "emails"}}, then use {{{{ recent_emails[0].from }}}}

    Available agents and tools:
    {capability_summary}

    Schema:
    {schema_text}

    Return ONLY the JSON plan."""

    # system_prompt = f"""You are the Supervisor agent creating multi-step execution plans.

    # CURRENT DATE CONTEXT:
    # - Today's date: {today_date}
    # - Yesterday's date: {yesterday_date}

    # PLANNING RULES:
    # 1. Reference previous outputs using {{{{ variable_name }}}} syntax
    # 2. Declare output_variables as {{"new_name": "source_field"}} to rename fields from tool's "returns"
    # 3. Break tasks into sequential steps with clear data flow
    # 4. Use date context variables: {{{{ today_date }}}}, {{{{ yesterday_date }}}} (format: YYYY-MM-DD)
    # 5. For ANY email sending: create_draft_email first, then optionally send_draft_email if explicitly requested
    # 6. IMPORTANT: read_recent_emails and search_emails return an "emails" array. Access items using array syntax:
    # - {{{{ emails[0].message_id }}}} for first email's message_id
    # - {{{{ emails[0].from }}}} for first email's sender
    # - {{{{ emails[0].subject }}}} for first email's subject
    # - Store array in variable: {{"recent_emails": "emails"}}, then use {{{{ recent_emails[0].from }}}}

    # Available agents and tools:
    # {capability_summary}

    # Schema:
    # {schema_text}

    # Return ONLY the JSON plan."""

    print("🤖 Calling LLM to generate multi-step plan...")
    print(f"💰 Token optimization: Using {len(relevant_agents)}/{len(agent_capabilities)} agents")
    
    llm_response = llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input}
    ])

    try:
        # Extract JSON from response
        response_text = llm_response.content.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:-3].strip()
        elif response_text.startswith("```"):
            response_text = response_text[3:-3].strip()
            
        plan = json.loads(response_text)
        
        print("✅ Plan generated successfully!")
        print(f"\n📋 Generated Plan:\n{json.dumps(plan, indent=2)}")
        
        # Save the plan to a file for inspection
        plan_file = os.path.join(OUTPUT_DIR, "supervisor_plan.json")
        with open(plan_file, 'w') as f:
            json.dump(plan, f, indent=2)
        print(f"\n💾 Plan saved to: {plan_file}")
        print("="*60 + "\n")

    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM response as JSON: {e}\nResponse: {llm_response.content}")
    
    return {"plan": plan, "context": state.get("context", {})}

class SharedState(TypedDict):
    input: str
    plan: dict
    context: dict
    memory: dict
    policy: list
    final_context:dict


def supervisor_node(state: SharedState) -> SharedState:
    """
    STEP 1: Supervisor generates a plan based on user input
    Enhanced to support multi-step workflows with data dependencies
    """
    print("\n" + "="*60)
    print("🧠 SUPERVISOR NODE - Planning Phase")
    print("="*60)
    
    user_input = state["input"]
    context = state.get("context", {})
    print(f"📥 User Input: {user_input}\n")
    
    # Extract date info from context
    today_date = context.get("today_date", "")
    yesterday_date = context.get("yesterday_date", "")
    print(f"📅 Context dates: today={today_date}, yesterday={yesterday_date}")
        
    # OPTIMIZATION: Filter relevant agents first (cheap)
    relevant_agents = identify_relevant_agents(user_input)

    print(f"📌 Relevant agents: {relevant_agents}")

    # Get only the needed capabilities
    filtered_capabilities = get_filtered_capabilities(relevant_agents)
    
    # Now send to LLM with reduced context
    capability_summary = json.dumps(filtered_capabilities, indent=2)
    schema_text = json.dumps(PLAN_SCHEMA, indent=2)

#     system_prompt = f"""You are the Supervisor agent creating multi-step execution plans.

# CURRENT DATE CONTEXT:
# - Today's date: {today_date}
# - Yesterday's date: {yesterday_date}
# - Available context variables: today_date, yesterday_date

# CRITICAL EMAIL SAFETY RULE:
# ⚠️ NEVER use send_draft_email, reply_to_email, or send_email_with_attachment as the first step.
# ✅ ALWAYS create drafts first using create_draft_email before any sending action.
# ✅ This allows human review before emails are actually sent.

# Example CORRECT workflow for sending email:
# Step 1: create_draft_email (creates draft for review)
# Step 2: send_draft_email (sends after approval) - OPTIONAL, only if user explicitly requests sending

# Example WRONG workflow:
# ❌ Step 1: send_email_with_attachment (NO! Create draft first!)
# ❌ Step 1: reply_to_email (NO! Create draft first!)

# PLANNING RULES:
# 1. Reference previous outputs using {{{{ variable_name }}}} syntax
# 2. Declare output_variables as {{"new_name": "source_field"}} to rename fields from tool's "returns"
# 3. Break tasks into sequential steps with clear data flow
# 4. Use date context variables: {{{{ today_date }}}}, {{{{ yesterday_date }}}} (format: YYYY-MM-DD)
# 5. For ANY email sending: create_draft_email first, then optionally send_draft_email if explicitly requested
# 6. IMPORTANT: read_recent_emails and search_emails return an "emails" array. Access items using array syntax:
#    - {{{{ emails[0].message_id }}}} for first email's message_id
#    - {{{{ emails[0].from }}}} for first email's sender
#    - {{{{ emails[0].subject }}}} for first email's subject
#    - Store array in variable: {{"recent_emails": "emails"}}, then use {{{{ recent_emails[0].from }}}}

# Available agents and tools:
# {capability_summary}

# Schema:
# {schema_text}

# Return ONLY the JSON plan."""

    system_prompt = f"""You are the Supervisor agent creating multi-step execution plans.

    CURRENT DATE CONTEXT:
    - Today's date: {today_date}
    - Yesterday's date: {yesterday_date}

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

    Available agents and tools:
    {capability_summary}

    Schema:
    {schema_text}

    Return ONLY the JSON plan."""

    print("🤖 Calling LLM to generate multi-step plan...")
    print(f"💰 Token optimization: Using {len(relevant_agents)}/{len(agent_capabilities)} agents")
    
    llm_response = llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input}
    ])

    try:
        # Extract JSON from response
        response_text = llm_response.content.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:-3].strip()
        elif response_text.startswith("```"):
            response_text = response_text[3:-3].strip()
            
        plan = json.loads(response_text)
        
        print("✅ Plan generated successfully!")
        print(f"\n📋 Generated Plan:\n{json.dumps(plan, indent=2)}")
        
        # Save the plan to a file for inspection
        plan_file = os.path.join(OUTPUT_DIR, "supervisor_plan.json")
        with open(plan_file, 'w') as f:
            json.dump(plan, f, indent=2)
        print(f"\n💾 Plan saved to: {plan_file}")
        print("="*60 + "\n")

    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM response as JSON: {e}\nResponse: {llm_response.content}")
    
    return {"plan": plan, "context": state.get("context", {})}

# IN MEMORY ONLY (ADJUST THIS LATER ON AND CONNECT TO DB)
PENDING_ACTIONS = {}

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
    """Represents an action waiting for approval"""
    def __init__(self, action_id: str, step_info: dict, execution_callback: Callable):
        self.action_id = action_id
        self.step_info = step_info
        self.execution_callback = execution_callback
        self.status = "pending"
        self.result = None
        self.created_at = datetime.now()
        
    def to_dict(self):
        return {
            "action_id": self.action_id,
            "step_number": self.step_info.get("step_number"),
            "agent": self.step_info.get("agent"),
            "tool": self.step_info.get("tool"),
            "description": self.step_info.get("description"),
            "inputs": self.step_info.get("inputs"),
            "risk_level": get_action_risk_level(self.step_info.get("tool")),
            "status": self.status,
            "created_at": self.created_at.isoformat()
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
    parts = path.split('.')
    
    current = data
    for part in parts:
        # Check if this part has array index notation: "field[index]" or "field[-index]"
        match = re.match(r'(\w+)\[(-?\d+)\]', part)
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
    """Store action waiting for approval"""
    PENDING_ACTIONS[action.action_id] = action

def get_pending_action(action_id: str) -> Optional[PendingAction]:
    """Retrieve pending action"""
    return PENDING_ACTIONS.get(action_id)

def remove_pending_action(action_id: str):
    """Remove completed action"""
    if action_id in PENDING_ACTIONS:
        del PENDING_ACTIONS[action_id]

def orchestrator_node(state: SharedState) -> SharedState:
    """
    Executes the plan by calling specialized agent microservices via HTTP.
    Supports both tool-based and task-based execution formats.
    Manages variable substitution and context flow between steps.
    """
    print("\n" + "="*60)
    print("⚙️ ORCHESTRATOR NODE - Execution Phase")
    print("="*60)
    
    plan = state["plan"].get("plan", [])
    variable_context = state.get("context", {})
    results = []
    
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

        # INSERT STARTS HERE. ABOVE IS NORMAL AND INCONJUCTURE WITH PREVIOUS CODE OR THOSE COMMENTED BELOW

        # Check if this action requires approval
        risk_level = get_action_risk_level(tool_name)
        needs_approval = requires_approval(tool_name)
        
        print(f"⚠️ Risk Level: {risk_level.value}")
        if needs_approval:
            print(f"⏸️ PAUSED - Action requires approval!")
            # Substitute variables first so user sees actual values
            substituted_inputs = {}
            for key, value in inputs.items():
                if isinstance(value, str):
                    template = Template(value)
                    substituted_inputs[key] = template.render(**variable_context)
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
                "risk_level": risk_level.value
            }
            
            # Store as pending
            pending_action = PendingAction(
                action_id=action_id,
                step_info=step_info,
                execution_callback=None  # We'll handle this differently
            )
            store_pending_action(pending_action)
            
            # Return early with pending action info
            # In a real implementation, this would trigger a webhook/notification
            print(f"🔔 Approval required for action: {action_id}")
            print(f"   Endpoint: POST /action/approve/{action_id}")
            print(f"   Details: {json.dumps(step_info, indent=4)}")
            
            # For demo purposes, we'll raise an exception that includes the action ID
            # In production, this would be handled by a queue/webhook system
            raise ApprovalRequiredException(
                action_id=action_id,
                step_info=step_info,
                message=f"Action requires approval. Please review and approve at /action/approve/{action_id}"
            )
        
        # If no approval needed, execute normally
        print(f"✅ Auto-executing (safe action)")


        # STEP 1: Variable Substitution
        # Replace {{ variable }} with actual values from variable_context
        print(f"\n🔄 Substituting variables in inputs...")
        print(f"   Original inputs: {json.dumps(inputs, indent=6)}")
        
        substituted_inputs = {}
        for key, value in inputs.items():
            if isinstance(value, str):
                # Use Jinja2 to substitute {{ variables }}
                template = Template(value)
                substituted_inputs[key] = template.render(**variable_context)
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
                "error": error_msg
            })
            continue
        
        print(f"\n🌐 Calling agent microservice: {agent_url}")
        
        # Prepare request payload (tool-based format)
        request_payload = {
            "tool": tool_name,
            "inputs": substituted_inputs,
            "credentials_dict": {
                "access_token": os.getenv("GOOGLE_ACCESS_TOKEN"),
                "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN")
            }
        }
        
        try:
            # Use retry logic with longer timeout (320 seconds) and exponential backoff
            result = call_agent_with_retry(
                agent_url=agent_url,
                request_payload=request_payload,
                max_retries=3,
                timeout=320.0
            )
            
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
                fields_to_add = {k: v for k, v in agent_result.items() 
                                if k not in ["success", "error"]}
                variable_context.update(fields_to_add)
                
                # Then, create renamed variables based on output_variables mapping
                # Format: "new_variable_name": "source_field_name" or "nested.path[0].field"
                print(f"\n📦 Variables added to context:")
                for new_var_name, source_field_name in output_variables.items():
                    # Try nested path extraction first (handles "drafts[0].id")
                    value = extract_nested_value(agent_result, source_field_name)
                    
                    if value is not None:
                        variable_context[new_var_name] = value
                        print(f"   ✓ {new_var_name} = {value} (from {source_field_name})")
                    # Fallback to simple field access for backward compatibility
                    elif source_field_name in agent_result:
                        variable_context[new_var_name] = agent_result[source_field_name]
                        print(f"   ✓ {new_var_name} = {agent_result[source_field_name]} (from {source_field_name})")
                    else:
                        print(f"   ⚠️ {new_var_name} = NOT FOUND (looking for {source_field_name} in result)")
                
                # Print updated context after this step
                print(f"\n📊 CONTEXT AFTER STEP {step_num}:")
                print("─" * 60)
                for key, value in variable_context.items():
                    if isinstance(value, list):
                        if len(value) > 0 and isinstance(value[0], dict):
                            # Array of objects (like emails)
                            print(f"   {key}: Array[{len(value)} items]")
                            if len(value) > 0:
                                print(f"      └─ First item keys: {list(value[0].keys())}")
                        else:
                            print(f"   {key}: {value}")
                    elif isinstance(value, dict):
                        print(f"   {key}: Dict with keys: {list(value.keys())}")
                    else:
                        print(f"   {key}: {value}")
                print("─" * 60)
                
                # Store step result
                results.append({
                    "step": step_num,
                    "agent": agent_name,
                    "tool": tool_name,
                    "description": description,
                    "inputs": substituted_inputs,
                    "output": agent_result,
                    "status": "success"
                })
            else:
                # Handle failure - distinguish between no_results and actual errors
                error_msg = result.get("error", "Unknown error")
                is_no_results = result.get("no_results", False)
                
                if is_no_results:
                    # Graceful handling for empty results
                    print(f"ℹ️ No results found: {error_msg}")
                    print(f"   This step returned no data, but the operation was valid.")
                    print(f"   Continuing to next step (if any)...")
                    
                    # Store as a special status for tracking
                    results.append({
                        "step": step_num,
                        "agent": agent_name,
                        "tool": tool_name,
                        "description": description,
                        "inputs": substituted_inputs,
                        "status": "no_results",
                        "message": error_msg,
                        "output": result
                    })
                    
                    # Add empty result context to prevent downstream failures
                    # Extract the result format to add empty defaults
                    agent_result = result.get("result", result)
                    fields_to_add = {k: v for k, v in agent_result.items() 
                                    if k not in ["success", "error", "no_results"]}
                    variable_context.update(fields_to_add)
                    
                    print(f"   Added empty context fields: {list(fields_to_add.keys())}")
                else:
                    # Actual error occurred - STOP EXECUTION
                    print(f"❌ Agent reported error: {error_msg}")
                    print(f"🛑 STOPPING WORKFLOW - Error in step {step_num}")
                    
                    results.append({
                        "step": step_num,
                        "agent": agent_name,
                        "tool": tool_name,
                        "description": description,
                        "inputs": substituted_inputs,
                        "status": "error",
                        "error": error_msg
                    })
                    
                    # Stop workflow and return early
                    print(f"\n{'='*60}")
                    print("🛑 ORCHESTRATOR STOPPED DUE TO ERROR")
                    print(f"{'='*60}")
                    print(f"📊 Completed steps: {step_num}/{len(plan)}")
                    print(f"✓ Successful: {sum(1 for r in results if r.get('status') == 'success')}")
                    print(f"ℹ️ No Results: {sum(1 for r in results if r.get('status') == 'no_results')}")
                    print(f"✗ Failed at step: {step_num}")
                    print(f"{'='*60}\n")
                    
                    return {
                        "final_context": variable_context,
                        "context": variable_context,
                        "results": results,
                        "stopped_at_step": step_num,
                        "error": error_msg
                    }
        
        except httpx.HTTPError as e:
            error_msg = f"HTTP error calling {agent_name}: {str(e)}"
            print(f"❌ {error_msg}")
            print(f"🛑 STOPPING WORKFLOW - HTTP Error in step {step_num}")
            
            results.append({
                "step": step_num,
                "agent": agent_name,
                "tool": tool_name,
                "status": "error",
                "error": error_msg
            })
            
            # Stop workflow and return early
            print(f"\n{'='*60}")
            print("🛑 ORCHESTRATOR STOPPED DUE TO HTTP ERROR")
            print(f"{'='*60}")
            print(f"📊 Completed steps: {step_num}/{len(plan)}")
            print(f"✓ Successful: {sum(1 for r in results if r.get('status') == 'success')}")
            print(f"ℹ️ No Results: {sum(1 for r in results if r.get('status') == 'no_results')}")
            print(f"✗ Failed at step: {step_num}")
            print(f"{'='*60}\n")
            
            return {
                "final_context": variable_context,
                "context": variable_context,
                "results": results,
                "stopped_at_step": step_num,
                "error": error_msg
            }
            
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            print(f"❌ {error_msg}")
            print(f"🛑 STOPPING WORKFLOW - Unexpected Error in step {step_num}")
            import traceback
            traceback.print_exc()
            
            results.append({
                "step": step_num,
                "agent": agent_name,
                "tool": tool_name,
                "status": "error",
                "error": error_msg
            })
            
            # Stop workflow and return early
            print(f"\n{'='*60}")
            print("🛑 ORCHESTRATOR STOPPED DUE TO UNEXPECTED ERROR")
            print(f"{'='*60}")
            print(f"📊 Completed steps: {step_num}/{len(plan)}")
            print(f"✓ Successful: {sum(1 for r in results if r.get('status') == 'success')}")
            print(f"ℹ️ No Results: {sum(1 for r in results if r.get('status') == 'no_results')}")
            print(f"✗ Failed at step: {step_num}")
            print(f"{'='*60}\n")
            
            return {
                "final_context": variable_context,
                "context": variable_context,
                "results": results,
                "stopped_at_step": step_num,
                "error": error_msg
            }
    
    print(f"\n{'='*60}")
    print("✅ ORCHESTRATOR COMPLETED")
    print(f"{'='*60}")
    print(f"📊 Total steps: {len(plan)}")
    print(f"✓ Successful: {sum(1 for r in results if r.get('status') == 'success')}")
    print(f"ℹ️ No Results: {sum(1 for r in results if r.get('status') == 'no_results')}")
    print(f"✗ Failed: {sum(1 for r in results if r.get('status') == 'error')}")
    
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
                    if 'message_id' in value[0]:
                        print(f"      └─ [0].message_id: {value[0].get('message_id')}")
                    if 'from' in value[0]:
                        print(f"      └─ [0].from: {value[0].get('from')}")
                    if 'subject' in value[0]:
                        print(f"      └─ [0].subject: {value[0].get('subject')}")
            else:
                print(f"   {key}: {value}")
        elif isinstance(value, dict):
            print(f"   {key}: Dict with keys: {list(value.keys())}")
        else:
            print(f"   {key}: {value}")
    print("─" * 60)
    print(f"{'='*60}\n")
    
    return {
        "final_context": variable_context,
        "context": variable_context,
        "results": results
    }


#Build langraph workflow
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
                "current_day": datetime.now().day
            },
            "memory": request.memory,
            "policy": request.policies,
            "final_context": {}
        }
        
        print(f"📅 Date context: today={today}, yesterday={yesterday}")
        
        # Execute workflow
        print("🚀 Starting workflow execution...")
        result_state = workflow.invoke(initial_state)
        
        print("\n✅ Workflow completed successfully")

        # Also print to console for immediate viewing
        print(f"\n📋 Generated Plan:\n{json.dumps(result_state.get('plan', {}), indent=2)}")
        print(f"\n📊 Final Context: {json.dumps(result_state.get('final_context', {}), indent=2)}")
        
        return WorkflowResponse(
            status="success",
            final_context=result_state.get("final_context", {}),
            plan=result_state.get("plan", {}),
            message="Workflow executed successfully"
        )
    
    except ApprovalRequiredException as approval_ex:
        # Handle approval requirement gracefully
        print(f"\n⏸️ Workflow paused - approval required for action: {approval_ex.action_id}")
        
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
                    "Include decision: 'approve', 'reject', or 'skip'"
                ]
            }
        )
        
    except Exception as e:
        print(f"\n❌ Error executing workflow: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Workflow execution failed: {str(e)}"
        )

@app.get("/actions/pending")
async def list_pending_actions():
    """List all actions waiting for approval"""
    pending = []
    
    for action_id, action in PENDING_ACTIONS.items():
        if action.status == "pending":
            pending.append(action.to_dict())
    
    return {
        "pending_actions": pending,
        "count": len(pending)
    }

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
        "expires_at": (action.created_at + timedelta(minutes=5)).isoformat()
    }

@app.post("/action/approve/{action_id}")
async def approve_action(action_id: str, approval: ActionApprovalRequest):
    """
    Approve or reject a specific action.
    After approval, the workflow continues from where it paused.
    """
    action = get_pending_action(action_id)
    
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    
    if action.status != "pending":
        raise HTTPException(status_code=400, detail=f"Action already {action.status}")
    
    # Check timeout
    if datetime.now() - action.created_at > timedelta(minutes=5):
        action.status = "expired"
        raise HTTPException(status_code=400, detail="Action approval expired")
    
    # Handle rejection
    if approval.decision == "reject":
        action.status = "rejected"
        print(f"❌ Action {action_id} rejected: {approval.rejection_reason}")
        return {
            "status": "rejected",
            "action_id": action_id,
            "message": f"Action rejected: {approval.rejection_reason}"
        }
    
    # Handle skip
    if approval.decision == "skip":
        action.status = "skipped"
        print(f"⏭️ Action {action_id} skipped")
        return {
            "status": "skipped",
            "action_id": action_id,
            "message": "Action skipped, workflow will continue to next step"
        }
    
    # Handle approval (with optional modifications)
    action.status = "approved"
    
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
        
        # Clean up
        remove_pending_action(action_id)
        
        return {
            "status": "completed",
            "action_id": action_id,
            "result": result,
            "message": "Action executed successfully"
        }
        
    except Exception as e:
        action.status = "failed"
        action.result = {"error": str(e)}
        
        return {
            "status": "failed",
            "action_id": action_id,
            "error": str(e),
            "message": f"Action execution failed: {str(e)}"
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
            "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN")
        }
    }
    
    # Use retry logic
    result = call_agent_with_retry(
        agent_url=agent_url,
        request_payload=request_payload,
        max_retries=3
    )
    
    if not result:
        raise ValueError("Agent call failed after retries")
    
    return result

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
            "health": "/health (GET) - Health check",
            "docs": "/docs (GET) - Swagger documentation"
        }
    }


# Run the server
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print(f"🚀 Starting Supervisor Agent on port {port}")
    print(f"📚 API Documentation: http://localhost:{port}/docs")
    uvicorn.run(app, host="0.0.0.0", port=port)