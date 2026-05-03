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
import html
from email_formatter import format_email_list, clean_email_body
import sqlite3
import json
import tempfile
import shutil
import httpx
from datetime import datetime


def get_google_service(service_name: str, version: str, credentials_dict: Dict):

    # credentials for google services
    #
    # NOTE: scopes= is intentionally omitted. The refresh_token is minted with
    # its own granted scope set by generate_gmail_tokens.py; passing a narrower
    # or different list here makes google-auth send a mismatched `scope`
    # parameter on refresh, which Google rejects with
    #     RefreshError: ('invalid_scope: Bad Request', {...})
    # even when the refresh_token actually covers all the Gmail scopes we need.
    # The access_token returned by refresh is already limited to whatever the
    # refresh_token was granted, so there is no privilege risk in omitting
    # scopes here â€” we just stop the spurious preflight mismatch.
    creds = Credentials(
        token=credentials_dict["access_token"],
        refresh_token=credentials_dict.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=credentials_dict.get("client_id", ""),
        client_secret=credentials_dict.get("client_secret", ""),
    )

    service = build(service_name, version, credentials=creds)
    return service


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


def _walk_mime_parts(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively walk a Gmail API message payload and extract body + attachment
    references. Handles arbitrarily nested multipart/* structures (mixed,
    alternative, related), which the previous top-level-only loop missed.

    Returns:
        {
          "plain_body": str,   # first text/plain content found, decoded UTF-8
          "html_body":  str,   # first text/html  content found, decoded UTF-8
          "attachments": [{"filename", "attachment_id", "mime_type", "size"}]
        }
    """
    result = {"plain_body": "", "html_body": "", "attachments": []}

    def _walk(part: Dict[str, Any]) -> None:
        mime = (part.get("mimeType") or "").lower()
        body = part.get("body") or {}
        filename = part.get("filename") or ""

        if mime.startswith("multipart/"):
            for sub in (part.get("parts") or []):
                _walk(sub)
            return

        if filename and body.get("attachmentId"):
            result["attachments"].append({
                "filename": filename,
                "attachment_id": body["attachmentId"],
                "mime_type": part.get("mimeType") or "application/octet-stream",
                "size": body.get("size", 0),
            })
            return

        data = body.get("data")
        if not data:
            return
        try:
            decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        except Exception:
            return
        if mime == "text/plain" and not result["plain_body"]:
            result["plain_body"] = decoded
        elif mime == "text/html" and not result["html_body"]:
            result["html_body"] = decoded

    _walk(payload)
    return result


def _forward_email_impl(
    message_id: str, to: str, forward_message: str = "", credentials_dict: Dict = None
) -> Dict[str, Any]:
    """Forward an email verbatim (HTML body + attachments) via Gmail API.

    Mirrors "Forward" in the Gmail web UI: the forwarded message contains the
    original HTML rendering AND a plain-text alternative, plus any original
    attachments re-attached in a multipart/mixed envelope.

    Args:
        message_id: The ID of the email message to forward
        to: Recipient email address to forward to
        forward_message: Optional note prepended before the forwarded content
        credentials_dict: Gmail OAuth credentials

    Returns:
        Dictionary with success status and forwarded email details.
    """
    try:
        gmail_service = get_google_service("gmail", "v1", credentials_dict)

        original_message = (
            gmail_service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

        payload = original_message.get("payload") or {}
        headers = payload.get("headers") or []
        original_subject = ""
        original_from = ""
        original_date = ""

        for header in headers:
            name = header.get("name", "")
            value = header.get("value", "")
            if name == "Subject":
                original_subject = value
            elif name == "From":
                original_from = value
            elif name == "Date":
                original_date = value

        extracted = _walk_mime_parts(payload)
        original_plain = extracted["plain_body"]
        original_html = extracted["html_body"]
        original_attachments = extracted["attachments"]

        if not original_plain and original_html:
            try:
                original_plain = clean_email_body(original_html).get("clean_text", "") or ""
            except Exception:
                original_plain = ""

        if not original_plain and not original_html:
            original_plain = original_message.get("snippet", "") or ""

        forward_subject = (
            f"Fwd: {original_subject}"
            if not original_subject.startswith("Fwd:")
            else original_subject
        )

        plain_header = (
            "---------- Forwarded message ---------\n"
            f"From: {original_from}\n"
            f"Date: {original_date}\n"
            f"Subject: {original_subject}\n\n"
        )
        forward_plain_body = ""
        if forward_message:
            forward_plain_body += f"{forward_message}\n\n"
        forward_plain_body += plain_header + (original_plain or "")

        forward_html_body = None
        if original_html:
            html_header = (
                "<br><div>---------- Forwarded message ---------<br>"
                f"<b>From:</b> {html.escape(original_from)}<br>"
                f"<b>Date:</b> {html.escape(original_date)}<br>"
                f"<b>Subject:</b> {html.escape(original_subject)}<br>"
                "</div><br>"
            )
            html_intro = ""
            if forward_message:
                escaped_note = html.escape(forward_message).replace("\n", "<br>")
                html_intro = f"<div>{escaped_note}</div><br>"
            forward_html_body = html_intro + html_header + original_html

        has_html = forward_html_body is not None
        has_attachments = bool(original_attachments)

        if has_attachments:
            root = MIMEMultipart("mixed")
            if has_html:
                alt = MIMEMultipart("alternative")
                alt.attach(MIMEText(forward_plain_body, "plain", "utf-8"))
                alt.attach(MIMEText(forward_html_body, "html", "utf-8"))
                root.attach(alt)
            else:
                root.attach(MIMEText(forward_plain_body, "plain", "utf-8"))
        elif has_html:
            root = MIMEMultipart("alternative")
            root.attach(MIMEText(forward_plain_body, "plain", "utf-8"))
            root.attach(MIMEText(forward_html_body, "html", "utf-8"))
        else:
            root = MIMEText(forward_plain_body, "plain", "utf-8")

        root["to"] = to
        root["subject"] = forward_subject

        forwarded_attachment_names = []
        for att in original_attachments:
            try:
                att_blob = (
                    gmail_service.users()
                    .messages()
                    .attachments()
                    .get(userId="me", messageId=message_id, id=att["attachment_id"])
                    .execute()
                )
                att_bytes = base64.urlsafe_b64decode(att_blob["data"])
            except Exception as att_err:
                print(f"[forward_email] Skipping attachment '{att['filename']}' â€” fetch failed: {att_err}")
                continue

            mime_type = att.get("mime_type") or "application/octet-stream"
            maintype, _, subtype = mime_type.partition("/")
            if not subtype:
                maintype, subtype = "application", "octet-stream"
            att_part = MIMEBase(maintype, subtype)
            att_part.set_payload(att_bytes)
            encoders.encode_base64(att_part)
            att_part.add_header(
                "Content-Disposition",
                f'attachment; filename="{att["filename"]}"',
            )
            root.attach(att_part)
            forwarded_attachment_names.append(att["filename"])

        raw_message = base64.urlsafe_b64encode(root.as_bytes()).decode()

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
            "attachments_forwarded": forwarded_attachment_names,
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
            "attachments_forwarded": [],
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
            "attachments_forwarded": [],
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
            # In Lambda, /var/task is read-only. Default to /tmp which is
            # the only writable location at runtime. The SQLite file is a
            # local scratchpad anyway — no requirement to persist it
            # across invocations.
            if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
                db_path = "/tmp/gmail_agent_data.db"
            else:
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
