import os
from typing import Dict, Any
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


def get_google_service(service_name: str, version: str, credentials_dict: Dict):

    # credentials for google services
    creds = Credentials(
        token=credentials_dict["access_token"],
        refresh_token=credentials_dict.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scopes=[
            "https://www.googleapis.com/auth/gmail.modify",
        ],
    )

    service = build(service_name, version, credentials=creds)
    return service


def _send_email_impl(to: str, subject: str, body: str, credentials_dict: Dict) -> str:
    """
    Implementation of sending email logic

    Args:
        to: Recipient email address
        subject: Subject of the email
        body: Email body text
        credentials_dict: Google OAuth credentials

    Returns:
        Success message or error
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

        return f"Email sent successfully!\nTo: {to}\nSubject: {subject}\nMessage ID: {send_result['id']}"

    except HttpError as error:
        return f"Error in sending email: {error}"
    except Exception as error:
        return f"Unexpected error: {error}"

def _read_recent_emails_impl(max_results: int, credentials_dict: Dict) -> str:
    """Read recent emails from Gmail"""
    try:
        # get gmail service
        gmail_service = get_google_service("gmail", "v1", credentials_dict)

        # list message IDs
        results = (
            gmail_service.users()
            .messages()
            .list(
                userId="me",
                maxResults=max_results,
            )
            .execute()
        )

        messages = results.get("messages", [])

        # check if empty
        if not messages:
            return "No emails found in inbox"

        # loops through the messages and fetches details
        email_list = []
        for msg in messages:
            # get message details
            message = (
                gmail_service.users()
                .messages()
                .get(userId="me", id=msg["id"])
                .execute()
            )

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

            # get snipper(preview)
            snippet = message.get("snippet", "")

            # get message ID for replies
            msg_id = msg["id"]

            # format this email
            email_info = f"Message ID: {msg_id}\nFrom: {from_addr}\nSubject: {subject}\nDate: {date}\nSnippet: {snippet}\n"
            email_list.append(email_info)

        # combine all emails into single string
        result = f"Recent Emails ({len(email_list)}):\n\n"
        result += "\n---\n".join(email_list)

        return result

    except HttpError as error:
        return f"Gmail API error: {error}"
    except Exception as error:
        return f"Unexpected error: {error}"

def _search_emails_impl(query: str, max_results: int, credentials_dict: Dict) -> str:
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
            )
            .execute()
        )

        messages = results.get("messages", [])

        # check if empty
        if not messages:
            return "No emails found matching query"

        # loops through the messages and fetches details
        email_list = []
        for msg in messages:
            # get message details
            message = (
                gmail_service.users()
                .messages()
                .get(userId="me", id=msg["id"])
                .execute()
            )

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

            # get snipper(preview)
            snippet = message.get("snippet", "")

            # get message ID for searches/replies
            msg_id = msg["id"]

            # format this email
            email_info = f"Message ID: {msg_id}\nFrom: {from_addr}\nSubject: {subject}\nDate: {date}\nSnippet: {snippet}\n"
            email_list.append(email_info)

        # combine all emails into single string
        result = f"Search results ({len(email_list)}):\n\n"
        result += "\n---\n".join(email_list)

        return result

    except HttpError as error:
        return f"Gmail API error: {error}"
    except Exception as error:
        return f"Unexpected error: {error}"

def _send_email_with_attachments_impl(
    to: str, subject: str, body: str, file_path: str, credentials_dict: Dict
) -> str:
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
            return f"Error: File not found at {file_path}"
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

        return f"Email with attachment sent successfully!\nTo: {to}\nSubject: {subject}\nAttachment: {filename}\nMessage ID: {send_result['id']}"

    except FileNotFoundError:
        return f"Error: File not found at {file_path}"
    except HttpError as error:
        return f"Gmail API error: {error}"
    except Exception as error:
        return f"Unexpected error: {error}"

def _reply_to_email_impl(
    message_id: str, reply_body: str, credentials_dict: Dict
) -> str:
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

        return f"Reply sent successfully!\nTo: {to_email}\nSubject: {subject}\nMessage ID: {send_result['id']}"

    except HttpError as error:
        return f"Gmail API error: {error}"
    except Exception as error:
        return f"Unexpected error: {error}"
