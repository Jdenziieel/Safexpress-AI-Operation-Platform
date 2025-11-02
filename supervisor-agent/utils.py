"""
Utility functions for the Supervisor Agent

This module contains helper functions for:
- Agent identification and filtering
- HTTP calls with retry logic
- Variable substitution
- Action summaries
"""

import json
import time
import httpx
from typing import List, Dict, Optional
from langchain_openai import ChatOpenAI
from agent_capabilities import agent_capabilities
from config import (
    CLASSIFIER_MODEL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    DEFAULT_BACKOFF_FACTOR,
    OPENAI_API_KEY,
)


def identify_relevant_agents(user_input: str) -> List[str]:
    """
    Use a cheap/fast LLM call to identify which agents are relevant.
    This is a simple classification task, much cheaper than full planning.
    """
    classifier_prompt = f"""
    Based on this user request, which agents are needed? 
    
    Available agents:
    - gmail_agent: Read, search, draft, send, reply to emails, manage labels, download attachments
    - docs_agent: Create, edit, and read Google Docs documents
    - mapping_agent: Parse CSV/Excel/JSON files, smart column mapping, data transformation
    - sheets_agent: Google Sheets CRUD operations, upload data to sheets
    - drive_agent: Manage Google Drive files and folders, upload/download files
    - calendar_agent: Create, update, delete, and read calendar events
    
    Note: calendar_agent, and drive_agent are defined but may not be implemented yet.
    
    User request: {user_input}
    
    Return ONLY a JSON array of agent names needed. Example: ["gmail_agent", "docs_agent"]
    """

    # Use cheaper model (gpt-3.5-turbo) or lower temperature
    classifier_llm = ChatOpenAI(
        model=CLASSIFIER_MODEL, temperature=0, openai_api_key=OPENAI_API_KEY
    )
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


def call_agent_with_retry(
    agent_url: str,
    request_payload: dict,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timeout: float = DEFAULT_TIMEOUT,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
) -> Optional[dict]:
    """
    Call an agent with exponential backoff retry logic.

    Args:
        agent_url: URL of the agent endpoint
        request_payload: JSON payload to send
        max_retries: Maximum number of retry attempts
        timeout: Request timeout in seconds
        backoff_factor: Multiplier for exponential backoff (2.0 = double each time)

    Returns:
        Response JSON or None if all retries failed
    """
    last_exception = None

    for attempt in range(max_retries):
        try:
            print(f"🔄 Attempt {attempt + 1}/{max_retries} calling {agent_url}")
            print(f"   ⏱️ Timeout set to: {timeout} seconds")

            # Configure httpx timeout properly - needs to be httpx.Timeout object for long operations
            timeout_config = httpx.Timeout(
                timeout=timeout,
                connect=10.0,  # Connection timeout
                read=timeout,  # Read timeout (for long-running operations)
                write=30.0,  # Write timeout
                pool=10.0,  # Pool timeout
            )

            with httpx.Client(timeout=timeout_config) as client:
                response = client.post(agent_url, json=request_payload)
                response.raise_for_status()
                result = response.json()

                # Check if the agent actually succeeded
                if result.get("success"):
                    print(f"✅ Agent call succeeded on attempt {attempt + 1}")
                    return result
                else:
                    # Agent returned error but HTTP was successful
                    print(f"⚠️ Agent reported error: {result.get('error')}")
                    if attempt < max_retries - 1:
                        wait_time = backoff_factor**attempt
                        print(f"   Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    return result  # Return the error result on last attempt

        except httpx.TimeoutException as e:
            last_exception = e
            print(f"⏱️ Timeout on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = backoff_factor**attempt
                print(f"   Retrying in {wait_time}s...")
                time.sleep(wait_time)

        except httpx.HTTPStatusError as e:
            last_exception = e
            print(f"❌ HTTP {e.response.status_code} on attempt {attempt + 1}")

            # Don't retry on 4xx client errors (except 429 rate limit)
            if 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                print(f"   Client error - not retrying")
                return None

            if attempt < max_retries - 1:
                wait_time = backoff_factor**attempt
                print(f"   Retrying in {wait_time}s...")
                time.sleep(wait_time)

        except httpx.HTTPError as e:
            last_exception = e
            print(f"❌ HTTP error on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = backoff_factor**attempt
                print(f"   Retrying in {wait_time}s...")
                time.sleep(wait_time)

        except Exception as e:
            last_exception = e
            print(f"❌ Unexpected error on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = backoff_factor**attempt
                print(f"   Retrying in {wait_time}s...")
                time.sleep(wait_time)

    # All retries exhausted
    print(f"💀 All {max_retries} attempts failed. Last error: {last_exception}")
    return None


def generate_action_summary(tool: str, inputs: dict) -> dict:
    """Generate human-readable summary of action"""
    summary = {"action": tool, "description": ""}

    if tool == "send_draft_email" or tool == "send_email_with_attachment":
        summary["description"] = f"Send email to {inputs.get('to', 'unknown')}"
        summary["details"] = {
            "recipient": inputs.get("to"),
            "subject": inputs.get("subject"),
            "body_preview": inputs.get("body", "")[:200] + "...",
        }

    elif tool == "reply_to_email":
        summary["description"] = f"Reply to email"
        summary["details"] = {
            "message_id": inputs.get("message_id"),
            "reply_preview": inputs.get("reply_body", "")[:200] + "...",
        }

    elif tool == "add_text":
        summary["description"] = f"Add text to document"
        summary["details"] = {
            "document_id": inputs.get("document_id"),
            "text_preview": inputs.get("text", "")[:200] + "...",
        }
    elif tool == "edit_doc":
        summary["description"] = f"Edit text in document"
        summary["details"] = {
            "document_id": inputs.get("document_id"),
            "find": (
                inputs.get("old_text", "")[:50] + "..."
                if len(inputs.get("old_text", "")) > 50
                else inputs.get("old_text", "")
            ),
            "replace_with": (
                inputs.get("new_text", "")[:50] + "..."
                if len(inputs.get("new_text", "")) > 50
                else inputs.get("new_text", "")
            ),
        }
    elif tool == "update_doc":
        summary["description"] = f"Update entire document content"
        summary["details"] = {
            "document_id": inputs.get("document_id"),
            "new_content_preview": inputs.get("new_content", "")[:200] + "...",
        }
    else:
        summary["description"] = f"Execute {tool}"
        summary["details"] = inputs

    return summary
