# Human-in-the-Loop (HITL) Implementation Guide

## 🎯 Overview

Add human approval checkpoints to prevent automated execution of sensitive actions like:
- ✉️ Sending emails
- 📄 Modifying documents
- 🗑️ Deleting data
- 📤 Sharing files externally

---

## 🏗️ Architecture Options

### **Option 1: Plan Review Before Execution** (RECOMMENDED)
Review and approve the entire plan before any steps execute.

### **Option 2: Step-by-Step Approval**
Approve each step individually during execution.

### **Option 3: Action-Based Approval**
Only require approval for specific "dangerous" actions.

---

## 📍 Implementation: Option 1 - Plan Review Before Execution

This is the **simplest and most effective** approach. The supervisor generates the plan, shows it to the user, and waits for approval before executing.

### Step 1: Add Approval Models

```python
# Add to supervisor_agent.py (after existing imports)

from enum import Enum

class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"

class PlanApprovalRequest(BaseModel):
    """Request to approve or reject a plan"""
    plan_id: str
    status: ApprovalStatus
    modified_plan: Optional[Dict[str, Any]] = None
    rejection_reason: Optional[str] = None

class PlanReviewResponse(BaseModel):
    """Response containing plan for review"""
    plan_id: str
    status: str
    plan: Dict[str, Any]
    message: str
    requires_approval: bool
    approval_endpoint: str
```

### Step 2: Add Plan Storage

```python
# Add after OUTPUT_DIR definition

# In-memory store for pending plans (use Redis/database in production)
PENDING_PLANS = {}

def generate_plan_id() -> str:
    """Generate unique plan ID"""
    import uuid
    return str(uuid.uuid4())

def store_pending_plan(plan_id: str, plan_data: dict, initial_state: dict):
    """Store plan for approval"""
    PENDING_PLANS[plan_id] = {
        "plan": plan_data,
        "initial_state": initial_state,
        "status": ApprovalStatus.PENDING,
        "created_at": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(hours=1)).isoformat()
    }

def get_pending_plan(plan_id: str) -> Optional[dict]:
    """Retrieve pending plan"""
    return PENDING_PLANS.get(plan_id)

def update_plan_status(plan_id: str, status: ApprovalStatus):
    """Update plan approval status"""
    if plan_id in PENDING_PLANS:
        PENDING_PLANS[plan_id]["status"] = status
```

### Step 3: Detect Actions Requiring Approval

```python
# Add after store functions

ACTIONS_REQUIRING_APPROVAL = {
    "send_email_with_attachment",
    "send_draft_email",
    "reply_to_email",
    "add_text",  # Modifying docs
    "create_doc",  # Creating docs
    # Add more as needed
}

def plan_requires_approval(plan: dict) -> bool:
    """Check if plan contains actions requiring approval"""
    plan_steps = plan.get("plan", [])
    
    for step in plan_steps:
        tool = step.get("tool", "")
        if tool in ACTIONS_REQUIRING_APPROVAL:
            return True
    
    return False

def get_approval_summary(plan: dict) -> dict:
    """Generate human-readable approval summary"""
    plan_steps = plan.get("plan", [])
    
    summary = {
        "total_steps": len(plan_steps),
        "requires_approval": plan_requires_approval(plan),
        "sensitive_actions": [],
        "steps_breakdown": []
    }
    
    for i, step in enumerate(plan_steps, 1):
        agent = step.get("agent", "unknown")
        tool = step.get("tool", "unknown")
        description = step.get("description", "")
        inputs = step.get("inputs", {})
        
        step_summary = {
            "step_number": i,
            "agent": agent,
            "tool": tool,
            "description": description,
            "is_sensitive": tool in ACTIONS_REQUIRING_APPROVAL
        }
        
        # Extract key details for sensitive actions
        if tool in ACTIONS_REQUIRING_APPROVAL:
            if tool == "send_draft_email" or tool == "send_email_with_attachment":
                step_summary["details"] = {
                    "to": inputs.get("to", "unknown"),
                    "subject": inputs.get("subject", "unknown"),
                    "body_preview": inputs.get("body", "")[:100] + "..."
                }
            elif tool == "reply_to_email":
                step_summary["details"] = {
                    "message_id": inputs.get("message_id", "unknown"),
                    "reply_preview": inputs.get("reply_body", "")[:100] + "..."
                }
            elif tool == "create_doc":
                step_summary["details"] = {
                    "title": inputs.get("title", "unknown")
                }
            
            summary["sensitive_actions"].append(step_summary)
        
        summary["steps_breakdown"].append(step_summary)
    
    return summary
```

### Step 4: Create Review Endpoint

```python
# Replace the existing /workflow endpoint with two-stage process

@app.post("/workflow/plan", response_model=PlanReviewResponse)
async def generate_plan_for_review(request: UserRequest):
    """
    STAGE 1: Generate plan and return for user review.
    Does NOT execute any actions.
    """
    try:
        print(f"\n📥 Received request for plan generation: {request.input}")
        
        # Get current date for date-aware queries
        today = datetime.now().strftime("%Y/%m/%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y/%m/%d")
        
        # Prepare initial state
        initial_state: SharedState = {
            "input": request.input,
            "plan": {},
            "context": {
                "today_date": today,
                "yesterday_date": yesterday,
            },
            "memory": request.memory,
            "policy": request.policies,
            "final_context": {}
        }
        
        print("🧠 Generating plan (supervisor node only)...")
        
        # Only run supervisor node to generate plan
        plan_result = supervisor_node(initial_state)
        plan_data = plan_result["plan"]
        
        # Check if approval is required
        requires_approval = plan_requires_approval(plan_data)
        
        if requires_approval:
            # Store plan for later execution
            plan_id = generate_plan_id()
            store_pending_plan(plan_id, plan_data, initial_state)
            
            # Generate approval summary
            summary = get_approval_summary(plan_data)
            
            print(f"\n⚠️ Plan requires approval!")
            print(f"   Plan ID: {plan_id}")
            print(f"   Sensitive actions: {len(summary['sensitive_actions'])}")
            
            return PlanReviewResponse(
                plan_id=plan_id,
                status="pending_approval",
                plan=plan_data,
                message=f"Plan requires approval. Contains {len(summary['sensitive_actions'])} sensitive action(s). Review and approve via /workflow/approve endpoint.",
                requires_approval=True,
                approval_endpoint=f"/workflow/approve/{plan_id}"
            )
        else:
            # Auto-execute safe plans
            print("✅ Plan contains only safe actions, auto-executing...")
            result_state = workflow.invoke(initial_state)
            
            return WorkflowResponse(
                status="success",
                final_context=result_state.get("final_context", {}),
                plan=result_state.get("plan", {}),
                message="Workflow executed successfully (auto-approved)"
            )
        
    except Exception as e:
        print(f"\n❌ Error generating plan: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/workflow/approve/{plan_id}")
async def approve_and_execute_plan(plan_id: str, approval: PlanApprovalRequest):
    """
    STAGE 2: Approve and execute a pending plan.
    
    Args:
        plan_id: The ID of the plan to execute
        approval: Approval decision (approved/rejected/modified)
    """
    try:
        # Retrieve pending plan
        pending = get_pending_plan(plan_id)
        
        if not pending:
            raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
        
        if pending["status"] != ApprovalStatus.PENDING:
            raise HTTPException(
                status_code=400,
                detail=f"Plan already {pending['status']}"
            )
        
        # Check if plan expired (1 hour timeout)
        expires_at = datetime.fromisoformat(pending["expires_at"])
        if datetime.now() > expires_at:
            update_plan_status(plan_id, ApprovalStatus.REJECTED)
            raise HTTPException(status_code=400, detail="Plan expired")
        
        # Handle rejection
        if approval.status == ApprovalStatus.REJECTED:
            update_plan_status(plan_id, ApprovalStatus.REJECTED)
            print(f"❌ Plan {plan_id} rejected by user")
            return {
                "status": "rejected",
                "message": f"Plan rejected: {approval.rejection_reason}",
                "plan_id": plan_id
            }
        
        # Handle modification
        if approval.status == ApprovalStatus.MODIFIED and approval.modified_plan:
            print(f"📝 Plan {plan_id} modified by user")
            pending["plan"] = approval.modified_plan
            pending["initial_state"]["plan"] = approval.modified_plan
        
        # Execute approved plan
        update_plan_status(plan_id, ApprovalStatus.APPROVED)
        print(f"✅ Plan {plan_id} approved, executing...")
        
        initial_state = pending["initial_state"]
        initial_state["plan"] = pending["plan"]
        
        # Execute the orchestrator node only (plan already generated)
        result = orchestrator_node(initial_state)
        
        # Clean up
        del PENDING_PLANS[plan_id]
        
        return WorkflowResponse(
            status="success",
            final_context=result.get("final_context", {}),
            plan=pending["plan"],
            message="Workflow executed successfully after approval"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"\n❌ Error executing approved plan: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/workflow/pending")
async def list_pending_plans():
    """List all pending plans awaiting approval"""
    pending = []
    
    for plan_id, data in PENDING_PLANS.items():
        if data["status"] == ApprovalStatus.PENDING:
            summary = get_approval_summary(data["plan"])
            pending.append({
                "plan_id": plan_id,
                "created_at": data["created_at"],
                "expires_at": data["expires_at"],
                "summary": summary
            })
    
    return {"pending_plans": pending, "count": len(pending)}


@app.get("/workflow/plan/{plan_id}")
async def get_plan_details(plan_id: str):
    """Get detailed view of a pending plan"""
    pending = get_pending_plan(plan_id)
    
    if not pending:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    summary = get_approval_summary(pending["plan"])
    
    return {
        "plan_id": plan_id,
        "status": pending["status"],
        "created_at": pending["created_at"],
        "expires_at": pending["expires_at"],
        "plan": pending["plan"],
        "summary": summary,
        "initial_request": pending["initial_state"]["input"]
    }
```

---

## 📱 Frontend/CLI Usage Examples

### Example 1: Generate Plan for Review

```bash
# Step 1: Generate plan (doesn't execute)
curl -X POST http://localhost:8000/workflow/plan \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Send an email to boss@company.com saying the project is complete"
  }'

# Response:
{
  "plan_id": "abc-123-def",
  "status": "pending_approval",
  "plan": {
    "plan": [
      {
        "agent": "gmail_agent",
        "tool": "send_email_with_attachment",
        "inputs": {
          "to": "boss@company.com",
          "subject": "Project Status Update",
          "body": "The project is complete!"
        }
      }
    ]
  },
  "message": "Plan requires approval. Contains 1 sensitive action(s).",
  "requires_approval": true,
  "approval_endpoint": "/workflow/approve/abc-123-def"
}
```

### Example 2: Review Plan Details

```bash
# View full plan details
curl http://localhost:8000/workflow/plan/abc-123-def

# Response shows:
# - What will be executed
# - Who will receive emails
# - What content will be sent
# - Expiration time
```

### Example 3: Approve Plan

```bash
# Approve and execute
curl -X POST http://localhost:8000/workflow/approve/abc-123-def \
  -H "Content-Type: application/json" \
  -d '{
    "plan_id": "abc-123-def",
    "status": "approved"
  }'
```

### Example 4: Reject Plan

```bash
# Reject with reason
curl -X POST http://localhost:8000/workflow/approve/abc-123-def \
  -H "Content-Type: application/json" \
  -d '{
    "plan_id": "abc-123-def",
    "status": "rejected",
    "rejection_reason": "Wrong recipient email address"
  }'
```

### Example 5: Modify and Approve

```bash
# Modify plan before execution
curl -X POST http://localhost:8000/workflow/approve/abc-123-def \
  -H "Content-Type: application/json" \
  -d '{
    "plan_id": "abc-123-def",
    "status": "modified",
    "modified_plan": {
      "plan": [
        {
          "agent": "gmail_agent",
          "tool": "create_draft_email",
          "inputs": {
            "to": "boss@company.com",
            "subject": "Project Status Update",
            "body": "CORRECTED: The project is 90% complete."
          }
        }
      ]
    }
  }'
```

---

## 📍 Option 2: Step-by-Step Approval (Advanced)

For more granular control, approve each step individually:

```python
@app.post("/workflow/execute-step/{plan_id}/{step_number}")
async def execute_single_step(
    plan_id: str,
    step_number: int,
    approval: Dict[str, Any]
):
    """Execute a single step after approval"""
    pending = get_pending_plan(plan_id)
    
    if not pending:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    plan_steps = pending["plan"].get("plan", [])
    
    if step_number < 1 or step_number > len(plan_steps):
        raise HTTPException(status_code=400, detail="Invalid step number")
    
    step = plan_steps[step_number - 1]
    
    # Execute this step only
    # ... (similar to orchestrator_node but for single step)
    
    return {
        "status": "success",
        "step_number": step_number,
        "step_result": "..."
    }
```

---

## 🎨 Interactive Web UI (Optional)

Create a simple approval interface:

```html
<!DOCTYPE html>
<html>
<head>
    <title>Plan Approval Dashboard</title>
    <style>
        .plan-step { padding: 10px; margin: 5px; border: 1px solid #ddd; }
        .sensitive { background-color: #fff3cd; }
        .safe { background-color: #d4edda; }
    </style>
</head>
<body>
    <h1>Pending Plans</h1>
    <div id="plans"></div>
    
    <script>
        async function loadPendingPlans() {
            const response = await fetch('/workflow/pending');
            const data = await response.json();
            
            const container = document.getElementById('plans');
            data.pending_plans.forEach(plan => {
                const div = document.createElement('div');
                div.innerHTML = `
                    <h3>Plan ${plan.plan_id}</h3>
                    <p>Created: ${plan.created_at}</p>
                    <p>Sensitive actions: ${plan.summary.sensitive_actions.length}</p>
                    <button onclick="approvePlan('${plan.plan_id}')">Approve</button>
                    <button onclick="rejectPlan('${plan.plan_id}')">Reject</button>
                `;
                container.appendChild(div);
            });
        }
        
        async function approvePlan(planId) {
            await fetch(`/workflow/approve/${planId}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({plan_id: planId, status: 'approved'})
            });
            location.reload();
        }
        
        loadPendingPlans();
    </script>
</body>
</html>
```

---

## 🔒 Security Best Practices

1. **Authentication**: Add user authentication to approval endpoints
2. **Authorization**: Check user permissions for approval
3. **Audit Logging**: Log all approvals/rejections
4. **Timeout**: Expire plans after 1 hour
5. **Rate Limiting**: Prevent approval spam

```python
# Add authentication
from fastapi.security import HTTPBearer

security = HTTPBearer()

@app.post("/workflow/approve/{plan_id}")
async def approve_plan(
    plan_id: str,
    approval: PlanApprovalRequest,
    credentials: str = Depends(security)
):
    # Verify user token
    user = verify_token(credentials)
    
    # Log approval
    log_approval(user, plan_id, approval.status)
    
    # ... rest of approval logic
```

---

## 📊 Configuration Options

```python
# Add to .env or config file

# Which actions require approval
APPROVAL_REQUIRED_ACTIONS = [
    "send_email_with_attachment",
    "send_draft_email",
    "reply_to_email",
    "add_text",
    "create_doc"
]

# Approval timeout (hours)
APPROVAL_TIMEOUT_HOURS = 1

# Auto-approve for specific users
AUTO_APPROVE_USERS = ["admin@company.com"]

# Require approval for all plans (even safe ones)
REQUIRE_APPROVAL_ALL = False
```

---

## 🧪 Testing

```python
# test_approval.py

def test_plan_generation():
    """Test that dangerous plans require approval"""
    response = client.post("/workflow/plan", json={
        "input": "Send email to test@example.com"
    })
    assert response.status_code == 200
    assert response.json()["requires_approval"] == True

def test_plan_approval():
    """Test plan approval flow"""
    # Generate plan
    plan_response = client.post("/workflow/plan", json={
        "input": "Send test email"
    })
    plan_id = plan_response.json()["plan_id"]
    
    # Approve plan
    approve_response = client.post(f"/workflow/approve/{plan_id}", json={
        "plan_id": plan_id,
        "status": "approved"
    })
    assert approve_response.status_code == 200

def test_plan_rejection():
    """Test plan rejection"""
    # Generate and reject
    plan_response = client.post("/workflow/plan", json={
        "input": "Send test email"
    })
    plan_id = plan_response.json()["plan_id"]
    
    reject_response = client.post(f"/workflow/approve/{plan_id}", json={
        "plan_id": plan_id,
        "status": "rejected",
        "rejection_reason": "Testing rejection"
    })
    assert reject_response.status_code == 200
```

---

## 🎯 Summary

**Recommended Approach:**

1. ✅ Use **Option 1** (Plan Review Before Execution)
2. ✅ Define `ACTIONS_REQUIRING_APPROVAL` list
3. ✅ Generate plan with `/workflow/plan` endpoint
4. ✅ Show plan to user for review
5. ✅ User approves via `/workflow/approve/{plan_id}`
6. ✅ Execute only after approval

**Benefits:**
- Simple to implement
- Clear user experience
- Prevents accidental data sending
- Allows plan modification
- Supports timeout/expiration

**Production Enhancements:**
- Add authentication
- Store plans in database (not in-memory)
- Add audit logging
- Create web UI for approvals
- Send approval requests via email/Slack

This gives you full control over sensitive operations! 🚀
