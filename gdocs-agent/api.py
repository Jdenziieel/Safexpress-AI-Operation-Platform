#GOOGLE DOCS API
import os
import re
import json
import time
from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agent import create_docs_agent
from tools import (
    _create_google_doc_impl,
    _add_text_to_doc_impl,
    _read_google_doc_impl,
    _share_google_docs_impl,
    _edit_google_doc_impl,
    _update_entire_doc_impl,
    _create_doc_with_content_impl,
    _add_text_from_file_impl,
    _list_user_docs_impl,
)
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


def _parse_tool_result(tool_name: str, raw: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert the string output of legacy _impl functions into a structured dict
    that the orchestrator can consume (matching the AgentTaskResponse.result schema).

    New tools (create_doc_with_content, add_text_from_file) return dicts directly
    and should NOT go through this function.
    """
    if not isinstance(raw, str):
        return raw

    is_error = (
        raw.lower().startswith("error")
        or "error" in raw.lower().split("\n")[0]
    ) and "successfully" not in raw.lower()

    if is_error:
        return {"success": False, "error": raw}

    doc_id_match = re.search(r"(?:ID|Document ID): ([a-zA-Z0-9_-]+)", raw)
    url_match = re.search(r"URL: (https://[^\s]+)", raw)
    title_match = re.search(r"Title: ([^\n]+)", raw)

    doc_id = doc_id_match.group(1) if doc_id_match else inputs.get("document_id", "")
    doc_url = url_match.group(1) if url_match else ""

    if tool_name == "create_doc":
        return {
            "success": True,
            "document_id": doc_id,
            "document_url": doc_url,
            "title": title_match.group(1).strip() if title_match else inputs.get("title", ""),
        }

    if tool_name == "add_text":
        return {
            "success": True,
            "document_id": doc_id,
            "document_url": doc_url,
            "text_length": len(inputs.get("text", "")),
        }

    if tool_name == "read_doc":
        content = ""
        content_match = re.search(r"Document content:\s*\n\n(.*?)\n\nDocument ID:", raw, re.DOTALL)
        if content_match:
            content = content_match.group(1)
        return {
            "success": True,
            "document_id": doc_id,
            "document_url": doc_url,
            "content": content,
            "title": title_match.group(1).strip() if title_match else "",
        }

    if tool_name == "share_doc":
        email_match = re.search(r"Shared with: ([^\n]+)", raw)
        role_match = re.search(r"Permission: ([^\n]+)", raw)
        return {
            "success": True,
            "document_id": doc_id,
            "document_url": doc_url,
            "shared_with": email_match.group(1).strip() if email_match else inputs.get("email", ""),
            "role": role_match.group(1).strip() if role_match else inputs.get("role", ""),
        }

    if tool_name == "edit_doc":
        return {
            "success": True,
            "document_id": doc_id,
            "document_url": doc_url,
            "old_text": inputs.get("old_text", ""),
            "new_text": inputs.get("new_text", ""),
        }

    if tool_name == "update_doc":
        length_match = re.search(r"New content length: (\d+)", raw)
        return {
            "success": True,
            "document_id": doc_id,
            "document_url": doc_url,
            "text_length": int(length_match.group(1)) if length_match else len(inputs.get("new_content", "")),
        }

    if tool_name == "list_my_docs":
        return {"success": True, "message": raw}

    return {"success": True, "raw_response": raw}


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
        # ✅ SPECIAL HANDLING: Direct execution for create_from_uploaded_template
        # Bypass agent because it sometimes refuses this operation
        if request.tool == "create_from_uploaded_template":
            print(f"🔧 Direct execution (bypassing agent): {request.tool}")
            
            from tools import _create_from_uploaded_template_impl
            
            # Extract inputs
            template_file_id = request.inputs.get("template_file_id")
            new_title = request.inputs.get("new_title")
            placeholders = request.inputs.get("placeholders", {})
            output_format = request.inputs.get("output_format", "google_docs")
            
            if not template_file_id:
                return AgentTaskResponse(
                    success=False,
                    result={},
                    error="template_file_id is required"
                )
            
            if not new_title:
                return AgentTaskResponse(
                    success=False,
                    result={},
                    error="new_title is required"
                )
            
            # Validate output_format
            if output_format not in ["google_docs", "pdf"]:
                print(f"⚠️ Invalid output_format '{output_format}', defaulting to 'google_docs'")
                output_format = "google_docs"
            
            print(f"📄 Output format requested: {output_format}")
            
            # Execute directly with output_format parameter
            try:
                result_text = _create_from_uploaded_template_impl(
                    template_file_id=template_file_id,
                    new_title=new_title,
                    placeholder_values=placeholders,
                    credentials_dict=request.credentials_dict,
                    output_format=output_format
                )
                
                print(f"📄 Direct execution result:\n{result_text}")
                
                # Parse result (it returns a formatted string)
                if "✅" in result_text:
                    # Extract document ID and URL from success message
                    import re
                    
                    # Check if PDF output
                    is_pdf = "PDF ID:" in result_text or output_format == "pdf"
                    
                    if is_pdf:
                        # Parse PDF response
                        pdf_id_match = re.search(r"PDF ID: ([a-zA-Z0-9_-]+)", result_text)
                        pdf_url_match = re.search(r"PDF URL: (https://[^\s]+)", result_text)
                        doc_id_match = re.search(r"Google Doc ID: ([a-zA-Z0-9_-]+)", result_text)
                        doc_url_match = re.search(r"Google Doc URL: (https://[^\s]+)", result_text)
                        title_match = re.search(r"Title: ([^\n]+)", result_text)
                        
                        parsed_result = {
                            "success": True,
                            "document_id": pdf_id_match.group(1) if pdf_id_match else None,
                            "document_url": pdf_url_match.group(1) if pdf_url_match else None,
                            "title": title_match.group(1).strip() if title_match else f"{new_title}.pdf",
                            "template_used": template_file_id,
                            "format": "PDF",
                            "editable": False,
                            "google_docs_version_id": doc_id_match.group(1) if doc_id_match else None,
                            "google_docs_version_url": doc_url_match.group(1) if doc_url_match else None
                        }
                    else:
                        # Parse Google Docs response
                        doc_id_match = re.search(r"Document ID: ([a-zA-Z0-9_-]+)", result_text)
                        url_match = re.search(r"URL: (https://[^\s]+)", result_text)
                        title_match = re.search(r"Title: ([^\n]+)", result_text)
                        
                        parsed_result = {
                            "success": True,
                            "document_id": doc_id_match.group(1) if doc_id_match else None,
                            "document_url": url_match.group(1) if url_match else None,
                            "title": title_match.group(1).strip() if title_match else new_title,
                            "template_used": template_file_id,
                            "format": "Google Docs",
                            "editable": True
                        }
                    
                    print(f"\n📤 Complete Result:")
                    print(json.dumps(parsed_result, indent=2, default=str))
                    print(f"{'='*60}\n")
                    
                    return AgentTaskResponse(
                        success=True,
                        result=parsed_result,
                        raw_response=result_text
                    )
                else:
                    # Error case
                    return AgentTaskResponse(
                        success=False,
                        result={},
                        error=result_text,
                        raw_response=result_text
                    )
            except Exception as direct_exec_error:
                print(f"❌ Direct execution failed: {str(direct_exec_error)}")
                import traceback
                traceback.print_exc()
                return AgentTaskResponse(
                    success=False,
                    result={},
                    error=str(direct_exec_error)
                )
            
        # ✅ SPECIAL HANDLING: Direct execution for create_from_template_and_data_ids
        if request.tool == "create_from_template_and_data_ids":
            print(f"🔧 Direct execution: {request.tool}")
            
            from tools import _create_from_template_and_data_ids_impl
            
            template_file_id = request.inputs.get("template_file_id")
            data_file_id = request.inputs.get("data_file_id")
            new_title = request.inputs.get("new_title")
            output_format = request.inputs.get("output_format", "google_docs")
            
            if not template_file_id:
                return AgentTaskResponse(
                    success=False,
                    result={},
                    error="template_file_id is required"
                )
            
            if not data_file_id:
                return AgentTaskResponse(
                    success=False,
                    result={},
                    error="data_file_id is required"
                )
            
            if not new_title:
                return AgentTaskResponse(
                    success=False,
                    result={},
                    error="new_title is required"
                )
            
            try:
                result_text = _create_from_template_and_data_ids_impl(
                    template_file_id=template_file_id,
                    data_file_id=data_file_id,
                    new_title=new_title,
                    credentials_dict=request.credentials_dict,
                    output_format=output_format
                )
                
                print(f"📄 Direct execution result:\n{result_text}")
                
                if "✅" in result_text:
                    import re
                    
                    is_pdf = "PDF ID:" in result_text or output_format == "pdf"
                    
                    if is_pdf:
                        pdf_id_match = re.search(r"PDF ID: ([a-zA-Z0-9_-]+)", result_text)
                        pdf_url_match = re.search(r"PDF URL: (https://[^\s]+)", result_text)
                        doc_id_match = re.search(r"Google Doc ID: ([a-zA-Z0-9_-]+)", result_text)
                        
                        parsed_result = {
                            "success": True,
                            "document_id": pdf_id_match.group(1) if pdf_id_match else None,
                            "document_url": pdf_url_match.group(1) if pdf_url_match else None,
                            "title": f"{new_title}.pdf",
                            "format": "PDF",
                            "google_docs_version_id": doc_id_match.group(1) if doc_id_match else None
                        }
                    else:
                        doc_id_match = re.search(r"Document ID: ([a-zA-Z0-9_-]+)", result_text)
                        url_match = re.search(r"URL: (https://[^\s]+)", result_text)
                        
                        parsed_result = {
                            "success": True,
                            "document_id": doc_id_match.group(1) if doc_id_match else None,
                            "document_url": url_match.group(1) if url_match else None,
                            "title": new_title,
                            "format": "Google Docs"
                        }
                    
                    return AgentTaskResponse(
                        success=True,
                        result=parsed_result,
                        raw_response=result_text
                    )
                else:
                    return AgentTaskResponse(
                        success=False,
                        result={},
                        error=result_text,
                        raw_response=result_text
                    )
            except Exception as e:
                print(f"❌ Direct execution failed: {str(e)}")
                import traceback
                traceback.print_exc()
                return AgentTaskResponse(
                    success=False,
                    result={},
                    error=str(e)
                )
        
        # ✅ SPECIAL HANDLING: Direct execution for analyze_uploaded_template
        if request.tool == "analyze_uploaded_template":
            print(f"🔬 Analyzing uploaded template: {request.tool}")
    
            from tools import _analyze_uploaded_template_impl
    
            template_file_id = request.inputs.get("template_file_id")
    
            if not template_file_id:
                return AgentTaskResponse(
                    success=False,
                    result={},
                    error="template_file_id is required"
                )
            
            try:
                analysis_json = _analyze_uploaded_template_impl(
                    template_file_id=template_file_id,
                    credentials_dict=request.credentials_dict
                )
        
                analysis_result = json.loads(analysis_json)
        
                print(f"\n📤 Template Analysis Result:")
                print(json.dumps(analysis_result, indent=2))
                print(f"{'='*60}\n")
        
                return AgentTaskResponse(
                    success=analysis_result.get("success", False),
                    result=analysis_result,
                    raw_response=analysis_json
                )
            except Exception as e:
                print(f"❌ Analysis failed: {str(e)}")
                import traceback
                traceback.print_exc()
                return AgentTaskResponse(
                    success=False,
                    result={},
                    error=str(e)
                )
        
        # =====================================================================
        # DIRECT DISPATCH VIA TOOL_MAP (no LLM overhead for tool-based calls)
        # =====================================================================
        TOOL_MAP = {
            "create_doc": _create_google_doc_impl,
            "add_text": _add_text_to_doc_impl,
            "read_doc": _read_google_doc_impl,
            "share_doc": _share_google_docs_impl,
            "edit_doc": _edit_google_doc_impl,
            "update_doc": _update_entire_doc_impl,
            "create_doc_with_content": _create_doc_with_content_impl,
            "add_text_from_file": _add_text_from_file_impl,
            "list_my_docs": _list_user_docs_impl,
        }

        DICT_RETURNING_TOOLS = {"create_doc_with_content", "add_text_from_file"}

        if request.tool and request.tool in TOOL_MAP:
            print(f"🔧 Direct dispatch: {request.tool}")
            tool_start = time.time()

            tool_impl = TOOL_MAP[request.tool]
            try:
                raw_result = tool_impl(**request.inputs, credentials_dict=request.credentials_dict)
                elapsed = time.time() - tool_start
                print(f"Tool executed in {elapsed:.2f}s")

                if request.tool in DICT_RETURNING_TOOLS:
                    parsed = raw_result
                else:
                    parsed = _parse_tool_result(request.tool, raw_result, request.inputs)

                is_success = parsed.get("success", True)

                print(f"\n{'='*60}")
                print(f"Result:")
                print(json.dumps(parsed, indent=2, default=str))
                print(f"{'='*60}\n")

                return AgentTaskResponse(
                    success=is_success,
                    result=parsed,
                    raw_response=raw_result if isinstance(raw_result, str) else json.dumps(raw_result),
                )
            except Exception as tool_err:
                print(f"Direct dispatch failed: {tool_err}")
                import traceback
                traceback.print_exc()
                return AgentTaskResponse(
                    success=False,
                    result={},
                    error=str(tool_err),
                )

        # =====================================================================
        # LANGCHAIN REACT AGENT FALLBACK (task-based requests only)
        # =====================================================================
        if request.task is not None:
            print(f"Task execution: {request.task}")
            agent = create_docs_agent(request.credentials_dict)

            agent_prompt = f"""You are a Google Docs specialist agent. Execute the following task intelligently.

TASK TYPE: {request.task}

INSTRUCTION:
{request.instruction if request.instruction else "Execute the task based on inputs provided"}

INPUTS/CONTEXT:
{json.dumps(request.inputs, indent=2)}

{f'EXPECTED OUTPUT STRUCTURE:\nYou MUST return a valid JSON object with these exact keys:\n' + json.dumps(request.expected_output, indent=2) if request.expected_output else ''}

INSTRUCTIONS:
1. Use your available tools intelligently to accomplish the task
2. Create, edit, or read documents as needed
3. Format content appropriately for Google Docs
4. Return your response as a JSON object matching the expected output structure

Execute the task now and return ONLY the JSON response with the expected keys.
"""
            result = agent.invoke({
                "messages": [("user", agent_prompt)]
            })

            messages = result.get("messages", [])
            if not messages:
                raise ValueError("No response from agent")

            final_message = messages[-1].content

            try:
                json_str = final_message
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0].strip()
                elif "```" in json_str:
                    json_str = json_str.split("```")[1].split("```")[0].strip()

                parsed_result = json.loads(json_str)

                if request.expected_output:
                    missing_keys = set(request.expected_output.keys()) - set(parsed_result.keys())
                    if missing_keys:
                        print(f"Warning: Missing expected keys: {missing_keys}")

                print(f"\n{'='*60}")
                print(f"Result:")
                print(json.dumps(parsed_result, indent=2, default=str))
                print(f"{'='*60}\n")

                return AgentTaskResponse(
                    success=True,
                    result=parsed_result,
                    raw_response=final_message
                )

            except json.JSONDecodeError as e:
                print(f"Warning: Agent response was not valid JSON: {e}")
                return AgentTaskResponse(
                    success=True,
                    result={
                        "response": final_message,
                        "note": "Agent did not return structured JSON"
                    },
                    raw_response=final_message
                )

        raise ValueError("Request must have either 'task' or 'tool' field")
    
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