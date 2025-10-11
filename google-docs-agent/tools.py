import os
from typing import Dict, Any
from langchain.tools import tool
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def get_google_service(service_name: str, version: str, credentials_dict: Dict):

    # credentials for google services
    creds = Credentials(
        token=credentials_dict["access_token"],
        refresh_token=credentials_dict.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scopes=[
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    # this uses the credentials for the google services
    service = build(service_name, version, credentials=creds)

    return service


# Plain function without decorator - can be used directly or wrapped
def _create_google_doc_impl(title: str, credentials_dict: Dict) -> str:
    """Implementation of Google Doc creation logic"""
    # create a google docs document
    try:
        # This connects to the google docs api
        docs_service = get_google_service("docs", "v1", credentials_dict)
        # creates document structure
        doc = {"title": title}

        # sends request to Google to create the document
        document = docs_service.documents().create(body=doc).execute()

        # extracts document id from google's response
        doc_id = document.get("documentId")

        # build the url for users
        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

        # return success message
        return f"Document created successfully!\nTitle: {title}\nID: {doc_id}\nURL: {doc_url}"

    except HttpError as error:
        return f"error in creating document: {error}"
    except KeyError as error:
        return f"Missing credentials: {error}"
    except Exception as error:
        return f"Unexpected error: {error}"


# Decorated version for standalone use
@tool
def create_google_doc(title: str, credentials_dict: Dict) -> str:
    """
    Creates a new Google Doc and returns its ID and URL.

    This tool connects to the Google Docs API and creates a blank document
    with the specified title.

    Args:
        title: The name of the document (e.g., "Project Notes")
        credentials_dict: User's OAuth tokens (access_token, refresh_token)

    Returns:
        Success message with document ID and URL, or error message
    """
    return _create_google_doc_impl(title, credentials_dict)


def _add_text_to_doc_impl(document_id: str, text: str, credentials_dict: Dict) -> str:
    """Implementation of adding text to a Google Doc"""
    try:
        docs_service = get_google_service("docs", "v1", credentials_dict)
        # Create the request body for inserting text
        requests = [{"insertText": {"location": {"index": 1}, "text": text}}]
        result = (
            docs_service.documents()
            .batchUpdate(documentId=document_id, body={"requests": requests})
            .execute()
        )
        doc_url = f"https://docs.google.com/document/d/{document_id}/edit"
        return f"Text added successfully!\nDocument ID: {document_id}\nURL: {doc_url}"
    except HttpError as error:
        return f"error adding text to document: {error}"
    except KeyError as error:
        return f"Missing credentials: {error}"
    except Exception as error:
        return f"Unexpected error: {error}"


@tool
def add_text_to_doc(document_id: str, text: str, credentials_dict: Dict) -> str:
    """
    Adds text to an existing Google Doc.

    This tool connects to the Google Docs API and inserts text at the beginning of the specified document.

    Args:
        document_id: The ID of the document to update
        text: The text to insert into the document
        credentials_dict: User's OAuth tokens (access_token, refresh_token)

    Returns:
        Success message with document ID and URL, or error message
    """
    return _add_text_to_doc_impl(document_id, text, credentials_dict)


def _read_google_doc_impl(document_id: str, credentials_dict: Dict) -> str:
    """Implementation of reading text from a Google Doc"""
    try:
        docs_service = get_google_service("docs", "v1", credentials_dict)
        document = docs_service.documents().get(documentId=document_id).execute()
        # initilize empty string to collect text
        text = ""

        # gets the content array from document body
        content = document.get("body", {}).get("content", [])

        # loop through each element in the content
        for element in content:
            # this checks if the element is a paragraph
            if "paragraph" in element:
                # get the element in the paragraph
                paragraph_elements = element["paragraph"].get("elements", [])

                # loop through each element in the paragraph
                for para_element in paragraph_elements:
                    # check if the element contains text
                    if "textRun" in para_element:
                        # extract the text content and add it to the string
                        text += para_element["textRun"].get("content", "")

        # return the extracted text with document info
        doc_url = f"https://docs.google.com/document/d/{document_id}/edit"
        return (
            f"Document content:\n\n{text}\n\nDocument ID: {document_id}\nURL: {doc_url}"
        )
    except HttpError as error:
        return f"error reading document: {error}"
    except KeyError as error:
        return f"Missing field in document: {error}"
    except Exception as error:
        return f"Unexpected error: {error}"


@tool
def read_google_doc(document_id: str, credentials_dict: Dict) -> str:
    """
    Reads text content from a Google Doc.

    This tool connects to the Google Docs API and retrieves the text
    content from the specified document.

    Args:
        document_id: The ID of the document to read
        credentials_dict: User's OAuth tokens

    Returns:
        Document text content with document ID and URL
    """
    return _read_google_doc_impl(document_id, credentials_dict)


def _share_google_docs_impl(
    document_id: str, email: str, role: str, credentials_dict: Dict
) -> str:
    """Implementation of sharing a Google Doc with a user via email

    Args:
        document_id: The ID of the document to share
        email: Email address of the person to share with
        role: Permission level - 'reader', 'commenter', 'writer'
        credentials_dict: Google OAuth credentials

    Returns:
        Success message with sharing details
    """
    try:
        drive_service = get_google_service("drive", "v3", credentials_dict)
        # Define the permission body
        permission = {
            "type": "user",
            "role": role,  # 'reader', 'commenter', 'writer'
            "emailAddress": email,
        }

        # Create the permission
        drive_service.permissions().create(
            fileId=document_id,
            body=permission,
            fields="id",
        ).execute()
        # return success message
        doc_url = f"https://docs.google.com/document/d/{document_id}/edit"
        return f"Document shared successfully!\nShared with: {email}\nPermission: {role}\nURL: {doc_url}"

    except HttpError as error:
        return f"error sharing document: {error}"
    except Exception as error:
        return f"unexpected error: {error}"


@tool
def share_google_doc(
    document_id: str, email: str, role: str, credentials_dict: Dict
) -> str:
    """
    Shares a Google Doc with someone via email.

    Args:
        document_id: The ID of the document to share
        email: Email address to share with (e.g., 'user@example.com')
        role: Permission level - 'reader', 'writer', or 'commenter'
        credentials_dict: User's OAuth tokens

    Returns:
        Success message with sharing details
    """
    return _share_google_docs_impl(document_id, email, role, credentials_dict)
