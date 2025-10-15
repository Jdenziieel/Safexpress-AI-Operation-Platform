"""
SafExpressOps Google Docs Agent Lambda
"""

import json
import os
from agent import create_docs_agent


def lambda_handler(event, context):
    """Google Docs Agent Lambda Handler"""
    try:
        print("📄 Docs Agent Lambda invoked")

        # Parse event
        if isinstance(event.get("body"), str):
            body = json.loads(event["body"])
        else:
            body = event

        tool = body.get("tool")
        task = body.get("task")
        instruction = body.get("instruction")
        inputs = body.get("inputs", {})
        expected_output = body.get("expected_output")
        credentials_dict = body.get("credentials", {})

        print(f"🔧 Tool/Task: {tool or task}")
        print(f"📝 Inputs: {json.dumps(inputs)}")

        # Validate credentials
        if not credentials_dict.get("access_token"):
            return {
                "statusCode": 401,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"success": False, "error": "Missing access_token"}),
            }

        # Get OpenAI API key from environment
        openai_api_key = os.environ.get("OPENAI_API_KEY")
        if not openai_api_key:
            return {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(
                    {
                        "success": False,
                        "error": "OPENAI_API_KEY not configured in Lambda environment",
                    }
                ),
            }

        # Create AI agent with explicit API key
        print("🤖 Creating Docs agent...")
        agent = create_docs_agent(credentials_dict, openai_api_key=openai_api_key)

        # Build prompt
        if tool:
            # Direct tool call
            tool_instructions = {
                "create_doc": 'Return JSON: {"success": true, "document_id": "...", "document_url": "...", "title": "..."}',
                "add_text": 'Return JSON: {"success": true, "document_id": "...", "document_url": "...", "text_length": N}',
                "read_doc": 'Return JSON: {"success": true, "document_id": "...", "document_url": "...", "content": "...", "title": "..."}',
                "share_doc": 'Return JSON: {"success": true, "document_id": "...", "document_url": "...", "shared_with": "...", "role": "..."}',
            }

            agent_prompt = f"""Execute tool: {tool}

Inputs: {json.dumps(inputs, indent=2)}

{tool_instructions.get(tool, "")}

Return ONLY valid JSON, no markdown."""

        elif task:
            agent_prompt = f"""Task: {task}
Instruction: {instruction or "Execute based on inputs"}
Inputs: {json.dumps(inputs, indent=2)}
{f"Expected output: {json.dumps(expected_output)}" if expected_output else ""}

Execute intelligently and return JSON."""

        else:
            return {
                "statusCode": 400,
                "body": json.dumps({"success": False, "error": "Need tool or task"}),
            }

        # Invoke AI agent
        print("🚀 Invoking AI agent...")
        result = agent.invoke({"messages": [("user", agent_prompt)]})

        # Parse response
        messages = result.get("messages", [])
        if not messages:
            raise ValueError("No response from agent")

        final_message = messages[-1].content
        print(f"📨 Agent responded: {final_message[:200]}...")

        # Try to parse as JSON
        try:
            json_str = final_message
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            parsed_result = json.loads(json_str)

            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(
                    {
                        "success": True,
                        "result": parsed_result,
                        "raw_response": final_message,
                    }
                ),
            }

        except json.JSONDecodeError:
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(
                    {
                        "success": True,
                        "result": {"response": final_message},
                        "raw_response": final_message,
                    }
                ),
            }

    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        import traceback

        traceback.print_exc()

        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {"success": False, "error": str(e), "type": type(e).__name__}
            ),
        }
