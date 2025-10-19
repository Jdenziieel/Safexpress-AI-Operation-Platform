# Option 3: Action-Based Approval - Detailed Guide

## 🎯 Overview

**Action-Based Approval** allows the workflow to execute freely **until** it encounters a sensitive action, at which point it **pauses** and asks for approval for **that specific action only**.

### Key Characteristics:
- ✅ **Automatic execution** of safe steps (reading emails, searching)
- ⏸️ **Pauses mid-workflow** when hitting sensitive actions
- 🎯 **Granular approval** per action, not per plan
- 🔄 **Continues automatically** after approval

---

## 🏗️ How It Works

```
User Request: "Find emails from John and reply to all of them"

Step 1: Search emails ✅ (Auto-execute - safe)
Step 2: Reply to email 1 ⏸️ (PAUSE - ask approval)
  → User approves → Continue
Step 3: Reply to email 2 ⏸️ (PAUSE - ask approval)
  → User approves → Continue
Step 4: Reply to email 3 ⏸️ (PAUSE - ask approval)
  → User approves → Continue
Done! ✅
```

---

## 💡 When to Use Action-Based Approval

### ✅ **Good For:**
- Mixed workflows (safe + dangerous actions)
- Workflows where early steps inform later decisions
- Iterative processes (process each item after seeing results)
- Learning from data before taking action

### ❌ **Not Ideal For:**
- All steps are sensitive (use Option 1 instead)
- Need to review entire plan upfront
- Batch operations where context matters
- When approval fatigue is a concern

---

## 🔧 Implementation

### Step 1: Define Action Risk Levels

```python
# Add to supervisor_agent.py

from enum import Enum

class ActionRiskLevel(str, Enum):
    SAFE = "safe"              # Read-only, no approval needed
    MODERATE = "moderate"       # Modifies data, optional approval
    DANGEROUS = "dangerous"     # Sends data out, always requires approval
    CRITICAL = "critical"       # Irreversible actions, requires approval + confirmation

# Categorize all actions by risk level
ACTION_RISK_LEVELS = {
    # SAFE - Read-only operations
    "read_recent_emails": ActionRiskLevel.SAFE,
    "search_emails": ActionRiskLevel.SAFE,
    "get_thread_conversation": ActionRiskLevel.SAFE,
    "read_doc": ActionRiskLevel.SAFE,
    
    # MODERATE - Modifies internal state
    "create_draft_email": ActionRiskLevel.MODERATE,  # Draft only, not sent
    "add_label": ActionRiskLevel.MODERATE,           # Just labels
    "remove_label": ActionRiskLevel.MODERATE,
    "create_doc": ActionRiskLevel.MODERATE,          # Creates but doesn't share
    
    # DANGEROUS - Sends data externally
    "send_draft_email": ActionRiskLevel.DANGEROUS,
    "reply_to_email": ActionRiskLevel.DANGEROUS,
    "send_email_with_attachment": ActionRiskLevel.DANGEROUS,
    "add_text": ActionRiskLevel.DANGEROUS,           # Modifies shared doc
    
    # CRITICAL - Irreversible actions
    "delete_email": ActionRiskLevel.CRITICAL,        # If you add this
    "remove_label_TRASH": ActionRiskLevel.CRITICAL,  # Permanently delete
}

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
```

### Step 2: Add Action Approval Storage

```python
# Add to supervisor_agent.py

import asyncio
from typing import Callable, Awaitable

# Store for pending action approvals
PENDING_ACTIONS = {}

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
    import uuid
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
```

### Step 3: Create Action Approval Models

```python
# Add to supervisor_agent.py

class ActionApprovalRequest(BaseModel):
    """Request to approve or reject a specific action"""
    action_id: str
    decision: str  # "approve", "reject", "skip"
    modified_inputs: Optional[Dict[str, Any]] = None
    rejection_reason: Optional[str] = None

class ActionApprovalResponse(BaseModel):
    """Response for action requiring approval"""
    action_id: str
    status: str
    step_info: Dict[str, Any]
    message: str
    approval_endpoint: str
    timeout_seconds: int = 300  # 5 minutes default
```

### Step 4: Modify Orchestrator Node for Action-Based Approval

```python
# Replace orchestrator_node function with this enhanced version

def orchestrator_node_with_action_approval(state: SharedState) -> SharedState:
    """
    Executes the plan with action-based approval.
    Pauses at dangerous actions and waits for approval.
    """
    print("\n" + "="*60)
    print("⚙️ ORCHESTRATOR NODE - Execution with Action Approval")
    print("="*60)
    
    plan = state["plan"].get("plan", [])
    variable_context = state.get("context", {})
    results = []
    
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
        
        # ... rest of normal execution logic ...
        # (Same as original orchestrator_node)

class ApprovalRequiredException(Exception):
    """Raised when an action requires approval"""
    def __init__(self, action_id: str, step_info: dict, message: str):
        self.action_id = action_id
        self.step_info = step_info
        super().__init__(message)
```

### Step 5: Create Action Approval Endpoints

```python
# Add these endpoints to supervisor_agent.py

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


def generate_action_summary(tool: str, inputs: dict) -> dict:
    """Generate human-readable summary of action"""
    summary = {
        "action": tool,
        "description": ""
    }
    
    if tool == "send_draft_email" or tool == "send_email_with_attachment":
        summary["description"] = f"Send email to {inputs.get('to', 'unknown')}"
        summary["details"] = {
            "recipient": inputs.get("to"),
            "subject": inputs.get("subject"),
            "body_preview": inputs.get("body", "")[:200] + "..."
        }
    
    elif tool == "reply_to_email":
        summary["description"] = f"Reply to email"
        summary["details"] = {
            "message_id": inputs.get("message_id"),
            "reply_preview": inputs.get("reply_body", "")[:200] + "..."
        }
    
    elif tool == "add_text":
        summary["description"] = f"Add text to document"
        summary["details"] = {
            "document_id": inputs.get("document_id"),
            "text_preview": inputs.get("text", "")[:200] + "..."
        }
    
    else:
        summary["description"] = f"Execute {tool}"
        summary["details"] = inputs
    
    return summary
```

---

## 🔄 Workflow Execution Flow

### Normal Flow (All Safe Actions):
```
User → /workflow → Plan Generated → All Steps Execute → Done ✅
```

### Flow with Dangerous Action:
```
User → /workflow → Plan Generated
  ↓
Step 1 (safe) → Executes ✅
Step 2 (safe) → Executes ✅
Step 3 (dangerous) → PAUSE ⏸️
  ↓
Returns: { action_id: "action_abc123", status: "awaiting_approval" }
  ↓
User Reviews: GET /action/action_abc123
  ↓
User Approves: POST /action/approve/action_abc123
  ↓
Step 3 Executes ✅
Step 4 (safe) → Executes ✅
Done ✅
```

---

## 📱 Usage Examples

### Example 1: Workflow Pauses at Dangerous Action

```bash
# Start workflow
curl -X POST http://localhost:8000/workflow \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Find emails from John and reply to all with thank you"
  }'

# Response (if it hits a dangerous action):
{
  "status": "paused",
  "message": "Workflow paused - action requires approval",
  "action_id": "action_abc123",
  "step_number": 2,
  "action_details": {
    "tool": "reply_to_email",
    "inputs": {
      "message_id": "msg_123",
      "reply_body": "Thank you for your email!"
    }
  },
  "approval_endpoint": "/action/approve/action_abc123"
}
```

### Example 2: Review Action Details

```bash
# Get full details
curl http://localhost:8000/action/action_abc123

# Response:
{
  "action_id": "action_abc123",
  "step_info": {
    "step_number": 2,
    "agent": "gmail_agent",
    "tool": "reply_to_email",
    "risk_level": "dangerous",
    "inputs": {
      "message_id": "msg_123",
      "reply_body": "Thank you for your email!"
    }
  },
  "summary": {
    "action": "reply_to_email",
    "description": "Reply to email",
    "details": {
      "message_id": "msg_123",
      "reply_preview": "Thank you for your email!"
    }
  },
  "status": "pending",
  "created_at": "2025-10-15T10:30:00",
  "expires_at": "2025-10-15T10:35:00"
}
```

### Example 3: Approve and Continue

```bash
# Approve the action
curl -X POST http://localhost:8000/action/approve/action_abc123 \
  -H "Content-Type: application/json" \
  -d '{
    "action_id": "action_abc123",
    "decision": "approve"
  }'

# Response:
{
  "status": "completed",
  "action_id": "action_abc123",
  "result": {
    "success": true,
    "reply_message_id": "reply_456"
  },
  "message": "Action executed successfully"
}

# Workflow automatically continues to next step!
```

### Example 4: Reject Action

```bash
# Reject with reason
curl -X POST http://localhost:8000/action/approve/action_abc123 \
  -H "Content-Type: application/json" \
  -d '{
    "action_id": "action_abc123",
    "decision": "reject",
    "rejection_reason": "Wrong email address"
  }'

# Workflow stops at this step
```

### Example 5: Modify Before Approval

```bash
# Modify inputs before executing
curl -X POST http://localhost:8000/action/approve/action_abc123 \
  -H "Content-Type: application/json" \
  -d '{
    "action_id": "action_abc123",
    "decision": "approve",
    "modified_inputs": {
      "message_id": "msg_123",
      "reply_body": "Thank you! I will review this and get back to you."
    }
  }'
```

### Example 6: Skip Action

```bash
# Skip this action but continue workflow
curl -X POST http://localhost:8000/action/approve/action_abc123 \
  -H "Content-Type: application/json" \
  -d '{
    "action_id": "action_abc123",
    "decision": "skip"
  }'

# Workflow continues to next step without executing this one
```

---

## 🎯 Advanced: Batch Approval

For workflows with multiple dangerous actions:

```python
@app.post("/actions/approve-batch")
async def approve_multiple_actions(approvals: List[ActionApprovalRequest]):
    """Approve multiple actions at once"""
    results = []
    
    for approval in approvals:
        try:
            result = await approve_action(approval.action_id, approval)
            results.append(result)
        except Exception as e:
            results.append({
                "action_id": approval.action_id,
                "status": "error",
                "error": str(e)
            })
    
    return {
        "results": results,
        "total": len(approvals),
        "approved": sum(1 for r in results if r.get("status") == "completed")
    }
```

---

## 🔔 Real-Time Notifications

Integrate with webhooks or websockets for real-time approval requests:

```python
import asyncio
from typing import Dict

# WebSocket connections for real-time updates
active_connections: Dict[str, WebSocket] = {}

@app.websocket("/ws/approvals")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_id = str(uuid.uuid4())
    active_connections[client_id] = websocket
    
    try:
        while True:
            # Wait for messages
            data = await websocket.receive_text()
            # Handle approval decisions via websocket
    except WebSocketDisconnect:
        del active_connections[client_id]

async def notify_approval_needed(action: PendingAction):
    """Notify all connected clients about pending approval"""
    message = {
        "type": "approval_required",
        "action_id": action.action_id,
        "step_info": action.step_info
    }
    
    for client_id, connection in active_connections.items():
        try:
            await connection.send_json(message)
        except:
            pass
```

---

## ⚙️ Configuration Options

```python
# Add to .env or config

# Auto-approve moderate risk actions (drafts, labels, etc.)
AUTO_APPROVE_MODERATE = true

# Action approval timeout (minutes)
ACTION_APPROVAL_TIMEOUT = 5

# Require double confirmation for critical actions
REQUIRE_DOUBLE_CONFIRM_CRITICAL = true

# Webhook URL for approval notifications
APPROVAL_WEBHOOK_URL = "https://slack.com/webhook/..."

# Email notifications for approvals
APPROVAL_EMAIL_ENABLED = true
APPROVAL_EMAIL_TO = "admin@company.com"
```

---

## 📊 Comparison: Option 3 vs Others

| Feature | Option 1: Plan Review | Option 2: Step-by-Step | **Option 3: Action-Based** |
|---------|---------------------|---------------------|------------------------|
| **Approval Points** | Once (before execution) | Every step | Only dangerous steps |
| **Auto-execution** | No | No | Yes (for safe actions) |
| **Flexibility** | Low | High | High |
| **User Burden** | Low | High | Medium |
| **Response Time** | Slow | Very slow | Fast for safe parts |
| **Best For** | All-dangerous workflows | Highly sensitive | Mixed workflows |

---

## 🎯 Summary

**Option 3: Action-Based Approval** is ideal when:
- ✅ Workflow has **mix of safe and dangerous actions**
- ✅ You want **fast execution** for read operations
- ✅ You need **granular control** over each sensitive action
- ✅ Workflow needs to **adapt based on data** gathered in safe steps

**Key Benefits:**
- 🚀 Fast execution of safe operations
- ⏸️ Pauses only when necessary
- 🎯 Granular approval control
- 🔄 Can continue after approval

**Implementation Checklist:**
```python
1. ✅ Define ACTION_RISK_LEVELS
2. ✅ Add requires_approval() function
3. ✅ Modify orchestrator to pause at dangerous actions
4. ✅ Add /action/approve/{action_id} endpoint
5. ✅ Add /actions/pending endpoint
6. ✅ Optional: Add websocket notifications
```

This gives you the perfect balance between automation and control! 🎛️
