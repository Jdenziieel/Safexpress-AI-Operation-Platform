"""
Response Templates -- deterministic formatting for agent tool outputs.

Every tool in agent_capabilities_v3.py has a registry entry that maps its
(agent, tool) pair to a formatting rule.  Two types:

  action  -- single confirmation line (prefer agent ``message`` field, else format string)
  query   -- numbered list with per-item display fields

format_step() is the single entry point consumed by SummarizationService.
"""

from collections import defaultdict
from typing import Optional, Dict, Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_format(template: str, data: dict) -> str:
    return template.format_map(defaultdict(str, {k: v for k, v in data.items() if v is not None}))


def _attachment_summary(attachments: list) -> str:
    if not attachments:
        return ""
    parts = []
    for att in attachments:
        name = att.get("filename", "unknown")
        size = att.get("size")
        if size and isinstance(size, (int, float)):
            if size > 1_048_576:
                parts.append(f"{name} ({size / 1_048_576:.1f}MB)")
            elif size > 1024:
                parts.append(f"{name} ({size / 1024:.0f}KB)")
            else:
                parts.append(f"{name} ({size}B)")
        else:
            parts.append(name)
    return ", ".join(parts)


def _link_count_summary(links: list) -> str:
    if not links:
        return ""
    return f"{len(links)} link(s)"


def _body_display(body: str, single_item: bool) -> str:
    """Full body for single result, 300-char preview for lists."""
    if not body:
        return ""
    if single_item:
        return body.strip()
    preview = body[:300].replace("\n", " ").strip()
    if len(body) > 300:
        preview += "..."
    return preview


# ---------------------------------------------------------------------------
# TOOL_TEMPLATES registry
# ---------------------------------------------------------------------------

TOOL_TEMPLATES: Dict[tuple, dict] = {

    # ========================= GMAIL AGENT =========================

    ("gmail_agent", "search_emails"): {
        "type": "query",
        "list_key": "emails",
        "count_key": "count",
        "item_fields": ["from", "subject", "date"],
        "body_field": "body",
        "show_attachments": True,
        "show_links": True,
        "header": "Found {count} email(s):",
    },
    ("gmail_agent", "get_thread_conversation"): {
        "type": "query",
        "list_key": "messages",
        "count_key": "message_count",
        "item_fields": ["from", "to", "subject", "date"],
        "body_field": "body",
        "header": "Thread ({count} message(s)):",
    },
    ("gmail_agent", "reply_to_email"): {
        "type": "action",
        "template": "Replied to **{subject}** (to: {to})",
    },
    ("gmail_agent", "forward_email"): {
        "type": "action",
        "template": "Forwarded **{subject}** to **{to}**",
    },
    ("gmail_agent", "create_draft_email"): {
        "type": "action",
        "template": "Draft created for **{to}**, subject: **{subject}**",
    },
    ("gmail_agent", "send_draft_email"): {
        "type": "action",
        "template": "Draft sent — to: **{to}**, subject: **{subject}**",
    },
    ("gmail_agent", "search_drafts"): {
        "type": "query",
        "list_key": "drafts",
        "count_key": "count",
        "nested_message": True,
        "item_fields": ["draft_id"],
        "header": "Found {count} draft(s):",
    },
    ("gmail_agent", "send_email_with_attachment"): {
        "type": "action",
        "template": "Sent email to **{to}**, subject: **{subject}** (attachment: {attachment_name})",
    },
    ("gmail_agent", "download_attachment"): {
        "type": "action",
        "template": "Downloaded **{filename}** to {save_path} ({file_size} bytes)",
    },
    ("gmail_agent", "search_emails_with_delivery_order_attachments"): {
        "type": "action",
        "template": "Found {total_emails_found} email(s) with {total_attachments_downloaded} attachment(s) downloaded to {temp_directory}",
    },
    ("gmail_agent", "save_attachment_metadata"): {
        "type": "action",
        "template": "Attachment metadata saved (record ID: {inserted_id})",
    },
    ("gmail_agent", "process_delivery_order_workflow"): {
        "type": "action",
        "template": "Delivery order workflow complete — {processed} order(s) processed",
        "append_url": "document_url",
    },

    # ========================= DOCS AGENT =========================

    ("docs_agent", "create_doc"): {
        "type": "action",
        "template": "Created document **{title}**: {document_url}",
    },
    ("docs_agent", "list_my_docs"): {
        "type": "action",
        "use_message": True,
    },
    ("docs_agent", "extract_template_format"): {
        "type": "action",
        "template": "Template placeholders found: {placeholders}",
    },
    ("docs_agent", "create_from_my_template"): {
        "type": "action",
        "template": "Created document from template: {url}",
    },
    ("docs_agent", "add_text"): {
        "type": "action",
        "template": "Added {text_length} characters to document: {document_url}",
    },
    ("docs_agent", "create_doc_with_content"): {
        "type": "action",
        "template": "Created **{title}** with content ({text_length} chars): {document_url}",
    },
    ("docs_agent", "add_text_from_file"): {
        "type": "action",
        "template": "Added file content ({text_length} chars) to document: {document_url}",
    },
    ("docs_agent", "read_doc"): {
        "type": "action",
        "template": "Document **{title}**:\n\n{content}",
        "content_field": "content",
        "content_max_length": 4000,
    },
    ("docs_agent", "create_from_template_and_data_ids"): {
        "type": "action",
        "template": "Created **{title}** from template: {document_url}",
        "append_url": "pdf_url",
    },

    # ========================= CALENDAR AGENT =========================

    ("calendar_agent", "list_events"): {
        "type": "action",
        "use_message": True,
    },
    ("calendar_agent", "create_event"): {
        "type": "action",
        "use_message": True,
    },
    ("calendar_agent", "update_event"): {
        "type": "action",
        "use_message": True,
    },
    ("calendar_agent", "delete_event"): {
        "type": "action",
        "use_message": True,
    },
    ("calendar_agent", "confirm_delete_event"): {
        "type": "action",
        "use_message": True,
    },
    ("calendar_agent", "list_calendars"): {
        "type": "query",
        "list_key": "calendars",
        "item_fields": ["name", "id"],
        "header": "Found {count} calendar(s):",
    },
    ("calendar_agent", "create_calendar"): {
        "type": "action",
        "use_message": True,
    },
    ("calendar_agent", "resolve_conflict"): {
        "type": "action",
        "use_message": True,
    },

    # ========================= DRIVE AGENT =========================

    ("drive_agent", "upload_file"): {
        "type": "action",
        "use_message": True,
        "template": "Uploaded **{filename}** to {folder_path}: {file_url}",
    },
    ("drive_agent", "create_folder"): {
        "type": "action",
        "use_message": True,
        "template": "Created folder: {folder_path}",
    },
    ("drive_agent", "list_folders"): {
        "type": "query",
        "list_key": "folders",
        "count_key": "count",
        "item_fields": ["name"],
        "tree_field": "tree",
        "header": "Found {count} folder(s):",
    },
    ("drive_agent", "list_files"): {
        "type": "action",
        "use_message": True,
    },
    ("drive_agent", "search_files"): {
        "type": "action",
        "use_message": True,
    },
    ("drive_agent", "get_folder_info"): {
        "type": "action",
        "use_message": True,
        "template": "Folder **{folder_name}**: {file_count} file(s), {subfolder_count} subfolder(s)",
    },
    ("drive_agent", "search_template_and_data"): {
        "type": "action",
        "use_message": True,
        "template": "Found template: **{template_file_name}**, data: **{data_file_name}**",
    },

    # ========================= MAPPING AGENT =========================

    ("mapping_agent", "parse_file"): {
        "type": "action",
        "template": "Parsed {row_count} rows — columns: {columns}",
    },
    ("mapping_agent", "extract_dates_from_all_rows"): {
        "type": "action",
        "template": "Extracted dates from {total_rows} rows (date column: {date_column})",
    },
    ("mapping_agent", "smart_column_mapping"): {
        "type": "action",
        "template": "Column mappings created: {mappings}",
    },
    ("mapping_agent", "transform_data"): {
        "type": "action",
        "template": "Data transformed successfully",
    },
    ("mapping_agent", "extract_date_from_data"): {
        "type": "action",
        "template": "Extracted date: {formatted_display}",
    },
    ("mapping_agent", "parse_delivery_order_pdfs"): {
        "type": "action",
        "template": "Parsed {total_parsed} delivery order(s), {total_rejected} file(s) rejected",
    },

    # ========================= SHEETS AGENT =========================

    ("sheets_agent", "update_by_date_match"): {
        "type": "action",
        "template": "Updated {rows_updated} row(s) by date match ({rows_not_found} not found)",
    },
    ("sheets_agent", "upload_mapped_data"): {
        "type": "action",
        "template": "Uploaded {rows_added} row(s) to sheet",
    },
    ("sheets_agent", "create_sheet"): {
        "type": "action",
        "template": "Created spreadsheet: {sheet_url}",
    },
    ("sheets_agent", "validate_delivery_sheet"): {
        "type": "action",
        "use_message": True,
    },
    ("sheets_agent", "preview_delivery_order_insertion"): {
        "type": "action",
        "use_message": True,
    },
    ("sheets_agent", "write_delivery_order_data"): {
        "type": "action",
        "use_message": True,
    },
}


# ---------------------------------------------------------------------------
# Common 2-step composition patterns  (tool1, tool2) -> connector label
# ---------------------------------------------------------------------------

COMPOSE_PATTERNS: Dict[tuple, str] = {
    ("search_emails", "forward_email"): "Found and forwarded",
    ("search_emails", "reply_to_email"): "Found and replied",
    ("create_draft_email", "send_draft_email"): "Created and sent",
    ("search_drafts", "send_draft_email"): "Found and sent draft",
    ("search_template_and_data", "create_from_template_and_data_ids"): "Found files and created document",
    ("list_my_docs", "read_doc"): "Found and read document",
    ("search_files", "upload_mapped_data"): "Found sheet and uploaded data",
    ("parse_file", "transform_data"): "Parsed and transformed data",
    ("search_emails_with_delivery_order_attachments", "parse_delivery_order_pdfs"): "Found and parsed delivery orders",
    ("validate_delivery_sheet", "preview_delivery_order_insertion"): "Validated sheet and prepared preview",
    ("preview_delivery_order_insertion", "write_delivery_order_data"): "Previewed and wrote delivery order data",
}


# ---------------------------------------------------------------------------
# Core formatting functions
# ---------------------------------------------------------------------------

def format_step(agent: str, tool: str, output: dict) -> Optional[str]:
    """
    Format a single step's output through its registered template.

    Returns formatted text, or None if no template matches.
    """
    template = TOOL_TEMPLATES.get((agent, tool))
    if not template:
        return None

    if template["type"] == "action":
        return _format_action(template, output)

    if template["type"] == "query":
        return _format_query_result(template, output)

    return None


def _format_action(template_def: dict, output: dict) -> str:
    if template_def.get("use_message") and output.get("message"):
        text = output["message"]
    elif template_def.get("template"):
        out = dict(output)
        content_field = template_def.get("content_field")
        max_len = template_def.get("content_max_length")
        if content_field and max_len and isinstance(out.get(content_field), str):
            if len(out[content_field]) > max_len:
                out[content_field] = out[content_field][:max_len] + "\n...[truncated]"
        text = _safe_format(template_def["template"], out)
    else:
        text = "Action completed"

    url_field = template_def.get("append_url")
    if url_field and output.get(url_field):
        text += f"\n{url_field.replace('_', ' ').title()}: {output[url_field]}"

    return text


def _format_query_result(template_def: dict, output: dict) -> str:
    list_key = template_def.get("list_key", "items")
    items = output.get(list_key, [])
    count_key = template_def.get("count_key", "count")
    count = output.get(count_key, len(items))

    header_data = defaultdict(str, {k: v for k, v in output.items() if not isinstance(v, (list, dict))})
    header_data["count"] = count
    header = template_def["header"].format_map(header_data)

    tree_field = template_def.get("tree_field")
    if tree_field and output.get(tree_field):
        return f"{header}\n{output[tree_field]}"

    single_item = (count == 1 and len(items) == 1)
    lines = [header]
    display_limit = 10

    for i, item in enumerate(items[:display_limit]):
        parts = _format_item(template_def, item, single_item)
        lines.append(f"  {i + 1}. " + " | ".join(parts))

    if count > display_limit:
        lines.append(f"  ... and {count - display_limit} more")

    return "\n".join(lines)


def _format_item(template_def: dict, item: dict, single_item: bool) -> list:
    """Build the display parts for a single list item."""

    # Drafts have a nested message object -- flatten it
    if template_def.get("nested_message") and isinstance(item.get("message"), dict):
        msg = item["message"]
        parts = []
        # Top-level item_fields first (e.g. draft_id lives outside message)
        for field in template_def.get("item_fields", []):
            val = item.get(field, "")
            if val:
                parts.append(f"{field.replace('_', ' ').title()}: {val}")
        for key in ("to", "subject", "date"):
            val = msg.get(key, "")
            if val:
                parts.append(f"{key.title()}: {val}")
        body = msg.get("body", "")
        if body:
            label = "Body" if single_item else "Preview"
            parts.append(f"{label}: {_body_display(body, single_item)}")
        return parts

    parts = []
    for field in template_def.get("item_fields", []):
        val = item.get(field, "")
        if val is None or val == "":
            continue
        if field == "size" and isinstance(val, (int, float)):
            if val > 1_048_576:
                parts.append(f"Size: {val / 1_048_576:.1f}MB")
            elif val > 1024:
                parts.append(f"Size: {val / 1024:.0f}KB")
            else:
                parts.append(f"Size: {val}B")
        elif isinstance(val, str):
            parts.append(f"{field.replace('_', ' ').title()}: {val}")
        else:
            parts.append(f"{field.replace('_', ' ').title()}: {val}")

    body_field = template_def.get("body_field")
    if body_field:
        body = item.get(body_field, "")
        if body:
            label = "Body" if single_item else "Preview"
            parts.append(f"{label}: {_body_display(body, single_item)}")

    if template_def.get("show_attachments"):
        atts = item.get("attachments", [])
        if atts:
            parts.append(f"Attachments: {_attachment_summary(atts)}")

    if template_def.get("show_links"):
        links = item.get("body_links", [])
        if links:
            parts.append(_link_count_summary(links))

    return parts
