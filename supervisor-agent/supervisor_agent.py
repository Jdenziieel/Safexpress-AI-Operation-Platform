from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
import json
import httpx
import jinja2
from typing import TypedDict, List, Optional, Dict, Any
from dotenv import load_dotenv
import os
import uvicorn
import asyncio


load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="Supervisor Agent API")

llm = ChatOpenAI(
        model="gpt-4", temperature=0, openai_api_key=os.getenv("OPENAI_API_KEY")
    )

# Microservice URLs for specialized agents
AGENT_ENDPOINTS = {
    "gmail_agent": os.getenv("GMAIL_AGENT_URL", "http://localhost:8001/execute_task"),
    "docs_agent": os.getenv("DOCS_AGENT_URL", "http://localhost:8002/execute_task"),
    "sheets_agent": os.getenv("SHEETS_AGENT_URL", "http://localhost:8003/execute_task"),
    "calendar_agent": os.getenv("CALENDAR_AGENT_URL", "http://localhost:8004/execute_task"),
    "drive_agent": os.getenv("DRIVE_AGENT_URL", "http://localhost:8005/execute_task"),
}

# Create output directory for saved JSON files
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "agent_outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

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

plan_schema = """
{
  "plan": [
    {
      "agent": "string - name of the agent to use (e.g., 'gmail_agent', 'docs_agent')",
      "tool": "string - exact tool name from agent's tools list (e.g., 'send_email', 'create_doc')",
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

# Examples of multi-step plans (condensed):
plan_examples = """
Example: Read email → Reply
{{"plan": [{{"agent": "gmail_agent", "tool": "read_recent_emails", "inputs": {{"max_results": 3}}, "output_variables": {{"sender": "email_1_from"}}}}, {{"agent": "gmail_agent", "tool": "send_email", "inputs": {{"to": "{{{{ sender }}}}", "subject": "Reply", "body": "Thanks"}}}}]}}

Example: Create doc → Email link
{{"plan": [{{"agent": "docs_agent", "tool": "create_doc", "inputs": {{"title": "Report"}}, "output_variables": {{"doc_link": "document_url"}}}}, {{"agent": "gmail_agent", "tool": "send_email", "inputs": {{"to": "team@ex.com", "subject": "Report", "body": "Link: {{{{ doc_link }}}}"}}}}]}}
"""

agent_capabilities = {
    "gmail_agent": {
        "description": "Send emails, read recent emails, search emails, and send emails with attachments using Gmail API.",
        "tools": {
            "send_email": {
                "description": "Sends an email using Gmail API",
                "args": {
                    "to": "str (required) — recipient email address",
                    "subject": "str (required) — subject line",
                    "body": "str (required) — email body content"
                },
                "returns": {
                    "success": "bool — whether email was sent successfully",
                    "message_id": "str — Gmail message ID (null if failed)",
                    "to": "str — recipient email address",
                    "subject": "str — email subject",
                    "body": "str — email body content",
                    "error": "str — error message (null if successful)"
                }
            },
            "read_recent_emails": {
                "description": "Reads recent emails from Gmail",
                "args": {
                    "max_results": "int (required) — number of recent emails to fetch"
                },
                "returns": {
                    "success": "bool — whether read was successful",
                    "emails": "list — array of email objects [{from, subject, date, snippet}, ...]",
                    "count": "int — number of emails found",
                    "email_1_from": "str — first email sender (null if no emails)",
                    "email_1_subject": "str — first email subject (null if no emails)",
                    "email_1_snippet": "str — first email preview (null if no emails)",
                    "email_1_date": "str — first email date (null if no emails)",
                    "error": "str — error message (null if successful)"
                }
            },
            "search_emails": {
                "description": "Search emails in Gmail matching a query",
                "args": {
                    "query": "str (required) — search query (e.g., 'from:example@example.com', 'subject:meeting')",
                    "max_results": "int (required) — number of emails to fetch"
                },
                "returns": {
                    "success": "bool — whether search was successful",
                    "emails": "list — array of matching email objects",
                    "count": "int — number of emails found",
                    "query": "str — the search query used",
                    "email_1_from": "str — first result sender (null if no results)",
                    "email_1_subject": "str — first result subject (null if no results)",
                    "email_1_snippet": "str — first result preview (null if no results)",
                    "email_1_date": "str — first result date (null if no results)",
                    "error": "str — error message (null if successful)"
                }
            },
            "send_email_with_attachment": {
                "description": "Sends an email with an attachment using Gmail API",
                "args": {
                    "to": "str (required) — recipient email address",
                    "subject": "str (required) — subject line",
                    "body": "str (required) — email body content",
                    "file_path": "str (required) — path to the file to attach"
                },
                "returns": {
                    "success": "bool — whether email was sent successfully",
                    "message_id": "str — Gmail message ID (null if failed)",
                    "to": "str — recipient email address",
                    "subject": "str — email subject",
                    "body": "str — email body content",
                    "attachment_name": "str — name of attached file (null if failed)",
                    "attachment_path": "str — path to attached file",
                    "error": "str — error message (null if successful)"
                }
            }
        }
    },
    "docs_agent": {
        "description": "Create, edit, and read Google Docs documents.",
        "tools": {
            "create_doc": {
                "description": "Creates a new Google Doc and returns its ID and URL",
                "args": {
                    "title": "str (required) — the name of the document (e.g., 'Project Notes')"
                },
                "returns": {
                    "success": "bool — whether document was created successfully",
                    "document_id": "str — Google Doc ID (null if failed)",
                    "document_url": "str — URL to access the document (null if failed)",
                    "title": "str — document title",
                    "error": "str — error message (null if successful)"
                }
            },
            "add_text": {
                "description": "Adds text to an existing Google Doc",
                "args": {
                    "document_id": "str (required) — the ID of the document",
                    "text": "str (required) — the text content to add"
                },
                "returns": {
                    "success": "bool — whether text was added successfully",
                    "document_id": "str — the document that was modified",
                    "document_url": "str — URL to access the document",
                    "text_length": "int — length of text added",
                    "error": "str — error message (null if successful)"
                }
            },
            "read_doc": {
                "description": "Reads text content from a Google Doc",
                "args": {
                    "document_id": "str (required) — the ID of the document to read"
                },
                "returns": {
                    "success": "bool — whether read was successful",
                    "document_id": "str — the document that was read",
                    "document_url": "str — URL to access the document",
                    "content": "str — full document text content",
                    "title": "str — document title",
                    "error": "str — error message (null if successful)"
                }
            }
        }
    },
    "sheets_agent": {
        "description": "Create or update Google Sheets.",
        "args": {
            "title": "str (required) — sheet title",
            "data": "List[List[str]] (required) — 2D list of rows"
        },
        "returns": ["sheet_url"]
    },
    "calendar_agent": {
        "description": "Create or update calendar events.",
        "args": {
            "title": "str (required) — event title",
            "datetime": "str (required) — ISO date/time",
            "attendees": "List[str] (optional) — participant emails",
            "description": "str (optional) — event details"
        },
        "returns": ["event_id"]
    },
    "drive_agent": {
        "description": "Upload or share files using Google Drive.",
        "args": {
            "filename": "str (required) — file name",
            "file_url": "str (optional) — URL or path of file to upload",
            "share_with": "List[str] (optional) — list of users to share with"
        },
        "returns": ["drive_url"]
    }
}

class SharedState(TypedDict):
    input: str
    plan: dict
    context: dict
    memory: dict
    policy: list
    final_context:dict

def identify_relevant_agents(user_input: str) -> List[str]:
    """
    Use a cheap/fast LLM call to identify which agents are relevant.
    This is a simple classification task, much cheaper than full planning.
    """
    classifier_prompt = f"""
    Based on this user request, which agents are needed? 
    Available agents: gmail_agent, docs_agent, sheets_agent, calendar_agent, drive_agent
    
    User request: {user_input}
    
    Return ONLY a JSON array of agent names needed. Example: ["docs_agent", "gmail_agent"]
    """
    
    # Use cheaper model (gpt-3.5-turbo) or lower temperature
    classifier_llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0)
    response = classifier_llm.invoke([{"role": "user", "content": classifier_prompt}])
    
    # Parse the agent list
    agent_list = json.loads(response.content.strip())
    return agent_list

def get_filtered_capabilities(agent_names: List[str]) -> Dict:
    """Only return capabilities for specified agents"""
    return {
        agent: agent_capabilities[agent]
        for agent in agent_names
        if agent in agent_capabilities
    }

def supervisor_node(state: SharedState) -> SharedState:
    """
    STEP 1: Supervisor generates a plan based on user input
    Enhanced to support multi-step workflows with data dependencies
    """
    print("\n" + "="*60)
    print("🧠 SUPERVISOR NODE - Planning Phase")
    print("="*60)
    
    user_input = state["input"]
    print(f"📥 User Input: {user_input}\n")
        
    # OPTIMIZATION: Filter relevant agents first (cheap)
    relevant_agents = identify_relevant_agents(user_input)

    print(f"📌 Relevant agents: {relevant_agents}")

    # Get only the needed capabilities
    filtered_capabilities = get_filtered_capabilities(relevant_agents)
    
    # Now send to LLM with reduced context
    capability_summary = json.dumps(filtered_capabilities, indent=2)
    schema_text = json.dumps(plan_schema, indent=2)

    system_prompt = f"""You are the Supervisor agent creating multi-step execution plans.

RULES:
1. Reference previous outputs using {{{{ variable_name }}}} syntax
2. Declare output_variables as {{"new_name": "source_field"}} to rename fields from tool's "returns"
3. Break tasks into sequential steps with clear data flow

Available agents and tools:
{capability_summary}

Schema:
{schema_text}

EXAMPLE - Search emails and forward content:
{{
  "plan": [
    {{"agent": "gmail_agent", "tool": "search_emails", "inputs": {{"query": "from:boss@company.com", "max_results": 1}}, 
      "output_variables": {{"boss_email": "email_1_from", "email_subject": "email_1_subject", "email_body": "email_1_snippet"}}, 
      "description": "Find latest email from boss"}},
    {{"agent": "gmail_agent", "tool": "send_email", 
      "inputs": {{"to": "team@company.com", "subject": "FWD: {{{{ email_subject }}}}", "body": "{{{{ email_body }}}}"}}, 
      "output_variables": {{"sent_status": "success"}}, 
      "description": "Forward email content to team"}}
  ]
}}

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
            # Make HTTP POST request to agent
            with httpx.Client(timeout=60.0) as client:
                response = client.post(agent_url, json=request_payload)
                response.raise_for_status()
                result = response.json()
            
            print(f"✅ Agent response received")
            print(f"   Response: {json.dumps(result, indent=6)}")
            
            # STEP 3: Extract variables from result
            if result.get("success"):
                agent_result = result.get("result", {})
                
                # First, add ALL fields from the result to context (for backward compatibility)
                variable_context.update(agent_result)
                
                # Then, create renamed variables based on output_variables mapping
                # Format: "new_variable_name": "source_field_name"
                print(f"\n📦 Variables added to context:")
                for new_var_name, source_field_name in output_variables.items():
                    if source_field_name in agent_result:
                        variable_context[new_var_name] = agent_result[source_field_name]
                        print(f"   ✓ {new_var_name} = {agent_result[source_field_name]} (from {source_field_name})")
                    else:
                        print(f"   ⚠️ {new_var_name} = NOT FOUND (looking for {source_field_name} in result)")
                
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
                error_msg = result.get("error", "Unknown error")
                print(f"❌ Agent reported error: {error_msg}")
                results.append({
                    "step": step_num,
                    "agent": agent_name,
                    "tool": tool_name,
                    "status": "error",
                    "error": error_msg
                })
                # Decide: continue or stop on error?
                # For now, continue to next step
        
        except httpx.HTTPError as e:
            error_msg = f"HTTP error calling {agent_name}: {str(e)}"
            print(f"❌ {error_msg}")
            results.append({
                "step": step_num,
                "agent": agent_name,
                "tool": tool_name,
                "status": "error",
                "error": error_msg
            })
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
            results.append({
                "step": step_num,
                "agent": agent_name,
                "tool": tool_name,
                "status": "error",
                "error": error_msg
            })
    
    print(f"\n{'='*60}")
    print("✅ ORCHESTRATOR COMPLETED")
    print(f"{'='*60}")
    print(f"📊 Total steps: {len(plan)}")
    print(f"✓ Successful: {sum(1 for r in results if r.get('status') == 'success')}")
    print(f"✗ Failed: {sum(1 for r in results if r.get('status') == 'error')}")
    print(f"📦 Variables in context: {list(variable_context.keys())}")
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
        
        # Prepare initial state
        initial_state: SharedState = {
            "input": request.input,
            "plan": {},
            "context": {},
            "memory": request.memory,
            "policy": request.policies,
            "final_context": {}
        }
        
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
        
    except Exception as e:
        print(f"\n❌ Error executing workflow: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Workflow execution failed: {str(e)}"
        )


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