import os
import json
from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agent import create_email_agent
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Gmail Agent API", version="1.0.0")


class AgentTaskRequest(BaseModel):
    """Request model for executing a task with the Gmail agent"""
    tool: str  # Tool name (e.g., "search_emails", "read_recent_emails")
    inputs: Dict[str, Any]  # Tool inputs and context from previous steps
    credentials_dict: Dict[str, str]  # User's OAuth credentials


class AgentTaskResponse(BaseModel):
    """Response model from the Gmail agent"""
    success: bool
    result: Dict[str, Any]
    raw_response: str = None
    error: str = None


@app.post("/execute_task", response_model=AgentTaskResponse)
async def execute_task(request: AgentTaskRequest):
    """
    Execute a tool with the Gmail agent.
    
    Request format:
    {
        "tool": "search_emails",
        "inputs": {"query": "from:lance@example.com", "max_results": 1},
        "credentials_dict": {...}
    }
    """
    try:
        # Create the agent with user credentials
        agent = create_email_agent(request.credentials_dict)
        
        print(f"🔧 Direct tool call: {request.tool}")
        
        # Build specific instructions based on the tool
        tool_specific_instructions = ""
        if request.tool == "search_emails":
            tool_specific_instructions = """
    RETURN FORMAT: The tool returns a structured JSON. Pass it through directly:
    {
        "success": true,
        "emails": [...array of email objects...],
        "count": <number of emails found>,
        "query": "<the search query used>",
        "first_message_id": "<message ID of first email or null>",
        "first_thread_id": "<thread ID of first email or null>",
        "error": null
    }
    
    CRITICAL: Return the EXACT output from the tool without modification."""
        elif request.tool == "read_recent_emails":
            tool_specific_instructions = """
    RETURN FORMAT: The tool returns a structured JSON. Pass it through directly:
    {
        "success": true,
        "emails": [...array of email objects...],
        "count": <number of emails>,
        "first_message_id": "<message ID of first email or null>",
        "first_thread_id": "<thread ID of first email or null>",
        "error": null
    }
    
    CRITICAL: Return the EXACT output from the tool without modification."""
        elif request.tool == "send_email":
            tool_specific_instructions = """
    RETURN FORMAT: Return JSON with send confirmation:
    {
        "success": true,
        "message_id": "<Gmail message ID>",
        "to": "<recipient email>",
        "subject": "<email subject>",
        "body": "<email body>"
    }"""
        elif request.tool == "send_email_with_attachment":
            tool_specific_instructions = """
    RETURN FORMAT: Return JSON with send confirmation:
    {
        "success": true,
        "message_id": "<Gmail message ID>",
        "to": "<recipient email>",
        "subject": "<email subject>",
        "body": "<email body>",
        "attachment_name": "<file name>",
        "attachment_path": "<file path>"
    }"""
        
        agent_prompt = f"""You are a Gmail specialist agent. Execute the following tool directly.

    TOOL TO USE: {request.tool}

    TOOL INPUTS:
    {json.dumps(request.inputs, indent=2)}

    INSTRUCTIONS:
    1. Call the specified tool '{request.tool}' with the provided inputs
    2. The tool will return a structured JSON dictionary
    3. Return the EXACT JSON output from the tool without any modifications
    4. Do NOT add, remove, or rename any fields
    5. Do NOT extract or transform the data
    {tool_specific_instructions}

    CRITICAL: Return ONLY the exact JSON from the tool, no markdown, no extra text, no modifications.
    """
        
        # Invoke the agent with the constructed prompt
        # Add recursion_limit to prevent excessive reasoning loops
        result = agent.invoke(
            {"messages": [("user", agent_prompt)]},
            config={"recursion_limit": 10}  # Max 10 reasoning steps
        )
        
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
        "service": "gmail-agent",
        "version": "1.0.0"
    }


@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "service": "Gmail Agent API",
        "description": "Gmail agent that executes tools directly via supervisor",
        "endpoints": {
            "POST /execute_task": "Execute a tool with the Gmail agent",
            "GET /health": "Health check",
            "GET /": "This information"
        },
        "example_request": {
            "tool": "search_emails",
            "inputs": {
                "query": "from:lance@example.com",
                "max_results": 5
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
    print("🚀 Starting Gmail Agent API Server")
    print("=" * 60)
    print("📡 Endpoint: http://localhost:8001")
    print("📚 Docs: http://localhost:8001/docs")
    print("=" * 60)
    
    uvicorn.run(app, host="0.0.0.0", port=8001)
