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

RULES:
- For ANY email sending (not forwarding/replying): ALWAYS include "create_draft_email" AND "send_draft_email". Only include "send_email_with_attachment" when user explicitly mentions attaching a LOCAL FILE.
- Return ONLY a JSON object mapping agent names to arrays of tool names.
- Include ONLY the agents and tools that will actually be used. Less is better.

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

        # Post-processing: keyword safety net — if the user mentions
        # email/cc/bcc keywords but the classifier missed gmail_agent,
        # inject the draft workflow tools so the plan can include emailing.
        _EMAIL_KEYWORDS = {"email", "cc", "bcc", "send an email", "mail", "send email"}
        input_lower = user_input.lower()
        if "gmail_agent" not in validated and any(kw in input_lower for kw in _EMAIL_KEYWORDS):
            validated["gmail_agent"] = ["create_draft_email", "send_draft_email"]

        # Enforce draft workflow: if gmail_agent is present with any
        # sending tool, ensure create_draft_email + send_draft_email exist.
        _EMAIL_SEND_TOOLS = {"send_email_with_attachment", "send_email", "create_draft_email", "send_draft_email"}
        _DRAFT_PAIR = ["create_draft_email", "send_draft_email"]
        if "gmail_agent" in validated:
            gmail_tools = validated["gmail_agent"]
            if any(t in _EMAIL_SEND_TOOLS for t in gmail_tools):
                gmail_caps = agent_capabilities.get("gmail_agent", {}).get("tools", {})
                for dt in _DRAFT_PAIR:
                    if dt not in gmail_tools and dt in gmail_caps:
                        gmail_tools.append(dt)

            # send_draft_email needs a draft_id which typically comes from
            # search_drafts.  Include it so the supervisor can plan a
            # search-first step when the user refers to a draft by name.
            if "send_draft_email" in gmail_tools and "search_drafts" not in gmail_tools:
                all_gmail = agent_capabilities.get("gmail_agent", {}).get("tools", {})
                if "search_drafts" in all_gmail:
                    gmail_tools.append("search_drafts")

        # Docs agent safety net: whenever docs_agent is included, ensure
        # list_my_docs is present so the supervisor can resolve document
        # names to IDs (required by Rule 9 in the planning prompt).
        # Also ensure edit/update tools are present when the request implies
        # modifying document content.
        if "docs_agent" in validated:
            docs_tools = validated["docs_agent"]
            docs_caps = agent_capabilities.get("docs_agent", {}).get("tools", {})
            if "list_my_docs" not in docs_tools and "list_my_docs" in docs_caps:
                docs_tools.append("list_my_docs")
            _DOC_EDIT_KEYWORDS = {"fix", "grammar", "edit", "rewrite", "update", "replace", "change", "modify", "correct", "summarize", "translate"}
            if any(kw in input_lower for kw in _DOC_EDIT_KEYWORDS):
                for t in ["read_doc", "edit_doc", "update_doc"]:
                    if t not in docs_tools and t in docs_caps:
                        docs_tools.append(t)
            # Block C extension (Phase 1): when create_doc is classified AND
            # the request carries the content inline (e.g. "with content",
            # "that says"), offer create_doc_with_content as an alternative
            # so the planner can do it in one step instead of the two-step
            # create_doc + add_text_to_doc chain. create_doc stays in the
            # filter so the planner can still pick the simpler tool when
            # the content is added later.
            _CONTENT_PHRASE_KEYWORDS = (
                "with content", "with text", "with the following",
                "containing", " that says ", " saying ", " with body ",
            )
            if "create_doc" in docs_tools and any(kw in input_lower for kw in _CONTENT_PHRASE_KEYWORDS):
                if "create_doc_with_content" not in docs_tools and "create_doc_with_content" in docs_caps:
                    docs_tools.append("create_doc_with_content")

        # Calendar agent safety net: whenever a calendar event mutation tool
        # is selected, also include list_events as a fallback lookup path.
        # update_event / delete_event / confirm_delete_event accept event_name
        # for internal auto-lookup, but that only works when the user refers
        # to the event by its exact title. When the reference is by date/time,
        # attendees, or other attributes, the planner needs list_events to
        # resolve the event_id before the mutation.
        _CALENDAR_EVENT_MUTATION_TOOLS = {
            "update_event", "delete_event", "confirm_delete_event",
        }
        if "calendar_agent" in validated:
            cal_tools = validated["calendar_agent"]
            cal_caps = agent_capabilities.get("calendar_agent", {}).get("tools", {})
            if any(t in _CALENDAR_EVENT_MUTATION_TOOLS for t in cal_tools):
                if "list_events" not in cal_tools and "list_events" in cal_caps:
                    cal_tools.append("list_events")

        # Block I (Phase 1): "move the file" keyword safety net.
        # Gated on drive_agent already present so we never fire on
        # "move the meeting" (calendar) or "move on to the next topic"
        # (chat). Placed BEFORE Block E so the subsequent search_files
        # pairing picks up the freshly-injected move_file automatically.
        # Narrow phrasings only; bare " move " requires an additional
        # context token (" into ", " to folder ", " to the ") to fire.
        _MOVE_PHRASES_STRICT = (
            "move the file", "move file ", "move it to ", "move them to ",
            "move the doc", "move the document", "move the sheet",
        )
        _MOVE_LOOSE_CONTEXT = (" into ", " to folder ", " to the ")
        mentions_move = any(p in input_lower for p in _MOVE_PHRASES_STRICT) or (
            " move " in input_lower and any(ctx in input_lower for ctx in _MOVE_LOOSE_CONTEXT)
        )
        if mentions_move and "drive_agent" in validated:
            drive_tools = validated["drive_agent"]
            drive_caps = agent_capabilities.get("drive_agent", {}).get("tools", {})
            if "move_file" not in drive_tools and "move_file" in drive_caps:
                drive_tools.append("move_file")

        # Block E (Phase 1 extended): drive_agent.rename_file and
        # drive_agent.move_file accept file_id only (no name-based auto-
        # lookup). Same story for the Phase-4-registered sheet tools
        # (read_sheet, update_sheet, append_rows, etc. — all take
        # sheet_id) and drive_agent.read_file_content (takes file_id
        # when no drive_path is given). Whenever any of these is in the
        # filter, ensure drive_agent.search_files is available so Rule 9
        # in the planner can resolve a name to an ID.
        # Phase 5 URL-parsing helpers make the lookup unnecessary when
        # the user pastes a URL; this block covers the no-URL case.
        _DRIVE_FILE_ID_MUTATIONS = {"rename_file", "move_file"}
        _SHEET_ID_CONSUMERS = {
            "read_sheet", "update_sheet", "append_rows",
            "get_sheet_metadata", "clear_sheet", "get_sheet_headers",
            "upload_mapped_data", "update_by_date_match",
        }
        sheets_tools_now = validated.get("sheets_agent", [])
        drive_tools_now = validated.get("drive_agent", [])
        needs_search_files = (
            any(t in _DRIVE_FILE_ID_MUTATIONS for t in drive_tools_now)
            or any(t in _SHEET_ID_CONSUMERS for t in sheets_tools_now)
            or ("read_file_content" in drive_tools_now)
        )
        if needs_search_files:
            drive_caps = agent_capabilities.get("drive_agent", {}).get("tools", {})
            if "drive_agent" not in validated:
                validated["drive_agent"] = []
            drive_tools = validated["drive_agent"]
            if "search_files" not in drive_tools and "search_files" in drive_caps:
                drive_tools.append("search_files")

        # Block H (Phase 1): sheets/spreadsheet keyword safety net.
        # Injects sheets_agent.create_sheet when the classifier missed
        # it. Placed BEFORE Block F so Block F can see create_sheet and
        # pair it with get_folder_info when the user mentions a folder.
        # Keyword set is deliberately narrow — bare " sheet " excluded
        # to avoid false positives on "cheat sheet", "datasheet",
        # "rate sheet". Composes with Block G (delivery orders), which
        # already injects its own sheets tools downstream.
        _SHEETS_KEYWORDS = (
            "google sheet", "google spreadsheet", "spreadsheet",
            " sheet titled ", " sheet named ", " sheet called ",
            "create a sheet", "new sheet",
            " tabs ", " tab named ", " tab called ",
        )
        if "sheets_agent" not in validated and any(kw in input_lower for kw in _SHEETS_KEYWORDS):
            sheets_caps = agent_capabilities.get("sheets_agent", {}).get("tools", {})
            if "create_sheet" in sheets_caps:
                validated["sheets_agent"] = ["create_sheet"]

        # "Put X in folder Y" safety net: when the user asks to create a
        # sheet or doc AND references a folder, the planner needs a way to
        # resolve the folder name to a folder_id. Without this, Tier 1 may
        # emit folder_id: {"query": "Y"} or the planner may hallucinate a
        # Jinja template that doesn't exist. We always include
        # drive_agent.get_folder_info (STRICT lookup, fails on missing folders
        # — by design, to avoid silently creating typo folders). If the user
        # explicitly asks to create the folder, we also include create_folder.
        _FOLDER_PLACEMENT_KEYWORDS = (
            " in folder ", " inside folder ", " into folder ", " to folder ",
            " in the folder ", " into the folder ", " inside the folder ",
            " in my folder ", " under folder ", " to the folder ",
        )
        _EXPLICIT_FOLDER_CREATE = (
            "create a folder", "create folder", "make a folder",
            "make a new folder", "new folder named", "new folder called",
            "make folder",
        )
        # Patterns like "create a <Name> folder", "make a Q1 budget folder",
        # "create new Finance folder" — the noun "folder" is preceded by a
        # folder-name token rather than the literal word "a folder". A
        # narrow regex keeps this off chatter like "create a file in folder".
        # Allows up to 3 intervening name tokens so "create a 2026 Q1 budget
        # folder" still registers as an explicit creation request.
        import re as _re
        _EXPLICIT_FOLDER_CREATE_PATTERNS = [
            _re.compile(r"\b(?:create|make)\s+(?:a|an|new|another)\s+(?:\S+\s+){0,3}folder\b"),
            _re.compile(r"\b(?:create|make)\s+new\s+folder\b"),
        ]
        _FILE_CREATION_TOOLS_IN_FOLDER = {
            ("sheets_agent", "create_sheet"),
            ("docs_agent", "create_doc"),
            ("docs_agent", "create_doc_with_content"),
            ("drive_agent", "upload_file"),
        }
        mentions_folder_placement = any(
            kw in input_lower for kw in _FOLDER_PLACEMENT_KEYWORDS
        ) or " folder " in input_lower or " folder." in input_lower or input_lower.endswith(" folder")
        asks_explicit_folder_create = any(
            kw in input_lower for kw in _EXPLICIT_FOLDER_CREATE
        ) or any(p.search(input_lower) for p in _EXPLICIT_FOLDER_CREATE_PATTERNS)
        has_file_creation_in_folder = any(
            tool in validated.get(agent_name, [])
            for agent_name, tool in _FILE_CREATION_TOOLS_IN_FOLDER
        )
        # Block F diagnostic trace (Phase 1 investigation): log the three
        # gating flags whenever any of them is truthy, so we can diagnose
        # future regressions where the block should have fired but did
        # not (see CM/Run-this-end-to-end-test-in-one-go.log turn 2/3).
        # Keeps noise down by staying silent when the request has no
        # folder-related keywords and no file-creation tool at all.
        if has_file_creation_in_folder or mentions_folder_placement or asks_explicit_folder_create:
            logger.info(
                f"[BlockF] has_file_creation_in_folder={has_file_creation_in_folder} "
                f"mentions_folder_placement={mentions_folder_placement} "
                f"asks_explicit_folder_create={asks_explicit_folder_create} "
                f"input_lower_sample={input_lower[:120]!r}"
            )
        if has_file_creation_in_folder and (mentions_folder_placement or asks_explicit_folder_create):
            drive_caps = agent_capabilities.get("drive_agent", {}).get("tools", {})
            if "drive_agent" not in validated:
                validated["drive_agent"] = []
            drive_tools = validated["drive_agent"]
            # Strict lookup so the planner can resolve "Finance" → folder_id
            # and fail loudly if it doesn't exist (user never asked to create).
            if "get_folder_info" not in drive_tools and "get_folder_info" in drive_caps:
                drive_tools.append("get_folder_info")
            # Only offer create_folder when the user explicitly asked for it.
            if asks_explicit_folder_create:
                if "create_folder" not in drive_tools and "create_folder" in drive_caps:
                    drive_tools.append("create_folder")

        # Delivery order workflow: ensure all three agents and their
        # specialised tools are present when the request involves
        # delivery/purchase orders.
        _DELIVERY_KEYWORDS = {"delivery order", "purchase order", "requisition list", "po attachment", "order list"}
        if any(kw in input_lower for kw in _DELIVERY_KEYWORDS):
            _do_tool_map = {
                "gmail_agent": ["search_emails", "search_emails_with_delivery_order_attachments"],
                "mapping_agent": ["parse_delivery_order_pdfs"],
                "sheets_agent": ["validate_delivery_sheet", "preview_delivery_order_insertion", "write_delivery_order_data"],
            }
            for agent_name, required_tools in _do_tool_map.items():
                agent_caps = agent_capabilities.get(agent_name, {}).get("tools", {})
                if agent_name not in validated:
                    valid = [t for t in required_tools if t in agent_caps]
                    if valid:
                        validated[agent_name] = valid
                else:
                    for t in required_tools:
                        if t not in validated[agent_name] and t in agent_caps:
                            validated[agent_name].append(t)

        return validated

    except Exception as e:
        if is_llm_error(e):
            logger.llm_call(
                model=CLASSIFIER_MODEL,
                operation="agent_tool_classification",
                input_tokens=(len(system_prompt) + len(user_prompt)) // 4,
                output_tokens=0,
                duration_ms=(time.time() - start_time) * 1000 if 'start_time' in locals() else 0,
                tier="classifier",
                prompt_summary=f"Classifying agents+tools for: {user_input[:50]}...",
                success=False,
                error=str(e),
            )
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

    # Always include llm_tool — it's a built-in orchestrator tool, not a classifiable agent
    if "llm_tool" not in capabilities:
        from agent_capabilities_v3 import agent_capabilities
        capabilities["llm_tool"] = agent_capabilities["llm_tool"]

    return capabilities, tool_filter
