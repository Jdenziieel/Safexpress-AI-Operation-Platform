"""
Tool-Level Filtering for Token Optimization

This module provides functions to filter tools within agents based on user intent,
reducing token consumption by ~60-80% compared to sending all tools.

STRATEGY: Two-Level Filtering
Level 1: Agent filtering (existing) - identify_relevant_agents()
Level 2: Tool filtering (NEW) - identify_relevant_tools()
"""

from typing import List, Dict, Set, Optional
import json
from langchain_openai import ChatOpenAI
from config import CLASSIFIER_MODEL, OPENAI_API_KEY

# Import LLM error handler for unified error handling
from llm_error_handler import handle_llm_error, LLMServiceException, is_llm_error


# =============================================================================
# TOOL CATEGORIES - Group tools by common intents/operations
# =============================================================================

TOOL_CATEGORIES = {
    "gmail_agent": {
        # Read operations
        "read": ["search_emails", "get_thread_conversation"],
        # Write operations  
        "draft": ["create_draft_email", "send_draft_email", "search_drafts"],
        "send": ["send_email_with_attachment", "reply_to_email", "forward_email"],
        # Management
        "attachment": ["download_attachment", "send_email_with_attachment"],
    },
    "docs_agent": {
        "read": ["read_doc", "list_my_docs"],
        "create": ["create_doc", "add_text", "create_from_my_template", "create_from_existing_data_and_template"],
        "template": ["extract_template_format", "create_from_my_template", "list_my_docs", "create_from_existing_data_and_template"],
    },
    "calendar_agent": {
        "read": ["list_events", "list_calendars", "get_event"],
        "create": ["create_event", "quick_add_event"],
        "modify": ["update_event", "delete_event"],
        "conflict": ["check_conflicts", "resolve_conflict"],
    },
    "drive_agent": {
        "read": ["list_files", "list_folders", "search_files", "get_folder_info"],
        "write": ["upload_file", "create_folder"],
    },
    "sheets_agent": {
        "read": [],
        "write": ["update_sheet_by_date", "upload_mapped_data", "create_sheet"],
    },
    "mapping_agent": {
        "parse": ["parse_file", "extract_dates_from_csv"],
        "map": ["smart_column_mapping", "generate_column_mapping_with_data"],
        "transform": ["transform_with_mapping"],
    },
}


# =============================================================================
# INTENT-TO-TOOL MAPPING - Maps user intent keywords to tool categories
# =============================================================================

INTENT_KEYWORDS = {
    # Gmail intents - more granular matching
    "search": {"agents": ["gmail_agent", "drive_agent"], "categories": ["read"]},
    "find": {"agents": ["gmail_agent", "drive_agent"], "categories": ["read"]},
    "look for": {"agents": ["gmail_agent", "drive_agent"], "categories": ["read"]},
    "read": {"agents": ["gmail_agent", "docs_agent"], "categories": ["read"]},
    "get": {"agents": ["gmail_agent", "calendar_agent"], "categories": ["read"]},
    "draft": {"agents": ["gmail_agent"], "categories": ["draft"]},
    "compose": {"agents": ["gmail_agent"], "categories": ["draft"]},
    "write": {"agents": ["gmail_agent", "docs_agent"], "categories": ["draft", "create"]},
    "send": {"agents": ["gmail_agent"], "categories": ["draft", "send"]},
    "reply": {"agents": ["gmail_agent"], "categories": ["read", "send"]},
    "forward": {"agents": ["gmail_agent"], "categories": ["read", "send"]},
    "attachment": {"agents": ["gmail_agent"], "categories": ["read", "attachment"]},
    "download": {"agents": ["gmail_agent", "drive_agent"], "categories": ["read", "attachment"]},
    
    # Docs intents
    "create": {"agents": ["docs_agent", "drive_agent", "sheets_agent", "calendar_agent"], "categories": ["create", "write"]},
    "document": {"agents": ["docs_agent"], "categories": ["read", "create"]},
    "doc": {"agents": ["docs_agent"], "categories": ["read", "create"]},
    "template": {"agents": ["docs_agent"], "categories": ["template"]},
    "mom": {"agents": ["docs_agent"], "categories": ["template"]},
    "minutes": {"agents": ["docs_agent"], "categories": ["template"]},
    
    # Calendar intents
    "schedule": {"agents": ["calendar_agent"], "categories": ["create"]},
    "meeting": {"agents": ["calendar_agent"], "categories": ["read", "create"]},
    "event": {"agents": ["calendar_agent"], "categories": ["read", "create", "modify"]},
    "calendar": {"agents": ["calendar_agent"], "categories": ["read"]},
    "appointment": {"agents": ["calendar_agent"], "categories": ["create"]},
    "reschedule": {"agents": ["calendar_agent"], "categories": ["modify"]},
    "cancel": {"agents": ["calendar_agent"], "categories": ["modify"]},
    "delete": {"agents": ["calendar_agent"], "categories": ["modify"]},
    "conflict": {"agents": ["calendar_agent"], "categories": ["conflict"]},
    
    # Drive intents
    "upload": {"agents": ["drive_agent"], "categories": ["write"]},
    "folder": {"agents": ["drive_agent"], "categories": ["read", "write"]},
    "file": {"agents": ["drive_agent"], "categories": ["read"]},
    "drive": {"agents": ["drive_agent"], "categories": ["read", "write"]},
    "list": {"agents": ["drive_agent", "calendar_agent", "docs_agent"], "categories": ["read"]},
    
    # Sheets intents
    "sheet": {"agents": ["sheets_agent"], "categories": ["read", "write"]},
    "spreadsheet": {"agents": ["sheets_agent"], "categories": ["read", "write"]},
    "update sheet": {"agents": ["sheets_agent"], "categories": ["write"]},
    
    # Mapping intents
    "map": {"agents": ["mapping_agent"], "categories": ["map"]},
    "csv": {"agents": ["mapping_agent"], "categories": ["parse"]},
    "excel": {"agents": ["mapping_agent"], "categories": ["parse"]},
    "transform": {"agents": ["mapping_agent"], "categories": ["transform"]},
    "parse": {"agents": ["mapping_agent"], "categories": ["parse"]},
    "column": {"agents": ["mapping_agent"], "categories": ["map"]},
}


def identify_relevant_tools_fast(user_input: str, agents: List[str]) -> Dict[str, List[str]]:
    """
    FAST/CHEAP: Use keyword matching to identify relevant tools.
    No LLM call - instant, zero tokens.
    
    Args:
        user_input: User's request
        agents: List of relevant agents (from identify_relevant_agents)
    
    Returns:
        Dict mapping agent -> list of relevant tool names
    """
    user_lower = user_input.lower()
    relevant_tools = {}
    
    for agent in agents:
        if agent not in TOOL_CATEGORIES:
            continue
        
        # Collect categories that match user intent
        matched_categories = set()
        
        for intent, mapping in INTENT_KEYWORDS.items():
            if intent in user_lower and agent in mapping["agents"]:
                matched_categories.update(mapping["categories"])
        
        # Get tools from matched categories
        tools = set()
        agent_categories = TOOL_CATEGORIES[agent]
        
        for category in matched_categories:
            if category in agent_categories:
                tools.update(agent_categories[category])
        
        # If no specific tools matched, include all tools for this agent
        # (fallback to full agent capabilities)
        if tools:
            relevant_tools[agent] = list(tools)
        else:
            # Fall back to all tools for this agent
            from agent_capabilities_v2 import agent_capabilities
            relevant_tools[agent] = list(agent_capabilities[agent]["tools"].keys())
    
    return relevant_tools


def identify_relevant_tools_llm(user_input: str, agents: List[str]) -> Dict[str, List[str]]:
    """
    LLM-BASED: More accurate tool identification using cheap classifier.
    Uses ~200 tokens (very cheap with gpt-3.5-turbo).
    
    Args:
        user_input: User's request
        agents: List of relevant agents
    
    Returns:
        Dict mapping agent -> list of relevant tool names
    """
    from agent_capabilities_v2 import agent_capabilities
    
    # Build compact tool list (just names + one-line descriptions)
    compact_tools = {}
    for agent in agents:
        if agent in agent_capabilities:
            compact_tools[agent] = {
                tool_name: tool_data["description"][:80]  # Truncate descriptions
                for tool_name, tool_data in agent_capabilities[agent]["tools"].items()
            }
    
    prompt = f"""Given this user request, identify the MINIMUM tools needed.

User: {user_input}

Available tools (agent -> tool: description):
{json.dumps(compact_tools, indent=2)}

Return ONLY a JSON object mapping agent names to arrays of tool names needed.
Example: {{"gmail_agent": ["search_emails", "forward_email"]}}

Include ONLY tools that will actually be used. Less is better."""

    classifier_llm = ChatOpenAI(
        model=CLASSIFIER_MODEL, 
        temperature=0, 
        openai_api_key=OPENAI_API_KEY
    )
    
    try:
        response = classifier_llm.invoke([{"role": "user", "content": prompt}])
        
        try:
            return json.loads(response.content.strip())
        except json.JSONDecodeError:
            # Fallback: return all tools for the agents
            return {
                agent: list(agent_capabilities[agent]["tools"].keys())
                for agent in agents
                if agent in agent_capabilities
            }
    except Exception as e:
        # Check if this is an LLM service error (rate limit, quota, etc.)
        if is_llm_error(e):
            raise LLMServiceException(handle_llm_error(e))
        # For other errors, fall back to all tools for the agents
        return {
            agent: list(agent_capabilities[agent]["tools"].keys())
            for agent in agents
            if agent in agent_capabilities
        }


def get_filtered_capabilities_v2(
    agents: List[str], 
    tool_filter: Optional[Dict[str, List[str]]] = None
) -> Dict:
    """
    Get capabilities filtered by both agent AND tools.
    
    Args:
        agents: List of agent names to include
        tool_filter: Optional dict of agent -> list of tool names to include
                    If None, includes all tools for the agents
    
    Returns:
        Filtered capabilities dict with only specified agents/tools
    """
    from agent_capabilities_v2 import agent_capabilities
    
    filtered = {}
    
    for agent in agents:
        if agent not in agent_capabilities:
            continue
        
        agent_data = agent_capabilities[agent].copy()
        
        # If we have a tool filter for this agent, apply it
        if tool_filter and agent in tool_filter:
            tools_to_include = set(tool_filter[agent])
            agent_data["tools"] = {
                tool_name: tool_data
                for tool_name, tool_data in agent_data["tools"].items()
                if tool_name in tools_to_include
            }
        
        filtered[agent] = agent_data
    
    return filtered


def get_compact_capabilities(
    agents: List[str],
    tool_filter: Optional[Dict[str, List[str]]] = None,
    include_returns: bool = True,
    include_can_be_derived: bool = False
) -> Dict:
    """
    Get COMPACT capabilities - removes verbose metadata to save tokens.
    
    Removes:
    - Detailed return field descriptions (keeps just field names)
    - can_be_derived_from metadata
    - usage_patterns, template_workflow, important_notes
    
    Args:
        agents: List of agent names
        tool_filter: Optional tool filter
        include_returns: If True, includes simplified returns. If False, omits entirely.
        include_can_be_derived: If True, keeps can_be_derived_from metadata
    
    Returns:
        Compact capabilities dict
    """
    from agent_capabilities_v2 import agent_capabilities
    
    compact = {}
    
    for agent in agents:
        if agent not in agent_capabilities:
            continue
        
        agent_data = agent_capabilities[agent]
        
        compact[agent] = {
            "description": agent_data["description"],
            "tools": {}
        }
        
        # Get tools (filtered if specified)
        tools_to_include = (
            set(tool_filter[agent]) if tool_filter and agent in tool_filter
            else set(agent_data["tools"].keys())
        )
        
        for tool_name, tool_data in agent_data["tools"].items():
            if tool_name not in tools_to_include:
                continue
            
            compact_tool = {
                "description": tool_data["description"],
                "args": tool_data["args"],
            }
            
            # Simplified returns: just field names
            if include_returns and "returns" in tool_data:
                # Keep only top-level return fields (not nested like emails[].field)
                returns = tool_data["returns"]
                compact_tool["returns"] = [
                    key for key in returns.keys()
                    if "[" not in key  # Skip array notation fields
                ]
            
            if include_can_be_derived and "can_be_derived_from" in tool_data:
                compact_tool["can_be_derived_from"] = tool_data["can_be_derived_from"]
            
            compact[agent]["tools"][tool_name] = compact_tool
    
    return compact


# =============================================================================
# MAIN OPTIMIZATION FUNCTION - Use this in supervisor_node
# =============================================================================

def get_optimized_capabilities(
    user_input: str,
    use_llm_filter: bool = False,
    compact_mode: bool = True
) -> tuple[Dict, Dict[str, List[str]]]:
    """
    Main entry point for optimized capability filtering.
    
    Strategy:
    1. Identify relevant agents (existing cheap LLM call)
    2. Identify relevant tools within those agents (keyword or cheap LLM)
    3. Return compact capabilities
    
    Args:
        user_input: User's request
        use_llm_filter: If True, use LLM for tool filtering (more accurate, ~200 tokens)
                       If False, use keyword matching (instant, 0 tokens)
        compact_mode: If True, return compact capabilities (less verbose)
    
    Returns:
        Tuple of (capabilities_dict, tool_filter_dict)
    """
    from utils import identify_relevant_agents
    
    # Step 1: Agent filtering (existing)
    agents = identify_relevant_agents(user_input)
    
    # Step 2: Tool filtering (new)
    if use_llm_filter:
        tool_filter = identify_relevant_tools_llm(user_input, agents)
    else:
        tool_filter = identify_relevant_tools_fast(user_input, agents)
    
    # Step 3: Get capabilities
    if compact_mode:
        capabilities = get_compact_capabilities(agents, tool_filter)
    else:
        capabilities = get_filtered_capabilities_v2(agents, tool_filter)
    
    return capabilities, tool_filter


# =============================================================================
# TESTING / METRICS
# =============================================================================

def measure_token_savings(user_input: str):
    """Measure token savings from filtering."""
    from agent_capabilities_v2 import agent_capabilities
    from utils import identify_relevant_agents, get_filtered_capabilities
    
    # Baseline: All capabilities
    full_json = json.dumps(agent_capabilities, indent=2)
    full_tokens = len(full_json) // 4
    
    # Level 1: Agent filtering only (current)
    agents = identify_relevant_agents(user_input)
    agent_filtered = get_filtered_capabilities(agents)
    agent_tokens = len(json.dumps(agent_filtered, indent=2)) // 4
    
    # Level 2: Agent + Tool filtering (new - fast)
    tool_filter = identify_relevant_tools_fast(user_input, agents)
    tool_filtered = get_filtered_capabilities_v2(agents, tool_filter)
    tool_tokens = len(json.dumps(tool_filtered, indent=2)) // 4
    
    # Level 3: Compact mode
    compact = get_compact_capabilities(agents, tool_filter)
    compact_tokens = len(json.dumps(compact, indent=2)) // 4
    
    return {
        "user_input": user_input,
        "relevant_agents": agents,
        "relevant_tools": tool_filter,
        "token_comparison": {
            "full": full_tokens,
            "agent_filtered": agent_tokens,
            "tool_filtered": tool_tokens,
            "compact": compact_tokens,
        },
        "savings": {
            "agent_only": f"{(1 - agent_tokens/full_tokens)*100:.0f}%",
            "agent_tool": f"{(1 - tool_tokens/full_tokens)*100:.0f}%",
            "compact": f"{(1 - compact_tokens/full_tokens)*100:.0f}%",
        }
    }


if __name__ == "__main__":
    # Test with sample inputs
    test_inputs = [
        "search for emails from john about the meeting",
        "forward the latest email to sarah@example.com",
        "create a draft email to mike about the project",
        "schedule a meeting for tomorrow at 2pm",
        "create a document from my MOM template",
        "upload the report to Google Drive",
    ]
    
    print("=" * 70)
    print("TOKEN OPTIMIZATION ANALYSIS")
    print("=" * 70)
    
    for input_text in test_inputs:
        result = measure_token_savings(input_text)
        print(f"\n📝 Input: {input_text}")
        print(f"   Agents: {result['relevant_agents']}")
        print(f"   Tools: {result['relevant_tools']}")
        print(f"   Tokens: full={result['token_comparison']['full']}, "
              f"agent={result['token_comparison']['agent_filtered']}, "
              f"tool={result['token_comparison']['tool_filtered']}, "
              f"compact={result['token_comparison']['compact']}")
        print(f"   Savings: {result['savings']['compact']} (compact mode)")
