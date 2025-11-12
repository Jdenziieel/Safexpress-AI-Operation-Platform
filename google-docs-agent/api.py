import os
import json
from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agent import create_docs_agent
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Google Docs Agent API", version="1.0.0")


class AgentTaskRequest(BaseModel):
    """Request model for executing a task with the Google Docs agent"""
    # Support both formats:
    task: str = None  # Task identifier (e.g., "create_and_populate") - NEW FORMAT
    tool: str = None  # Tool name (e.g., "create_doc") - OLD FORMAT
    
    instruction: str = None  # Natural language instruction (optional for tool-based)
    inputs: Dict[str, Any]  # Context and variables from previous steps
    expected_output: Dict[str, str] = None  # Keys that the agent should return (optional)
    credentials_dict: Dict[str, str]  # User's OAuth credentials


class AgentTaskResponse(BaseModel):
    """Response model from the Google Docs agent"""
    success: bool
    result: Dict[str, Any]
    raw_response: str = None
    error: str = None


@app.post("/execute_task", response_model=AgentTaskResponse)
async def execute_task(request: AgentTaskRequest):
    """
    Execute a task with the Google Docs agent.
    
    Supports TWO formats:
    
    FORMAT 1 - Task-based (with agent intelligence):
    {
        "task": "create_and_populate",
        "instruction": "Create a project report document with the given content",
        "inputs": {"title": "Q4 Report", "content": "..."},
        "expected_output": {"document_id": "...", "document_url": "..."},
        "credentials_dict": {...}
    }
    
    FORMAT 2 - Tool-based (direct tool call from supervisor):
    {
        "tool": "create_doc",
        "inputs": {"title": "Project Report"},
        "credentials_dict": {...}
    }
    """
    try:
        # Create the agent with user credentials
        agent = create_docs_agent(request.credentials_dict)
        
        # Determine which format is being used
        is_tool_based = request.tool is not None
        is_task_based = request.task is not None
        
        if is_tool_based:
            # FORMAT 2: Direct tool call (supervisor specifies exact tool)
            print(f"🔧 Direct tool call: {request.tool}")
            
            # Build specific instructions based on the tool
            tool_specific_instructions = ""
            if request.tool == "create_doc":
                tool_specific_instructions = """
    RETURN FORMAT: Return JSON with document creation details:
    {
        "success": true,
        "document_id": "<Google Docs ID>",
        "document_url": "<URL to access document>",
        "title": "<document title>"
    }"""
            elif request.tool == "add_text":
                tool_specific_instructions = """
    RETURN FORMAT: Return JSON with text addition confirmation:
    {
        "success": true,
        "document_id": "<the document ID>",
        "document_url": "<URL to access document>",
        "text_length": <number of characters added>
    }"""
            elif request.tool == "read_doc":
                tool_specific_instructions = """
    RETURN FORMAT: Return JSON with document content:
    {
        "success": true,
        "document_id": "<the document ID>",
        "document_url": "<URL to access document>",
        "content": "<full document text>",
        "title": "<document title>"
    }"""
            
            agent_prompt = f"""You are a Google Docs specialist agent. Execute the following tool directly.

    TOOL TO USE: {request.tool}

    TOOL INPUTS:
    {json.dumps(request.inputs, indent=2)}

    INSTRUCTIONS:
    1. Call the specified tool '{request.tool}' with the provided inputs
    2. Parse the tool's output carefully (it may return formatted text)
    3. Extract all relevant information from the tool output
    4. Return a properly structured JSON object
    {tool_specific_instructions}

    CRITICAL: Return ONLY valid JSON, no markdown, no extra text.
    """
        
        elif is_task_based:
            # FORMAT 1: Task-based with agent intelligence
            print(f"🎯 Task execution: {request.task}")
            
            agent_prompt = f"""You are a Google Docs specialist agent. Execute the following task intelligently.

    TASK TYPE: {request.task}

    INSTRUCTION:
    {request.instruction if request.instruction else "Execute the task based on inputs provided"}

    INPUTS/CONTEXT:
    {json.dumps(request.inputs, indent=2)}

    {f'''EXPECTED OUTPUT STRUCTURE:
    You MUST return a valid JSON object with these exact keys:
    {json.dumps(request.expected_output, indent=2)}''' if request.expected_output else ''}

    INSTRUCTIONS:
    1. Use your available tools intelligently to accomplish the task
    2. Create, edit, or read documents as needed
    3. Format content appropriately for Google Docs
    4. Return your response as a JSON object matching the expected output structure

    Execute the task now and return ONLY the JSON response with the expected keys.
    """
        else:
            raise ValueError("Request must have either 'task' or 'tool' field")
        
        # Invoke the agent with the constructed prompt
        result = agent.invoke({
            "messages": [("user", agent_prompt)]
        })
        
        # Extract the agent's final response
        messages = result.get("messages", [])
        if not messages:
            raise ValueError("No response from agent")
        
        final_message = messages[-1].content
        
        # Try to parse the response as JSON
        try:
            # Look for JSON in the response (might be wrapped in markdown code blocks)
            json_str = final_message
            
            # Remove markdown code blocks if present
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()
            
            parsed_result = json.loads(json_str)
            
            # Verify that expected output keys are present (only for task-based)
            if request.expected_output:
                missing_keys = set(request.expected_output.keys()) - set(parsed_result.keys())
                if missing_keys:
                    print(f"⚠️ Warning: Missing expected keys: {missing_keys}")
            
            # Print complete result before returning
            print(f"\n📤 Complete Result:")
            print(json.dumps(parsed_result, indent=2, default=str))
            print(f"{'='*60}\n")
            
            return AgentTaskResponse(
                success=True,
                result=parsed_result,
                raw_response=final_message
            )
            
        except json.JSONDecodeError as e:
            # If agent didn't return valid JSON, wrap the response
            print(f"⚠️ Warning: Agent response was not valid JSON: {e}")
            print(f"Raw response: {final_message}")
            
            # Return the raw response wrapped in a result object
            return AgentTaskResponse(
                success=True,
                result={
                    "response": final_message,
                    "note": "Agent did not return structured JSON"
                },
                raw_response=final_message
            )
    
    except Exception as e:
        print(f"❌ Error executing task: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return AgentTaskResponse(
            success=False,
            result={},
            error=str(e)
        )


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "google-docs-agent",
        "version": "1.0.0"
    }


@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "service": "Google Docs Agent API",
        "description": "Intelligent Google Docs agent that creates and manages documents",
        "endpoints": {
            "POST /execute_task": "Execute a task with the Google Docs agent",
            "GET /health": "Health check",
            "GET /": "This information"
        },
        "example_request": {
            "task": "create_and_populate",
            "instruction": "Create a document and add the provided content",
            "inputs": {
                "title": "Project Report",
                "content": "This is the project summary..."
            },
            "expected_output": {
                "document_id": "Google Docs ID",
                "document_url": "URL to access the document",
                "title": "Document title"
            },
            "credentials_dict": {
                "access_token": "...",
                "refresh_token": "..."
            }
        }
    }


if __name__ == "__main__":
    import uvicorn
    
    print("=" * 60)
    print("🚀 Starting Google Docs Agent API Server")
    print("=" * 60)
    print("📡 Endpoint: http://localhost:8002")
    print("📚 Docs: http://localhost:8002/docs")
    print("=" * 60)
    
    uvicorn.run(app, host="0.0.0.0", port=8002)
