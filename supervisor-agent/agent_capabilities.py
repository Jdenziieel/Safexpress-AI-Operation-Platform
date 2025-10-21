"""
Agent Capabilities Configuration

This file defines the tools and capabilities of each specialized agent in the system.
Each agent has a description, and a list of tools with their arguments and return values.
"""

agent_capabilities = {
    "gmail_agent": {
        "description": "Comprehensive Gmail operations: read, search, draft, send, reply, manage labels, download attachments, and view conversation threads.",
        "tools": {
            "send_email": {
                "description": "DEPRECATED: Sends an email immediately without review. Use create_draft_email + send_draft_email for safer workflow with human approval.",
                "args": {
                    "to": "str (required) — recipient email address",
                    "subject": "str (required) — subject line",
                    "body": "str (required) — email body content"
                },
                "returns": {
                    "success": "bool — whether email was sent successfully",
                    "message_id": "str — Gmail message ID",
                    "thread_id": "str — thread ID of the email",
                    "to": "str — recipient email address",
                    "subject": "str — email subject",
                    "body": "str — email body",
                    "error": "str — error message (null if successful)"
                }
            },
            "search_emails": {
                "description": "Search emails in Gmail matching a query with full message bodies and attachment info. Supports date filters (after:YYYY/MM/DD, before:YYYY/MM/DD), sender (from:), subject, has:attachment, is:unread, etc.",
                "args": {
                    "query": "str (required) — search query (e.g., 'from:john@example.com', 'after:{{ yesterday_date }}', 'subject:meeting has:attachment')",
                    "max_results": "int (required) — number of emails to fetch"
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
                    "error": "str — error message (null if successful)"
                }
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
                    "error": "str — error message (null if successful)"
                }
            },
            "reply_to_email": {
                "description": "Replies to an email in its thread (maintains conversation)",
                "args": {
                    "message_id": "str (required) — message ID of email to reply to",
                    "reply_body": "str (required) — reply message content"
                },
                "returns": {
                    "success": "bool — whether reply was sent successfully",
                    "original_message_id": "str — the message ID that was replied to",
                    "reply_message_id": "str — message ID of the sent reply",
                    "thread_id": "str — thread ID of the conversation",
                    "to": "str — recipient email address",
                    "subject": "str — reply subject",
                    "error": "str — error message (null if successful)"
                }
            },
            "create_draft_email": {
                "description": "Creates a draft email without sending it (safer than send_email)",
                "args": {
                    "to": "str (required) — recipient email address",
                    "subject": "str (required) — subject line",
                    "body": "str (required) — email body content"
                },
                "returns": {
                    "success": "bool — whether draft was created successfully",
                    "draft_id": "str — Gmail top-level draft ID for sending later with send_draft_email",
                    "message_id": "str — underlying message ID",
                    "to": "str — recipient email address",
                    "subject": "str — email subject",
                    "error": "str — error message (null if successful)"
                }
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
                    "error": "str — error message (null if successful)"
                }
            },
            "search_drafts": {
                "description": "Search for draft emails in Gmail. Returns drafts with nested message details matching Gmail API format.",
                "args": {
                    "query": "str (optional) — Gmail search query (e.g., 'subject:meeting', 'to:john@example.com'). Empty string searches all drafts.",
                    "max_results": "int (optional) — maximum number of drafts to return (default: 10)"
                },
                "returns": {
                    "success": "bool — whether search was successful",
                    "count": "int — number of drafts found",
                    "drafts": "list — array of draft objects, each containing: {id: draft_id, message: {id, threadId, labelIds, to, subject, body, snippet, date}}",
                    "query": "str — search query used",
                    "error": "str — error message (null if successful)"
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
                        "date": "str — date string"
                    }
                },
                "usage_note": "Use drafts[i].id with send_draft_email to send a draft. Access message details via drafts[i].message.subject, drafts[i].message.to, etc."
            },
            "send_email_with_attachment": {
                "description": "Sends an email with a file attachment",
                "args": {
                    "to": "str (required) — recipient email address",
                    "subject": "str (required) — subject line",
                    "body": "str (required) — email body content",
                    "file_path": "str (required) — absolute path to the file to attach"
                },
                "returns": {
                    "success": "bool — whether email was sent successfully",
                    "message_id": "str — Gmail message ID",
                    "thread_id": "str — thread ID of the email",
                    "to": "str — recipient email address",
                    "subject": "str — email subject",
                    "attachment_name": "str — name of attached file",
                    "error": "str — error message (null if successful)"
                }
            },
            "add_label": {
                "description": "Adds a system label to an email (star, mark unread, mark important, move to spam/trash)",
                "args": {
                    "message_id": "str (required) — message ID of email to label",
                    "label": "str (required) — label to add: STARRED, UNREAD, IMPORTANT, SPAM, TRASH"
                },
                "returns": {
                    "success": "bool — whether label was added successfully",
                    "message_id": "str — the message ID that was modified",
                    "thread_id": "str — thread ID of the email",
                    "label_added": "str — the label that was added",
                    "current_labels": "str — comma-separated list of all current labels",
                    "from": "str — email sender",
                    "subject": "str — email subject",
                    "error": "str — error message (null if successful)"
                }
            },
            "remove_label": {
                "description": "Removes a system label from an email (unstar, mark read, unmark important, remove from spam/trash)",
                "args": {
                    "message_id": "str (required) — message ID of email to unlabel",
                    "label": "str (required) — label to remove: STARRED, UNREAD, IMPORTANT, SPAM, TRASH"
                },
                "returns": {
                    "success": "bool — whether label was removed successfully",
                    "message_id": "str — the message ID that was modified",
                    "thread_id": "str — thread ID of the email",
                    "label_removed": "str — the label that was removed",
                    "current_labels": "str — comma-separated list of remaining labels",
                    "from": "str — email sender",
                    "subject": "str — email subject",
                    "error": "str — error message (null if successful)"
                }
            },
            "download_attachment": {
                "description": "Downloads an email attachment to local storage",
                "args": {
                    "message_id": "str (required) — message ID of email containing attachment",
                    "attachment_id": "str (required) — attachment ID from email details",
                    "save_path": "str (required) — absolute path where file should be saved"
                },
                "returns": {
                    "success": "bool — whether download was successful",
                    "message_id": "str — the message ID",
                    "thread_id": "str — thread ID of the email",
                    "attachment_id": "str — the attachment ID",
                    "filename": "str — name of downloaded file",
                    "save_path": "str — full path where file was saved",
                    "file_size": "int — size in bytes",
                    "error": "str — error message (null if successful)"
                }
            }
        }
    },
    "docs_agent": {
        "description": "Create, edit, and read Google Docs documents.",
        "tools": {
            "create_doc": {
                "description": "Creates a new Google Doc and returns its ID and URL",
                "args": {
                    "title": "str (required) — the name of the document (e.g., 'Project Notes')"
                },
                "returns": {
                    "success": "bool — whether document was created successfully",
                    "document_id": "str — Google Doc ID (null if failed)",
                    "document_url": "str — URL to access the document (null if failed)",
                    "title": "str — document title",
                    "error": "str — error message (null if successful)"
                }
            },
            "add_text": {
                "description": "Adds text to an existing Google Doc",
                "args": {
                    "document_id": "str (required) — the ID of the document",
                    "text": "str (required) — the text content to add"
                },
                "returns": {
                    "success": "bool — whether text was added successfully",
                    "document_id": "str — the document that was modified",
                    "document_url": "str — URL to access the document",
                    "text_length": "int — length of text added",
                    "error": "str — error message (null if successful)"
                }
            },
            "read_doc": {
                "description": "Reads text content from a Google Doc",
                "args": {
                    "document_id": "str (required) — the ID of the document to read"
                },
                "returns": {
                    "success": "bool — whether read was successful",
                    "document_id": "str — the document that was read",
                    "document_url": "str — URL to access the document",
                    "content": "str — full document text content",
                    "title": "str — document title",
                    "error": "str — error message (null if successful)"
                }
            }
        }
    },
    "sheets_agent": {
        "description": "Create or update Google Sheets.",
        "args": {
            "title": "str (required) — sheet title",
            "data": "List[List[str]] (required) — 2D list of rows"
        },
        "returns": ["sheet_url"]
    },
    "calendar_agent": {
        "description": "Create or update calendar events.",
        "args": {
            "title": "str (required) — event title",
            "datetime": "str (required) — ISO date/time",
            "attendees": "List[str] (optional) — participant emails",
            "description": "str (optional) — event details"
        },
        "returns": ["event_id"]
    },
    "drive_agent": {
        "description": "Upload or share files using Google Drive.",
        "args": {
            "filename": "str (required) — file name",
            "file_url": "str (optional) — URL or path of file to upload",
            "share_with": "List[str] (optional) — list of users to share with"
        },
        "returns": ["drive_url"]
    }
}
