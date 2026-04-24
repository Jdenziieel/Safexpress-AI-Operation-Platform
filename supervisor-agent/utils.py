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
import asyncio
import httpx
from typing import Any, List, Dict, Optional
from langchain_openai import ChatOpenAI
from agent_capabilities_v3 import agent_capabilities
import tiktoken
from config import (
    CLASSIFIER_MODEL,
    LLM_MODEL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    DEFAULT_BACKOFF_FACTOR,
    OPENAI_API_KEY,
    TRANSFORM_MODEL,
    TRANSFORM_MAX_INPUT_TOKENS,
)

# Import LLM error handler for unified error handling
from llm_error_handler import handle_llm_error, LLMServiceException, is_llm_error

# Import logging module
from logging_config import utils_logger as logger


def identify_relevant_agents(user_input: str) -> List[str]:
    """
    Use a cheap/fast LLM call to identify which agents are relevant.
    This is a simple classification task, much cheaper than full planning.
    """
    # Fixed instructions in system message (cacheable across calls)
    system_prompt = """Identify which agents are needed for a user request. Return ONLY a JSON array of agent names.

Available agents:
- gmail_agent: Search emails, read threads, reply, forward, create/send drafts, manage labels, download attachments
- docs_agent: Create/edit/read Google Docs, extract template formats, create from templates
- mapping_agent: Parse CSV/Excel/JSON files, extract dates, smart column mapping, transform data
- sheets_agent: Update sheets by date match, upload mapped data, create new sheets
- calendar_agent: List/create/update/delete calendar events, manage calendars, resolve conflicts
- drive_agent: Upload/download files, create folders, list files/folders, search files

Example: ["gmail_agent", "docs_agent"]"""

    user_prompt = user_input

    classifier_llm = ChatOpenAI(
        model=CLASSIFIER_MODEL, temperature=0, openai_api_key=OPENAI_API_KEY
    )
    
    try:
        # === TOKEN TRACKING: Agent Classification ===
        start_time = time.time()
        response = classifier_llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        duration_ms = (time.time() - start_time) * 1000
        
        # Extract token usage from response
        total_prompt_len = len(system_prompt) + len(user_prompt)
        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        if hasattr(response, 'response_metadata'):
            token_usage = response.response_metadata.get('token_usage', {})
            input_tokens = token_usage.get('prompt_tokens', total_prompt_len // 4)
            output_tokens = token_usage.get('completion_tokens', len(response.content) // 4)
            cached_tokens = token_usage.get('prompt_tokens_details', {}).get('cached_tokens', 0)
        else:
            input_tokens = total_prompt_len // 4
            output_tokens = len(response.content) // 4
        
        # Log the LLM call with token tracking
        logger.llm_call(
            model=CLASSIFIER_MODEL,
            operation="agent_classification",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
            tier="classifier",
            prompt_summary=f"Classifying agents for: {user_input[:50]}...",
            success=True,
            cached_tokens=cached_tokens
        )

        # Parse the agent list
        agent_list = json.loads(response.content.strip())
        return agent_list
    except Exception as e:
        if is_llm_error(e):
            logger.llm_call(
                model=CLASSIFIER_MODEL,
                operation="agent_classification",
                input_tokens=(len(system_prompt) + len(user_prompt)) // 4,
                output_tokens=0,
                duration_ms=(time.time() - start_time) * 1000 if 'start_time' in locals() else 0,
                tier="classifier",
                prompt_summary=f"Classifying agents for: {user_input[:50]}...",
                success=False,
                error=str(e),
            )
            logger.error(f"LLM service error during agent classification: {e}")
            raise LLMServiceException(handle_llm_error(e))
        # For other errors (like JSON parse), log and fall back to all agents
        logger.warning(f"Error in agent classification, using all agents: {e}")
        return list(agent_capabilities.keys())


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
            print(f"Attempt {attempt + 1}/{max_retries} calling {agent_url}")
            print(f" ⏱ Timeout set to: {timeout} seconds")

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
                    print(f"Agent call succeeded on attempt {attempt + 1}")
                    return result
                elif result.get("no_results"):
                    print(f"ℹ Agent returned no results: {result.get('error')}")
                    return result
                else:
                    # Agent returned error but HTTP was successful
                    error_type = result.get("error_type", "")
                    error_detail = result.get("error") or (result.get("result") or {}).get("error") or "Unknown error"
                    print(f"Agent reported error: {error_detail}")

                    _NO_RETRY_TYPES = {"conflict", "validation_error", "not_found", "permission_denied", "read_only"}
                    if error_type in _NO_RETRY_TYPES:
                        print(f"   Non-retryable error type: {error_type}")
                        return result

                    if attempt < max_retries - 1:
                        wait_time = backoff_factor**attempt
                        print(f"   Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    return result  # Return the error result on last attempt

        except httpx.TimeoutException as e:
            last_exception = e
            print(f"⏱ Timeout on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = backoff_factor**attempt
                print(f"   Retrying in {wait_time}s...")
                time.sleep(wait_time)

        except httpx.HTTPStatusError as e:
            last_exception = e
            print(f"HTTP {e.response.status_code} on attempt {attempt + 1}")

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
            print(f"HTTP error on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = backoff_factor**attempt
                print(f"   Retrying in {wait_time}s...")
                time.sleep(wait_time)

        except Exception as e:
            last_exception = e
            print(f"Unexpected error on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = backoff_factor**attempt
                print(f"   Retrying in {wait_time}s...")
                time.sleep(wait_time)

    # All retries exhausted
    print(f"All {max_retries} attempts failed. Last error: {last_exception}")
    return None


async def async_call_agent_with_retry(
    agent_url: str,
    request_payload: dict,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timeout: float = DEFAULT_TIMEOUT,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
) -> Optional[dict]:
    """
    Async version of call_agent_with_retry using httpx.AsyncClient.
    Does not block the event loop during HTTP calls or backoff sleeps.
    """
    last_exception = None

    for attempt in range(max_retries):
        try:
            print(f"Attempt {attempt + 1}/{max_retries} calling {agent_url}")

            timeout_config = httpx.Timeout(
                timeout=timeout, connect=10.0, read=timeout, write=30.0, pool=10.0,
            )

            async with httpx.AsyncClient(timeout=timeout_config) as client:
                response = await client.post(agent_url, json=request_payload)
                response.raise_for_status()
                result = response.json()

                if result.get("success"):
                    print(f"Agent call succeeded on attempt {attempt + 1}")
                    return result
                else:
                    print(f"Agent reported error: {result.get('error')}")
                    if attempt < max_retries - 1:
                        wait_time = backoff_factor ** attempt
                        print(f"   Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    return result

        except httpx.TimeoutException as e:
            last_exception = e
            print(f"⏱ Timeout on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = backoff_factor ** attempt
                await asyncio.sleep(wait_time)

        except httpx.HTTPStatusError as e:
            last_exception = e
            print(f"HTTP {e.response.status_code} on attempt {attempt + 1}")
            if 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                return None
            if attempt < max_retries - 1:
                wait_time = backoff_factor ** attempt
                await asyncio.sleep(wait_time)

        except httpx.HTTPError as e:
            last_exception = e
            print(f"HTTP error on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = backoff_factor ** attempt
                await asyncio.sleep(wait_time)

        except Exception as e:
            last_exception = e
            print(f"Unexpected error on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = backoff_factor ** attempt
                await asyncio.sleep(wait_time)

    print(f"All {max_retries} attempts failed. Last error: {last_exception}")
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


def _strip_transform_fences(s: str) -> str:
    """Strip leading ```lang\\n and trailing ``` from an LLM response.

    Local to this module; same semantics as Sheets-agent's `_strip_md_fences`
    but duplicated to keep the supervisor-agent free of sub-agent imports."""
    stripped = s.strip()
    changed = False
    if stripped.startswith("```"):
        nl = stripped.find("\n")
        if nl != -1:
            stripped = stripped[nl + 1 :]
            changed = True
    if stripped.endswith("```"):
        stripped = stripped[:-3].rstrip()
        changed = True
    return stripped.strip() if changed else s.strip()


_SCALAR_TYPES = (str, int, float, bool, type(None))


def _validate_json_rows(parsed: Any) -> Optional[str]:
    """Return None if `parsed` is a valid 2D list of scalars, else a
    human-readable error describing what's wrong."""
    if not isinstance(parsed, list):
        return f"expected a JSON array, got {type(parsed).__name__}"
    for i, row in enumerate(parsed):
        if not isinstance(row, list):
            return f"row {i} is {type(row).__name__}, expected a JSON array"
        for j, cell in enumerate(row):
            if not isinstance(cell, _SCALAR_TYPES):
                return f"row {i} cell {j} is {type(cell).__name__}, expected a scalar (string/number/bool/null)"
    return None


def _validate_json_table(parsed: Any) -> Optional[str]:
    """Return None if `parsed` is a valid `{"headers":[...], "rows":[[...]]}`
    shape, else a human-readable error describing what's wrong."""
    if not isinstance(parsed, dict):
        return f"expected a JSON object, got {type(parsed).__name__}"
    if "headers" not in parsed or "rows" not in parsed:
        return f"expected keys 'headers' and 'rows', got {list(parsed.keys())}"
    headers = parsed["headers"]
    rows = parsed["rows"]
    if not isinstance(headers, list):
        return f"headers must be an array, got {type(headers).__name__}"
    for i, h in enumerate(headers):
        if not isinstance(h, str):
            return f"headers[{i}] is {type(h).__name__}, expected a string"
    err = _validate_json_rows(rows)
    if err is not None:
        return f"rows: {err}"
    return None


def execute_llm_transform(
    instruction: str,
    content: str,
    trace=None,
    output_format: str = "text",
) -> dict:
    """
    Run an LLM transformation on content (e.g., fix grammar, summarize,
    translate, or produce a structured rows/table payload).

    This is a local call — no HTTP to an external agent.

    Args:
        instruction: What transformation to apply (e.g. "Fix the grammar
            and spelling", or — when output_format is structured — "Extract
            order lines as rows of (date, order_ref, item_code, qty)").
        content: The text content to transform.
        trace: Optional trace object for logging.
        output_format: Output shape contract:
            - "text" (default): return the transformed text verbatim.
              Back-compatible — behavior identical to pre-Commit 2.
            - "json_rows": return a 2D JSON array `[[...], [...]]` with
              scalar cells. Markdown fences are stripped, json.loads runs,
              shape is validated; on failure returns success=False.
              Result is re-serialized to a compact JSON string so the
              orchestrator's Jinja substitution + Sheets-agent's
              `_coerce_rows` both see clean JSON.
            - "json_table": return `{"headers":[...], "rows":[[...]]}`
              with string headers and scalar cells. Same parse/validate/
              re-serialize path as json_rows.

    Returns:
        dict with keys: success, transformed_content, error. When
        output_format is "json_rows" or "json_table", transformed_content
        is a canonical JSON string of the parsed+validated value.
    """
    if not content or not content.strip():
        return {"success": False, "error": "No text content provided to transform", "transformed_content": ""}
    if not instruction or not instruction.strip():
        return {"success": False, "error": "No transformation instruction provided", "transformed_content": ""}

    output_format = (output_format or "text").strip().lower()
    if output_format not in ("text", "json_rows", "json_table"):
        return {
            "success": False,
            "error": f"Unsupported output_format '{output_format}'. Expected one of: text, json_rows, json_table.",
            "transformed_content": "",
        }

    _encoding = tiktoken.get_encoding("cl100k_base")
    estimated_tokens = len(_encoding.encode(content))
    if estimated_tokens > TRANSFORM_MAX_INPUT_TOKENS:
        error_msg = (
            f"Content too large for transform "
            f"(~{estimated_tokens:,} tokens, limit is {TRANSFORM_MAX_INPUT_TOKENS:,}). "
            f"Try a smaller document or a specific section."
        )
        if trace:
            trace.warning(f"llm_transform rejected: {estimated_tokens} tokens exceeds limit")
        return {"success": False, "error": error_msg, "transformed_content": ""}

    if output_format == "text":
        system_prompt = (
            "You are a precise text transformation assistant. "
            "Apply the requested transformation to the provided content. "
            "Return ONLY the transformed text — no explanations, no markdown fences, no preamble."
        )
    elif output_format == "json_rows":
        system_prompt = (
            "You are a precise text-to-structured-data transformation assistant. "
            "Apply the requested transformation and return ONLY a JSON array of arrays "
            "(a 2D list of rows). Each inner array is one row; cells must be strings, "
            "numbers, booleans, or null — no nested objects. "
            "Return ONLY the JSON value — no explanations, no markdown fences, no preamble. "
            "Example: [[\"Nov 05\",\"VRM001\",\"A1\"],[\"Nov 05\",\"VRM002\",\"B2\"]]"
        )
    else:  # json_table
        system_prompt = (
            "You are a precise text-to-structured-data transformation assistant. "
            "Apply the requested transformation and return ONLY a JSON object of shape "
            "{\"headers\": [\"col1\", ...], \"rows\": [[cell1, cell2, ...], ...]}. "
            "Headers must be strings; row cells must be strings, numbers, booleans, or "
            "null — no nested objects. Each row should have the same number of cells as "
            "headers (pad with null if a value is unknown). "
            "Return ONLY the JSON value — no explanations, no markdown fences, no preamble. "
            "Example: {\"headers\":[\"Date\",\"Ref\",\"Code\"],\"rows\":[[\"Nov 05\",\"VRM001\",\"A1\"]]}"
        )
    user_prompt = f"Instruction: {instruction}\n\nContent to transform:\n{content}"

    llm = ChatOpenAI(
        model=TRANSFORM_MODEL,
        temperature=0.1,
        openai_api_key=OPENAI_API_KEY,
    )

    try:
        start_time = time.time()
        response = llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        duration_ms = (time.time() - start_time) * 1000

        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        if hasattr(response, "response_metadata"):
            token_usage = response.response_metadata.get("token_usage", {})
            input_tokens = token_usage.get("prompt_tokens", 0)
            output_tokens = token_usage.get("completion_tokens", 0)
            cached_tokens = token_usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)

        logger.llm_call(
            model=TRANSFORM_MODEL,
            operation="transform_text",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
            tier="orchestrator",
            prompt_summary=f"Transform: {instruction[:50]}...",
            success=True,
            cached_tokens=cached_tokens,
        )

        transformed = response.content.strip()

        if output_format in ("json_rows", "json_table"):
            cleaned = _strip_transform_fences(transformed)
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError as e:
                err = (
                    f"LLM output for output_format='{output_format}' was not valid JSON: {e}. "
                    f"Sample: {cleaned[:200]!r}"
                )
                if trace:
                    trace.warning(err)
                return {"success": False, "error": err, "transformed_content": ""}
            validator = _validate_json_rows if output_format == "json_rows" else _validate_json_table
            shape_err = validator(parsed)
            if shape_err is not None:
                err = (
                    f"LLM output for output_format='{output_format}' had invalid shape: {shape_err}. "
                    f"Sample: {cleaned[:200]!r}"
                )
                if trace:
                    trace.warning(err)
                return {"success": False, "error": err, "transformed_content": ""}
            transformed = json.dumps(parsed, ensure_ascii=False)

        if trace:
            trace.step(
                "llm_transform",
                f"Transformed {len(content)} chars -> {len(transformed)} chars "
                f"(output_format={output_format})",
            )

        return {
            "success": True,
            "transformed_content": transformed,
        }

    except Exception as e:
        if is_llm_error(e):
            logger.llm_call(
                model=TRANSFORM_MODEL,
                operation="transform_text",
                input_tokens=(len(system_prompt) + len(user_prompt)) // 4,
                output_tokens=0,
                duration_ms=(time.time() - start_time) * 1000 if "start_time" in locals() else 0,
                tier="orchestrator",
                prompt_summary=f"Transform: {instruction[:50]}...",
                success=False,
                error=str(e),
            )
            raise LLMServiceException(handle_llm_error(e))
        logger.error(f"LLM transform failed: {e}")
        return {
            "success": False,
            "error": f"Transform failed: {str(e)}",
            "transformed_content": "",
        }
