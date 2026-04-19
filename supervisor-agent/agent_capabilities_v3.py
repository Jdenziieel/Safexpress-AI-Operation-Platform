"""
Agent Capabilities Configuration V3

Slimmed-down capabilities definition optimized for token efficiency.
Changes from V2:
- returns: flat list of key field names (not verbose descriptions)
- Removed nested array field descriptions (emails[].X, files[].X, etc.)
- Removed draft_structure, usage_note, usage_patterns, important_notes, example, notes
- Removed redundant template_workflow (kept template_with_data_workflow)
- Simplified can_be_derived_from to {"arg": "source_tool"}
- Removed {{ yesterday_date }} references (LLM computes relative dates from today_date)
"""

agent_capabilities = {
    "gmail_agent": {
        "description": "Gmail operations: search, read threads, draft, send, reply, forward, manage labels, download attachments.",
        "tools": {
            "search_emails": {
                "description": "Search emails with Gmail query syntax (from:, after:YYYY/MM/DD, before:YYYY/MM/DD, subject:, has:attachment, is:unread).",
                "args": {
                    "query": "str (required) — Gmail search query",
                    "max_results": "int (required) — number of emails to fetch",
                    "label_ids": "List[str] (optional) — filter by label IDs",
                },
                "returns": ["success", "emails", "count", "query", "error"],
                "returns_detail": "emails is an array; each email has: message_id, thread_id, from, subject, date, body, has_attachments, attachments",
                "array_access": "Use {{ emails[0].message_id }}, {{ emails[0].from }}, {{ emails[0].subject }}. Store via output_variables: {\"recent_emails\": \"emails\"}, then use {{ recent_emails[0].from }}",
            },
            "get_thread_conversation": {
                "description": "Retrieve all messages in an email thread with full bodies.",
                "args": {
                    "thread_id": "str (required) — thread ID from search_emails",
                },
                "returns": ["success", "thread_id", "message_count", "messages", "all_message_ids", "error"],
                "returns_detail": "messages is an array; each message has: message_id, from, to, subject, date, body",
                "can_be_derived_from": {"thread_id": "search_emails"},
            },
            "reply_to_email": {
                "description": "Reply to an email in its thread (maintains conversation).",
                "args": {
                    "message_id": "str (required) — message ID to reply to",
                    "reply_body": "str (required) — reply content",
                },
                "returns": ["success", "reply_message_id", "thread_id", "to", "subject", "error"],
                "can_be_derived_from": {"message_id": "search_emails"},
            },
            "forward_email": {
                "description": "Forward an email to another recipient.",
                "args": {
                    "message_id": "str (required) — message ID to forward",
                    "to": "str (required) — recipient email",
                    "forward_message": "str (optional) — additional message",
                },
                "returns": ["success", "forwarded_message_id", "thread_id", "to", "subject", "error"],
                "can_be_derived_from": {"message_id": "search_emails"},
            },
            "create_draft_email": {
                "description": "Create a draft email without sending (safer than direct send).",
                "args": {
                    "to": "str (required) — recipient email",
                    "subject": "str (required) — subject line",
                    "body": "str (required) — email body",
                    "cc": "str (optional) — CC recipients, comma-separated emails",
                    "bcc": "str (optional) — BCC recipients, comma-separated emails",
                },
                "returns": ["success", "draft_id", "message_id", "to", "subject", "error"],
            },
            "send_draft_email": {
                "description": "Send a previously created draft by its draft_id.",
                "args": {
                    "draft_id": "str (required) — draft_id from create_draft_email or search_drafts",
                },
                "returns": ["success", "draft_id", "message_id", "thread_id", "to", "subject", "error"],
                "can_be_derived_from": {"draft_id": "search_drafts"},
            },
            "search_drafts": {
                "description": "Search draft emails. Returns drafts with {draft_id, message: {id, to, subject, body, date}}.",
                "args": {
                    "query": "str (optional) — Gmail search query",
                    "max_results": "int (optional) — max drafts to return",
                },
                "returns": ["success", "count", "drafts", "query", "error"],
                "returns_detail": "drafts is an array; each draft has: draft_id, message {id, to, subject, body, date}",
            },
            "send_email_with_attachment": {
                "description": "Send email with a LOCAL file attachment. file_path must be an absolute path to a file on disk — NOT a URL or web link.",
                "args": {
                    "to": "str (required) — recipient email",
                    "subject": "str (required) — subject line",
                    "body": "str (required) — email body",
                    "file_path": "str (required) — absolute path to a LOCAL file on disk (NOT a URL)",
                    "cc": "str (optional) — CC recipients, comma-separated emails",
                    "bcc": "str (optional) — BCC recipients, comma-separated emails",
                },
                "returns": ["success", "message_id", "thread_id", "to", "subject", "attachment_name", "error"],
            },
            "download_attachment": {
                "description": "Download an email attachment to local storage.",
                "args": {
                    "message_id": "str (required) — message ID containing attachment",
                    "attachment_id": "str (required) — attachment ID from email details",
                    "save_path": "str (required) — path to save file",
                },
                "returns": ["success", "filename", "save_path", "file_size", "error"],
                "can_be_derived_from": {"message_id": "search_emails"},
            },
            "search_emails_with_delivery_order_attachments": {
                "description": "Search Gmail for emails with PDF/Excel delivery order attachments. Downloads files to temp directory.",
                "args": {
                    "query": "str (optional) — Gmail search query (default: 'delivery order')",
                    "max_results": "int (optional) — max emails to search",
                    "download_attachments": "bool (optional) — download files (default: True)",
                    "temp_dir": "str (optional) — custom save directory",
                },
                "returns": ["success", "emails_with_attachments", "total_emails_found", "total_attachments_downloaded", "temp_directory", "error"],
            },
            "save_attachment_metadata": {
                "description": "Save attachment metadata to local SQLite database.",
                "args": {
                    "metadata": "dict (required) — {message_id, filename, file_path, from, subject, timestamp, mime_type, size}",
                    "db_path": "str (optional) — path to SQLite DB",
                },
                "returns": ["success", "inserted_id", "db_path", "error"],
            },
            "process_delivery_order_workflow": {
                "description": "End-to-end: search emails → download attachments → parse/transform → upload to Sheets → save metadata → create summary doc.",
                "args": {
                    "query": "str (optional) — Gmail search query",
                    "max_results": "int (optional) — emails to search",
                    "download_attachments": "bool (optional)",
                    "temp_dir": "str (optional)",
                    "save_to_db": "bool (optional)",
                    "upload_to_sheets": "bool (optional)",
                    "sheets_sheet_id": "str (optional) — Google Sheets ID",
                    "create_summary_doc": "bool (optional)",
                    "summary_doc_title": "str (optional)",
                },
                "returns": ["success", "processed", "search_summary", "document_url", "error"],
            },
        },
    },
    "docs_agent": {
        "description": "Create, edit, and read Google Docs documents. Supports template-based document creation.",
        "tools": {
            "create_doc": {
                "description": "Create a new Google Doc.",
                "args": {
                    "title": "str (required) — document name",
                },
                "returns": ["success", "document_id", "document_url", "title", "error"],
            },
            "list_my_docs": {
                "description": "Search user's Google Docs by name. ALWAYS use this first to resolve a document name/title to its ID before calling read_doc, edit_doc, update_doc, or add_text. Returns a list of matching documents with their IDs.",
                "args": {
                    "search_query": "str (optional) — document name or keyword to search",
                },
                "returns": ["success", "documents", "error"],
                "returns_detail": "documents is array of {id, name}",
            },
            "extract_template_format": {
                "description": "Analyze a template document to find placeholders.",
                "args": {
                    "template_document_id": "str (required)",
                },
                "returns": ["success", "placeholders", "error"],
                "can_be_derived_from": {"template_document_id": "list_my_docs"},
            },
            "create_from_my_template": {
                "description": "Create document from template with placeholder replacement. Keys must EXACTLY match placeholder names without brackets.",
                "args": {
                    "template_document_id": "str (required)",
                    "new_title": "str (required)",
                    "placeholders": "str (required) — JSON string of {PLACEHOLDER_NAME: value}",
                },
                "returns": ["success", "document_id", "url", "error"],
                "can_be_derived_from": {"template_document_id": "list_my_docs"},
            },
            "add_text": {
                "description": "Add text to an existing Google Doc.",
                "args": {
                    "document_id": "str (required) — document ID",
                    "text": "str (required) — text content to add",
                },
                "returns": ["success", "document_id", "document_url", "text_length", "error"],
                "can_be_derived_from": {"document_id": "list_my_docs"},
            },
            "create_doc_with_content": {
                "description": "Create a new Google Doc and populate it with content in one step. Accepts text directly or reads from a local file (PDF, txt). Prefer this over separate create_doc + add_text when content is available.",
                "args": {
                    "title": "str (required) — document name",
                    "text": "str (optional) — text content to add to the document",
                    "file_path": "str (optional) — local file path to read content from (PDF, txt). Use {{ uploaded_file.temp_path }} when user uploads a file.",
                },
                "returns": ["success", "document_id", "document_url", "title", "text_length", "error"],
                "note": "At least one of 'text' or 'file_path' must be provided. file_path takes precedence if both given.",
            },
            "add_text_from_file": {
                "description": "Read a local file (PDF, txt) and add its content to an existing Google Doc.",
                "args": {
                    "document_id": "str (required) — document ID",
                    "file_path": "str (required) — local file path to read and add. Use {{ uploaded_file.temp_path }}.",
                },
                "returns": ["success", "document_id", "document_url", "text_length", "error"],
                "can_be_derived_from": {"document_id": "create_doc"},
            },
            "read_doc": {
                "description": "Read text content from a Google Doc.",
                "args": {
                    "document_id": "str (required) — document ID to read",
                },
                "returns": ["success", "document_id", "content", "title", "error"],
                "can_be_derived_from": {"document_id": "list_my_docs: title"},
            },
            "edit_doc": {
                "description": "Find and replace specific text in a Google Doc. Use for targeted edits like fixing a paragraph or replacing a section.",
                "args": {
                    "document_id": "str (required) — document ID",
                    "old_text": "str (required) — exact text to find in the document",
                    "new_text": "str (required) — replacement text",
                },
                "returns": ["success", "document_id", "error"],
                "can_be_derived_from": {"document_id": "list_my_docs"},
            },
            "update_doc": {
                "description": "Replace the entire content of a Google Doc with new content. Use for full rewrites like grammar-fixed versions.",
                "args": {
                    "document_id": "str (required) — document ID",
                    "new_content": "str (required) — the complete new content for the document",
                },
                "returns": ["success", "document_id", "error"],
                "can_be_derived_from": {"document_id": "list_my_docs"},
            },
            "create_from_template_and_data_ids": {
                "description": "Create document from template and data files using Google Drive file IDs. Requires drive_agent.search_template_and_data first.",
                "triggers": ["template and data", "using X template and Y data"],
                "args": {
                    "template_file_id": "str (required) — Drive file ID of template",
                    "data_file_id": "str (required) — Drive file ID of data file",
                    "new_title": "str (required) — title for new document",
                    "output_format": "str (optional) — 'google_docs' (default) or 'pdf'",
                },
                "returns": ["success", "document_id", "document_url", "title", "format", "pdf_id", "pdf_url", "error"],
                "can_be_derived_from": {
                    "template_file_id": "drive_agent.search_template_and_data",
                    "data_file_id": "drive_agent.search_template_and_data",
                },
            },
        },
        "template_with_data_workflow": {
            "when_to_use": "When user mentions BOTH a template AND data/content files. ALWAYS use this 2-step workflow.",
            "workflow_steps": {
                "step_1": {
                    "agent": "drive_agent",
                    "tool": "search_template_and_data",
                    "purpose": "Search Google Drive for both template and data files",
                },
                "step_2": {
                    "agent": "docs_agent",
                    "tool": "create_from_template_and_data_ids",
                    "purpose": "Create document using the file IDs found by Drive Agent",
                },
            },
            "extraction_rules": {
                "template_name": "Look for keywords: 'template', 'format', 'use X template' - extract the file name",
                "data_name": "Look for keywords: 'data', 'content', 'use X document/file' - extract the file name",
                "new_title": "Look for: 'titled X', 'call it X', 'name it X', or infer from context",
            },
        },
    },
    "mapping_agent": {
        "description": "Parse LOCAL files (CSV/Excel/JSON), intelligently map columns, transform data structure. LIMITATION: Can only process files already on disk (user uploads, email attachments). Cannot download or read files from Google Drive — there is no Drive download tool.",
        "tools": {
            "parse_file": {
                "description": "Parse a LOCAL CSV/Excel/JSON file into structured data. Requires a local file path (e.g. from user upload or email attachment download). CANNOT read files from Google Drive by file ID.",
                "args": {
                    "file_content": "str (required) — local file path or raw content string (NOT a Google Drive file ID)",
                    "file_type": "str (required) — csv, xlsx, xls, excel, or json",
                },
                "returns": ["success", "columns", "row_count", "full_data", "sample_data"],
            },
            "extract_dates_from_all_rows": {
                "description": "Extract dates from ALL rows for date-based sheet matching.",
                "args": {
                    "data": "str (required) — JSON string from parse_file full_data",
                    "date_column_name": "str (optional) — default 'Date'",
                },
                "returns": ["success", "rows_with_dates", "total_rows", "date_column"],
                "returns_detail": "rows_with_dates is an array; each row has: row_index, date, date_formatted, row_data",
            },
            "smart_column_mapping": {
                "description": "AI-powered column mapping (skips temporal columns like Week/Date/Day).",
                "args": {
                    "source_columns": "List[str] (required)",
                    "sample_data": "list (optional)",
                    "skip_temporal": "bool (optional) — default true",
                },
                "returns": ["success", "mappings", "confidence_scores"],
            },
            "transform_data": {
                "description": "Transform data using column mappings.",
                "args": {
                    "source_data": "str (required) — JSON from parse_file",
                    "mappings": "dict (required) — column mappings",
                    "target_columns": "List[str] (optional)",
                },
                "returns": ["success", "transformed_data"],
            },
            "extract_date_from_data": {
                "description": "Extract date from parsed data (first row).",
                "args": {
                    "data": "str (required) — JSON from parse_file full_data",
                    "date_column_hints": "List[str] (optional) — candidate column names",
                },
                "returns": ["success", "date", "formatted_display"],
            },
            "parse_delivery_order_pdfs": {
                "description": "Parse PDF attachments as Production Materials Requisition Lists. Reads each PDF, detects valid templates by content, extracts header and line items. Reports rejected/non-template files. Accepts flat file path list OR the full response from search_emails_with_delivery_order_attachments (emails_with_attachments array).",
                "args": {
                    "file_paths": "List[str] or List[dict] (required) — flat list of local file paths, or emails_with_attachments array from gmail search",
                },
                "returns": ["success", "parsed_orders", "rejected_files", "total_parsed", "total_rejected", "error"],
                "returns_detail": "parsed_orders is array; each has: file, header {reference_number, date, category, allergen, cb_date, requested_by}, line_items [{item_code, item_description, qty, uom, cb_date}], warnings",
                "can_be_derived_from": {"file_paths": "gmail_agent.search_emails_with_delivery_order_attachments"},
            },
        },
    },
    "sheets_agent": {
        "description": "Google Sheets CRUD. Upload pre-transformed data from mapping_agent.",
        "tools": {
            "update_by_date_match": {
                "description": "Update Sheets rows by matching dates (update existing rows only, no append). Requires locally processed data.",
                "args": {
                    "sheet_id": "str (required) — Google Sheets ID",
                    "transformed_data": "str (required) — JSON array of row objects from mapping_agent.transform_data (NOT a file ID)",
                    "rows_with_dates": "list (required) — from mapping_agent.extract_dates_from_all_rows",
                    "sheet_name": "str (optional) — default 'DATA ENTRY'",
                    "date_column": "str (optional) — default 'Date'",
                },
                "returns": ["success", "rows_updated", "rows_not_found"],
                "can_be_derived_from": {"sheet_id": "drive_agent.search_files"},
            },
            "upload_mapped_data": {
                "description": "Upload/append pre-transformed data to a Google Sheet. Requires locally processed data — CANNOT accept a Google Drive file ID or URL as transformed_data.",
                "args": {
                    "sheet_id": "str (required) — Google Sheets ID",
                    "transformed_data": "str (required) — JSON array of row objects from mapping_agent.transform_data (NOT a file ID or file path)",
                    "sheet_name": "str (optional) — default 'Sheet1'",
                    "append_mode": "bool (optional) — true to append",
                },
                "returns": ["success", "rows_added"],
                "can_be_derived_from": {"sheet_id": "drive_agent.search_files"},
            },
            "create_sheet": {
                "description": "Create new Google Spreadsheet.",
                "args": {
                    "title": "str (required)",
                },
                "returns": ["success", "sheet_id", "sheet_url"],
            },
            "validate_delivery_sheet": {
                "description": "Validate that a Google Sheet matches the Production Materials Requisition List template. Checks headers (Date, Order Reference, Item Code, Item Description, QTY, UOM, CB Date, Requested by) and tabs (Food, non-food) with case-insensitive tab matching. Also verifies the caller has Editor (write) access. Returns specific errors for: sheet not found, no access, read-only access, or template mismatch.",
                "args": {
                    "sheet_id": "str (required) — Google Sheets ID or URL (URL is auto-parsed to extract ID)",
                },
                "returns": ["success", "is_valid", "headers_by_tab", "tabs_found", "matching_tabs", "mismatch_details", "error", "error_type"],
            },
            "preview_delivery_order_insertion": {
                "description": "Preview what will be written to the requisition sheet. Checks for duplicates (same Order Reference + Item Code), missing data, and rows that would be overridden. Returns preview for user approval.",
                "args": {
                    "sheet_id": "str (required) — Google Sheets ID",
                    "parsed_orders": "str (required) — JSON of parsed orders from mapping_agent.parse_delivery_order_pdfs",
                },
                "returns": ["success", "preview_rows", "total_new_rows", "duplicates", "duplicate_count", "warnings", "target_tabs", "message", "error"],
                "can_be_derived_from": {"parsed_orders": "mapping_agent.parse_delivery_order_pdfs"},
            },
            "write_delivery_order_data": {
                "description": "Write confirmed delivery order data to the requisition sheet. Appends rows to the correct tab (Food or non-food) based on category.",
                "args": {
                    "sheet_id": "str (required) — Google Sheets ID",
                    "parsed_orders": "str (required) — JSON of parsed orders from mapping_agent.parse_delivery_order_pdfs",
                },
                "returns": ["success", "rows_written", "tabs_used", "message", "error"],
                "can_be_derived_from": {"parsed_orders": "mapping_agent.parse_delivery_order_pdfs"},
            },
        },
    },
    "calendar_agent": {
        "description": "Manage Google Calendar: list, create, update, delete events. Supports Google Meet and multi-calendar.",
        "tools": {
            "list_events": {
                "description": "List upcoming calendar events.",
                "args": {
                    "time_min": "str (optional) — start time (YYYY-MM-DD or ISO)",
                    "time_max": "str (optional) — end time (YYYY-MM-DD or ISO)",
                    "max_results": "int (optional) — default 10",
                    "calendar_name": "str (optional) — default 'primary'",
                },
                "returns": ["success", "events", "count", "message"],
                "returns_detail": "events is array of {event_id, summary, start, end, location, attendees}",
            },
            "create_event": {
                "description": "Create calendar event. Auto-sends invitations to attendees.",
                "args": {
                    "summary": "str (required) — event title",
                    "start_time": "str (required) — supports natural language ('tomorrow 2pm', '12 AM')",
                    "end_time": "str (optional) — auto +1 hour if omitted",
                    "description": "str (optional)",
                    "location": "str (optional)",
                    "attendees": "list (optional) — email addresses",
                    "calendar_name": "str (optional)",
                    "add_meet_link": "bool (optional) — add Google Meet",
                },
                "returns": ["success", "event_id", "event_url", "meet_link", "message", "status", "conflict_id"],
            },
            "update_event": {
                "description": "Update existing event (title, time, location, attendees). Notifies attendees.",
                "args": {
                    "event_id": "str (optional) — use if already known from a previous step",
                    "event_name": "str (optional) — event title/name for auto-lookup. Preferred when user refers to event by name",
                    "new_summary": "str (optional)",
                    "new_start": "str (optional)",
                    "new_end": "str (optional)",
                    "new_description": "str (optional)",
                    "new_location": "str (optional)",
                    "new_attendees": "list (optional)",
                    "calendar_name": "str (optional)",
                },
                "returns": ["success", "event_id", "event_url", "changes", "message"],
                "note": "Pass event_name directly instead of listing events and guessing the index. The agent resolves the name to an ID internally.",
            },
            "delete_event": {
                "description": "Delete calendar event. Sends cancellation to attendees.",
                "args": {
                    "event_id": "str (optional) — use if already known from a previous step",
                    "event_name": "str (optional) — event title/name for auto-lookup. Preferred when user refers to event by name",
                    "calendar_name": "str (optional)",
                    "confirmed": "bool (always pass true — the orchestrator approval workflow handles user confirmation)",
                },
                "returns": ["success", "deleted", "requires_confirmation", "event_title", "confirmation_prompt", "message"],
                "note": "Pass event_name directly instead of listing events and guessing the index. The agent resolves the name to an ID internally.",
            },
            "confirm_delete_event": {
                "description": "Confirm deletion after delete_event returns requires_confirmation=true.",
                "args": {
                    "event_id": "str (optional) — use if already known from a previous step",
                    "event_name": "str (optional) — event title/name for auto-lookup",
                    "calendar_name": "str (optional)",
                },
                "returns": ["success", "deleted", "message"],
                "note": "Pass event_name directly instead of listing events and guessing the index. The agent resolves the name to an ID internally.",
            },
            "list_calendars": {
                "description": "List all user's calendars.",
                "args": {},
                "returns": ["success", "calendars", "message"],
                "returns_detail": "calendars is an array; each calendar has: id, name, primary",
            },
            "create_calendar": {
                "description": "Create a new Google Calendar.",
                "args": {
                    "calendar_name": "str (required)",
                    "description": "str (optional)",
                },
                "returns": ["success", "calendar_id", "message"],
            },
            "rename_calendar": {
                "description": "Rename an existing Google Calendar.",
                "args": {
                    "calendar_name": "str (required) — current calendar name",
                    "new_calendar_name": "str (required) — new name for the calendar",
                },
                "returns": ["success", "calendar_id", "message"],
            },
            "resolve_conflict": {
                "description": "Resolve scheduling conflict: moves conflicting event 1h later, then creates new event.",
                "args": {
                    "conflict_id": "str (required) — from create_event conflict_id",
                    "new_event": "dict (required) — {summary, start_time, end_time, attendees, description, location}",
                    "calendar_name": "str (optional)",
                },
                "returns": ["success", "event_id", "message"],
                "can_be_derived_from": {"conflict_id": "create_event"},
            },
        },
    },
    "drive_agent": {
        "description": "Google Drive: upload files, create folders, list/search files. All operations scoped to SafeExpress root folder.",
        "tools": {
            "upload_file": {
                "description": "Upload file to Google Drive.",
                "args": {
                    "file_path": "str (required) — local file path",
                    "filename": "str (required) — name for uploaded file",
                    "folder_path": "str (optional) — target folder (e.g., 'Operations/2024')",
                    "mime_type": "str (optional)",
                },
                "returns": ["success", "file_id", "file_url", "filename", "folder_path", "message", "error"],
            },
            "create_folder": {
                "description": "Create folder or nested folder structure. Auto-creates parent folders.",
                "args": {
                    "folder_path": "str (required) — path to create (e.g., 'Operations/2024/Reports')",
                },
                "returns": ["success", "folder_id", "folder_url", "folder_path", "message", "error"],
            },
            "list_folders": {
                "description": "List all folders with tree structure.",
                "args": {
                    "max_results": "int (optional) — limit number of folders returned",
                },
                "returns": ["success", "folders", "count", "tree", "message", "error"],
                "returns_detail": "folders is an array; each folder has: id, name, createdTime",
            },
            "list_files": {
                "description": "List files in a folder.",
                "args": {
                    "folder_path": "str (optional) — folder to list (default: root)",
                },
                "returns": ["success", "files", "count", "folder_path", "message", "error"],
                "returns_detail": "files is array of {id, name, mimeType, size, createdTime, webViewLink}",
            },
            "search_files": {
                "description": "Search files by name/keywords.",
                "args": {
                    "search_term": "str (required) — keywords to search",
                },
                "returns": ["success", "results", "count", "search_term", "message", "error"],
                "returns_detail": "results is an array; each result has: id, name, mimeType, size, createdTime, webViewLink",
            },
            "get_folder_info": {
                "description": "Get folder details (file count, subfolder count).",
                "args": {
                    "folder_path": "str (required)",
                },
                "returns": ["success", "folder_id", "folder_name", "file_count", "subfolder_count", "message", "error"],
            },
            "search_template_and_data": {
                "description": "Search Drive for BOTH a template file and a data file by name. Required before docs_agent.create_from_template_and_data_ids.",
                "args": {
                    "template_name": "str (required) — name/partial name of template file",
                    "data_name": "str (required) — name/partial name of data file",
                },
                "returns": ["success", "template_file_id", "template_file_name", "data_file_id", "data_file_name", "message", "error"],
            },
            "rename_file": {
                "description": "Rename a file OR folder in Google Drive. Works for both — Google Drive treats folders as files internally.",
                "args": {
                    "file_id": "str (required) — Drive file or folder ID to rename [via search_files: search_term]",
                    "new_name": "str (required) — new name for the file or folder",
                },
                "returns": ["success", "file_id", "new_name", "message", "error"],
                "can_be_derived_from": {"file_id": "search_files"},
            },
        },
    },
    "llm_tool": {
        "description": "Built-in LLM transformation tool. Runs locally in the orchestrator — no external agent call. Use this between read and write steps to transform content.",
        "tools": {
            "transform_text": {
                "description": "Transform text content using an LLM (e.g. fix grammar, summarize, translate, rewrite). Place between a read step and a write step. The instruction should describe the transformation; content is the text to transform.",
                "args": {
                    "instruction": "str (required) — what to do with the content (e.g. 'Fix all grammar and spelling errors')",
                    "content": "str (required) — the text to transform (use {{ variable }} from a previous read step)",
                },
                "returns": ["success", "transformed_content", "error"],
            },
        },
    },
}
