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


def get_google_service(service_name: str, version: str, credentials_dict: Dict):

    # credentials for google services
    creds = Credentials(
        token=credentials_dict["access_token"],
        refresh_token=credentials_dict.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scopes=[
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.readonly",
        ],
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
        email_list = []
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
            email_list.append(email_obj)
        
        # Format all emails before returning
        email_list = format_email_list(email_list)
        
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
