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

            # Block A extension — attachment-bearing email tools.
            # Closes the capability gap that previously caused the planner
            # to hallucinate `send_email_with_attachment(draft_id=...)` when
            # the user wanted a DRAFT with an attached file: there is no
            # post-creation "attach to draft" Gmail API, so a one-shot
            # `create_draft_email_with_attachment` tool is required.
            #
            # Trigger on attach-keyword co-occurrence with email keywords
            # (already gated by `gmail_agent in validated`). Inject the
            # one-shot draft+attachment tool when draft phrasing is present,
            # and the send+attachment tool when send phrasing is present.
            # When the user uses ambiguous phrasing ("attach this PDF") and
            # didn't say "draft" / "send", both are added so the planner
            # can disambiguate against the rest of the user message.
            _ATTACH_KEYWORDS = (
                "attach", "attachment", "attached",
                "with the file", "with this file", "with the pdf",
            )
            _DRAFT_PHRASE_KEYWORDS = (
                "draft", "drafts", "gmaildraft", "gmail draft",
                "as a draft", "as draft", "save as draft",
            )
            _SEND_PHRASE_KEYWORDS = (
                "send", "send it", "send the email", "send out",
                "ship", "deliver",
            )
            attach_present = any(kw in input_lower for kw in _ATTACH_KEYWORDS)
            if attach_present:
                gmail_caps = agent_capabilities.get("gmail_agent", {}).get("tools", {})
                draft_present = any(kw in input_lower for kw in _DRAFT_PHRASE_KEYWORDS)
                send_present = any(kw in input_lower for kw in _SEND_PHRASE_KEYWORDS)

                if draft_present and "create_draft_email_with_attachment" in gmail_caps:
                    if "create_draft_email_with_attachment" not in gmail_tools:
                        gmail_tools.append("create_draft_email_with_attachment")

                if send_present and "send_email_with_attachment" in gmail_caps:
                    if "send_email_with_attachment" not in gmail_tools:
                        gmail_tools.append("send_email_with_attachment")

                # Ambiguous "attach" with neither draft nor send phrasing —
                # offer both so the planner picks based on the rest of the
                # user message + capability descriptions.
                if not draft_present and not send_present:
                    if "create_draft_email_with_attachment" in gmail_caps and "create_draft_email_with_attachment" not in gmail_tools:
                        gmail_tools.append("create_draft_email_with_attachment")
                    if "send_email_with_attachment" in gmail_caps and "send_email_with_attachment" not in gmail_tools:
                        gmail_tools.append("send_email_with_attachment")

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
            # "that says", "with sections"), offer create_doc_with_content
            # as an alternative so the planner can do it in one step instead
            # of the two-step create_doc + add_text chain. create_doc stays
            # in the filter so the planner can still pick the simpler tool
            # when the content is added later.
            #
            # The structural variants ("with sections", "with headings",
            # "with bullet") cover agenda-style requests like the DEMO8.log
            # scenario ("Google Doc agenda with sections Yesterday's Issues,
            # Today's Priorities, and Blockers"), where the user supplies
            # the content inline via section titles rather than the prose
            # "with content" phrasing. Without this, the planner is forced
            # into create_doc + add_text, and add_text is DANGEROUS-tier
            # (models.py:161), causing an unnecessary approval pause even
            # for doc content the user has just specified.
            _CONTENT_PHRASE_KEYWORDS = (
                "with content", "with text", "with the following",
                "containing", " that says ", " saying ", " with body ",
                "with sections", "with a section", "with headings",
                "with a heading", "with bullet",
            )
            if "create_doc" in docs_tools and any(kw in input_lower for kw in _CONTENT_PHRASE_KEYWORDS):
                if "create_doc_with_content" not in docs_tools and "create_doc_with_content" in docs_caps:
                    docs_tools.append("create_doc_with_content")

        # Calendar agent safety nets.
        _CALENDAR_EVENT_MUTATION_TOOLS = {
            "update_event", "delete_event", "confirm_delete_event",
        }
        # Block J: when the classifier picks create_event but the user's
        # phrasing also describes modifying the just-created event (e.g.
        # "create an event ... then attach the agenda link in the event
        # description"), inject update_event so the planner can emit a
        # create_event -> update_event chain using the freshly captured
        # event_id. Without this, the planner has only create_event and
        # improvises by duplicating it with the description added, which
        # Google Calendar's conflict detection correctly rejects as a
        # double-booking (see execution_logs/CM/DEMO8.log).
        #
        # Gated narrowly on phrases that unambiguously refer to modifying
        # an existing event: "event description" references, explicit
        # update/modify/change-the-event verbs, and attach-the-[artifact]
        # patterns. Bare "update" / "attach" without the event noun is
        # deliberately excluded to avoid false positives on email / doc
        # workflows (e.g. "attach a PDF to the email", "update the doc").
        _EVENT_MODIFICATION_PHRASES = (
            " event description", " event's description",
            "update the event", "modify the event",
            "change the event description", "change the event ",
            " add to the event ", " add to the meeting ",
            "attach the agenda", "attach the doc", "attach the link",
            "attach the document", "attach the sheet",
            " in the event description", " in the event's description",
            " to the event description",
        )
        # Block D: whenever a calendar event mutation tool is selected,
        # also include list_events as a fallback lookup path.
        # update_event / delete_event / confirm_delete_event accept event_name
        # for internal auto-lookup, but that only works when the user refers
        # to the event by its exact title. When the reference is by date/time,
        # attendees, or other attributes, the planner needs list_events to
        # resolve the event_id before the mutation.
        if "calendar_agent" in validated:
            cal_tools = validated["calendar_agent"]
            cal_caps = agent_capabilities.get("calendar_agent", {}).get("tools", {})
            # Block J runs first so Block D can then pair list_events
            # with the freshly-injected update_event if needed.
            if (
                "create_event" in cal_tools
                and "update_event" not in cal_tools
                and "update_event" in cal_caps
                and any(kw in input_lower for kw in _EVENT_MODIFICATION_PHRASES)
            ):
                cal_tools.append("update_event")
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
        # it. Placed BEFORE Block K so Block K's extension can see the
        # freshly-injected create_sheet and pair it with append_rows +
        # header companions when the request also carries a cross-agent
        # data source (e.g. gmail.search_emails + "new sheet"). Placed
        # BEFORE Block F so Block F can see create_sheet and pair it
        # with get_folder_info when the user mentions a folder.
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

        # Block K (Commit 3): schema-aware append safety net.
        # When the classifier selected a sheets WRITE tool (the user is
        # writing INTO an existing sheet), the planner needs the two
        # header-management companions so it can implement Rule 17:
        #   - get_sheet_headers: read existing row 1 to align column order
        #     of the incoming rows (feeds the transform_text instruction).
        #   - ensure_headers: idempotently create / validate row 1 when
        #     the tab might be empty (DEMO5.2-style "append to a blank
        #     tab" or fresh-sheet paths that skipped create_sheet's
        #     initial_data).
        # Block E (above) already injected drive_agent.search_files for
        # sheet-id resolution; Block K complements that with the header
        # companions. Firing signal is presence-based (no keyword check)
        # so the block fires for any write tool — keeps the logic simple
        # and avoids the false-negative trap where a user's phrasing
        # happens to dodge a keyword list.
        # Placed AFTER Block H so Block K's extension sees any create_sheet
        # that Block H injected on keyword alone (classifier miss case).
        _SHEET_WRITE_TOOLS = {
            "append_rows", "update_sheet",
            "upload_mapped_data", "update_by_date_match",
        }
        if "sheets_agent" in validated:
            sheets_tools_for_k = validated["sheets_agent"]
            sheets_caps_for_k = agent_capabilities.get("sheets_agent", {}).get("tools", {})
            if any(t in _SHEET_WRITE_TOOLS for t in sheets_tools_for_k):
                for companion in ("get_sheet_headers", "ensure_headers"):
                    if companion not in sheets_tools_for_k and companion in sheets_caps_for_k:
                        sheets_tools_for_k.append(companion)

            # Block K extension (Commit 4): fresh-sheet pipeline safety net.
            # When sheets_agent.create_sheet is present (either from the
            # classifier or freshly injected by Block H above) AND the
            # request is a cross-agent ingestion (reads from emails/docs/
            # drive/mapping plus a sheet creation), the planner also needs
            # append_rows in case the body is large enough to warrant the
            # split create_sheet → append_rows flow from Rule 18's alternate
            # path. For the primary path (Rule 18 step D with initial_data
            # carrying headers+body), append_rows is harmless — the planner
            # just won't emit it. Signal is presence-based: any data-source
            # agent/tool in validated is enough. We also key off append-
            # intent keywords ("append", "add these", "populate with", "put
            # ... into") as an explicit signal when create_sheet is the
            # only tool in the request. Gated on create_sheet being present
            # AND append_rows NOT already injected.
            _DATA_SOURCE_TOOLS = {
                "gmail_agent": ("search_emails", "read_email_content", "search_drafts"),
                "docs_agent": ("read_doc", "list_my_docs"),
                "drive_agent": ("read_file_content", "download_file", "search_files", "list_files"),
                "mapping_agent": ("parse_file", "smart_column_mapping", "transform_data"),
            }
            _APPEND_INTENT_KEYWORDS = (
                " append ", " add these ", " add them ", " add the ",
                " populate ", " populated ", " fill in ", " fill with ",
                " put them ", " put the ", " put those ", " write them ",
                " with the data ", " with these ", " with the rows ",
                " rows from ", " data from ", " entries from ",
            )
            has_create_sheet = "create_sheet" in sheets_tools_for_k
            has_append_rows = "append_rows" in sheets_tools_for_k
            if has_create_sheet and not has_append_rows and "append_rows" in sheets_caps_for_k:
                has_data_source = any(
                    other_agent in validated
                    and any(t in validated[other_agent] for t in source_tools)
                    for other_agent, source_tools in _DATA_SOURCE_TOOLS.items()
                )
                has_append_intent = any(kw in input_lower for kw in _APPEND_INTENT_KEYWORDS)
                if has_data_source or has_append_intent:
                    sheets_tools_for_k.append("append_rows")
                    # If we just injected append_rows, the Rule-17 companions
                    # (get_sheet_headers, ensure_headers) are still useful for
                    # the alternate Rule-18 path where the sheet is created
                    # blank and headers land via ensure_headers. Re-run the
                    # header-companion injection so the planner has them too.
                    for companion in ("get_sheet_headers", "ensure_headers"):
                        if companion not in sheets_tools_for_k and companion in sheets_caps_for_k:
                            sheets_tools_for_k.append(companion)

            # Block L (TestURLERR fix): tab-creation safety net.
            # When the user asks for data to land in named tabs of an
            # EXISTING spreadsheet and explicitly says to create the tabs
            # if they don't exist, the classifier must offer add_sheet_tab
            # to the planner — without it, the planner improvises by
            # using read_sheet as an existence probe (which raises HTTP 400
            # on missing tabs and stops the workflow) or by creating a
            # disposable temporary spreadsheet via create_sheet (wasted
            # Drive bloat, and the temp tabs aren't even in the user's
            # destination).
            # The block fires only when BOTH signals are present:
            #   (a) the input mentions tabs in the multi-tab sense (the
            #       Block H tab keywords like "tabs ", "tab named", "tab
            #       called"), AND
            #   (b) the input has a conditional-create phrasing like "if
            #       missing", "if it doesn't have", "create them",
            #       "create if".
            # This conservative gating avoids over-injection on routine
            # single-tab read/write requests where the user already
            # provided the tab name and isn't asking for tab creation.
            # Companion: also injects get_sheet_metadata so the planner
            # can emit a list-tabs step when the response composer
            # benefits from a "tabs found" line.
            _TAB_REFERENCE_KEYWORDS = (
                " tabs ", " tabs,", " tabs.", " tab named ", " tab called ",
                "sheet tabs", "sheet tab ",
                "tabs like ", "tabs named ", "tabs called ",
            )
            _TAB_CONDITIONAL_CREATE_KEYWORDS = (
                "create them",
                "create the tabs", "create the tab", "create tabs", "create tab ",
                "add them", "add the tabs", "add the tab", "add tabs", "add a tab ",
                "make them", "make the tabs", "make the tab",
                "if missing", "if it's missing", "if its missing",
                "if not exist", "if they don't exist", "if it doesn't exist",
                "if doesn't have", "if doesnt have", "if it doesn't have", "if it doesnt have",
                "if there's no", "if there is no", "if not present",
                "doesn't have ", "doesnt have ",
            )
            mentions_tabs = any(kw in input_lower for kw in _TAB_REFERENCE_KEYWORDS)
            asks_conditional_tab_create = any(
                kw in input_lower for kw in _TAB_CONDITIONAL_CREATE_KEYWORDS
            )
            if mentions_tabs and asks_conditional_tab_create:
                if (
                    "add_sheet_tab" not in sheets_tools_for_k
                    and "add_sheet_tab" in sheets_caps_for_k
                ):
                    sheets_tools_for_k.append("add_sheet_tab")
                if (
                    "get_sheet_metadata" not in sheets_tools_for_k
                    and "get_sheet_metadata" in sheets_caps_for_k
                ):
                    sheets_tools_for_k.append("get_sheet_metadata")

        # Block M (DEMO SHEET 1.2 fix): mirror-all-tabs safety net.
        # When the user asks to copy / mirror / sync / replicate every
        # tab from one spreadsheet to another, the planner cannot
        # express that as a static plan because the per-tab loop
        # depends on metadata that's only known at execution time
        # (Invariant 7: ReAct disabled — no orchestrator for_each).
        # In the DEMO SHEET 1.2 log the planner attempted to "meta-plan"
        # this with 17 llm_tool.transform_text steps that described
        # what should happen rather than executing real sheet ops, and
        # zero data made it to the target. The fix is to expose a
        # compound tool — sheets_agent.mirror_tabs — that runs the
        # per-tab loop INSIDE the sub-agent. This block ensures the
        # planner sees that tool whenever the request matches the
        # mirror pattern.
        # NOTE: `import re as _re` happens here (early in the function)
        # so Block M can use _re without depending on the later
        # folder-block import at line ~552 of the original file. Re-
        # importing the same module at line 552 is harmless — Python's
        # import machinery short-circuits on cached modules.
        import re as _re
        # Fires when the input matches ANY of:
        #   - explicit verbs: "mirror tabs", "sync tabs", "replicate tabs"
        #   - copy + scope quantifiers: "copy all tabs", "copy every tab",
        #     "copy each tab", "copy the tabs"
        #   - cross-spreadsheet phrasing: "(copy|move|transfer) … tabs …
        #     (from|in) … to …" with both source and target referenced
        # Companion: drive_agent.search_files is added so the planner
        # can resolve sheet NAMES (the most common phrasing) to
        # sheet IDs before calling mirror_tabs.
        # Block M runs as a top-level block — it does NOT require
        # sheets_agent to already be in validated, because the
        # classifier often misroutes mirror requests to llm_tool only
        # (the meta-planning failure mode in the original log).
        # Direct keyword set — substring match, case-insensitive
        # (input_lower already applied). The four "the tabs" variants
        # (mirror/sync/replicate/duplicate the tabs) were added after the
        # overlap-simulation suite caught a gap on "Sync the tabs between
        # source and target" — that phrasing fails the broad pattern's
        # "from ... to" requirement, and the keyword "sync tabs" doesn't
        # match the literal "sync the tabs" substring (the article "the"
        # breaks adjacency). Adding "the tabs" variants keeps the keyword
        # path as the primary trigger and avoids forcing all callers
        # through the broad-pattern alternative.
        _MIRROR_TABS_DIRECT_KEYWORDS = (
            "mirror tabs", "mirror all tabs", "mirror every tab", "mirror the tabs",
            "sync tabs", "sync all tabs", "sync every tab", "sync the tabs",
            "replicate tabs", "replicate all tabs", "replicate every tab", "replicate the tabs",
            "duplicate tabs", "duplicate all tabs", "duplicate every tab", "duplicate the tabs",
            "copy all tabs", "copy every tab", "copy each tab",
            "copy the tabs", "copy all the tabs",
            "copy tabs from", "copy all tabs from",
            "copy contents of all tabs", "copy contents from all tabs",
            "copy data from all tabs", "copy all data and tabs",
            "copy all tabs and contents", "copy tabs and contents",
            "copy tabs and data", "copy all tabs and data",
            "all tabs and contents", "all tabs and data",
        )
        # Broad pattern — verb + tab quantifier + cross-spreadsheet
        # connector. Two connector forms are accepted:
        #   - "from|in|of … to" (e.g. "copy all tabs from A to B")
        #   - "between … and" (e.g. "sync all tabs between A and B")
        # Verbs include the standard set plus "clone" and "back up" —
        # both are common synonyms for "duplicate / copy" in a sheets
        # context (e.g. "clone all tabs from prod to staging" or "back
        # up every tab from main to archive"). Two-word "back up" needs
        # to match both "back up" (verb + adverb) and "backup" (single
        # word) so we use `back\s*up` in a non-capturing group.
        # The 80-char inner gap intentionally allows intervening
        # adjectives ("the source spreadsheet") and short clause
        # fragments without spanning sentence boundaries (the gap is
        # `[^.]{0,80}` — period-bounded). Period boundaries prevent the
        # pattern from accidentally matching across two unrelated
        # sentences in a multi-clause request.
        _MIRROR_TABS_BROAD_PATTERN = _re.compile(
            r"\b(?:copy|move|transfer|mirror|sync|replicate|duplicate|clone|back\s*up|backup)\b"
            r"[^.]{0,80}\b(?:all|every|each|the)\s+tabs?\b"
            r"[^.]{0,80}"
            r"(?:"
            r"\b(?:from|in|of)\b[^.]{0,80}\bto\b"
            r"|"
            r"\bbetween\b[^.]{0,80}\band\b"
            r")",
            _re.IGNORECASE,
        )
        # Explicit mapping pattern: "put the [SrcTab] tab into the
        # [TgtTab] tab" / "copy [SrcTab] tab to [TgtTab] tab" / "map
        # [X] to [Y]". Catches the rename case where source and target
        # tab names diverge (e.g. "put the Food tab from sheet A into
        # the Groceries tab of sheet B"). Distinct from the broader
        # mirror pattern above — does NOT require the "all/every/each"
        # quantifier because explicit per-tab mappings are inherently
        # enumerated.
        _MIRROR_TABS_MAPPING_PATTERN = _re.compile(
            r"\b(?:put|copy|move|map|transfer)\b"
            r"[^.]{0,40}\b(?:the\s+)?(?:[a-z0-9_\-]+\s+)?tab\b"
            r"[^.]{0,80}\b(?:in(?:to)?|to)\b"
            r"[^.]{0,40}\b(?:the\s+)?(?:[a-z0-9_\-]+\s+)?tab\b",
            _re.IGNORECASE,
        )
        # Defensive guard: STRONG delivery-order signals — phrasings
        # that unambiguously indicate the delivery-order pipeline (Rule
        # 16) rather than a generic sheet-to-sheet mirror. A user who
        # says "process this delivery order PDF" or "extract from
        # delivery order" is invoking Block G's territory, not Block
        # M's, even if their phrasing happens to include "tabs"
        # somewhere.
        #
        # The previous implementation used a tuple of phrases that
        # included bare "delivery order" / "purchase order". Those
        # could appear in legitimate spreadsheet NAMES (e.g.
        # "Delivery Order Log Sheet", "Purchase Order Master"), causing
        # false negatives for users who wanted to mirror tabs of such a
        # sheet. The regex below only fires on phrasings that combine
        # the noun with a workflow signal (PDF/form/email file
        # markers, or process/extract/parse/handle verbs).
        #
        # Three alternations:
        #   (a) bare "po pdf|form|attachment" — workflow file markers
        #       that wouldn't appear in a legitimate sheet name
        #   (b) "delivery|purchase order pdf|form|attachment|email" —
        #       the DO/PO noun paired with a file marker
        #   (c) "process|extract|parse|handle [the/this/an/from] +
        #       delivery-order|purchase-order|requisition list" — verb
        #       paired with the workflow noun phrase
        #
        # NOT matched (so Block M can still fire):
        #   - "Mirror all tabs from Delivery Order Log to Archive"
        #     (no PDF/form/email after "Order Log", no verb before)
        #   - "Mirror tabs from Purchase Order Master to Backup"
        #   - "Process the delivery confirmations" (no DO/PO noun)
        _DELIVERY_ORDER_WORKFLOW_PATTERN = _re.compile(
            r"\b(?:"
            r"po\s+(?:pdf|form|attachment)"
            r"|"
            r"(?:delivery|purchase)[-\s]?order\s+(?:pdf|form|attachment|email)"
            r"|"
            r"(?:process|extract|parse|handle)\s+"
            r"(?:(?:the|this|that|a|an|from(?:\s+(?:the|this))?)\s+)?"
            r"(?:delivery[-\s]?order|purchase[-\s]?order|requisition\s+list)"
            r")\b",
            _re.IGNORECASE,
        )
        mentions_mirror_direct = any(
            kw in input_lower for kw in _MIRROR_TABS_DIRECT_KEYWORDS
        )
        mentions_mirror_pattern = bool(
            _MIRROR_TABS_BROAD_PATTERN.search(input_lower)
        )
        mentions_mapping_pattern = bool(
            _MIRROR_TABS_MAPPING_PATTERN.search(input_lower)
        )
        is_delivery_order_workflow = bool(
            _DELIVERY_ORDER_WORKFLOW_PATTERN.search(input_lower)
        )
        if (
            (mentions_mirror_direct or mentions_mirror_pattern or mentions_mapping_pattern)
            and not is_delivery_order_workflow
        ):
            sheets_caps_for_m = agent_capabilities.get("sheets_agent", {}).get("tools", {})
            if "mirror_tabs" in sheets_caps_for_m:
                sheets_tools_for_m = validated.setdefault("sheets_agent", [])
                if "mirror_tabs" not in sheets_tools_for_m:
                    sheets_tools_for_m.append("mirror_tabs")
                # Companion: source/target sheet names → IDs via Drive
                # search. Without this the planner has no way to resolve
                # "PMRL" → spreadsheet ID. (Invariant 13 covers URL inputs;
                # this covers the bare-name case which is the more common
                # phrasing.)
                drive_caps_for_m = agent_capabilities.get("drive_agent", {}).get("tools", {})
                if "search_files" in drive_caps_for_m:
                    drive_tools_for_m = validated.setdefault("drive_agent", [])
                    if "search_files" not in drive_tools_for_m:
                        drive_tools_for_m.append("search_files")
                # Companion: get_sheet_metadata is occasionally useful
                # downstream of mirror_tabs (e.g. user asks to "tell me
                # what tabs got mirrored" as a follow-up). Cheap to add.
                if (
                    "get_sheet_metadata" in sheets_caps_for_m
                    and "get_sheet_metadata" not in validated["sheets_agent"]
                ):
                    validated["sheets_agent"].append("get_sheet_metadata")

        # Block N (Bug J fix): template-with-data workflow tool completeness.
        #
        # When the user asks "create a new doc from <template> using <data>",
        # the planner needs the FULL chain available so it can pick the
        # right path based on whether the template is uploaded vs already
        # in Drive. The classifier (gpt-4o-mini) routinely misses parts of
        # this chain — observed failure modes:
        #   - Test 1 (no upload, "use template MinutesOfMeetingTEMP and
        #     data TestData123"): classifier returned only
        #     {docs_agent: [create_from_template_and_data_ids,
        #     list_my_docs]} with NO drive_agent at all. The merge tool
        #     was present but the prerequisite Drive lookup was missing.
        #   - Test 2 (uploaded template + Drive data): classifier returned
        #     {drive_agent: [search_files], docs_agent:
        #     [create_from_uploaded_template, list_my_docs]} — the
        #     create_from_uploaded_template tool is single-source (it
        #     copies one Drive file into a new doc, "uploaded" is a
        #     misnomer for "an existing Drive file"); the actual two-
        #     source merge tool create_from_template_and_data_ids was
        #     missing entirely.
        #
        # Both failure modes manifest identically downstream: gpt-4.1
        # tries to plan a workflow it cannot express with the available
        # function schemas. It falls back to writing prose in the
        # `description` field and omits `inputs` because no valid value
        # exists. Pydantic then rejects the function call with
        # "validation error: steps.N.inputs Field required" — observed
        # with output_tokens=77/81/82 (vs ~127-144 on a properly-filled
        # 2-step plan). With no planner retry layer, that's a hard fail.
        #
        # This block ensures all 4 tools needed for the two paths are
        # available whenever the template+data co-occurrence is detected
        # in the user input:
        #   Path A — both files in Drive (no uploaded_file in context):
        #     drive_agent.search_template_and_data → docs_agent.create_from_template_and_data_ids
        #   Path B — uploaded template + data file in Drive:
        #     drive_agent.upload_template → drive_agent.search_files →
        #     docs_agent.create_from_template_and_data_ids
        # The planner picks the path based on uploaded_file context
        # (visible to it via context_vars_note in the system prompt) —
        # see Rule 21 for the explicit decision guide.
        #
        # Detection: co-occurrence of a TEMPLATE noun phrase AND a
        # DATA noun phrase in the user's input. Both halves must be
        # present to fire — keeps the block off generic "create a doc"
        # requests while still catching every real two-source merge.
        # Conservative phrasing list — bare "data" alone is excluded
        # to avoid firing on chatter like "summarize this data" where
        # there's no template involved.
        _TEMPLATE_REFERENCE_KEYWORDS = (
            " template ", " template,", " template.",
            " template named", " template called", " template titled",
            "the template ", "this template", "uploaded template",
            "as the template", "as a template", "for the template",
            " format file ",
        )
        _DATA_FOR_TEMPLATE_KEYWORDS = (
            " data ", " data,", " data.",
            " data named", " data called", " data titled",
            " data doc", " data document", " data file",
            "for the data", "with the data", "using the data",
            "the data doc", "the data document", "the data file",
            " content file", "the content file",
        )
        mentions_template_for_merge = any(
            kw in input_lower for kw in _TEMPLATE_REFERENCE_KEYWORDS
        )
        mentions_data_for_template = any(
            kw in input_lower for kw in _DATA_FOR_TEMPLATE_KEYWORDS
        )
        if mentions_template_for_merge and mentions_data_for_template:
            drive_caps_for_n = agent_capabilities.get("drive_agent", {}).get("tools", {})
            docs_caps_for_n = agent_capabilities.get("docs_agent", {}).get("tools", {})
            drive_tools_for_n = validated.setdefault("drive_agent", [])
            docs_tools_for_n = validated.setdefault("docs_agent", [])

            # Always-needed: the two-source merge tool.
            if (
                "create_from_template_and_data_ids" in docs_caps_for_n
                and "create_from_template_and_data_ids" not in docs_tools_for_n
            ):
                docs_tools_for_n.append("create_from_template_and_data_ids")
            # docs_agent.list_my_docs is already added by the docs_agent
            # safety net above (line ~154); no need to re-add here.

            # Path A: both files in Drive — search_template_and_data
            # finds both in one call.
            if (
                "search_template_and_data" in drive_caps_for_n
                and "search_template_and_data" not in drive_tools_for_n
            ):
                drive_tools_for_n.append("search_template_and_data")

            # Path B step 1: uploaded template → push to Drive Templates
            # folder. Harmless to include when no upload exists — the
            # planner won't pick it because uploaded_file is absent from
            # context.
            if (
                "upload_template" in drive_caps_for_n
                and "upload_template" not in drive_tools_for_n
            ):
                drive_tools_for_n.append("upload_template")

            # Path B step 2: data-file lookup. (Path A's
            # search_template_and_data covers both lookups in one call;
            # Path B needs search_files for the data half because the
            # template half is the upload.)
            if (
                "search_files" in drive_caps_for_n
                and "search_files" not in drive_tools_for_n
            ):
                drive_tools_for_n.append("search_files")

            try:
                logger.info(
                    "[BlockN] template+data workflow tools injected "
                    f"(template_kw_match=True, data_kw_match=True, "
                    f"path_A_tools=[search_template_and_data, create_from_template_and_data_ids], "
                    f"path_B_tools=[upload_template, search_files, create_from_template_and_data_ids])"
                )
            except Exception:
                pass

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
        #
        # drive_agent.search_files is included so the planner can resolve a
        # sheet NAME to a sheet_id when the user refers to their requisition
        # sheet by title rather than pasting a URL. All three delivery Sheet
        # tools (validate_delivery_sheet / preview_delivery_order_insertion /
        # write_delivery_order_data) take sheet_id only — no name-based auto-
        # lookup exists. URL pastes are handled inside _extract_sheet_id at
        # the Sheets agent; name-based references need this search_files hop.
        # Block E's _SHEET_ID_CONSUMERS deliberately excludes delivery tools
        # (Block E runs BEFORE Block G and so can't see them anyway); keeping
        # the dependency self-contained inside Block G is cheaper and more
        # auditable than reordering the blocks.
        # Keywords are aligned with the Tier 1 DELIVERY ORDER WORKFLOW vocabulary
        # in conversational_agent.py (delivery-order / requisition / purchase-order /
        # PO / "order list"). Both hyphenated and spaced forms are matched because
        # users write both. "PO" alone is deliberately excluded — too many false
        # positives (post office, post-op, etc.) — but the common attachment phrasings
        # ("po attachment", "po pdf", "po form") are included.
        _DELIVERY_KEYWORDS = {
            "delivery order", "delivery-order",
            "purchase order", "purchase-order",
            "requisition list", "requisition",
            "po attachment", "po pdf", "po form",
            "order list",
        }
        if any(kw in input_lower for kw in _DELIVERY_KEYWORDS):
            _do_tool_map = {
                "gmail_agent": ["search_emails", "search_emails_with_delivery_order_attachments"],
                "mapping_agent": ["parse_delivery_order_pdfs"],
                "sheets_agent": ["validate_delivery_sheet", "preview_delivery_order_insertion", "write_delivery_order_data"],
                "drive_agent": ["search_files"],
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

            # Remove the generic upload_mapped_data from sheets_agent so the planner
            # can't accidentally bypass validate_delivery_sheet / preview_delivery_order_insertion
            # for this intent. The delivery-specific write_delivery_order_data does
            # template validation, row alignment, and tab-aware routing — picking the
            # generic tool silently skips all of that.
            if "sheets_agent" in validated and "upload_mapped_data" in validated["sheets_agent"]:
                validated["sheets_agent"] = [
                    t for t in validated["sheets_agent"] if t != "upload_mapped_data"
                ]

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
