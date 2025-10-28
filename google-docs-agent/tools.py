import os
from typing import Dict, Any
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from document_format_extractor import DocumentFormatExtractor


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


def _edit_google_doc_impl(
    document_id: str, old_text: str, new_text: str, credentials_dict: Dict
) -> str:
    """Implementation of editing/replacing text in a Google Doc

    Args:
        document_id: The ID of the document to edit
        old_text: The text to find and replace
        new_text: The replacement text
        credentials_dict: Google OAuth credentials

    Returns:
        Success message with edit details
    """
    try:
        docs_service = get_google_service("docs", "v1", credentials_dict)

        # First, read the document to find the old text
        document = docs_service.documents().get(documentId=document_id).execute()

        # Extract full document text to find the position
        full_text = ""
        content = document.get("body", {}).get("content", [])

        for element in content:
            if "paragraph" in element:
                paragraph_elements = element["paragraph"].get("elements", [])
                for para_element in paragraph_elements:
                    if "textRun" in para_element:
                        full_text += para_element["textRun"].get("content", "")

        # Find the position of old_text
        if old_text not in full_text:
            return f"Error: Text '{old_text}' not found in document"

        # Calculate start and end indices
        start_index = full_text.index(old_text) + 1  # +1 because Docs API is 1-indexed
        end_index = start_index + len(old_text)

        # Create the batch update requests
        requests = [
            # First, delete the old text
            {
                "deleteContentRange": {
                    "range": {"startIndex": start_index, "endIndex": end_index}
                }
            },
            # Then, insert the new text at the same position
            {"insertText": {"location": {"index": start_index}, "text": new_text}},
        ]

        # Execute the batch update
        result = (
            docs_service.documents()
            .batchUpdate(documentId=document_id, body={"requests": requests})
            .execute()
        )

        doc_url = f"https://docs.google.com/document/d/{document_id}/edit"
        return (
            f"Text edited successfully!\n"
            f"Replaced: '{old_text}'\n"
            f"With: '{new_text}'\n"
            f"Document ID: {document_id}\n"
            f"URL: {doc_url}"
        )

    except HttpError as error:
        return f"Error editing document: {error}"
    except ValueError as error:
        return f"Text not found in document: {error}"
    except Exception as error:
        return f"Unexpected error: {error}"


def _update_entire_doc_impl(
    document_id: str, new_content: str, credentials_dict: Dict
) -> str:
    """Implementation of replacing entire document content

    Args:
        document_id: The ID of the document to update
        new_content: The new complete content for the document
        credentials_dict: Google OAuth credentials

    Returns:
        Success message with update details
    """
    try:
        docs_service = get_google_service("docs", "v1", credentials_dict)

        # First, get the document to find the end index
        document = docs_service.documents().get(documentId=document_id).execute()

        # Calculate the end index (total length of current content)
        end_index = document.get("body", {}).get("content", [{}])[-1].get("endIndex", 1)

        # Create batch update requests
        requests = []

        # Only delete if there's content to delete (end_index > 2)
        if end_index > 2:
            requests.append(
                {
                    "deleteContentRange": {
                        "range": {
                            "startIndex": 1,
                            "endIndex": end_index
                            - 1,  # -1 to avoid deleting the protected last character
                        }
                    }
                }
            )

        # Always insert new content at the beginning
        requests.append({"insertText": {"location": {"index": 1}, "text": new_content}})

        # Execute the batch update
        result = (
            docs_service.documents()
            .batchUpdate(documentId=document_id, body={"requests": requests})
            .execute()
        )

        doc_url = f"https://docs.google.com/document/d/{document_id}/edit"
        return (
            f"Document content updated successfully!\n"
            f"Document ID: {document_id}\n"
            f"New content length: {len(new_content)} characters\n"
            f"URL: {doc_url}"
        )

    except HttpError as error:
        return f"Error updating document: {error}"
    except Exception as error:
        return f"Unexpected error: {error}"


def _list_user_docs_impl(credentials_dict: Dict, search_query: str = "") -> str:
    """List user's Google Docs (to find their templates)

    Args:
        credentials_dict: Google OAuth credentials
        search_query: Optional search term (e.g., "template", "MOM")

    Returns:
        Formatted list of user's documents
    """
    try:
        extractor = DocumentFormatExtractor(credentials_dict)
        docs = extractor.list_my_docs(search_query)

        if not docs:
            return "No documents found. Please upload a template document to your Google Drive first."

        result = f"📁 Found {len(docs)} document(s):\n\n"
        for i, doc in enumerate(docs, 1):
            result += f"{i}. {doc['name']}\n"
            result += f"   ID: {doc['id']}\n"
            result += f"   URL: {doc['url']}\n"
            result += f"   Modified: {doc['modified']}\n\n"

        return result

    except Exception as error:
        return f"Error listing documents: {error}"


def _extract_template_structure_impl(
    template_document_id: str, credentials_dict: Dict
) -> str:
    """Extract formatting and structure from a reference document

    Args:
        template_document_id: ID of the template document
        credentials_dict: Google OAuth credentials

    Returns:
        Summary of extracted structure
    """
    try:
        extractor = DocumentFormatExtractor(credentials_dict)
        structure = extractor.extract_document_structure(template_document_id)

        if "error" in structure:
            return structure["error"]

        # Identify placeholders
        placeholders = extractor.identify_placeholders(structure)

        result = f"✅ Template Structure Extracted!\n\n"
        result += f"📄 Template: {structure['title']}\n"
        result += f"📝 Content Blocks: {len(structure['content_blocks'])}\n\n"

        if placeholders:
            result += f"🔍 Found Placeholders:\n"
            for placeholder in placeholders:
                result += f"   • [{placeholder}]\n"
            result += f"\n💡 You can fill these when creating a new document.\n"
        else:
            result += "ℹ️ No placeholders found. This template will be copied as-is.\n"

        result += f"\n📋 Document ID: {template_document_id}"

        return result

    except Exception as error:
        return f"Error extracting template: {error}"


def _create_from_reference_impl(
    template_document_id: str,
    new_title: str,
    placeholder_values: Dict[str, str],
    credentials_dict: Dict,
) -> str:
    """Create a new document based on user's reference template

    Args:
        template_document_id: ID of the template document
        new_title: Title for the new document
        placeholder_values: Dict of placeholder replacements
            Example: {"DATE": "Jan 15, 2025", "VENUE": "Room A"}
        credentials_dict: Google OAuth credentials

    Returns:
        Success message with new document details
    """
    try:
        extractor = DocumentFormatExtractor(credentials_dict)

        result = extractor.create_from_template(
            template_document_id=template_document_id,
            new_title=new_title,
            placeholder_values=placeholder_values,
        )

        if result.get("success"):
            response = f"✅ Document created from your template!\n\n"
            response += f"📄 Title: {result['title']}\n"
            response += f"📋 Template Used: {result['template_used']}\n"
            response += f"🆔 Document ID: {result['document_id']}\n"
            response += f"🔗 URL: {result['url']}\n"

            if placeholder_values:
                response += f"\n✏️ Placeholders Filled:\n"
                for key, value in placeholder_values.items():
                    response += f"   • [{key}] → {value}\n"

            return response
        else:
            return f"❌ Error: {result.get('error')}"

    except Exception as error:
        return f"Error creating document: {error}"
