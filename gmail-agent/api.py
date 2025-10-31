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


@app.post("/execute_task")
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
        print(f"\n{'='*60}")
        print(f"📨 Incoming Request")
        print(f"{'='*60}")
        print(f"🔧 Tool: {request.tool}")
        print(f"📥 Inputs: {json.dumps(request.inputs, indent=2)}")
        print(f"{'='*60}\n")
        
        import time
        start_time = time.time()
        
        # Option 1: Use ReAct agent (slower but can reason)
        # agent = create_email_agent(request.credentials_dict)
        # print(f"✅ Agent created in {time.time() - start_time:.2f}s")
        
        # Option 2: Direct tool execution with simple LLM for input transformation (FAST)
        from tools import (
            _search_emails_impl,
            _send_email_impl,
            _send_email_with_attachments_impl,
            _reply_to_email_impl,
            _forward_email_impl,
            _create_draft_email_impl,
            _send_draft_email_impl,
            _search_drafts_impl,
            _get_thread_conversation_impl,
            _add_label_impl,
            _remove_label_impl,
            _download_attachment_impl,
        )
        
        # Map tool names to implementations
        TOOL_MAP = {
            "search_emails": _search_emails_impl,
            "send_email": _send_email_impl,
            "send_email_with_attachment": _send_email_with_attachments_impl,
            "reply_to_email": _reply_to_email_impl,
            "forward_email": _forward_email_impl,
            "create_draft_email": _create_draft_email_impl,
            "send_draft_email": _send_draft_email_impl,
            "search_drafts": _search_drafts_impl,
            "get_thread_conversation": _get_thread_conversation_impl,
            "add_label": _add_label_impl,
            "remove_label": _remove_label_impl,
            "download_attachment": _download_attachment_impl,
        }
        
        tool_impl = TOOL_MAP.get(request.tool)
        if not tool_impl:
            return {
                "success": False,
                "error": f"Unknown tool: {request.tool}"
            }
        
        # Apply transformations for email-sending tools using simple LLM
        transformed_inputs = dict(request.inputs)
        
        if request.tool in ["send_draft_email", "reply_to_email", "forward_email", "send_email", "create_draft_email"]:
            # Only use LLM if we need to transform the body
            if "body" in transformed_inputs or "reply_body" in transformed_inputs or "forward_message" in transformed_inputs:
                from langchain_openai import ChatOpenAI
                llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=os.getenv("OPENAI_API_KEY"))
                
                # Determine which field to transform
                body_field = None
                original_content = ""
                if "body" in transformed_inputs:
                    body_field = "body"
                    original_content = transformed_inputs['body']
                elif "reply_body" in transformed_inputs:
                    body_field = "reply_body"
                    original_content = transformed_inputs['reply_body']
                elif "forward_message" in transformed_inputs:
                    body_field = "forward_message"
                    original_content = transformed_inputs['forward_message']
                
                if body_field and original_content:
                    transform_prompt = f"""Add this signature to the end of the email body:

--- 
This is written by Assistant Agent

Original body:
{original_content}

Return ONLY the modified body text, nothing else."""
                    
                    print(f"🤖 Using LLM to transform email {body_field}...")
                    llm_start = time.time()
                    response = llm.invoke(transform_prompt)
                    transformed_inputs[body_field] = response.content.strip()
                    print(f"✅ LLM transformation completed in {time.time() - llm_start:.2f}s")
        
        # Call tool directly
        print(f"🔧 Calling tool implementation directly...")
        tool_start = time.time()
        result = tool_impl(**transformed_inputs, credentials_dict=request.credentials_dict)
        print(f"✅ Tool executed in {time.time() - tool_start:.2f}s")
        
        print(f"\n{'='*60}")
        print(f"✅ Success! Total time: {time.time() - start_time:.2f}s")
        print(f"{'='*60}\n")
        
        return result
    
    except Exception as e:
        print(f"❌ Error executing task: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return {
            "success": False,
            "error": str(e)
        }


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


# import os
# import json
# from typing import Dict, Any
# from fastapi import FastAPI, HTTPException
# from pydantic import BaseModel
# from agent import create_email_agent
# from dotenv import load_dotenv

# load_dotenv()

# app = FastAPI(title="Gmail Agent API", version="1.0.0")


# class AgentTaskRequest(BaseModel):
#     """Request model for executing a task with the Gmail agent"""
#     tool: str  # Tool name (e.g., "search_emails", "read_recent_emails")
#     inputs: Dict[str, Any]  # Tool inputs and context from previous steps
#     credentials_dict: Dict[str, str]  # User's OAuth credentials


# class AgentTaskResponse(BaseModel):
#     """Response model from the Gmail agent"""
#     success: bool
#     result: Dict[str, Any]
#     raw_response: str = None
#     error: str = None


# @app.post("/execute_task")
# async def execute_task(request: AgentTaskRequest):
#     """
#     Execute a tool with the Gmail agent.
    
#     Request format:
#     {
#         "tool": "search_emails",
#         "inputs": {"query": "from:lance@example.com", "max_results": 1},
#         "credentials_dict": {...}
#     }
#     """
#     try:
#         # Create the agent with user credentials
#         print(f"\n{'='*60}")
#         print(f"📨 Incoming Request")
#         print(f"{'='*60}")
#         print(f"🔧 Tool: {request.tool}")
#         print(f"📥 Inputs: {json.dumps(request.inputs, indent=2)}")
#         print(f"{'='*60}\n")
        
#         import time
#         start_time = time.time()
        
#         agent = create_email_agent(request.credentials_dict)
        
#         print(f"✅ Agent created in {time.time() - start_time:.2f}s")
        
#         # Build email signature instruction for email-sending tools
#         email_signature_instruction = ""
#         if request.tool in ["send_draft_email", "reply_to_email", "send_email"]:
#             email_signature_instruction = """
#     IMPORTANT: Before sending any email, append the following signature to the end of the body:
    
#     ---
#     This is written by Assistant Agent
#     """
        
#         agent_prompt = f"""You are a Gmail specialist agent. Execute the following tool directly.

#     TOOL TO USE: {request.tool}

#     TOOL INPUTS:
#     {json.dumps(request.inputs, indent=2)}
#     {email_signature_instruction}
#     CRITICAL INSTRUCTIONS:
#     1. Call the tool '{request.tool}' IMMEDIATELY with the exact inputs provided
#     2. Do NOT ask questions, do NOT explain, do NOT plan
#     3. Just call the tool and return its JSON output
#     4. Return ONLY the JSON from the tool, nothing else
#     """
        
#         # Invoke the agent with the constructed prompt
#         # Set recursion_limit to 5 - enough for ReAct pattern (think→act→respond) but prevents excessive loops
#         print(f"🤖 Invoking agent with recursion_limit=5...")
#         invoke_start = time.time()
        
#         result = agent.invoke(
#             {"messages": [("user", agent_prompt)]},
#             config={"recursion_limit": 5}  # Balanced: enough for ReAct, but prevents excessive reasoning
#         )
        
#         print(f"✅ Agent invocation completed in {time.time() - invoke_start:.2f}s")
        
#         # Extract the agent's final response
#         messages = result.get("messages", [])
#         if not messages:
#             raise ValueError("No response from agent")
        
#         final_message = messages[-1].content
        
#         # Try to parse the response as JSON
#         try:
#             # Look for JSON in the response (might be wrapped in markdown code blocks)
#             json_str = final_message
            
#             # Remove markdown code blocks if present
#             if "```json" in json_str:
#                 json_str = json_str.split("```json")[1].split("```")[0].strip()
#             elif "```" in json_str:
#                 json_str = json_str.split("```")[1].split("```")[0].strip()
            
#             parsed_result = json.loads(json_str)
            
#             print(f"\n{'='*60}")
#             print(f"✅ Success! Total time: {time.time() - start_time:.2f}s")
#             print(f"{'='*60}\n")
            
#             # Return the tool's result directly (tools already have "success" field)
#             return parsed_result
            
#         except json.JSONDecodeError as e:
#             # If agent didn't return valid JSON, return error in same format as tools
#             print(f"⚠️ Warning: Agent response was not valid JSON: {e}")
#             print(f"Raw response: {final_message}")
            
#             return {
#                 "success": False,
#                 "error": f"Agent did not return valid JSON: {str(e)}",
#                 "raw_response": final_message
#             }
    
#     except Exception as e:
#         print(f"❌ Error executing task: {str(e)}")
#         import traceback
#         traceback.print_exc()
        
#         return {
#             "success": False,
#             "error": str(e)
#         }


# @app.get("/health")
# async def health_check():
#     """Health check endpoint"""
#     return {
#         "status": "healthy",
#         "service": "gmail-agent",
#         "version": "1.0.0"
#     }


# @app.get("/")
# async def root():
#     """Root endpoint with API information"""
#     return {
#         "service": "Gmail Agent API",
#         "description": "Gmail agent that executes tools directly via supervisor",
#         "endpoints": {
#             "POST /execute_task": "Execute a tool with the Gmail agent",
#             "GET /health": "Health check",
#             "GET /": "This information"
#         },
#         "example_request": {
#             "tool": "search_emails",
#             "inputs": {
#                 "query": "from:lance@example.com",
#                 "max_results": 5
#             },
#             "credentials_dict": {
#                 "access_token": "...",
#                 "refresh_token": "..."
#             }
#         }
#     }


# if __name__ == "__main__":
#     import uvicorn
    
#     print("=" * 60)
#     print("🚀 Starting Gmail Agent API Server")
#     print("=" * 60)
#     print("📡 Endpoint: http://localhost:8001")
#     print("📚 Docs: http://localhost:8001/docs")
#     print("=" * 60)
    
#     uvicorn.run(app, host="0.0.0.0", port=8001)

