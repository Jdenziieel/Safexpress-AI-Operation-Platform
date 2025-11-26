"""
Agent Capabilities Configuration V2

This file defines the tools and capabilities of each specialized agent in the system.
Each agent has a description, and a list of tools with their arguments and return values.

VERSION 2 ENHANCEMENTS:
- Added "can_be_derived_from" metadata for tools requiring technical IDs
- Enables smart field inference for multi-step workflows
- Supports conversational UX improvements (ask for search criteria instead of IDs)
"""

agent_capabilities = {
    "gmail_agent": {
        "description": "Comprehensive Gmail operations: read, search, draft, send, reply, manage labels, download attachments, and view conversation threads.",
        "tools": {
            "search_emails": {
                "description": "Search emails in Gmail matching a query with full message bodies and attachment info. Supports date filters (after:YYYY/MM/DD, before:YYYY/MM/DD), sender (from:), subject, has:attachment, is:unread, etc.",
                "args": {
                    "query": "str (required) — search query (e.g., 'from:john@example.com', 'after:{{ yesterday_date }}', 'subject:meeting has:attachment')",
                    "max_results": "int (required) — number of emails to fetch",
                    "label_ids": "List[str] (optional) — filter by specific label IDs (e.g., ['INBOX', 'UNREAD'])",
                },
                "returns": {
                    "success": "bool — whether search was successful",
                    "emails": "list — array of email objects, each containing:",
                    "emails[].message_id": "str — unique message ID",
                    "emails[].thread_id": "str — conversation thread ID",
                    "emails[].from": "str — sender email address",
                    "emails[].subject": "str — email subject",
                    "emails[].date": "str — email date from headers",
                    "emails[].internal_date": "str — Gmail internal timestamp (milliseconds since epoch)",
                    "emails[].label_ids": "list — array of label IDs (e.g., ['INBOX', 'UNREAD', 'IMPORTANT'])",
                    "emails[].body": "str — full email body text (plain text preferred, falls back to HTML or snippet)",
                    "emails[].has_attachments": "bool — whether email has attachments",
                    "emails[].attachments": "list — array of attachment objects with filename, attachment_id, mime_type, size",
                    "count": "int — number of emails returned",
                    "query": "str — the search query that was used",
                    "error": "str — error message (null if successful)",
                },
            },
            "get_thread_conversation": {
                "description": "Retrieves all messages in an email thread/conversation with full bodies",
                "args": {
                    "thread_id": "str (required) — thread ID from search_emails or read_recent_emails"
                },
                "returns": {
                    "success": "bool — whether retrieval was successful",
                    "thread_id": "str — the thread ID",
                    "message_count": "int — number of messages in thread",
                    "messages": "list — array of full message objects with id, from, to, subject, date, body",
                    "all_message_ids": "str — comma-separated list of all message IDs in thread",
                    "error": "str — error message (null if successful)",
                },
                "can_be_derived_from": {
                    "thread_id": {
                        "source_tool": "search_emails",
                    }
                }
            },
            "reply_to_email": {
                "description": "Replies to an email in its thread (maintains conversation)",
                "args": {
                    "message_id": "str (required) — message ID of email to reply to",
                    "reply_body": "str (required) — reply message content",
                },
                "returns": {
                    "success": "bool — whether reply was sent successfully",
                    "original_message_id": "str — the message ID that was replied to",
                    "reply_message_id": "str — message ID of the sent reply",
                    "thread_id": "str — thread ID of the conversation",
                    "to": "str — recipient email address",
                    "subject": "str — reply subject",
                    "error": "str — error message (null if successful)",
                },
                "can_be_derived_from": {
                    "message_id": {
                        "source_tool": "search_emails",

                    }
                }
            },
            "forward_email": {
                "description": "Forwards an email to another recipient with optional message",
                "args": {
                    "message_id": "str (required) — message ID of email to forward",
                    "to": "str (required) — recipient email address to forward to",
                    "forward_message": "str (optional) — additional message to include with the forward",
                },
                "returns": {
                    "success": "bool — whether forward was sent successfully",
                    "original_message_id": "str — the message ID that was forwarded",
                    "forwarded_message_id": "str — message ID of the forwarded email",
                    "thread_id": "str — thread ID of the new forward",
                    "to": "str — recipient email address",
                    "subject": "str — forward subject (Fwd: ...)",
                    "original_from": "str — original sender of the forwarded email",
                    "error": "str — error message (null if successful)",
                },
                "can_be_derived_from": {
                    "message_id": {
                        "source_tool": "search_emails",
                        
                    }
                }
            },
            "create_draft_email": {
                "description": "Creates a draft email without sending it (safer than send_email)",
                "args": {
                    "to": "str (required) — recipient email address",
                    "subject": "str (required) — subject line",
                    "body": "str (required) — email body content",
                },
                "returns": {
                    "success": "bool — whether draft was created successfully",
                    "draft_id": "str — Gmail top-level draft ID for sending later with send_draft_email",
                    "message_id": "str — underlying message ID",
                    "to": "str — recipient email address",
                    "subject": "str — email subject",
                    "error": "str — error message (null if successful)",
                },
            },
            "send_draft_email": {
                "description": "Sends a previously created draft email by draft ID",
                "args": {
                    "draft_id": "str (required) — draft_id from create_draft_email or search_drafts"
                },
                "returns": {
                    "success": "bool — whether draft was sent successfully",
                    "draft_id": "str — top-level draft ID",
                    "message_id": "str — Gmail message ID of sent email",
                    "thread_id": "str — thread ID of the email",
                    "to": "str — recipient email address",
                    "subject": "str — email subject",
                    "error": "str — error message (null if successful)",
                },
                "can_be_derived_from": {
                    "draft_id": {
                        "source_tool": "search_drafts",
                        
                    }
                }
            },
            "search_drafts": {
                "description": "Search for draft emails in Gmail. Returns drafts with nested message details matching Gmail API format.",
                "args": {
                    "query": "str (optional) — Gmail search query (e.g., 'subject:meeting', 'to:john@example.com'). Empty string searches all drafts.",
                    "max_results": "int (optional) — maximum number of drafts to return (default: 10)",
                },
                "returns": {
                    "success": "bool — whether search was successful",
                    "count": "int — number of drafts found",
                    "drafts": "list — array of draft objects, each containing: {draft_id: draft_id, message: {id, threadId, labelIds, to, subject, body, snippet, date}}",
                    "query": "str — search query used",
                    "error": "str — error message (null if successful)",
                },
                "draft_structure": {
                    "id": "str — top-level draft ID (use this with send_draft_email)",
                    "message": {
                        "id": "str — underlying message ID",
                        "threadId": "str — thread ID",
                        "labelIds": "list — array of label IDs (e.g., ['DRAFT'])",
                        "to": "str — recipient email address",
                        "subject": "str — email subject",
                        "body": "str — full email body text",
                        "snippet": "str — first 100 characters of body as preview",
                        "date": "str — date string",
                    },
                },
                "usage_note": "Use drafts[i].id with send_draft_email to send a draft. Access message details via drafts[i].message.subject, drafts[i].message.to, etc.",
            },
            "send_email_with_attachment": {
                "description": "Sends an email with a file attachment",
                "args": {
                    "to": "str (required) — recipient email address",
                    "subject": "str (required) — subject line",
                    "body": "str (required) — email body content",
                    "file_path": "str (required) — absolute path to the file to attach",
                },
                "returns": {
                    "success": "bool — whether email was sent successfully",
                    "message_id": "str — Gmail message ID",
                    "thread_id": "str — thread ID of the email",
                    "to": "str — recipient email address",
                    "subject": "str — email subject",
                    "attachment_name": "str — name of attached file",
                    "error": "str — error message (null if successful)",
                },
            },
            "download_attachment": {
                "description": "Downloads an email attachment to local storage",
                "args": {
                    "message_id": "str (required) — message ID of email containing attachment",
                    "attachment_id": "str (required) — attachment ID from email details",
                    "save_path": "str (required) — absolute path where file should be saved",
                },
                "returns": {
                    "success": "bool — whether download was successful",
                    "message_id": "str — the message ID",
                    "thread_id": "str — thread ID of the email",
                    "attachment_id": "str — the attachment ID",
                    "filename": "str — name of downloaded file",
                    "save_path": "str — full path where file was saved",
                    "file_size": "int — size in bytes",
                    "error": "str — error message (null if successful)",
                },
                "can_be_derived_from": {
                    "message_id": {
                        "source_tool": "search_emails",
                        
                    }
                },
            },
        },
    },
    "mapping_agent": {
        "description": "Parse files (CSV/Excel/JSON), intelligently map columns, validate mappings, transform data structure. NO Google Sheets operations.",
        "tools": {
            "parse_file": {
                "description": "Parse CSV/Excel/JSON files into structured data",
                "args": {
                    "file_content": "str (required) — file path or content",
                    "file_type": "str (required) — csv, xlsx, xls, excel, or json",
                },
                "returns": {
                    "success": "bool",
                    "columns": "list — column names",
                    "row_count": "int",
                    "full_data": "str — JSON string of all data",
                    "sample_data": "list — first 5 rows for analysis",
                },
            },
            "extract_dates_from_all_rows": {
                "description": "Extract dates from ALL rows for date-based matching",
                "args": {
                    "data": "str (required) — JSON string from parse_file's full_data",
                    "date_column_name": "str (optional) — default 'Date'",
                },
                "returns": {
                    "success": "bool",
                    "rows_with_dates": "list — [{row_index, date, date_formatted, row_data}]",
                    "total_rows": "int",
                    "date_column": "str",
                },
            },
            "smart_column_mapping": {
                "description": "AI-powered intelligent column mapping (skips temporal columns)",
                "args": {
                    "source_columns": "List[str] (required)",
                    "sample_data": "list (optional)",
                    "skip_temporal": "bool (optional) — default true, skips Wee/Week/Date/Day",
                },
                "returns": {
                    "success": "bool",
                    "mappings": "dict — source to target column mappings",
                    "confidence_scores": "dict",
                },
            },
            "transform_data": {
                "description": "Transform data using column mappings (MAIN TOOL)",
                "args": {
                    "source_data": "str (required) — JSON string from parse_file",
                    "mappings": "dict (required) — column mappings",
                    "target_columns": "List[str] (optional)",
                },
                "returns": {
                    "success": "bool",
                    "transformed_data": "str — JSON string ready for sheets_agent",
                },
            },
            "extract_date_from_data": {
                "description": "Extract date from parsed file data (first row only)",
                "args": {
                    "data": "str (required) — JSON string from parse_file's full_data",
                    "date_column_hints": "List[str] (optional) — column names that might contain dates",
                },
                "returns": {
                    "success": "bool",
                    "date": "str — extracted date in YYYY-MM-DD format",
                    "formatted_display": "str — human-readable format (DD-MMM-YYYY)",
                },
            },
        },
    },
    "sheets_agent": {
        "description": "Google Sheets CRUD operations. Upload pre-transformed data from mapping_agent.",
        "tools": {
            "update_by_date_match": {
                "description": "Update Google Sheets rows by matching dates (NO append, only update existing rows)",
                "args": {
                    "sheet_id": "str (required) — Google Sheets ID",
                    "transformed_data": "str (required) — JSON from mapping_agent.transform_data",
                    "rows_with_dates": "list (required) — from mapping_agent.extract_dates_from_all_rows",
                    "sheet_name": "str (optional) — default 'DATA ENTRY'",
                    "date_column": "str (optional) — default 'Date'",
                },
                "returns": {
                    "success": "bool",
                    "rows_updated": "int — number of rows successfully updated",
                    "rows_not_found": "list — dates in Excel but not in Sheets",
                },
                "can_be_derived_from": {
                    "sheet_id": {
                        "source_tool": "drive_agent.search_files",
                        
                    }
                }
            },
            "upload_mapped_data": {
                "description": "Upload/append pre-transformed data (USE update_by_date_match FOR DATE MATCHING)",
                "args": {
                    "sheet_id": "str (required) — Google Sheets ID",
                    "transformed_data": "str (required) — JSON from mapping_agent.transform_data",
                    "sheet_name": "str (optional) — default 'Sheet1'",
                    "append_mode": "bool (optional) — true to append",
                },
                "returns": {
                    "success": "bool",
                    "rows_added": "int",
                },
                "can_be_derived_from": {
                    "sheet_id": {
                        "source_tool": "drive_agent.search_files",
                        
                    }
                }
            },
            "create_sheet": {
                "description": "Create new Google Spreadsheet",
                "args": {
                    "title": "str (required)",
                },
                "returns": {
                    "success": "bool",
                    "sheet_id": "str",
                    "sheet_url": "str",
                },
            },
        },
    },
    "calendar_agent": {
        "description": "Manage Google Calendar events: list, create, update, delete events and calendars. Supports Google Meet integration and multi-calendar management.",
        "tools": {
            "list_events": {
                "description": "List upcoming calendar events with structured output",
                "args": {
                    "time_min": "str (optional) - Start time (YYYY-MM-DD or ISO)",
                    "time_max": "str (optional) - End time (YYYY-MM-DD or ISO)",
                    "max_results": "int (optional) - Number of events (default: 10)",
                    "calendar_name": "str (optional) - Calendar name (defaults to 'primary')",
                },
                "returns": {
                    "success": "bool",
                    "events": "list - array of event objects",
                    "events[].event_id": "str",
                    "events[].summary": "str",
                    "events[].start": "str",
                    "events[].end": "str",
                    "events[].location": "str",
                    "events[].attendees": "list",
                    "count": "int",
                    "message": "str",
                },
            },
            "create_event": {
                "description": "Create a new calendar event with optional Google Meet link. Automatically sends invitations to attendees.",
                "args": {
                    "summary": "str (required) - Event title",
                    "start_time": "str (required) - Start datetime (supports '12 AM', 'tomorrow 2pm', etc.)",
                    "end_time": "str (optional) - End datetime (auto-calculated as start_time + 1 hour if not provided)",
                    "description": "str (optional)",
                    "location": "str (optional)",
                    "attendees": "list (optional) - List of email addresses",
                    "calendar_name": "str (optional) - Calendar name (defaults to 'primary')",
                    "add_meet_link": "bool (optional) - Add Google Meet link (default: false)",
                },
                "returns": {
                    "success": "bool",
                    "event_id": "str",
                    "event_url": "str",
                    "meet_link": "str - Google Meet link if add_meet_link=true",
                    "message": "str",
                    "status": "str - 'conflict' if scheduling conflict detected",
                    "conflict_id": "str - ID of conflicting event if status='conflict'",
                },
            },
            "update_event": {
                "description": "Update an existing calendar event (title, time, location, attendees). Automatically notifies attendees.",
                "args": {
                    "event_id": "str (required) - From list_events or create_event",
                    "new_summary": "str (optional)",
                    "new_start": "str (optional)",
                    "new_end": "str (optional)",
                    "new_description": "str (optional)",
                    "new_location": "str (optional)",
                    "new_attendees": "list (optional) - New list of attendee emails",
                    "calendar_name": "str (optional)",
                },
                "returns": {
                    "success": "bool",
                    "event_id": "str",
                    "event_url": "str",
                    "changes": "list - what was changed",
                    "message": "str",
                },
                "can_be_derived_from": {
                    "event_id": {
                        "source_tool": "list_events",
                        
                    }
                }
            },
            "delete_event": {
                "description": "Delete a calendar event (requires confirmation first). Sends cancellation emails to attendees.",
                "args": {
                    "event_id": "str (required)",
                    "calendar_name": "str (optional)",
                    "confirmed": "bool (optional) - Set true to skip confirmation",
                },
                "returns": {
                    "success": "bool",
                    "deleted": "bool",
                    "requires_confirmation": "bool - true if confirmation needed",
                    "event_title": "str",
                    "event_start": "str",
                    "confirmation_prompt": "str - if confirmation needed",
                    "message": "str",
                },
                "can_be_derived_from": {
                    "event_id": {
                        "source_tool": "list_events",
                       
                    }
                }
            },
            "confirm_delete_event": {
                "description": "Confirm and execute deletion after delete_event returns requires_confirmation=true",
                "args": {
                    "event_id": "str (required)",
                    "calendar_name": "str (optional)",
                },
                "returns": {
                    "success": "bool",
                    "deleted": "bool",
                    "message": "str",
                },
                "can_be_derived_from": {
                    "event_id": {
                        "source_tool": "list_events",
                        
                    }
                }
            },
            "list_calendars": {
                "description": "List all user's calendars",
                "args": {},
                "returns": {
                    "success": "bool",
                    "calendars": "list - array of {id, name, primary}",
                    "message": "str",
                },
            },
            "create_calendar": {
                "description": "Create a new Google Calendar",
                "args": {
                    "calendar_name": "str (required)",
                    "description": "str (optional)",
                },
                "returns": {
                    "success": "bool",
                    "calendar_id": "str",
                    "message": "str",
                },
            },
            "resolve_conflict": {
                "description": "Resolve scheduling conflict by moving conflicting event 1 hour later, then create new event",
                "args": {
                    "conflict_id": "str (required) - From create_event's conflict_id",
                    "new_event": "dict (required) - {summary, start_time, end_time, attendees, description, location}",
                    "calendar_name": "str (optional)",
                },
                "returns": {
                    "success": "bool",
                    "event_id": "str",
                    "message": "str",
                },
                "can_be_derived_from": {
                    "conflict_id": {
                        "source_tool": "create_event",
                        
                    }
                }
            },
        },
    },
   "drive_agent": {
        "description": "Manages Google Drive operations: upload files, create folders, list files/folders, search files, and get folder information. All operations are within the SafeExpress root folder.",
        "tools": {
            "upload_file": {
                "description": "Upload a file to Google Drive (SafeExpress folder or specific path)",
                "args": {
                    "file_path": "str (required) — Local file path to upload",
                    "filename": "str (required) — Name for the uploaded file",
                    "folder_path": "str (optional) — Target folder path (e.g., 'Operations/2024')",
                    "mime_type": "str (optional) — MIME type of the file (default: application/octet-stream)"
                },
                "returns": {
                    "success": "bool",
                    "file_id": "str — Google Drive file ID",
                    "file_url": "str — Direct link to file",
                    "filename": "str",
                    "folder_path": "str",
                    "message": "str",
                    "error": "str"
                },
            },
            "upload_template": {
                "description": "Upload template file (PDF, DOCX, DOC) to SafeExpress/Templates with auto-conversion to Google Docs format",
                "instructions": """
🔄 AUTOMATIC CONVERSION:
- PDF, DOCX, DOC files are automatically converted to Google Docs format
- This makes them editable and allows placeholder replacement
- Original format is preserved in metadata
- This is STEP 1 of the template workflow

IMPORTANT: Always follow with analyze_uploaded_template (Step 2)
                """,
                "args": {
                    "file_path": "str (required) — Local file path to upload",
                    "template_name": "str (required) — Name for the template",
                    "file_type": "str (optional) — MIME type (auto-detected if not provided)",
                    "preserve_format": "bool (optional, default: false) — Keep original format (not recommended for templates)"
                },
                "returns": {
                    "success": "bool",
                    "file_id": "str — Use this for analyze_uploaded_template in Step 2",
                    "file_url": "str",
                    "template_name": "str",
                    "original_format": "str — PDF, DOCX, or DOC",
                    "current_format": "str — 'Google Docs' if converted",
                    "is_editable": "bool — Whether placeholders can be replaced",
                    "folder_path": "str — Always 'SafeExpress/Templates'",
                    "message": "str",
                    "error": "str"
                },
                "example": "upload_template(file_path={{uploaded_file.temp_path}}, template_name='Weekly Template')"
            },
            "create_folder": {
                "description": "Create a folder or nested folder structure in SafeExpress",
                "args": {
                    "folder_path": "str (required) — Folder path to create (e.g., 'Operations/2024/Reports')"
                },
                "returns": {
                    "success": "bool",
                    "folder_id": "str",
                    "folder_url": "str",
                    "folder_path": "str",
                    "message": "str",
                    "error": "str"
                },
                "notes": "Automatically creates parent folders if they don't exist."
            },
            "list_folders": {
                "description": "List all folders in SafeExpress with tree structure",
                "args": {},
                "returns": {
                    "success": "bool",
                    "folders": "list — Array of folder objects",
                    "count": "int",
                    "tree": "str",
                    "message": "str",
                    "error": "str"
                },
            },
            "list_files": {
                "description": "List files in SafeExpress root or specific folder",
                "args": {
                    "folder_path": "str (optional) — Folder path to list files from"
                },
                "returns": {
                    "success": "bool",
                    "files": "list",
                    "count": "int",
                    "folder_path": "str",
                    "message": "str",
                    "error": "str"
                },
            },
            "search_files": {
                "description": "Search for files in SafeExpress by name or keywords",
                "args": {
                    "search_term": "str (required) — Keywords to search for"
                },
                "returns": {
                    "success": "bool",
                    "results": "list",
                    "count": "int",
                    "search_term": "str",
                    "message": "str",
                    "error": "str"
                },
            },
            "get_folder_info": {
                "description": "Get detailed information about a specific folder",
                "args": {
                    "folder_path": "str (required) — Folder path"
                },
                "returns": {
                    "success": "bool",
                    "folder_id": "str",
                    "folder_name": "str",
                    "folder_path": "str",
                    "file_count": "int",
                    "subfolder_count": "int",
                    "message": "str",
                    "error": "str"
                },
            }
        },
        "important_notes": [
            "All operations are scoped to the 'SafeExpress' root folder",
            "Folder paths are relative to SafeExpress (don't include 'SafeExpress/' prefix)",
            "Nested folder creation is automatic",
            "File uploads support any MIME type",
            "PDF/DOCX templates are auto-converted to Google Docs for editing"
        ]
    },
    
   "docs_agent": {
    "description": "Create, edit, and read Google Docs documents. Supports template workflows with placeholder replacement and PDF export.",
    "tools": {
        "create_doc": {
            "description": "Creates a new Google Doc and returns its ID and URL",
            "args": {"title": "str (required) — the name of the document"},
            "returns": {"success": "bool", "document_id": "str", "document_url": "str", "title": "str", "error": "str"}
        },
        "list_my_docs": {
            "description": "List user's Google Docs to find templates",
            "args": {"search_query": "str (optional) — keyword"},
            "returns": {"success": "bool", "documents": "list", "error": "str"}
        },
        "extract_template_format": {
            "description": "Analyze existing Google Doc template to find placeholders",
            "args": {"template_document_id": "str (required)"},
            "returns": {"success": "bool", "placeholders": "list", "error": "str"}
        },
        "analyze_uploaded_template": {
            "description": "Analyze uploaded template file to extract structure and placeholders",
            "args": {"template_file_id": "str (required) — Google Drive file ID from upload_template"},
            "returns": {"success": "bool", "template_id": "str", "placeholders": "list", "error": "str"}
        },
        "create_from_uploaded_template": {
            "description": "Create document from analyzed template with placeholder replacement and optional PDF export",
            "args": {
                "template_file_id": "str (required)",
                "new_title": "str (required)",
                "placeholders": "str (optional) — JSON string",
                "output_format": "str (optional) — 'google_docs' or 'pdf'"
            },
            "returns": {"success": "bool", "document_id": "str", "document_url": "str", "title": "str", "error": "str"}
        },
        "create_from_my_template": {
            "description": "Create from existing Google Doc template with placeholder replacement",
            "args": {
                "template_document_id": "str (required)",
                "new_title": "str (required)",
                "placeholders": "str (required) — JSON string"
            },
            "returns": {"success": "bool", "document_id": "str", "url": "str", "error": "str"}
        },
        "create_from_existing_data_and_template": {
            "description": "Create document from existing data and template files in Google Drive (using file names, not IDs)",
            "args": {
                "template_file_name": "str (required) — Name of template file in Google Drive",
                "data_file_name": "str (required) — Name of data file in Google Drive",
                "new_title": "str (required) — Title for new document",
                "output_format": "str (optional) — 'google_docs' (default) or 'pdf'"
            },
            "returns": {
                "success": "bool",
                "document_id": "str",
                "document_url": "str",
                "title": "str",
                "format": "str",
                "error": "str"
            }
        },
        "add_text": {
            "description": "Adds text to an existing Google Doc",
            "args": {
                "document_id": "str (required)",
                "text": "str (required) — ACTUAL content to add"
            },
            "returns": {"success": "bool", "document_id": "str", "document_url": "str", "text_length": "int", "error": "str"}
        },
        "read_doc": {
            "description": "Reads text content from a Google Doc",
            "args": {"document_id": "str (required)"},
            "returns": {"success": "bool", "document_id": "str", "document_url": "str", "content": "str", "title": "str", "error": "str"}
        }
    },
    
    "template_workflows": {
        "uploaded_template_workflow": {
            "when_to_use": "When user uploads a file (PDF, DOCX) and wants to create a document from it"
        },
        "existing_template_workflow": {
            "when_to_use": "When user mentions 'my template', 'my format', or wants to use an existing Google Doc as template"
        },
        "existing_data_and_template_workflow": {
            "when_to_use": "When user mentions template AND data files that are BOTH already in Google Drive",
            "tool": "create_from_existing_data_and_template",
            "example": "Create document using template 'X' and data 'Y'"
            }
        }
    }
}