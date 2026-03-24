"""
Tool-Level Filtering for Token Optimization

Merged agent+tool identification in ONE cheap LLM call.
Returns Dict[str, List[str]] mapping agent names to relevant tool names.
"""

from typing import List, Dict, Optional
import json
import time
from langchain_openai import ChatOpenAI
from config import CLASSIFIER_MODEL, OPENAI_API_KEY

# Import LLM error handler for unified error handling
from llm_error_handler import handle_llm_error, LLMServiceException, is_llm_error

# Import logging module
from logging_config import utils_logger as logger


_cached_system_prompt: Optional[str] = None

def _get_tool_filter_system_prompt() -> str:
    """Build and cache the system prompt once — agent capabilities are static
    within a deployment, so the system prompt is identical across calls."""
    global _cached_system_prompt
    if _cached_system_prompt is not None:
        return _cached_system_prompt

    from agent_capabilities_v3 import agent_capabilities
    compact_tools = {
        agent: {
            tool_name: tool_data["description"][:80]
            for tool_name, tool_data in agent_data["tools"].items()
        }
        for agent, agent_data in agent_capabilities.items()
    }

    _cached_system_prompt = f"""Identify which agents and tools are needed for a user request.

Available tools by agent:
{json.dumps(compact_tools, indent=2)}

Return ONLY a JSON object mapping agent names to arrays of tool names.
Include ONLY the agents and tools that will actually be used. Less is better.
Example: {{"gmail_agent": ["search_emails", "reply_to_email"], "calendar_agent": ["create_event"]}}"""

    return _cached_system_prompt


def identify_agents_and_tools(user_input: str) -> Dict[str, List[str]]:
    """
    Single cheap LLM call to identify both relevant agents AND their tools.
    Replaces the two-step flow (identify_relevant_agents → identify_relevant_tools_fast).

    Args:
        user_input: User's request

    Returns:
        Dict mapping agent name -> list of tool names needed
    """
    from agent_capabilities_v3 import agent_capabilities

    system_prompt = _get_tool_filter_system_prompt()
    user_prompt = user_input

    classifier_llm = ChatOpenAI(
        model=CLASSIFIER_MODEL, temperature=0, openai_api_key=OPENAI_API_KEY
    )

    try:
        start_time = time.time()
        response = classifier_llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        duration_ms = (time.time() - start_time) * 1000

        # Extract token usage
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

        logger.llm_call(
            model=CLASSIFIER_MODEL,
            operation="agent_tool_classification",
            input_tokens=input_tokens,
            cached_tokens=cached_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
            tier="classifier",
            prompt_summary=f"Classifying agents+tools for: {user_input[:50]}...",
            success=True
        )

        result = json.loads(response.content.strip())

        # Validate: only keep agents/tools that actually exist
        validated = {}
        for agent, tools in result.items():
            if agent in agent_capabilities:
                valid_tools = [t for t in tools if t in agent_capabilities[agent]["tools"]]
                if valid_tools:
                    validated[agent] = valid_tools
        return validated

    except Exception as e:
        if is_llm_error(e):
            logger.error(f"LLM service error during agent+tool classification: {e}")
            raise LLMServiceException(handle_llm_error(e))
        # Fallback: return all agents with all tools
        logger.warning(f"Error in agent+tool classification, using all: {e}")
        return {
            agent: list(agent_data["tools"].keys())
            for agent, agent_data in agent_capabilities.items()
        }


def get_filtered_capabilities_v2(
    tool_filter: Dict[str, List[str]]
) -> Dict:
    """
    Get capabilities filtered by agent AND tools.

    Args:
        tool_filter: Dict of agent -> list of tool names to include

    Returns:
        Filtered capabilities dict
    """
    from agent_capabilities_v3 import agent_capabilities

    filtered = {}
    for agent, tool_names in tool_filter.items():
        if agent not in agent_capabilities:
            continue

        agent_data = agent_capabilities[agent].copy()
        tools_to_include = set(tool_names)
        agent_data["tools"] = {
            tool_name: tool_data
            for tool_name, tool_data in agent_data["tools"].items()
            if tool_name in tools_to_include
        }

        # Preserve non-tool top-level keys (template_with_data_workflow, etc.)
        filtered[agent] = agent_data

    return filtered


def get_optimized_capabilities(
    user_input: str,
    **kwargs,
) -> tuple[Dict, Dict[str, List[str]]]:
    """
    Main entry point for optimized capability filtering.

    Single LLM call identifies agents + tools, then filters capabilities.
    Extra kwargs are accepted for backward compatibility but ignored.

    Returns:
        Tuple of (capabilities_dict, tool_filter_dict)
    """
    # One LLM call for both agent and tool identification
    tool_filter = identify_agents_and_tools(user_input)

    # Filter capabilities using the result
    capabilities = get_filtered_capabilities_v2(tool_filter)

    return capabilities, tool_filter
