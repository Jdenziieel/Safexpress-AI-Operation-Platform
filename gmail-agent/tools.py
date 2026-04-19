import os
from typing import Dict, Any, List
from langchain.tools import tool
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import mimetypes
import base64
from email_formatter import format_email_list
import sqlite3
import json
import tempfile
import shutil
import httpx
from datetime import datetime


def get_google_service(service_name: str, version: str, credentials_dict: Dict):

    # credentials for google services
    #
    # NOTE: Do NOT pass scopes=[...] here. The auth server / local token
    # generator decides which scopes the refresh_token was granted. Passing
    # a fixed scope list forces google-auth to send `scope=...` on every
    # refresh request; if ANY of those scopes weren't granted (e.g. the
    # user ran generate_gdrive_token.py which omits gmail.send and
    # gmail.readonly) Google rejects the refresh with
    # `invalid_scope: Bad Request`. The granted scope set already provides
    # everything this agent needs (gmail.modify alone covers read + send +
    # label operations). Mirror the calendar-agent pattern.
    creds = Credentials(
        token=credentials_dict["access_token"],
        refresh_token=credentials_dict.get("refresh_token"),
        token_uri=credentials_dict.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=credentials_dict.get("client_id", ""),
        client_secret=credentials_dict.get("client_secret", ""),
    )

    service = build(service_name, version, credentials=creds)
    return service


def _extract_attachment_data_impl(
    attachment_data: str,      # base64-encoded file from _download_attachment_impl
    file_name: str,
    credentials_dict: Dict = None
) -> Dict[str, Any]:
    import base64, json
    from io import BytesIO

    file_bytes = base64.b64decode(attachment_data)
    ext = file_name.lower().split(".")[-1]

    # ── XLSX / CSV ────────────────────────────────────────────
    if ext in ["xlsx", "xls", "csv"]:
        try:
            import pandas as pd
            df = pd.read_csv(BytesIO(file_bytes)) if ext == "csv" else pd.read_excel(BytesIO(file_bytes))
            df.columns = [str(c) if not str(c).startswith("Unnamed") else f"col_{i}" for i, c in enumerate(df.columns)]
            df = df.dropna(how="all")
            return {
                "success": True,
                "columns": list(df.columns),
                "rows": df.fillna("").to_dict(orient="records"),
                "row_count": len(df),
                "raw_text": df.to_string(index=False),
                "source_type": ext,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── PDF or image ──────────────────────────────────────────
    elif ext in ["pdf", "png", "jpg", "jpeg", "webp"]:
        try:
            import anthropic, base64 as b64
            from PIL import Image

            # Convert PDF pages to images
            if ext == "pdf":
                from pdf2image import convert_from_bytes
                images = convert_from_bytes(file_bytes, dpi=250, fmt="png")
            else:
                images = [Image.open(BytesIO(file_bytes))]

            client = anthropic.Anthropic()
            all_rows, detected_columns, raw_pages = [], [], []

            for page_num, image in enumerate(images):
                if image.mode != "RGB":
                    image = image.convert("RGB")
                # Upscale tiny images
                w, h = image.size
                if w < 1000:
                    image = image.resize((int(w * 1000/w), int(h * 1000/w)))

                buf = BytesIO()
                image.save(buf, format="PNG")
                img_b64 = b64.b64encode(buf.getvalue()).decode()

                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                            {"type": "text", "text": """Extract ALL structured data from this document.
Instructions:
1. Read every piece of text including handwritten notes
2. Find tables — extract headers and all rows exactly
3. Find key-value pairs (e.g. "Invoice No: 123") — treat keys as columns
4. If the document has BOTH a header section AND a table, add header fields as extra columns on every table row
5. For merged/spanned cells, repeat the value in each affected row
6. Preserve original values exactly

Return ONLY this JSON, nothing else:
{"columns": ["col1", ...], "rows": [{"col1": "val"}, ...], "raw_text": "full plain text of document"}
If no table exists, put key-value pairs as a single row.
If blank, return {"columns": [], "rows": [], "raw_text": ""}"""}
                        ]
                    }]
                )

                text = response.content[0].text.strip()
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()

                try:
                    page_data = json.loads(text)
                    if page_data.get("columns") and not detected_columns:
                        detected_columns = page_data["columns"]
                    all_rows.extend(page_data.get("rows", []))
                    raw_pages.append(page_data.get("raw_text", ""))
                except json.JSONDecodeError:
                    raw_pages.append(text)

            return {
                "success": True,
                "columns": detected_columns,
                "rows": all_rows,
                "row_count": len(all_rows),
                "raw_text": "\n\n".join(raw_pages),
                "source_type": ext,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    else:
        return {"success": False, "error": f"Unsupported file type: {ext}"}


def _map_columns_to_sheet_impl(
    extracted_columns: list,
    sheet_columns: list,
    sample_rows: list = None,
    credentials_dict: Dict = None
) -> Dict[str, Any]:
    import anthropic, json
    client = anthropic.Anthropic()

    sample_str = ""
    if sample_rows:
        sample_str = f"\nSample data (first 2 rows):\n{json.dumps(sample_rows[:2], indent=2)}"

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": f"""Map the extracted columns to the sheet columns.

Extracted columns: {extracted_columns}
Sheet columns: {sheet_columns}{sample_str}

Rules:
- Map each extracted column to the BEST matching sheet column
- If no match, map to null
- Consider abbreviations, synonyms, different naming conventions
- Return ONLY valid JSON: {{"extracted_col": "sheet_col_or_null"}}"""
        }]
    )

    text = response.content[0].text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    mapping = json.loads(text)
    return {
        "success": True,
        "mapping": mapping,
        "unmapped": [k for k, v in mapping.items() if v is None]
    }


def _send_email_impl(to: str, subject: str, body: str, credentials_dict: Dict) -> Dict[str, Any]:
    """
    Implementation of sending email logic

    Args:
        to: Recipient email address
        subject: Subject of the email
        body: Email body text
        credentials_dict: Google OAuth credentials

    Returns:
        Dictionary with success status and email details
    """

    try:
        gmail_service = get_google_service("gmail", "v1", credentials_dict)

        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        send_result = (
            gmail_service.users()
            .messages()
            .send(userId="me", body={"raw": raw_message})
            .execute()
        )

        message_id = send_result['id']
        thread_id = send_result.get('threadId', message_id)

        return {
            "success": True,
            "message_id": message_id,
            "thread_id": thread_id,
            "to": to,
            "subject": subject,
            "body": body,
            "error": None
        }

    except HttpError as error:
        return {
            "success": False,
            "message_id": None,
            "thread_id": None,
            "to": to,
            "subject": subject,
            "body": body,
            "error": f"Gmail API error: {str(error)}"
        }
    except Exception as error:
        return {
            "success": False,
            "message_id": None,
            "thread_id": None,
            "to": to,
            "subject": subject,
            "body": body,
            "error": f"Unexpected error: {str(error)}"
        }
    
# checking - status: Done (Added LabelIds is not being used nor relevant in searches currently)
def _search_emails_impl(
        query: str,
        max_results: int,
        credentials_dict: Dict,
        label_ids: List[str] = None) -> Dict[str, Any]:
    """Search emails in Gmail matching a query"""

    try:
        # get gmail service
        gmail_service = get_google_service("gmail", "v1", credentials_dict)
        # list message IDs
        results = (
            gmail_service.users()
            .messages()
            .list(
                userId="me",
                q=query,  # different variable from read_recent_emails
                maxResults=max_results,
                labelIds=label_ids if label_ids else None,
            )
            .execute()
        )

        messages = results.get("messages", [])

        # check if empty
        if not messages:
            label_info = f" with labels: {', '.join(label_ids)}" if label_ids else ""
            return {
                "success": False,
                "emails": [],
                "count": 0,
                "query": query,
                "label_filter": label_ids,
                "error": f"No emails found matching query: '{query}'{label_info}",
                "no_results": True
            }

        # loops through the messages and fetches details
        emails = []
        for msg in messages:
            msg_id = msg["id"]
            
            # get message details with full format
            message = (
                gmail_service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )

            # get thread ID
            thread_id = message.get("threadId", "")

            # get internalDate and labelIds
            internal_date = message.get("internalDate", "")
            label_ids = message.get("labelIds", [])

            # extract headers (From, Subject, Date)
            headers = message["payload"]["headers"]
            from_addr = ""
            subject = ""
            date = ""

            for header in headers:
                if header["name"] == "From":
                    from_addr = header["value"]
                elif header["name"] == "Subject":
                    subject = header["value"]
                elif header["name"] == "Date":
                    date = header["value"]

            # get full message body
            body = ""
            if "parts" in message["payload"]:
                # multipart message
                for part in message["payload"]["parts"]:
                    if part["mimeType"] == "text/plain" and "data" in part.get("body", {}):
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                        break
                    elif part["mimeType"] == "text/html" and not body and "data" in part.get("body", {}):
                        # fallback to HTML if no plain text
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
            elif "body" in message["payload"] and "data" in message["payload"]["body"]:
                # simple message
                body = base64.urlsafe_b64decode(message["payload"]["body"]["data"]).decode("utf-8")

            # if body is still empty, use snippet
            if not body:
                body = message.get("snippet", "")

            # check for attachments
            attachments = []
            if "parts" in message["payload"]:
                for part in message["payload"]["parts"]:
                    if part.get("filename") and part.get("body", {}).get("attachmentId"):
                        attachment_info = {
                            "filename": part["filename"],
                            "attachment_id": part["body"]["attachmentId"],
                            "mime_type": part["mimeType"],
                            "size": part["body"].get("size", 0)
                        }
                        attachments.append(attachment_info)

            # Create structured email object
            email_obj = {
                "message_id": msg_id,
                "thread_id": thread_id,
                "from": from_addr,
                "subject": subject,
                "date": date,
                "internal_date": internal_date,
                "label_ids": label_ids,
                "body": body,
                "has_attachments": len(attachments) > 0,
                "attachments": attachments
            }
            emails.append(email_obj)
        
        # Format all emails before returning
        email_list = format_email_list(emails)

        return {
            "success": True,
            "emails": email_list,
            "count": len(email_list),
            "query": query,
            "error": None
        }

    except HttpError as error:
        return {
            "success": False,
            "emails": [],
            "count": 0,
            "query": query,
            "error": f"Gmail API error: {str(error)}"
        }
    except Exception as error:
        return {
            "success": False,
            "emails": [],
            "count": 0,
            "query": query,
            "error": f"Unexpected error: {str(error)}"
        }

# checking - status:
def _send_email_with_attachments_impl(
    to: str, subject: str, body: str, file_path: str, credentials_dict: Dict
) -> Dict[str, Any]:
    """Send email with attachment via Gmail"""
    try:
        # get credentials
        gmail_service = get_google_service("gmail", "v1", credentials_dict)

        # headers
        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = subject

        message.attach(MIMEText(body, "plain"))

        if not os.path.exists(file_path):
            return {
                "success": False,
                "message_id": None,
                "thread_id": None,
                "to": to,
                "subject": subject,
                "attachment_name": None,
                "attachment_path": file_path,
                "error": f"File not found at {file_path}"
            }
        # open and read the file
        with open(file_path, "rb") as file:
            file_data = file.read()
        # This creates the attachment
        part = MIMEBase("application", "octet-stream")
        part.set_payload(file_data)

        encoders.encode_base64(part)
        # add the filename header
        filename = os.path.basename(file_path)
        part.add_header("Content-Disposition", f"attachment; filename={filename}")
        # attach the file to the message
        message.attach(part)

        # send the email
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        send_result = (
            gmail_service.users()
            .messages()
            .send(userId="me", body={"raw": raw_message})
            .execute()
        )

        message_id = send_result['id']
        thread_id = send_result.get('threadId', message_id)

        return {
            "success": True,
            "message_id": message_id,
            "thread_id": thread_id,
            "to": to,
            "subject": subject,
            "body": body,
            "attachment_name": filename,
            "attachment_path": file_path,
            "error": None
        }

    except FileNotFoundError:
        return {
            "success": False,
            "message_id": None,
            "thread_id": None,
            "to": to,
            "subject": subject,
            "attachment_name": None,
            "attachment_path": file_path,
            "error": f"File not found at {file_path}"
        }
    except HttpError as error:
        return {
            "success": False,
            "message_id": None,
            "thread_id": None,
            "to": to,
            "subject": subject,
            "attachment_name": None,
            "attachment_path": file_path,
            "error": f"Gmail API error: {str(error)}"
        }
    except Exception as error:
        return {
            "success": False,
            "message_id": None,
            "thread_id": None,
            "to": to,
            "subject": subject,
            "attachment_name": None,
            "attachment_path": file_path,
            "error": f"Unexpected error: {str(error)}"
        }

# checking - status:
def _reply_to_email_impl(
    message_id: str, reply_body: str, credentials_dict: Dict
) -> Dict[str, Any]:
    """Reply to an email via Gmail API"""
    try:
        # get gmail service
        gmail_service = get_google_service("gmail", "v1", credentials_dict)

        # get original email
        original_message = (
            gmail_service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")  # this gets all the headers
            .execute()
        )

        # Extract for threading
        thread_id = original_message["threadId"]
        headers = original_message["payload"]["headers"]

        # initialize the variables
        message_id_header = ""
        subject = ""
        to_email = ""

        # loop through the headers
        for header in headers:
            if header["name"] == "Message-ID":
                message_id_header = header["value"]
            elif header["name"] == "Subject":
                subject = header["value"]
            elif header["name"] == "From":
                to_email = header["value"]

        # create reply message
        message = MIMEText(reply_body)
        message["to"] = to_email
        message["subject"] = (
            "Re: " + subject if not subject.startswith("Re:") else subject
        )
        message["In-Reply-To"] = message_id_header
        message["References"] = message_id_header

        # encodes the message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        send_result = (
            gmail_service.users()
            .messages()
            .send(userId="me", body={"raw": raw_message, "threadId": thread_id})
            .execute()
        )

        reply_message_id = send_result['id']
        reply_thread_id = send_result.get('threadId', thread_id)

        return {
            "success": True,
            "original_message_id": message_id,
            "reply_message_id": reply_message_id,
            "thread_id": reply_thread_id,
            "to": to_email,
            "subject": subject,
            "reply_body": reply_body,
            "error": None
        }

    except HttpError as error:
        return {
            "success": False,
            "original_message_id": message_id,
            "reply_message_id": None,
            "thread_id": None,
            "to": None,
            "subject": None,
            "reply_body": reply_body,
            "error": f"Gmail API error: {str(error)}"
        }
    except Exception as error:
        return {
            "success": False,
            "original_message_id": message_id,
            "reply_message_id": None,
            "thread_id": None,
            "to": None,
            "subject": None,
            "reply_body": reply_body,
            "error": f"Unexpected error: {str(error)}"
        }


def _forward_email_impl(
    message_id: str, to: str, forward_message: str = "", credentials_dict: Dict = None
) -> Dict[str, Any]:
    """Forward an email to another recipient via Gmail API
    
    Args:
        message_id: The ID of the email message to forward
        to: Recipient email address to forward to
        forward_message: Optional message to add before the forwarded content
        credentials_dict: Gmail OAuth credentials
        
    Returns:
        Dictionary with success status and forwarded email details
    """
    try:
        # get gmail service
        gmail_service = get_google_service("gmail", "v1", credentials_dict)

        # get original email
        original_message = (
            gmail_service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

        # Extract headers
        headers = original_message["payload"]["headers"]
        original_subject = ""
        original_from = ""
        original_date = ""
        
        for header in headers:
            if header["name"] == "Subject":
                original_subject = header["value"]
            elif header["name"] == "From":
                original_from = header["value"]
            elif header["name"] == "Date":
                original_date = header["value"]

        # Get original body
        original_body = ""
        if "parts" in original_message["payload"]:
            for part in original_message["payload"]["parts"]:
                if part["mimeType"] == "text/plain":
                    if "data" in part["body"]:
                        original_body = base64.urlsafe_b64decode(
                            part["body"]["data"]
                        ).decode("utf-8")
                    break
        else:
            if "body" in original_message["payload"] and "data" in original_message["payload"]["body"]:
                original_body = base64.urlsafe_b64decode(
                    original_message["payload"]["body"]["data"]
                ).decode("utf-8")

        # Build forwarded message
        forward_subject = f"Fwd: {original_subject}" if not original_subject.startswith("Fwd:") else original_subject
        
        # Create multipart message
        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = forward_subject
        
        # Build forward body
        forward_body = ""
        if forward_message:
            forward_body = f"{forward_message}\n\n"
        
        forward_body += f"---------- Forwarded message ---------\n"
        forward_body += f"From: {original_from}\n"
        forward_body += f"Date: {original_date}\n"
        forward_body += f"Subject: {original_subject}\n\n"
        forward_body += original_body
        
        message.attach(MIMEText(forward_body, "plain"))

        # Encode and send
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        
        send_result = (
            gmail_service.users()
            .messages()
            .send(userId="me", body={"raw": raw_message})
            .execute()
        )

        forwarded_message_id = send_result['id']
        forwarded_thread_id = send_result.get('threadId', forwarded_message_id)

        return {
            "success": True,
            "original_message_id": message_id,
            "forwarded_message_id": forwarded_message_id,
            "thread_id": forwarded_thread_id,
            "to": to,
            "subject": forward_subject,
            "original_from": original_from,
            "forward_message": forward_message,
            "error": None
        }

    except HttpError as error:
        return {
            "success": False,
            "original_message_id": message_id,
            "forwarded_message_id": None,
            "thread_id": None,
            "to": to,
            "subject": None,
            "original_from": None,
            "forward_message": forward_message,
            "error": f"Gmail API error: {str(error)}"
        }
    except Exception as error:
        return {
            "success": False,
            "original_message_id": message_id,
            "forwarded_message_id": None,
            "thread_id": None,
            "to": to,
            "subject": None,
            "original_from": None,
            "forward_message": forward_message,
            "error": f"Unexpected error: {str(error)}"
        }


def _get_thread_conversation_impl(thread_id: str, credentials_dict: Dict) -> Dict[str, Any]:
    """Get all messages in an email thread/conversation"""
    try:
        # get gmail service
        gmail_service = get_google_service("gmail", "v1", credentials_dict)

        # get thread with all messages
        thread = (
            gmail_service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )

        messages = thread.get("messages", [])

        if not messages:
            return {
                "success": False,
                "thread_id": thread_id,
                "message_count": 0,
                "messages": [],
                "error": f"Thread '{thread_id}' exists but contains no messages",
                "no_results": True
            }

        # format each message in the thread
        message_list = []
        for idx, message in enumerate(messages, 1):
            headers = message["payload"]["headers"]

            # extract headers
            from_addr = ""
            to_addr = ""
            subject = ""
            date = ""
            message_id = message["id"]

            for header in headers:
                if header["name"] == "From":
                    from_addr = header["value"]
                elif header["name"] == "To":
                    to_addr = header["value"]
                elif header["name"] == "Subject":
                    subject = header["value"]
                elif header["name"] == "Date":
                    date = header["value"]

            # get message body
            body = ""
            if "parts" in message["payload"]:
                # multipart message
                for part in message["payload"]["parts"]:
                    if part["mimeType"] == "text/plain" and "data" in part["body"]:
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                        break
            elif "body" in message["payload"] and "data" in message["payload"]["body"]:
                # simple message
                body = base64.urlsafe_b64decode(message["payload"]["body"]["data"]).decode("utf-8")

            # get snippet if body is empty
            if not body:
                body = message.get("snippet", "")

            # Create structured message object
            msg_obj = {
                "message_number": idx,
                "message_id": message_id,
                "from": from_addr,
                "to": to_addr,
                "subject": subject,
                "date": date,
                "body": body
            }
            message_list.append(msg_obj)

        # Format all messages before returning
        message_list = format_email_list(message_list)

        return {
            "success": True,
            "thread_id": thread_id,
            "message_count": len(message_list),
            "messages": message_list,
            "error": None
        }

    except HttpError as error:
        return {
            "success": False,
            "thread_id": thread_id,
            "message_count": 0,
            "messages": [],
            "error": f"Gmail API error: {str(error)}"
        }
    except Exception as error:
        return {
            "success": False,
            "thread_id": thread_id,
            "message_count": 0,
            "messages": [],
            "error": f"Unexpected error: {str(error)}"
        }

# checking - status: Done
def _create_draft_email_impl(
    to: str, subject: str, body: str, credentials_dict: Dict
) -> Dict[str, Any]:
    """Create a draft email in Gmail"""
    try:
        # get gmail service
        gmail_service = get_google_service("gmail", "v1", credentials_dict)

        # create message
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject

        # encode message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        # create draft
        draft = (
            gmail_service.users()
            .drafts()
            .create(
                userId="me",
                body={"message": {"raw": raw_message}}
            )
            .execute()
        )

        draft_id = draft["id"]
        message_id = draft["message"]["id"]

        return {
            "success": True,
            "draft_id": draft_id,
            "message_id": message_id,
            "to": to,
            "subject": subject,
            "body": body,
            "error": None
        }

    except HttpError as error:
        return {
            "success": False,
            "draft_id": None,
            "message_id": None,
            "to": to,
            "subject": subject,
            "body": body,
            "error": f"Gmail API error: {str(error)}"
        }
    except Exception as error:
        return {
            "success": False,
            "draft_id": None,
            "message_id": None,
            "to": to,
            "subject": subject,
            "body": body,
            "error": f"Unexpected error: {str(error)}"
        }

# checking - status: Done
def _send_draft_email_impl(draft_id: str, credentials_dict: Dict) -> Dict[str, Any]:
    """Send a draft email by draft ID"""
    try:
        # get gmail service
        gmail_service = get_google_service("gmail", "v1", credentials_dict)

        # send the draft
        sent_message = (
            gmail_service.users()
            .drafts()
            .send(userId="me", body={"id": draft_id})
            .execute()
        )

        message_id = sent_message["id"]
        thread_id = sent_message.get("threadId", "")

        # get message details to show what was sent
        message_details = (
            gmail_service.users()
            .messages()
            .get(userId="me", id=message_id, format="metadata", metadataHeaders=["To", "Subject"])
            .execute()
        )

        headers = message_details["payload"]["headers"]
        to_addr = ""
        subject = ""

        for header in headers:
            if header["name"] == "To":
                to_addr = header["value"]
            elif header["name"] == "Subject":
                subject = header["value"]

        return {
            "success": True,
            "draft_id": draft_id,
            "message_id": message_id,
            "thread_id": thread_id,
            "to": to_addr,
            "subject": subject,
            "error": None
        }

    except HttpError as error:
        return {
            "success": False,
            "draft_id": draft_id,
            "message_id": None,
            "thread_id": None,
            "to": None,
            "subject": None,
            "error": f"Gmail API error: {str(error)}"
        }
    except Exception as error:
        return {
            "success": False,
            "draft_id": draft_id,
            "message_id": None,
            "thread_id": None,
            "to": None,
            "subject": None,
            "error": f"Unexpected error: {str(error)}"
        }

# checking - status: Done
def _search_drafts_impl(    
    query: str = "", max_results: int = 10, credentials_dict: Dict = None
) -> Dict[str, Any]:
    """Search for draft emails in Gmail
    
    Args:
        query: Optional search query (e.g., "subject:meeting", "to:john@example.com")
        max_results: Maximum number of drafts to return (default: 10)
        credentials_dict: Gmail OAuth credentials
        
    Returns:
        Dictionary with draft_id (top-level ID) and message details for each draft
    """
    try:
        # get gmail service
        gmail_service = get_google_service("gmail", "v1", credentials_dict)

        # list drafts with optional query
        list_params = {
            "userId": "me",
            "maxResults": max_results
        }
        
        if query:
            list_params["q"] = query

        drafts_response = (
            gmail_service.users()
            .drafts()
            .list(**list_params)
            .execute()
        )

        drafts = drafts_response.get("drafts", [])

        if not drafts:
            query_info = f" matching query: '{query}'" if query else ""
            return {
                "success": False,
                "count": 0,
                "drafts": [],
                "query": query,
                "error": f"No draft emails found{query_info}",
                "no_results": True
            }

        # get full details for each draft
        draft_details = []
        for draft in drafts:
            draft_id = draft["id"]
            
            # get full draft details
            draft_full = (
                gmail_service.users()
                .drafts()
                .get(userId="me", id=draft_id, format="full")
                .execute()
            )

            message = draft_full["message"]
            message_id = message["id"]
            thread_id = message.get("threadId", "")
            labels = message.get("labelIds", [])
            headers = message["payload"]["headers"]

            # extract headers
            to_addr = ""
            subject = ""
            date = ""
            
            for header in headers:
                if header["name"] == "To":
                    to_addr = header["value"]
                elif header["name"] == "Subject":
                    subject = header["value"]
                elif header["name"] == "Date":
                    date = header["value"]
            
            # get message body
            body = ""
            if "parts" in message["payload"]:
                # multipart message
                for part in message["payload"]["parts"]:
                    if part["mimeType"] == "text/plain" and "data" in part["body"]:
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                        break
            elif "body" in message["payload"] and "data" in message["payload"]["body"]:
                # simple message
                body = base64.urlsafe_b64decode(message["payload"]["body"]["data"]).decode("utf-8")
            
            # Structure to match Gmail API format with nested message object
            draft_details.append({
                "draft_id": draft_id,  # Top-level draft ID for send_draft_email
                "message": {
                    "id": message_id,
                    "threadId": thread_id,
                    "labelIds": labels,
                    "to": to_addr,
                    "subject": subject,
                    "body": body,
                    "snippet": body[:100] + ("..." if len(body) > 100 else ""),  # Preview
                    "date": date
                }
            })

        # Format all draft message bodies before returning
        for draft in draft_details:
            if "message" in draft and "body" in draft["message"]:
                # Format the nested message object
                formatted_messages = format_email_list([draft["message"]])
                if formatted_messages:
                    draft["message"] = formatted_messages[0]

        return {
            "success": True,
            "count": len(draft_details),
            "drafts": draft_details,
            "query": query,
            "error": None
        }

    except HttpError as error:
        return {
            "success": False,
            "count": 0,
            "drafts": [],
            "query": query,
            "error": f"Gmail API error: {str(error)}"
        }
    except Exception as error:
        return {
            "success": False,
            "count": 0,
            "drafts": [],
            "query": query,
            "error": f"Unexpected error: {str(error)}"
        }


def _add_label_impl(message_id: str, label: str, credentials_dict: Dict) -> Dict[str, Any]:
    """Add a system label to an email
    
    Supported labels: STARRED, UNREAD, IMPORTANT, SPAM, TRASH, INBOX
    """
    try:
        # get gmail service
        gmail_service = get_google_service("gmail", "v1", credentials_dict)

        # validate label
        valid_labels = ["STARRED", "UNREAD", "IMPORTANT", "SPAM", "TRASH"]
        label_upper = label.upper()
        
        if label_upper not in valid_labels:
            return {
                "success": False,
                "message_id": message_id,
                "thread_id": None,
                "label_added": label,
                "current_labels": None,
                "from": None,
                "subject": None,
                "error": f"Invalid label '{label}'. Valid labels are: {', '.join(valid_labels)}"
            }

        # add label
        result = (
            gmail_service.users()
            .messages()
            .modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": [label_upper]}
            )
            .execute()
        )

        # get email details to confirm
        message = (
            gmail_service.users()
            .messages()
            .get(userId="me", id=message_id, format="metadata", metadataHeaders=["Subject", "From"])
            .execute()
        )

        headers = message["payload"]["headers"]
        subject = ""
        from_addr = ""

        for header in headers:
            if header["name"] == "Subject":
                subject = header["value"]
            elif header["name"] == "From":
                from_addr = header["value"]

        thread_id = result.get("threadId", "")
        current_labels = ", ".join(result.get("labelIds", []))

        return {
            "success": True,
            "message_id": message_id,
            "thread_id": thread_id,
            "label_added": label_upper,
            "current_labels": current_labels,
            "from": from_addr,
            "subject": subject,
            "error": None
        }

    except HttpError as error:
        return {
            "success": False,
            "message_id": message_id,
            "thread_id": None,
            "label_added": label,
            "current_labels": None,
            "from": None,
            "subject": None,
            "error": f"Gmail API error: {str(error)}"
        }
    except Exception as error:
        return {
            "success": False,
            "message_id": message_id,
            "thread_id": None,
            "label_added": label,
            "current_labels": None,
            "from": None,
            "subject": None,
            "error": f"Unexpected error: {str(error)}"
        }


def _remove_label_impl(message_id: str, label: str, credentials_dict: Dict) -> Dict[str, Any]:
    """Remove a system label from an email
    
    Supported labels: STARRED, UNREAD, IMPORTANT, SPAM, TRASH, INBOX
    """
    try:
        # get gmail service
        gmail_service = get_google_service("gmail", "v1", credentials_dict)

        # validate label
        valid_labels = ["STARRED", "UNREAD", "IMPORTANT", "SPAM", "TRASH"]
        label_upper = label.upper()
        
        if label_upper not in valid_labels:
            return {
                "success": False,
                "message_id": message_id,
                "thread_id": None,
                "label_removed": label,
                "current_labels": None,
                "from": None,
                "subject": None,
                "error": f"Invalid label '{label}'. Valid labels are: {', '.join(valid_labels)}"
            }

        # remove label
        result = (
            gmail_service.users()
            .messages()
            .modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": [label_upper]}
            )
            .execute()
        )

        # get email details to confirm
        message = (
            gmail_service.users()
            .messages()
            .get(userId="me", id=message_id, format="metadata", metadataHeaders=["Subject", "From"])
            .execute()
        )

        headers = message["payload"]["headers"]
        subject = ""
        from_addr = ""

        for header in headers:
            if header["name"] == "Subject":
                subject = header["value"]
            elif header["name"] == "From":
                from_addr = header["value"]

        thread_id = result.get("threadId", "")
        current_labels = ", ".join(result.get("labelIds", []))

        return {
            "success": True,
            "message_id": message_id,
            "thread_id": thread_id,
            "label_removed": label_upper,
            "current_labels": current_labels,
            "from": from_addr,
            "subject": subject,
            "error": None
        }

    except HttpError as error:
        return {
            "success": False,
            "message_id": message_id,
            "thread_id": None,
            "label_removed": label,
            "current_labels": None,
            "from": None,
            "subject": None,
            "error": f"Gmail API error: {str(error)}"
        }
    except Exception as error:
        return {
            "success": False,
            "message_id": message_id,
            "thread_id": None,
            "label_removed": label,
            "current_labels": None,
            "from": None,
            "subject": None,
            "error": f"Unexpected error: {str(error)}"
        }


def _download_attachment_impl(
    message_id: str, attachment_id: str, save_path: str, credentials_dict: Dict
) -> Dict[str, Any]:
    """Download an email attachment"""
    try:
        # get gmail service
        gmail_service = get_google_service("gmail", "v1", credentials_dict)

        # get the attachment
        attachment = (
            gmail_service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )

        # decode the attachment data
        file_data = base64.urlsafe_b64decode(attachment["data"])

        # save to file
        with open(save_path, "wb") as f:
            f.write(file_data)

        file_size = len(file_data)
        filename = os.path.basename(save_path)
        
        # get message details for context
        message = (
            gmail_service.users()
            .messages()
            .get(userId="me", id=message_id, format="metadata", metadataHeaders=["Subject", "From"])
            .execute()
        )
        
        thread_id = message.get("threadId", "")

        return {
            "success": True,
            "message_id": message_id,
            "thread_id": thread_id,
            "attachment_id": attachment_id,
            "filename": filename,
            "save_path": save_path,
            "file_size": file_size,
            "error": None
        }

    except FileNotFoundError:
        return {
            "success": False,
            "message_id": message_id,
            "thread_id": None,
            "attachment_id": attachment_id,
            "filename": None,
            "save_path": save_path,
            "file_size": 0,
            "error": f"Invalid save path: {save_path}"
        }
    except HttpError as error:
        return {
            "success": False,
            "message_id": message_id,
            "thread_id": None,
            "attachment_id": attachment_id,
            "filename": None,
            "save_path": save_path,
            "file_size": 0,
            "error": f"Gmail API error: {str(error)}"
        }
    except Exception as error:
        return {
            "success": False,
            "message_id": message_id,
            "thread_id": None,
            "attachment_id": attachment_id,
            "filename": None,
            "save_path": save_path,
            "file_size": 0,
            "error": f"Unexpected error: {str(error)}"
        }

def _search_emails_with_delivery_order_attachments_impl(
    query: str = "delivery order",
    max_results: int = 10,
    download_attachments: bool = True,
    temp_dir: str = None,
    credentials_dict: Dict = None
) -> Dict[str, Any]:
    """
    Search Gmail for emails with PDF or Excel attachments containing delivery orders.
    Extracts sender, subject, timestamp, and optionally downloads attachments.
    
    Args:
        query: Search query to find delivery order emails (default: "delivery order")
        max_results: Maximum number of emails to search (default: 10)
        download_attachments: Whether to download attachments (default: True)
        temp_dir: Temporary directory to save attachments. If None, creates a temp dir.
        credentials_dict: Gmail OAuth credentials
        
    Returns:
        Dictionary with success status, email metadata, attachment file paths, and errors
    """
    import tempfile
    import shutil
    from datetime import datetime
    
    try:
        # get gmail service
        gmail_service = get_google_service("gmail", "v1", credentials_dict)
        
        # Create temp directory if not provided and downloads are enabled
        created_temp_dir = False
        if download_attachments and not temp_dir:
            temp_dir = tempfile.mkdtemp(prefix="gmail_delivery_orders_")
            created_temp_dir = True
        
        # Search for emails with the query
        search_results = (
            gmail_service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                maxResults=max_results
            )
            .execute()
        )
        
        messages = search_results.get("messages", [])
        
        if not messages:
            return {
                "success": False,
                "emails_with_attachments": [],
                "total_emails_found": 0,
                "total_attachments_downloaded": 0,
                "temp_directory": temp_dir if created_temp_dir else None,
                "query": query,
                "error": f"No emails found matching query: '{query}'",
                "no_results": True
            }
        
        emails_with_attachments = []
        total_attachments_downloaded = 0
        
        # Process each message
        for msg in messages:
            msg_id = msg["id"]
            
            # Get message details with full format
            message = (
                gmail_service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )
            
            # Extract headers (From, Subject, Date)
            headers = message["payload"]["headers"]
            from_addr = ""
            subject = ""
            date = ""
            
            for header in headers:
                if header["name"] == "From":
                    from_addr = header["value"]
                elif header["name"] == "Subject":
                    subject = header["value"]
                elif header["name"] == "Date":
                    date = header["value"]
            
            # Get internal date
            internal_date = message.get("internalDate", "")
            
            # Convert internal date to readable format
            try:
                timestamp_ms = int(internal_date)
                readable_timestamp = datetime.fromtimestamp(timestamp_ms / 1000).isoformat()
            except (ValueError, TypeError):
                readable_timestamp = date if date else "Unknown"
            
            # Check for attachments
            attachment_list = []
            if "parts" in message["payload"]:
                for part in message["payload"]["parts"]:
                    filename = part.get("filename", "")
                    mime_type = part.get("mimeType", "")
                    attachment_id = part.get("body", {}).get("attachmentId")
                    
                    # Filter for PDF or Excel files
                    is_pdf = mime_type == "application/pdf"
                    is_excel = mime_type in [
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
                        "application/vnd.ms-excel",  # .xls
                        "application/vnd.google-apps.spreadsheet"  # Google Sheets
                    ]
                    
                    if (filename and attachment_id and (is_pdf or is_excel)):
                        attachment_info = {
                            "filename": filename,
                            "attachment_id": attachment_id,
                            "mime_type": mime_type,
                            "size": part.get("body", {}).get("size", 0),
                            "file_path": None
                        }
                        
                        # Download attachment if requested
                        if download_attachments and temp_dir:
                            try:
                                # Create subdirectory for this email's attachments
                                email_dir = os.path.join(temp_dir, msg_id)
                                os.makedirs(email_dir, exist_ok=True)
                                
                                # Build full file path
                                save_path = os.path.join(email_dir, filename)
                                
                                # Download the attachment
                                attachment_data = (
                                    gmail_service.users()
                                    .messages()
                                    .attachments()
                                    .get(userId="me", messageId=msg_id, id=attachment_id)
                                    .execute()
                                )
                                
                                # Decode and save
                                file_data = base64.urlsafe_b64decode(attachment_data.get("data", ""))
                                with open(save_path, "wb") as f:
                                    f.write(file_data)
                                
                                attachment_info["file_path"] = save_path
                                total_attachments_downloaded += 1
                                
                            except Exception as download_error:
                                attachment_info["download_error"] = str(download_error)
                        
                        attachment_list.append(attachment_info)
            
            # Only add to results if there are relevant attachments
            if attachment_list:
                email_obj = {
                    "message_id": msg_id,
                    "from": from_addr,
                    "subject": subject,
                    "date": date,
                    "timestamp": readable_timestamp,
                    "internal_date_ms": internal_date,
                    "attachments": attachment_list,
                    "attachment_count": len(attachment_list)
                }
                emails_with_attachments.append(email_obj)
        
        if not emails_with_attachments:
            # Clean up temp dir if we created it and found no attachments
            if created_temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass
            
            return {
                "success": False,
                "emails_with_attachments": [],
                "total_emails_found": len(messages),
                "total_attachments_downloaded": 0,
                "temp_directory": None,
                "query": query,
                "error": f"No emails found with PDF or Excel attachments matching query: '{query}'",
                "no_attachments": True
            }
        
        return {
            "success": True,
            "emails_with_attachments": emails_with_attachments,
            "total_emails_found": len(messages),
            "total_attachments_downloaded": total_attachments_downloaded,
            "temp_directory": temp_dir if created_temp_dir else None,
            "query": query,
            "download_attachments": download_attachments,
            "error": None
        }
    
    except HttpError as error:
        return {
            "success": False,
            "emails_with_attachments": [],
            "total_emails_found": 0,
            "total_attachments_downloaded": 0,
            "temp_directory": None,
            "query": query,
            "error": f"Gmail API error: {str(error)}"
        }
    except Exception as error:
        return {
            "success": False,
            "emails_with_attachments": [],
            "total_emails_found": 0,
            "total_attachments_downloaded": 0,
            "temp_directory": None,
            "query": query,
            "error": f"Unexpected error: {str(error)}"
        }


def _save_attachment_metadata_impl(
    metadata: Dict[str, Any],
    db_path: str = None,
    credentials_dict: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Save attachment metadata to SQLite database.
    
    Args:
        metadata: Dictionary with keys: message_id, filename, file_path, sender, subject, timestamp, mime_type, size
        db_path: Path to SQLite database (default: gmail_agent_data.db in current directory)
        credentials_dict: Credentials (not used but accepted for API consistency)
    
    Returns:
        Dictionary with success status, inserted_id, db_path, and error (if any)
    """
    try:
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), "gmail_agent_data.db")
        
        # Ensure db directory exists
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create attachments table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_path TEXT,
                sender TEXT,
                subject TEXT,
                timestamp TEXT,
                mime_type TEXT,
                size INTEGER,
                saved_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(message_id, filename)
            )
        """)
        
        # Insert the metadata
        saved_at = datetime.utcnow().isoformat()
        cursor.execute("""
            INSERT OR REPLACE INTO attachments 
            (message_id, filename, file_path, sender, subject, timestamp, mime_type, size, saved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metadata.get("message_id"),
            metadata.get("filename"),
            metadata.get("file_path"),
            metadata.get("sender"),
            metadata.get("subject"),
            metadata.get("timestamp"),
            metadata.get("mime_type"),
            metadata.get("size"),
            saved_at
        ))
        
        conn.commit()
        inserted_id = cursor.lastrowid
        conn.close()
        
        return {
            "success": True,
            "inserted_id": inserted_id,
            "db_path": db_path,
            "saved_at": saved_at,
            "error": None
        }
    
    except sqlite3.IntegrityError as e:
        return {
            "success": False,
            "inserted_id": None,
            "db_path": db_path if db_path else "unknown",
            "error": f"Duplicate entry: {str(e)}"
        }
    
    except Exception as e:
        return {
            "success": False,
            "inserted_id": None,
            "db_path": db_path if db_path else "unknown",
            "error": f"Database error: {str(e)}"
        }


def _process_delivery_order_workflow_impl(
    query: str,
    max_results: int = 10,
    download_attachments: bool = True,
    save_to_db: bool = True,
    upload_to_sheets: bool = True,
    sheets_sheet_id: str = None,
    create_summary_doc: bool = True,
    summary_doc_title: str = None,
    mapping_agent_url: str = None,
    sheets_agent_url: str = None,
    docs_agent_url: str = None,
    credentials_dict: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    End-to-end delivery order automation workflow:
    1. Search Gmail for delivery order emails with attachments
    2. Parse files using mapping agent
    3. Transform data using mapping agent
    4. Upload results to Google Sheets
    5. Save metadata to local database
    6. Create summary document in Google Docs (optional)
    
    Args:
        query: Gmail search query (e.g., "delivery order from:sender@company.com")
        max_results: Maximum emails to process
        download_attachments: Whether to download files during search
        save_to_db: Whether to save metadata to database
        upload_to_sheets: Whether to upload results to Google Sheets
        sheets_sheet_id: Google Sheets ID (required if upload_to_sheets=True)
        create_summary_doc: Whether to create summary document in Google Docs
        summary_doc_title: Title for summary document (default: "Delivery Orders - {date}")
        mapping_agent_url: URL of mapping agent (default from env MAPPING_AGENT_URL)
        sheets_agent_url: URL of sheets agent (default from env SHEETS_AGENT_URL)
        docs_agent_url: URL of docs agent (default from env DOCS_AGENT_URL)
        credentials_dict: OAuth credentials dict
    
    Returns:
        Dictionary with success status, processed items, summary, document_url, and error (if any)
    """
    try:
        # Get agent URLs from parameters or environment
        if mapping_agent_url is None:
            mapping_agent_url = os.getenv("MAPPING_AGENT_URL", "http://localhost:8002")
        if sheets_agent_url is None:
            sheets_agent_url = os.getenv("SHEETS_AGENT_URL", "http://localhost:8001")
        if docs_agent_url is None:
            docs_agent_url = os.getenv("DOCS_AGENT_URL", "http://localhost:8003")
        
        processed = []
        errors = []
        document_url = None
        
        # Step 1: Search for delivery orders with attachments
        search_result = _search_emails_with_delivery_order_attachments_impl(
            query=query,
            max_results=max_results,
            download_attachments=download_attachments,
            credentials_dict=credentials_dict
        )
        
        if not search_result["success"]:
            return {
                "success": False,
                "processed": [],
                "search_summary": search_result,
                "error": search_result.get("error", "Search failed")
            }
        
        emails_with_attachments = search_result["emails_with_attachments"]
        temp_dir = search_result["temp_directory"]
        
        # Process each attachment
        for email_item in emails_with_attachments:
            try:
                email_id = email_item["id"]
                attachments = email_item.get("attachments", [])
                
                for attachment in attachments:
                    try:
                        file_path = attachment.get("file_path")
                        filename = attachment.get("filename")
                        
                        if not file_path or not os.path.exists(file_path):
                            errors.append(f"File not found: {file_path}")
                            continue
                        
                        # Step 2: Parse file using mapping agent
                        with open(file_path, 'rb') as f:
                            file_content = base64.b64encode(f.read()).decode('utf-8')
                        
                        parse_payload = {
                            "tool": "parse_file",
                            "inputs": {
                                "file_path": file_path,
                                "file_name": filename,
                                "file_content": file_content
                            },
                            "credentials_dict": credentials_dict or {}
                        }
                        
                        async_parse = httpx.post(
                            f"{mapping_agent_url}/execute_task",
                            json=parse_payload,
                            timeout=30.0
                        )
                        parse_result = async_parse.json()
                        
                        if not parse_result.get("success"):
                            errors.append(f"Parse failed for {filename}: {parse_result.get('error')}")
                            continue
                        
                        parsed_data = parse_result.get("parsed_data", {})
                        
                        # Step 3: Transform data using mapping agent
                        transform_payload = {
                            "tool": "transform_data",
                            "inputs": {
                                "data": parsed_data,
                                "target_schema": "delivery_order"
                            },
                            "credentials_dict": credentials_dict or {}
                        }
                        
                        transform_response = httpx.post(
                            f"{mapping_agent_url}/execute_task",
                            json=transform_payload,
                            timeout=30.0
                        )
                        transform_result = transform_response.json()
                        
                        if not transform_result.get("success"):
                            errors.append(f"Transform failed for {filename}: {transform_result.get('error')}")
                            continue
                        
                        transformed_data = transform_result.get("transformed_data", {})
                        
                        # Step 4: Upload to Google Sheets (if enabled)
                        if upload_to_sheets and sheets_sheet_id:
                            upload_payload = {
                                "tool": "upload_mapped_data",
                                "inputs": {
                                    "sheet_id": sheets_sheet_id,
                                    "data": transformed_data,
                                    "append": True
                                },
                                "credentials_dict": credentials_dict or {}
                            }
                            
                            upload_response = httpx.post(
                                f"{sheets_agent_url}/execute_task",
                                json=upload_payload,
                                timeout=30.0
                            )
                            upload_result = upload_response.json()
                            
                            if not upload_result.get("success"):
                                errors.append(f"Upload failed for {filename}: {upload_result.get('error')}")
                                continue
                        
                        # Step 5: Save metadata to database (if enabled)
                        if save_to_db:
                            metadata = {
                                "message_id": email_id,
                                "filename": filename,
                                "file_path": file_path,
                                "sender": email_item.get("from"),
                                "subject": email_item.get("subject"),
                                "timestamp": email_item.get("date"),
                                "mime_type": attachment.get("mime_type"),
                                "size": attachment.get("size")
                            }
                            
                            db_result = _save_attachment_metadata_impl(metadata, credentials_dict=credentials_dict)
                            if not db_result["success"]:
                                errors.append(f"Failed to save metadata for {filename}: {db_result.get('error')}")
                        
                        # Record successful processing
                        processed.append({
                            "file_name": filename,
                            "email_id": email_id,
                            "email_from": email_item.get("from"),
                            "email_subject": email_item.get("subject"),
                            "parsed_successfully": True,
                            "transformed_successfully": True,
                            "uploaded": upload_to_sheets and sheets_sheet_id,
                            "metadata_saved": save_to_db
                        })
                    
                    except Exception as e:
                        errors.append(f"Error processing attachment {filename}: {str(e)}")
                        continue
            
            except Exception as e:
                errors.append(f"Error processing email {email_id}: {str(e)}")
                continue
        
        # Clean up temp directory if needed
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
        
        # Step 6: Create summary document in Google Docs (if enabled)
        if create_summary_doc and len(processed) > 0:
            try:
                # Generate default title if not provided
                if summary_doc_title is None:
                    from datetime import datetime
                    today = datetime.now().strftime("%Y-%m-%d")
                    summary_doc_title = f"Delivery Orders Summary - {today}"
                
                # Build document content
                doc_content = f"# {summary_doc_title}\n\n"
                doc_content += f"**Processing Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                doc_content += f"**Total Orders Processed:** {len(processed)}\n\n"
                doc_content += "---\n\n"
                
                # Add details for each processed order
                for i, item in enumerate(processed, 1):
                    doc_content += f"## Order {i}: {item.get('file_name', 'Unknown')}\n\n"
                    doc_content += f"**From:** {item.get('email_from', 'Unknown')}\n\n"
                    doc_content += f"**Subject:** {item.get('email_subject', 'N/A')}\n\n"
                    doc_content += f"**Status:**\n"
                    doc_content += f"- Parsed: {'✓' if item.get('parsed_successfully') else '✗'}\n"
                    doc_content += f"- Transformed: {'✓' if item.get('transformed_successfully') else '✗'}\n"
                    doc_content += f"- Uploaded to Sheets: {'✓' if item.get('uploaded') else '✗'}\n"
                    doc_content += f"- Metadata Saved: {'✓' if item.get('metadata_saved') else '✗'}\n\n"
                    doc_content += "---\n\n"
                
                # Add errors section if any
                if errors:
                    doc_content += "## Processing Errors\n\n"
                    for error in errors:
                        doc_content += f"- {error}\n\n"
                
                # Create document via Docs agent
                doc_payload = {
                    "tool": "create_document",
                    "inputs": {
                        "title": summary_doc_title,
                        "content": doc_content,
                        "folder_id": None  # Creates in root of My Drive
                    },
                    "credentials_dict": credentials_dict or {}
                }
                
                doc_response = httpx.post(
                    f"{docs_agent_url}/execute_task",
                    json=doc_payload,
                    timeout=30.0
                )
                
                if doc_response.status_code == 200:
                    doc_result = doc_response.json()
                    if doc_result.get("success"):
                        document_url = doc_result.get("document_url") or doc_result.get("document_id")
                    else:
                        errors.append(f"Failed to create document: {doc_result.get('error', 'Unknown error')}")
                else:
                    errors.append(f"Docs agent error: {doc_response.status_code}")
            
            except Exception as e:
                errors.append(f"Document creation error: {str(e)}")
        
        # Compile results
        result = {
            "success": len(errors) == 0 or len(processed) > 0,
            "processed": processed,
            "search_summary": {
                "total_emails_found": search_result.get("total_emails_found", 0),
                "total_attachments_found": len(emails_with_attachments),
                "errors_occurred": len(errors) > 0
            },
            "document_url": document_url,
            "errors": errors if errors else None,
            "error": None if (len(errors) == 0 or len(processed) > 0) else "No items processed successfully"
        }
        
        return result
    
    except Exception as e:
        return {
            "success": False,
            "processed": [],
            "search_summary": {},
            "error": f"Workflow error: {str(e)}"
        }