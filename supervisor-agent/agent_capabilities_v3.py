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
                "description": "Forward an email verbatim (HTML body + original attachments preserved) to another recipient.",
                "args": {
                    "message_id": "str (required) — message ID to forward",
                    "to": "str (required) — recipient email",
                    "forward_message": "str (optional) — additional message prepended before the forwarded content",
                },
                "returns": ["success", "forwarded_message_id", "thread_id", "to", "subject", "original_from", "forward_message", "attachments_forwarded", "error"],
                "returns_detail": "attachments_forwarded is a list of filenames re-attached from the original message (may be empty)",
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
        },
    },
    "docs_agent": {
        "description": "Create, edit, and read Google Docs documents. Supports template-based document creation.",
        "tools": {
            "create_doc": {
                "description": "Create a new Google Doc, optionally inside a specific Drive folder. If folder_id is given, the doc is reparented via Drive API after creation.",
                "args": {
                    "title": "str (required) — document name",
                    "folder_id": "str (optional) — Drive folder ID to place the doc in. Resolve via drive_agent.get_folder_info (strict) or drive_agent.create_folder (explicit create) in an earlier step. DO NOT use 'folder_path' — this tool does not accept that argument. If you only have a folder path, resolve it first via drive_agent.get_folder_info or drive_agent.create_folder and wire the folder_id output here via {{ folder_id }}.",
                },
                "returns": ["success", "document_id", "document_url", "title", "folder_id", "folder_moved", "folder_move_error", "error"],
                "can_be_derived_from": {"folder_id": "drive_agent.get_folder_info|drive_agent.create_folder"},
            },
            "list_my_docs": {
                "description": "Search user's Google Docs by name. ALWAYS use this first to resolve a document name/title to its ID before calling read_doc, edit_doc, update_doc, or add_text. Returns a list of matching documents with their IDs.",
                "args": {
                    "search_query": "str (optional) — document name or keyword to search",
                },
                "returns": ["success", "documents", "error"],
                "returns_detail": "documents is array of {id, name}",
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
                "description": "Create a new Google Doc and populate it with content in one step. Accepts text directly or reads from a local file (PDF, txt). Prefer this over separate create_doc + add_text when content is available. Supports folder_id to place the doc in a specific Drive folder.",
                "args": {
                    "title": "str (required) — document name",
                    "text": "str (optional) — text content to add to the document. DO NOT use 'content' — the argument name is 'text'.",
                    "file_path": "str (optional) — local file path to read content from (PDF, txt). Use {{ uploaded_file.temp_path }} when user uploads a file.",
                    "folder_id": "str (optional) — Drive folder ID to place the doc in. Resolve via drive_agent.get_folder_info (strict) or drive_agent.create_folder (explicit create) in an earlier step. DO NOT use 'folder_path' — this tool does not accept that argument. If you only have a folder path, resolve it first via drive_agent.get_folder_info or drive_agent.create_folder and wire the folder_id output here via {{ folder_id }}.",
                },
                "returns": ["success", "document_id", "document_url", "title", "text_length", "folder_id", "folder_moved", "folder_move_error", "error"],
                "note": "At least one of 'text' or 'file_path' must be provided. file_path takes precedence if both given.",
                "can_be_derived_from": {"folder_id": "drive_agent.get_folder_info|drive_agent.create_folder"},
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
            "create_from_uploaded_template": {
                "description": "Create a new Google Doc from an existing file in Google Drive. Converts .docx, .pdf, .txt files to editable Google Docs.",
                "triggers": ["find file", "create document from", "make a new document out of"],
                "args": {
                    "template_file_id": "str (required) — Drive file ID of the source file",
                    "new_title": "str (required) — title for new document",
                    "placeholders": "str (optional) — JSON string OR dict mapping placeholder → replacement value, e.g. '{\"[NAME]\": \"Acme Corp\"}'. A JSON string is parsed automatically by the impl; a dict is accepted as-is.",
                    "output_format": "str (optional) — 'google_docs' (default) or 'pdf'",
                },
                "returns": ["success", "document_id", "document_url", "title", "error"],
                "can_be_derived_from": {"template_file_id": "drive_agent.search_files"},
            },
            "analyze_uploaded_template": {
                "description": "Analyze a Google Doc template in Drive to extract its structure and detected placeholders (e.g. [NAME], {DATE}, <<COMPANY>>). Use this after drive_agent.upload_template / drive_agent.search_files to preview placeholders before calling create_from_uploaded_template.",
                "args": {
                    "template_file_id": "str (required) — Google Drive file ID of the uploaded template. Resolve via drive_agent.upload_template or drive_agent.search_files in a prior step.",
                },
                "returns": ["success", "template_id", "title", "content_blocks", "placeholders", "has_placeholders", "structure_type", "ready_for_use", "error"],
                "returns_detail": "placeholders is a list of detected placeholder names (strings). structure_type is 'structured' when placeholders are present, else 'unstructured'.",
                "can_be_derived_from": {"template_file_id": "drive_agent.upload_template|drive_agent.search_files"},
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
        "copy_existing_file_to_document": {
            "when_to_use": "When user wants to find an existing file in Google Drive and create a new Google Doc from it. Triggers on 'find file X and make a new document', 'create document from Y', 'convert Z to Google Doc'.",
            "workflow_steps": {
                "step_1": {
                    "agent": "drive_agent",
                    "tool": "search_files",
                    "purpose": "Search Google Drive for the specified file",
                },
                "step_2": {
                    "agent": "docs_agent",
                    "tool": "create_from_uploaded_template",
                    "purpose": "Create a new Google Doc from the found file",
                },
            },
            "extraction_rules": {
                "file_name": "Look for the file name to search for (e.g., 'project_brief', 'report.docx')",
                "new_title": "Look for the desired title of the new document (e.g., 'New_Document_Brief', 'Report Copy')",
            },
        },
    },
    "mapping_agent": {
        "description": "Parse LOCAL files (CSV/Excel/JSON), intelligently map columns, transform data structure. LIMITATION: Can only process files already on disk (user uploads, email attachments). Cannot download or read files from Google Drive — there is no Drive download tool.",
        "tools": {
            "parse_file": {
                "description": "Parse a LOCAL CSV/Excel/JSON file into structured data. Requires a local file path (e.g. from user upload, email attachment download, or drive_agent.download_file). CANNOT read files from Google Drive by file ID — download first via drive_agent.download_file and pass local_path here.",
                "args": {
                    "file_content": "str (required) — LOCAL file path (e.g. '/tmp/foo.csv', 'C:\\\\Users\\\\...'). The tool auto-detects path-vs-inline using a heuristic: starts with '/' or a Windows drive letter ('C:\\\\') → treated as a path; otherwise treated as raw content. Prefer pass-a-path (from attachment download or drive_agent.download_file). NOT a Google Drive file ID and NOT a Drive logical path.",
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
                    "sheet_id": "str (required) — Google Sheets ID or URL. If a full URL with a `?gid=` tab identifier is supplied and `sheet_name` is omitted, the tool resolves the correct tab from the gid.",
                    "transformed_data": "str (required) — JSON array of row objects from mapping_agent.transform_data (NOT a file ID or file path)",
                    "sheet_name": "str (optional) — tab name. When omitted, the tool resolves the tab via the URL's `gid=` parameter, or falls back to the first tab of the spreadsheet.",
                    "append_mode": "bool (optional) — true to append",
                },
                "returns": ["success", "rows_added", "sheet_name"],
                "can_be_derived_from": {"sheet_id": "drive_agent.search_files"},
            },
            "create_sheet": {
                "description": "Create a new Google Spreadsheet, optionally inside a specific Drive folder. If folder_id is given, the sheet is reparented via Drive API after creation.",
                "args": {
                    "title": "str (required) — spreadsheet name",
                    "sheet_names": "List[str] (optional) — tab names (default: ['Sheet1']). DO NOT use 'tabs' — the argument name is 'sheet_names'.",
                    "initial_data": "List[List[Any]] (optional) — 2D rows to populate the first sheet. DO NOT use 'rows' — the argument name is 'initial_data'.",
                    "folder_id": "str (optional) — Drive folder ID to place the sheet in. Resolve via drive_agent.get_folder_info (strict) or drive_agent.create_folder (explicit create) in an earlier step. DO NOT use 'folder_path' — this tool does not accept that argument. If you only have a folder path, resolve it first via drive_agent.get_folder_info or drive_agent.create_folder and wire the folder_id output here via {{ folder_id }}.",
                },
                "returns": ["success", "sheet_id", "sheet_url", "title", "folder_id", "folder_moved", "warning", "message"],
                "can_be_derived_from": {"folder_id": "drive_agent.get_folder_info|drive_agent.create_folder"},
            },
            "read_sheet": {
                "description": "Read cell values from a Google Sheet. Accepts the spreadsheet ID OR a full spreadsheet URL — URLs are auto-parsed to extract the ID.",
                "args": {
                    "sheet_id": "str (required) — Google Sheets ID or URL (https://docs.google.com/spreadsheets/d/<id>/edit). A `?gid=` tab identifier in the URL is used when range_name is omitted or uses the legacy 'Sheet1' default.",
                    "range_name": "str (optional) — A1 notation range (e.g. 'Sheet1', 'Sheet1!A1:D10'). When omitted (or when the prefix is the legacy 'Sheet1' default), the tab is resolved from the URL's `gid=` parameter or falls back to the first tab. Explicit non-default tab prefixes like 'Orders!A1:D10' are honored as-is.",
                },
                "returns": ["success", "data", "row_count", "column_count", "range", "message", "error"],
                "returns_detail": "data is a 2D list of cell values (strings).",
                "can_be_derived_from": {"sheet_id": "drive_agent.search_files"},
            },
            "update_sheet": {
                "description": "Overwrite a specific range in a Google Sheet with a 2D array of values. Accepts the spreadsheet ID OR a full spreadsheet URL.",
                "args": {
                    "sheet_id": "str (required) — Google Sheets ID or URL. A `?gid=` tab identifier in the URL is honored when range_name uses the legacy 'Sheet1' prefix.",
                    "range_name": "str (required) — A1 notation range to overwrite (e.g. 'Sheet1!A1:D10'). If the prefix is exactly the legacy 'Sheet1' default it is rewritten to the tab identified by the URL's `gid=` parameter. Other explicit tab prefixes are honored as-is.",
                    "data": "List[List[Any]] (required) — 2D rows to write. DO NOT use 'values' — the argument name is 'data'.",
                },
                "returns": ["success", "updated_cells", "updated_range", "range", "error"],
                "can_be_derived_from": {"sheet_id": "drive_agent.search_files"},
            },
            "append_rows": {
                "description": "Append rows to the END of a sheet tab (does not overwrite existing rows). Use update_sheet or update_by_date_match for in-place edits. Accepts the spreadsheet ID OR a full spreadsheet URL.",
                "args": {
                    "sheet_id": "str (required) — Google Sheets ID or URL. A `?gid=` tab identifier in the URL is used when sheet_name is omitted.",
                    "data": "List[List[Any]] (required) — 2D rows to append. DO NOT use 'values' or 'rows' — the argument name is 'data'.",
                    "sheet_name": "str (optional) — tab name to append to. When omitted, the tab is resolved from the URL's `gid=` parameter, or falls back to the first tab of the spreadsheet. Pass an explicit name to override.",
                },
                "returns": ["success", "rows_added", "range_updated", "updated_cells", "sheet_name", "message", "error"],
                "can_be_derived_from": {"sheet_id": "drive_agent.search_files"},
            },
            "get_sheet_metadata": {
                "description": "Introspect a spreadsheet — returns title, tab names, row/column counts per tab. Use before read_sheet/update_sheet when the tab name or size is unknown. Accepts the spreadsheet ID OR a full spreadsheet URL.",
                "args": {
                    "sheet_id": "str (required) — Google Sheets ID or URL",
                },
                "returns": ["success", "spreadsheet_id", "title", "sheets", "sheet_count", "error"],
                "returns_detail": "sheets is an array of {sheet_id, title, index, row_count, column_count}.",
                "can_be_derived_from": {"sheet_id": "drive_agent.search_files"},
            },
            "get_sheet_headers": {
                "description": "Return the header row (row 1) of a specific tab. Useful before column-mapping or before update_sheet to align incoming data. Accepts the spreadsheet ID OR a full spreadsheet URL.",
                "args": {
                    "sheet_id": "str (required) — Google Sheets ID or URL. A `?gid=` tab identifier in the URL is used when sheet_name is omitted.",
                    "sheet_name": "str (optional) — tab name. When omitted, the tab is resolved from the URL's `gid=` parameter, or falls back to the first tab of the spreadsheet.",
                },
                "returns": ["success", "headers", "column_count", "sheet_name", "error"],
                "returns_detail": "headers is a list of header strings from row 1.",
                "can_be_derived_from": {"sheet_id": "drive_agent.search_files"},
            },
            "clear_sheet": {
                "description": "Clear cell values in a range (structure/formatting preserved — only values are wiped). Destructive for data. Accepts the spreadsheet ID OR a full spreadsheet URL.",
                "args": {
                    "sheet_id": "str (required) — Google Sheets ID or URL. A `?gid=` tab identifier in the URL is used when range_name is omitted or uses the legacy 'Sheet1' default.",
                    "range_name": "str (optional) — A1 notation range to clear. When omitted (or when the prefix is the legacy 'Sheet1' default), the tab is resolved from the URL's `gid=` parameter or falls back to the first tab.",
                },
                "returns": ["success", "cleared_range", "range", "message", "error"],
                "can_be_derived_from": {"sheet_id": "drive_agent.search_files"},
            },
            "validate_delivery_sheet": {
                "description": "Validate that a Google Sheet matches the Production Materials Requisition List template. Checks headers (Date, Order Reference, Item Code, Item Description, QTY, UOM, CB Date, Requested by) and tabs (Food, non-food) with case-insensitive tab matching. Also verifies the caller has Editor (write) access. Returns specific errors for: sheet not found, no access, read-only access, or template mismatch.",
                "args": {
                    "sheet_id": "str (required) — Google Sheets ID or URL (URL is auto-parsed to extract ID)",
                },
                "returns": ["success", "is_valid", "headers_by_tab", "tabs_found", "matching_tabs", "mismatch_details", "error", "error_type"],
                "can_be_derived_from": {"sheet_id": "drive_agent.search_files"},
            },
            "preview_delivery_order_insertion": {
                "description": "Preview what will be written to the requisition sheet. Checks for duplicates (same Order Reference + Item Code), missing data, and rows that would be overridden. Returns preview for user approval.",
                "args": {
                    "sheet_id": "str (required) — Google Sheets ID",
                    "parsed_orders": "list|str (required) — parsed_orders output from mapping_agent.parse_delivery_order_pdfs. Pass the variable directly ({{ parsed_orders }}); accepts a native list, JSON string, or Python repr string.",
                },
                "returns": ["success", "preview_rows", "total_new_rows", "duplicates", "duplicate_count", "warnings", "target_tabs", "message", "error"],
                "can_be_derived_from": {
                    "parsed_orders": "mapping_agent.parse_delivery_order_pdfs",
                    "sheet_id": "drive_agent.search_files",
                },
            },
            "write_delivery_order_data": {
                "description": "Write confirmed delivery order data to the requisition sheet. Appends rows to the correct tab (Food or non-food) based on category.",
                "args": {
                    "sheet_id": "str (required) — Google Sheets ID",
                    "parsed_orders": "list|str (required) — parsed_orders output from mapping_agent.parse_delivery_order_pdfs. Pass the variable directly ({{ parsed_orders }}); accepts a native list, JSON string, or Python repr string.",
                },
                "returns": ["success", "rows_written", "tabs_used", "message", "error"],
                "can_be_derived_from": {
                    "parsed_orders": "mapping_agent.parse_delivery_order_pdfs",
                    "sheet_id": "drive_agent.search_files",
                },
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
                    "new_start": "str (optional) — supports natural language ('tomorrow 2pm')",
                    "new_end": "str (optional)",
                    "new_description": "str (optional) — to attach a doc/sheet link, pass the URL string here",
                    "new_location": "str (optional)",
                    "new_attendees": "list (optional) — email addresses",
                    "calendar_name": "str (optional)",
                },
                "returns": ["success", "event_id", "event_url", "changes", "message"],
                "note": "ARG NAMING: mutation fields ALL require the `new_` prefix — new_summary, new_start, new_end, new_description, new_location, new_attendees. Do NOT reuse create_event's bare names (summary / start_time / end_time / description / location / attendees / emails) — those are the create-side names and they will be silently ignored here (the event returns `changes: []` with no actual update). TARGETING: pass event_name directly instead of listing events and guessing the index; the agent resolves name → id internally.",
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
        "description": "Google Drive: upload, create folders, list/search/move/rename files across the user's entire Drive (My Drive root by default). Full `auth/drive` scope — no sandboxing.",
        "tools": {
            "upload_file": {
                "description": "Upload a LOCAL file to Google Drive. Accepts either folder_id (preferred when known) or folder_path (find-or-created at Drive root). Defaults to My Drive root.",
                "args": {
                    "file_path": "str (required) — LOCAL file path on disk (e.g. '/tmp/foo.csv', 'C:\\\\Users\\\\...'). NOT a Drive file ID and NOT a Drive logical path. Use {{ uploaded_file.temp_path }} for user-uploaded files.",
                    "filename": "str (required) — name for uploaded file",
                    "folder_id": "str (optional) — destination folder Drive ID (preferred when known from a prior step)",
                    "folder_path": "str (optional) — destination folder path (e.g., 'Operations/2024'). Find-or-created.",
                    "mime_type": "str (optional)",
                },
                "returns": ["success", "file_id", "file_url", "filename", "folder_id", "folder_path", "message", "error"],
                "can_be_derived_from": {"folder_id": "drive_agent.get_folder_info|drive_agent.create_folder"},
            },
            "upload_template": {
                "description": "Upload a template file (PDF, DOCX, DOC, TXT) from local disk to the 'Templates' folder in Google Drive. PDFs/DOCs/DOCX are auto-converted to editable Google Docs format unless preserve_format=True. Returns the new Drive file_id so a follow-up docs_agent.analyze_uploaded_template / create_from_uploaded_template step can consume it.",
                "args": {
                    "file_path": "str (required) — LOCAL file path on disk (use {{ uploaded_file.temp_path }} when the user uploaded a file)",
                    "template_name": "str (required) — name for the template in Drive",
                    "file_type": "str (optional) — MIME type override; auto-detected from extension when omitted",
                    "preserve_format": "bool (optional, default false) — keep original PDF/DOCX format instead of converting to Google Docs",
                },
                "returns": ["success", "file_id", "file_url", "template_name", "original_format", "current_format", "is_editable", "folder_path", "message", "error"],
            },
            "read_file_content": {
                "description": "Read text content from a Drive file. Accepts (a) file_id (preferred when known — resolve via drive_agent.search_files), or (b) drive_path (a Drive logical path like 'Data/customer_info.txt' — NOT a local OS path, and NOT a full Drive URL). Supports text, PDFs (extracted via PyPDF2), Google Docs (exported as text), and spreadsheets (exported as CSV).",
                "args": {
                    "file_id": "str (optional) — Google Drive file ID. Preferred when available from a prior search_files step.",
                    "drive_path": "str (optional) — Drive logical path, e.g. 'Data/customer_info.txt'. Final segment is the filename; leading segments are folders resolved from Drive root. Provide this OR file_id (not both).",
                },
                "returns": ["success", "file_id", "file_name", "mime_type", "content", "content_length", "message", "error"],
                "note": "Exactly one of file_id or drive_path must be provided. drive_path is a LOGICAL path inside Drive, NOT a local OS file path — for local files, use drive_agent.upload_file or mapping_agent.parse_file instead.",
                "can_be_derived_from": {"file_id": "drive_agent.search_files"},
            },
            "create_folder": {
                "description": "Find-or-create a folder (or nested folder chain) anywhere in the user's Drive. Idempotent — repeated calls with the same path return the same folder ID instead of duplicating. Use this ONLY when the user explicitly asks to create a folder, OR when a creation flow implies folder creation (e.g., 'upload X to NewFolder' and NewFolder doesn't exist yet and user consents).",
                "args": {
                    "folder_path": "str (required) — path to create (e.g., 'Operations/2024/Reports')",
                    "parent_folder_id": "str (optional) — anchor the chain under this folder ID instead of Drive root",
                },
                "returns": ["success", "folder_id", "folder_url", "folder_path", "message", "error"],
                "can_be_derived_from": {"parent_folder_id": "drive_agent.get_folder_info"},
            },
            "list_folders": {
                "description": "List folders under a parent (defaults to My Drive root).",
                "args": {
                    "parent_folder_id": "str (optional) — folder ID to list under (default: Drive root)",
                    "max_results": "int (optional) — limit number of folders returned",
                    "max_depth": "int (optional) — tree depth (default 3)",
                },
                "returns": ["success", "folders", "count", "tree", "message", "error"],
                "returns_detail": "folders is an array; each folder has: id, name, createdTime, parents",
            },
            "list_files": {
                "description": "List files inside a Drive folder (by folder_id or folder_path). Defaults to My Drive root when neither is provided.",
                "args": {
                    "folder_id": "str (optional) — folder Drive ID (preferred when known)",
                    "folder_path": "str (optional) — folder path relative to Drive root (resolved to ID)",
                },
                "returns": ["success", "files", "count", "folder_id", "folder_path", "message", "error"],
                "returns_detail": "files is array of {id, name, mimeType, size, createdTime, webViewLink}",
                "can_be_derived_from": {"folder_id": "drive_agent.get_folder_info"},
            },
            "search_files": {
                "description": "Search files by name across the user's whole Drive (all folders). Returns files the user has access to. Optional createdTime bounds scope results to a date window — e.g. 'files created this month', 'this quarter', 'since my last review'.",
                "args": {
                    "search_term": "str (required) — keywords to match against file NAMES (uses Drive `name contains` semantics, case-insensitive). Does NOT match inside file bodies/content. Partial matches are OK, e.g. search_term='Q1' matches 'Q1 Budget.xlsx'.",
                    "created_after": "str (optional) — ISO-8601 date ('YYYY-MM-DD') or datetime ('YYYY-MM-DDTHH:MM:SS'). INCLUSIVE lower bound on createdTime. Compute bounds yourself from today_date (e.g. 'this month' → first-of-current-month). Drive does NOT accept natural-language strings like 'this month'.",
                    "created_before": "str (optional) — ISO-8601 date or datetime. EXCLUSIVE upper bound on createdTime. Pair with created_after to form a half-open [after, before) window. For 'April 2026': created_after='2026-04-01' + created_before='2026-05-01' — no double-counting at month boundaries.",
                },
                "returns": ["success", "results", "count", "search_term", "message", "error"],
                "returns_detail": "results is an array; each result has: id, name, mimeType, size, createdTime, webViewLink, parents",
                "note": "Date bounds must be pre-computed by the planner from today_date and passed as ISO strings. The agent will NOT parse natural-language like 'this month' / 'last week' / 'yesterday'. Malformed dates return success=false with a clear error; no Drive call is made.",
            },
            "get_folder_info": {
                "description": "STRICT folder lookup by path — resolves a folder_path (e.g. 'Finance/Q1') to its ID and returns summary stats. Does NOT create missing folders; returns an error if the folder is not found. Use this BEFORE any create/upload/move step when the user specified a folder but did not explicitly ask to create it.",
                "args": {
                    "folder_path": "str (required)",
                },
                "returns": ["success", "folder_id", "folder_name", "folder_path", "file_count", "subfolder_count", "message", "error"],
            },
            "move_file": {
                "description": "Move (reparent) a Drive file or folder to another folder. Reparents cleanly — removes all existing parents and adds the destination. Requires the file/folder ID (use search_files or list_files to resolve a name → ID first). By default, fails fast if the destination folder_path does not exist — call create_folder first when folder creation is intended.",
                "args": {
                    "file_id": "str (required) — Drive file or folder ID to move [via search_files: search_term]",
                    "folder_id": "str (optional) — destination folder Drive ID (preferred when known)",
                    "folder_path": "str (optional) — destination folder path, e.g. 'Finance/Q1'",
                    "create_if_missing": "bool (optional, default false) — when folder_path is used, auto-create missing segments. Leave false so typos fail loud; use create_folder explicitly when new folders are intended.",
                },
                "returns": ["success", "file_id", "file_name", "file_url", "destination_folder_id", "destination_folder_path", "new_parents", "message", "error"],
                "can_be_derived_from": {
                    "file_id": "drive_agent.search_files|drive_agent.list_files",
                    "folder_id": "drive_agent.get_folder_info|drive_agent.create_folder",
                },
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
            "download_file": {
                "description": "Download a Google Drive file to a SERVER-SIDE temp path and return its local_path. Unblocks chains like 'Drive file → mapping_agent.parse_file'. Native Google files (Docs/Sheets/Slides/Drawings) are auto-exported to docx/xlsx/pptx/png; binary files are streamed as-is.",
                "args": {
                    "file_id": "str (optional) — Drive file ID (or a Drive/Docs/Sheets URL, auto-normalized). Prefer this when known from a prior search_files step.",
                    "drive_path": "str (optional) — Drive LOGICAL path (e.g. 'Data/customer_info.txt'). Resolved like drive_agent.read_file_content. NOT a local OS path.",
                },
                "returns": ["success", "local_path", "file_id", "file_name", "mime_type", "exported_as", "size_bytes", "message", "error"],
                "note": "Exactly one of file_id or drive_path must be provided. Caller (next step) consumes local_path directly; temp dir lifecycle is per-call.",
                "can_be_derived_from": {"file_id": "drive_agent.search_files"},
            },
            "copy_file": {
                "description": "Duplicate an existing Drive file under a new name (and optional destination folder). Uses the Drive copy API — no local round-trip. Native Google files stay native; binary files stay binary. Use for 'duplicate this template' flows before edits.",
                "args": {
                    "source_file_id": "str (required) — Drive ID (or URL) of the file to copy [via drive_agent.search_files: search_term]",
                    "new_name": "str (required) — name for the copied file",
                    "folder_id": "str (optional) — destination folder Drive ID (preferred when known). (DO NOT use folder_path when a folder_id is available from a prior create_folder / get_folder_info step; wire the ID via output_variables + {{ folder_id }}.)",
                    "folder_path": "str (optional) — destination folder path, e.g. 'Operations/2024'. Find-or-created. Ignored when folder_id is supplied.",
                },
                "returns": ["success", "file_id", "file_url", "new_name", "folder_id", "folder_path", "message", "error"],
                "note": "When neither folder_id nor folder_path is provided, the copy lands in the source file's existing parent folder.",
                "can_be_derived_from": {
                    "source_file_id": "drive_agent.search_files",
                    "folder_id": "drive_agent.get_folder_info|drive_agent.create_folder",
                },
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
