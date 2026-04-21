"""
Google Drive Agent API - Supervisor-Compatible Version
Handles Google Drive operations via /execute_task endpoint
"""

from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import os
import re
import json
import uvicorn
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload, MediaIoBaseDownload
import io
import tempfile


_DRIVE_FILE_URL_RE = re.compile(r"/file/d/([A-Za-z0-9_-]+)")
_DRIVE_DOC_URL_RE = re.compile(r"/document/d/([A-Za-z0-9_-]+)")
_DRIVE_SHEET_URL_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")


def _extract_drive_file_id(file_id_or_url: str) -> str:
    """Extract a Drive file ID from a URL or return the input as-is.

    Handles Drive view links (/file/d/<id>/view), Docs URLs (/document/d/<id>),
    and Sheets URLs (/spreadsheets/d/<id>) so a planner or user who pasted a
    full URL into a file_id slot will not break the call. No-op for strings
    that already look like a bare ID, so it is safe to call at the top of a
    tool that accepts file_id.
    """
    if not file_id_or_url:
        return file_id_or_url
    for pattern in (_DRIVE_FILE_URL_RE, _DRIVE_DOC_URL_RE, _DRIVE_SHEET_URL_RE):
        match = pattern.search(file_id_or_url)
        if match:
            return match.group(1)
    return file_id_or_url.strip()

# Import your existing tools (supervisor-compatible versions)
from tools import (
    get_session_drive_service,
    get_token_drive_service,
    create_nested_folder_impl,
    upload_file_to_folder_impl,
    upload_stream_to_folder_impl,
    list_folders_in_safeexpress_impl,
    list_files_in_folder_impl,
    get_folder_structure_impl,
    search_files_in_safeexpress_impl,
    get_folder_info_impl,
    get_safeexpress_folder_id,
    find_folder,
    resolve_folder_path_to_id,
    move_file_impl,
    # Legacy compatibility
    create_nested_folder,
    upload_stream_to_folder,
    list_folders_in_safeexpress,
    list_files_in_folder,
    get_folder_structure,
    search_files_in_safeexpress,
    rename_file_impl,
)

# Initialize FastAPI app
app = FastAPI(
    title="SafexpressOps Google Drive Agent API",
    description="AI-powered Google Drive file management API integrated with Supervisor Agent",
    version="2.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# MODELS (Matching Supervisor's Format)
# ============================================================

class CredentialsDict(BaseModel):
    """Google OAuth credentials from supervisor"""
    access_token: str
    refresh_token: str
    token_uri: str = "https://oauth2.googleapis.com/token"
    client_id: str = ""
    client_secret: str = ""


class TaskRequest(BaseModel):
    """Request format from supervisor"""
    tool: str
    inputs: Dict[str, Any]
    credentials_dict: Optional[CredentialsDict] = None


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_service_from_creds(credentials_dict: CredentialsDict):
    """Get Drive service from credentials dict"""
    import json
    
    # Get client_id and client_secret from credentials.json file
    client_id = credentials_dict.client_id
    client_secret = credentials_dict.client_secret
    
    # If not provided in request, load from credentials.json
    if not client_id or not client_secret:
        try:
            with open('credentials.json', 'r') as f:
                creds_file = json.load(f)
                if 'installed' in creds_file:
                    client_id = creds_file['installed']['client_id']
                    client_secret = creds_file['installed']['client_secret']
                elif 'web' in creds_file:
                    client_id = creds_file['web']['client_id']
                    client_secret = creds_file['web']['client_secret']
        except Exception as e:
            print(f"Warning: Could not load credentials.json: {e}")
            # Fall back to environment variables
            client_id = os.getenv('GOOGLE_CLIENT_ID', '')
            client_secret = os.getenv('GOOGLE_CLIENT_SECRET', '')
    
    creds_dict = {
        "token": credentials_dict.access_token,
        "refresh_token": credentials_dict.refresh_token,
        "token_uri": credentials_dict.token_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    return get_session_drive_service(creds_dict)


def format_folder_tree(folders: list) -> str:
    """Format folder structure as a readable tree"""
    if not folders:
        return "No folders found."

    lines = ["My Drive/"]
    for folder in folders:
        lines.append(folder["display"])
    return "\n".join(lines)


def format_file_list(files: list, location: str = "My Drive") -> str:
    """Format file list as readable text"""
    if not files:
        return f"No files in {location}"
    
    lines = [f"Files in {location}:"]
    for file in files:
        size = file.get('size', 'N/A')
        if size != 'N/A' and size.isdigit():
            size_mb = round(int(size) / (1024 * 1024), 2)
            size = f"{size_mb} MB"
        link = file.get('webViewLink', '')
        link_part = f" — {link}" if link else ""
        lines.append(f"  {file['name']} ({size}){link_part}")
    
    return "\n".join(lines)


# ============================================================
# TOOL IMPLEMENTATIONS
# ============================================================

def upload_file_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    Upload a LOCAL file to Google Drive.

    Inputs:
        file_path: str (required) - Local file path to upload
        filename: str (required) - Name for the uploaded file
        folder_id: str (optional) - Target folder Drive ID (preferred when known)
        folder_path: str (optional) - Target folder path, e.g. 'Operations/2024'
                     (find-or-created at Drive root)
        mime_type: str (optional) - MIME type of the file

    Returns:
        success: bool
        file_id: str - Google Drive file ID
        file_url: str - Direct link to file
        folder_id: str - Resolved destination folder ID
        folder_path: str - Human-readable destination label
        message: str
    """
    try:
        service = get_service_from_creds(credentials_dict)

        file_path = inputs.get("file_path")
        filename = inputs.get("filename")
        folder_path = inputs.get("folder_path")
        folder_id = inputs.get("folder_id")
        mime_type = inputs.get("mime_type", "application/octet-stream")

        if not file_path:
            return {"success": False, "error": "file_path is required"}
        if not filename:
            return {"success": False, "error": "filename is required"}

        if not os.path.exists(file_path):
            return {"success": False, "error": f"File not found: {file_path}"}

        # Resolve target folder
        if folder_id:
            target_folder_id = folder_id
            location = folder_path or "(existing folder)"
        elif folder_path:
            resolved = resolve_folder_path_to_id(service, folder_path, create_if_missing=True)
            if not resolved:
                return {"success": False, "error": f"Could not resolve folder '{folder_path}'"}
            target_folder_id = resolved
            location = folder_path
        else:
            target_folder_id = "root"
            location = "My Drive"

        # Target folder is already resolved above (whether from folder_id,
        # resolved folder_path, or the 'root' default). Hand the resolved ID
        # straight to the raw-stream helper — it still handles .doc/.docx
        # auto-conversion. Calling upload_stream_to_folder_impl here would
        # re-resolve folder_path a second time and ignore a caller-supplied
        # folder_id.
        with open(file_path, 'rb') as f:
            upload_result = _raw_stream_upload_to_folder_id(
                service, f, filename, mime_type, target_folder_id
            )

        if not upload_result.get("success"):
            return upload_result

        return {
            "success": True,
            "file_id": upload_result.get("file_id"),
            "file_url": upload_result.get("file_url"),
            "filename": filename,
            "folder_id": target_folder_id,
            "folder_path": location,
            "message": f"Uploaded '{filename}' to {location}",
            "error": None,
        }

    except Exception as e:
        return {
            "success": False,
            "file_id": None,
            "error": str(e),
            "message": f"Upload failed: {str(e)}"
        }


def _raw_stream_upload_to_folder_id(service, file_stream, filename: str, mimetype: str, folder_id: str) -> dict:
    """Upload a raw stream directly to folder_id without find-or-create logic.

    Used by upload_file_tool when the caller provides folder_id directly (from
    a prior list_folders / create_folder step) instead of folder_path. Keeps
    .doc/.docx auto-conversion behaviour consistent with upload_stream_to_folder_impl.
    """
    try:
        metadata = {'name': filename, 'parents': [folder_id]}

        if mimetype in [
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/msword',
        ]:
            metadata['mimeType'] = 'application/vnd.google-apps.document'
            media = MediaIoBaseUpload(file_stream, mimetype=mimetype, resumable=True)
        else:
            media = MediaIoBaseUpload(file_stream, mimetype=mimetype)

        file = service.files().create(body=metadata, media_body=media, fields='id').execute()
        file_id = file.get('id')
        file_url = f"https://drive.google.com/file/d/{file_id}/view"

        return {
            "success": True,
            "file_id": file_id,
            "file_url": file_url,
            "folder_id": folder_id,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_folder_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    Find-or-create a folder (or nested folder chain) in the user's Google Drive.

    Inputs:
        folder_path: str (required) - Folder path (e.g., 'Operations/2024/Reports')
        parent_folder_id: str (optional) - Parent folder ID to anchor the chain.
                          Defaults to the user's My Drive root.

    Idempotent: if the folder already exists at the specified path, its ID is
    returned without creating duplicates.

    Returns:
        success: bool
        folder_id: str - Google Drive folder ID
        folder_url: str - Direct link to folder
        folder_path: str - Full path created
        message: str
    """
    try:
        service = get_service_from_creds(credentials_dict)

        folder_path = inputs.get("folder_path")
        parent_folder_id = inputs.get("parent_folder_id")
        if not folder_path:
            return {"success": False, "error": "folder_path is required"}

        result = create_nested_folder_impl(service, folder_path, parent_folder_id=parent_folder_id)
        return result

    except Exception as e:
        return {
            "success": False,
            "folder_id": None,
            "error": str(e),
            "message": f"Folder creation failed: {str(e)}"
        }


def list_folders_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    List folders in the user's Google Drive (tree structure).

    Inputs:
        parent_folder_id: str (optional) - Folder ID to list under. Defaults to Drive root.
        max_results: int (optional) - Limit number of folders returned
        max_depth: int (optional) - Tree depth (default 3)

    Returns:
        success: bool
        folders: list - Array of folder objects with id, name, display, level
        count: int - Number of folders
        tree: str - Tree structure as string
        message: str
    """
    try:
        service = get_service_from_creds(credentials_dict)
        max_results = inputs.get("max_results")
        max_depth = inputs.get("max_depth", 3)
        parent_folder_id = inputs.get("parent_folder_id")

        structure_result = get_folder_structure_impl(
            service, folder_id=parent_folder_id, level=0, max_level=max_depth
        )
        if not structure_result.get("success"):
            return structure_result

        structure = structure_result.get("folders", [])

        if max_results and isinstance(max_results, int) and max_results > 0:
            structure = structure[:max_results]

        tree = format_folder_tree(structure)

        return {
            "success": True,
            "folders": structure,
            "count": len(structure),
            "tree": tree,
            "message": f"Found {len(structure)} folder(s) in Drive",
            "error": None
        }

    except Exception as e:
        return {
            "success": False,
            "folders": [],
            "count": 0,
            "error": str(e),
            "message": f"Failed to list folders: {str(e)}"
        }


def list_files_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    List files in a Drive folder (or Drive root if no folder is specified).

    Inputs:
        folder_id: str (optional) - Folder Drive ID (preferred when known)
        folder_path: str (optional) - Folder path relative to Drive root,
                     e.g. 'Operations/2024'. Resolved to an ID.

    Returns:
        success: bool
        files: list - Array of file objects with id, name, mimeType, size, createdTime
        count: int - Number of files
        folder_id: str - Resolved folder ID
        folder_path: str - Location label
        message: str
    """
    try:
        service = get_service_from_creds(credentials_dict)

        folder_id = inputs.get("folder_id")
        folder_path = inputs.get("folder_path")

        if folder_id:
            target_id = folder_id
            location = folder_path or "(specified folder)"
        elif folder_path:
            target_id = resolve_folder_path_to_id(service, folder_path, create_if_missing=False)
            if not target_id:
                # Fuzzy fallback: look for a loose match in the full tree
                structure_result = get_folder_structure_impl(service)
                if structure_result.get("success"):
                    folders = structure_result.get("folders", [])
                    matching = [f for f in folders if folder_path.lower() in f['name'].lower()]
                    if matching:
                        target_id = matching[0]['id']

            if not target_id:
                return {
                    "success": False,
                    "files": [],
                    "count": 0,
                    "error": f"Folder '{folder_path}' not found",
                    "message": f"Folder '{folder_path}' not found"
                }

            location = folder_path
        else:
            target_id = "root"
            location = "My Drive"

        files = list_files_in_folder(service, target_id)

        return {
            "success": True,
            "files": files,
            "count": len(files),
            "folder_id": target_id,
            "folder_path": location,
            "message": format_file_list(files, location),
            "error": None
        }

    except Exception as e:
        return {
            "success": False,
            "files": [],
            "count": 0,
            "error": str(e),
            "message": f"Failed to list files: {str(e)}"
        }


def search_files_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    Search files by name across the user's whole Drive.

    Inputs:
        search_term: str (required) - Keywords to search for

    Returns:
        success: bool
        results: list - Array of matching file objects
        count: int - Number of results
        search_term: str - Search term used
        message: str
    """
    try:
        service = get_service_from_creds(credentials_dict)

        search_term = inputs.get("search_term")
        if not search_term:
            return {"success": False, "error": "search_term is required"}

        results = search_files_in_safeexpress(service, search_term)
        
        if not results:
            return {
                "success": True,
                "results": [],
                "count": 0,
                "search_term": search_term,
                "message": f"No files found matching '{search_term}'",
                "error": None
            }
        
        # Format results
        result_lines = [f"Found {len(results)} file(s) matching '{search_term}':"]
        for file in results:
            result_lines.append(f"  {file['name']}")
        
        return {
            "success": True,
            "results": results,
            "count": len(results),
            "search_term": search_term,
            "message": "\n".join(result_lines),
            "error": None
        }
        
    except Exception as e:
        return {
            "success": False,
            "results": [],
            "count": 0,
            "error": str(e),
            "message": f"Search failed: {str(e)}"
        }
    
def search_template_and_data_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    Search for template and data files in Google Drive
    
    Inputs:
        template_name: str (required) - Name of template file
        data_name: str (required) - Name of data file
    
    Returns:
        success: bool
        template_file_id: str - Template file ID
        template_file_name: str - Template file name
        data_file_id: str - Data file ID
        data_file_name: str - Data file name
        message: str
    """
    try:
        service = get_service_from_creds(credentials_dict)
        
        template_name = inputs.get("template_name")
        data_name = inputs.get("data_name")
        
        if not template_name:
            return {"success": False, "error": "template_name is required"}
        if not data_name:
            return {"success": False, "error": "data_name is required"}
        
        print(f"Searching for template: '{template_name}'")
        print(f"Searching for data: '{data_name}'")
        
        # Search for template file
        template_query = f"name contains '{template_name}' and trashed=false"
        template_results = service.files().list(
            q=template_query,
            fields="files(id, name, mimeType)",
            pageSize=10
        ).execute()
        
        template_files = template_results.get('files', [])
        
        # Search for data file
        data_query = f"name contains '{data_name}' and trashed=false"
        data_results = service.files().list(
            q=data_query,
            fields="files(id, name, mimeType)",
            pageSize=10
        ).execute()
        
        data_files = data_results.get('files', [])
        
        # Check if files were found
        if not template_files:
            return {
                "success": False,
                "error": f"Template file '{template_name}' not found in Google Drive",
                "message": f"Template file '{template_name}' not found"
            }
        
        if not data_files:
            return {
                "success": False,
                "error": f"Data file '{data_name}' not found in Google Drive",
                "message": f"Data file '{data_name}' not found"
            }
        
        # Use first match for each
        template_file = template_files[0]
        data_file = data_files[0]
        
        print(f"Found template: {template_file['name']} (ID: {template_file['id']})")
        print(f"Found data: {data_file['name']} (ID: {data_file['id']})")
        
        return {
            "success": True,
            "template_file_id": template_file['id'],
            "template_file_name": template_file['name'],
            "data_file_id": data_file['id'],
            "data_file_name": data_file['name'],
            "message": f"Found template '{template_file['name']}' and data '{data_file['name']}'",
            "error": None
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            "message": f"Search failed: {str(e)}"
        }
    
def upload_template_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    Upload a template file (PDF, DOCX, DOC) to Google Drive Templates folder
    with automatic conversion to Google Docs format for editing
    """
    try:
        service = get_service_from_creds(credentials_dict)
        
        file_path = inputs.get("file_path")
        template_name = inputs.get("template_name")
        file_type = inputs.get("file_type")
        preserve_format = inputs.get("preserve_format", False)  # New parameter
        
        if not file_path:
            return {"success": False, "error": "file_path is required"}
        if not template_name:
            return {"success": False, "error": "template_name is required"}
        
        if not os.path.exists(file_path):
            return {"success": False, "error": f"File not found: {file_path}"}
        
        # Auto-detect file type and format
        detected_format = "Unknown"
        if not file_type:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == '.pdf':
                file_type = 'application/pdf'
                detected_format = 'PDF'
            elif ext == '.docx':
                file_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                detected_format = 'DOCX'
            elif ext == '.doc':
                file_type = 'application/msword'
                detected_format = 'DOC'
            elif ext == '.txt':
                file_type = 'text/plain'
                detected_format = 'TXT'
            else:
                file_type = 'application/octet-stream'
                detected_format = 'Unknown'
        
        print(f"Detected format: {detected_format}")
        
        # Use correct function names from tools.py
        # Get or create Templates folder using create_nested_folder_impl
        folder_path = "Templates"
        folder_result = create_nested_folder_impl(service, folder_path)
        
        if not folder_result.get("success"):
            return {
                "success": False,
                "file_id": None,
                "error": folder_result.get("error"),
                "message": f"Failed to create Templates folder: {folder_result.get('error')}"
            }
        
        templates_folder_id = folder_result.get("folder_id")
        
        # Determine if we should convert to Google Docs
        should_convert = not preserve_format and detected_format in ['PDF', 'DOCX', 'DOC']
        
        if should_convert:
            print(f"Converting {detected_format} to Google Docs format for editing...")
            target_mime = 'application/vnd.google-apps.document'
            conversion_note = f"Converted from {detected_format} to Google Docs (editable)"
        else:
            print(f"Preserving original {detected_format} format...")
            target_mime = file_type
            conversion_note = f"Preserved original {detected_format} format"
        
        # Upload with conversion
        file_metadata = {
            'name': template_name,
            'parents': [templates_folder_id],
            'mimeType': target_mime,
            'description': f"Original format: {detected_format}"
        }
        
        # MediaFileUpload is already imported in tools.py
        media = MediaFileUpload(file_path, mimetype=file_type, resumable=True)
        
        uploaded_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, webViewLink, mimeType'
        ).execute()
        
        file_id = uploaded_file.get('id')
        file_url = uploaded_file.get('webViewLink')
        
        return {
            "success": True,
            "file_id": file_id,
            "file_url": file_url,
            "template_name": template_name,
            "original_format": detected_format,
            "current_format": "Google Docs" if should_convert else detected_format,
            "is_editable": should_convert,
            "folder_path": "Templates",
            "message": f"Template '{template_name}' uploaded to Templates. {conversion_note}",
            "error": None
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "file_id": None,
            "error": str(e),
            "message": f"Upload failed: {str(e)}"
        }

def get_folder_info_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    Resolve a folder by path and return its ID + summary stats.

    Does NOT create missing folders — returns an error instead. Use this when
    you need to look up an existing folder's ID to pass into downstream tools
    like sheets_agent.create_sheet or drive_agent.move_file.

    Inputs:
        folder_path: str (required) - Folder path to resolve, e.g. 'Finance' or 'Work/2026'

    Returns:
        success: bool
        folder_id: str
        folder_name: str
        folder_path: str
        file_count: int
        subfolder_count: int
        message: str
    """
    try:
        service = get_service_from_creds(credentials_dict)

        folder_path = inputs.get("folder_path")
        if not folder_path:
            return {"success": False, "error": "folder_path is required"}

        return get_folder_info_impl(service, folder_path)

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to get folder info: {str(e)}"
        }


def move_file_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    Move (reparent) a Drive file or folder to a target folder.

    Provide EITHER:
      - folder_id: destination folder's Drive ID (preferred when known from a prior step)
      - folder_path: destination folder path, e.g. 'Finance/Q1'
        (resolved strictly by default — set create_if_missing=True to auto-create)

    Inputs:
        file_id: str (required) - The file or folder to move
        folder_id: str (optional)
        folder_path: str (optional)
        create_if_missing: bool (optional, default False) - When True, missing
                          folder segments in folder_path are auto-created.
                          Keeping this False prevents silent folder creation
                          from a typo (e.g. 'Fiance' → would create a new
                          'Fiance' folder instead of moving to 'Finance').
                          The planner should explicitly use create_folder
                          first when folder creation is actually intended.

    Returns:
        success, file_id, file_name, file_url, destination_folder_id,
        destination_folder_path, new_parents, message
    """
    try:
        service = get_service_from_creds(credentials_dict)

        file_id = inputs.get("file_id")
        folder_id = inputs.get("folder_id")
        folder_path = inputs.get("folder_path")
        create_if_missing = inputs.get("create_if_missing", False)

        if not file_id:
            return {"success": False, "error": "file_id is required"}
        if not folder_id and not folder_path:
            return {"success": False, "error": "Provide folder_id or folder_path"}

        return move_file_impl(
            service,
            file_id=file_id,
            folder_id=folder_id,
            folder_path=folder_path,
            create_if_missing=create_if_missing,
        )

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"Move failed: {str(e)}"
        }

def read_file_content_impl(service, file_id: str) -> Dict:
    """
    Read content from a file in Google Drive - RETURNS DICT
    Supports text files, Google Docs, and CSVs
    """
    try:
        # Get file metadata
        file_metadata = service.files().get(fileId=file_id, fields='name, mimeType').execute()
        mime_type = file_metadata.get('mimeType')
        file_name = file_metadata.get('name')
        
        content = ""
        
        # Handle different file types
        if mime_type == 'application/vnd.google-apps.document':
            # Google Docs - export as plain text
            content = service.files().export(fileId=file_id, mimeType='text/plain').execute().decode('utf-8')
        elif mime_type == 'text/plain' or mime_type == 'text/csv':
            # Plain text or CSV
            content = service.files().get_media(fileId=file_id).execute().decode('utf-8')
        elif mime_type == 'application/vnd.google-apps.spreadsheet':
            # Google Sheets - export as CSV
            content = service.files().export(fileId=file_id, mimeType='text/csv').execute().decode('utf-8')
        else:
            return {
                "success": False,
                "content": None,
                "error": f"Unsupported file type: {mime_type}",
                "message": f"Cannot read content from {mime_type} files"
            }
        
        return {
            "success": True,
            "file_id": file_id,
            "file_name": file_name,
            "mime_type": mime_type,
            "content": content,
            "content_length": len(content),
            "message": f"Read {len(content)} characters from '{file_name}'",
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "content": None,
            "error": str(e),
            "message": f"Failed to read file content: {str(e)}"
        }


def read_file_content_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    Read content from a file in Google Drive.

    Inputs:
        file_id: str (optional) - Google Drive file ID, or a full Drive/Docs/Sheets
                 URL (e.g. https://drive.google.com/file/d/<id>/view) which is
                 auto-normalized to the bare ID.
        drive_path: str (optional) - DRIVE logical path (e.g. 'Data/customer_info.txt').
                    The final segment is the filename; leading segments are
                    folders resolved from the Drive root. Note: this is NOT a
                    local OS path — for local files use drive_agent.upload_file.
        file_path: str (DEPRECATED) - Backwards-compatible alias for drive_path.
                   Retained for one release cycle; emits a deprecation log line
                   when used. Renamed to drive_path to disambiguate from
                   upload_file.file_path which means a LOCAL OS path.

    Exactly one of file_id or drive_path must be provided.

    Returns:
        success, file_id, file_name, mime_type, content, content_length, message
    """
    try:
        service = get_service_from_creds(credentials_dict)

        file_id = inputs.get("file_id")
        drive_path = inputs.get("drive_path") or inputs.get("file_path")

        if inputs.get("file_path") and not inputs.get("drive_path"):
            print(
                "[DEPRECATION] drive_agent.read_file_content: argument 'file_path' "
                "is renamed to 'drive_path' to disambiguate from upload_file.file_path "
                "(local OS path). Still accepting it for backwards-compat."
            )

        if file_id:
            file_id = _extract_drive_file_id(file_id)

        if not file_id and drive_path:
            path_parts = drive_path.split('/')
            filename = path_parts[-1]
            folder_path = '/'.join(path_parts[:-1]) if len(path_parts) > 1 else None

            if folder_path:
                folder_id = resolve_folder_path_to_id(service, folder_path, create_if_missing=False)
                if not folder_id:
                    folders = get_folder_structure(service)
                    matching = [f for f in folders if folder_path.lower() in f['name'].lower()]
                    if matching:
                        folder_id = matching[0]['id']
            else:
                folder_id = "root"

            if not folder_id:
                return {
                    "success": False,
                    "error": f"Folder not found: {folder_path}",
                    "message": f"Could not find folder '{folder_path}'"
                }

            safe_name = filename.replace("'", "\\'")
            query = f"name='{safe_name}' and '{folder_id}' in parents and trashed=false"
            results = service.files().list(q=query, fields="files(id)").execute()
            files = results.get('files', [])

            if not files:
                return {
                    "success": False,
                    "error": f"File not found: {filename}",
                    "message": f"Could not find file '{filename}' in {folder_path or 'My Drive'}"
                }

            file_id = files[0]['id']

        if not file_id:
            return {
                "success": False,
                "error": "file_id or drive_path is required",
                "message": "Must provide either file_id or drive_path"
            }

        return read_file_content_impl(service, file_id)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "content": None,
            "error": str(e),
            "message": f"Failed to read file: {str(e)}"
        }


def rename_file_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    Rename a file or folder in Google Drive.

    Inputs:
        file_id: str (required) - Drive file/folder ID to rename
        new_name: str (required) - New name for the file/folder

    Returns:
        success: bool
        file_id: str - ID of the renamed file
        new_name: str - New name after renaming
        message: str
        error: str or None
    """
    try:
        service = get_service_from_creds(credentials_dict)

        file_id = inputs.get("file_id")
        new_name = inputs.get("new_name")
        if not file_id:
            return {"success": False, "error": "file_id is required"}
        if not new_name:
            return {"success": False, "error": "new_name is required"}

        return rename_file_impl(service, file_id, new_name)

    except Exception as e:
        return {
            "success": False,
            "file_id": None,
            "new_name": None,
            "error": str(e),
            "message": f"Rename failed: {str(e)}"
        }


# Google-native MIME types and their preferred local export format.
# Order matters: export mime on the LEFT is what we ask Drive for, extension
# on the RIGHT is the tempfile suffix we write to disk.
_GOOGLE_NATIVE_EXPORTS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}


def _resolve_drive_file_id_from_path(service, drive_path: str) -> Optional[str]:
    """Resolve a Drive logical path (e.g. 'Data/customer_info.txt') to a file ID.

    Mirrors the path-resolution logic in read_file_content_tool so download_file
    can accept drive_path with identical semantics. Returns None when any
    segment is unresolved.
    """
    path_parts = drive_path.split('/')
    filename = path_parts[-1]
    folder_path = '/'.join(path_parts[:-1]) if len(path_parts) > 1 else None

    if folder_path:
        folder_id = resolve_folder_path_to_id(service, folder_path, create_if_missing=False)
        if not folder_id:
            folders = get_folder_structure(service)
            matching = [f for f in folders if folder_path.lower() in f['name'].lower()]
            if matching:
                folder_id = matching[0]['id']
        if not folder_id:
            return None
    else:
        folder_id = "root"

    safe_name = filename.replace("'", "\\'")
    query = f"name='{safe_name}' and '{folder_id}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id)").execute()
    files = results.get('files', [])
    return files[0]['id'] if files else None


def download_file_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    Download a file from Google Drive to a server-side temp path.

    Native Google files (Docs/Sheets/Slides/Drawings) are exported to their
    Office equivalents (docx/xlsx/pptx) or PNG; everything else is streamed
    as-is via MediaIoBaseDownload.

    Inputs:
        file_id: str (preferred) - Drive file ID, or a Drive/Docs/Sheets URL
                 (auto-normalized to the bare ID).
        drive_path: str (optional) - Drive logical path (e.g. 'Data/customer_info.txt').
                    Resolved like drive_agent.read_file_content.

    Exactly one of file_id or drive_path must be provided.

    Returns:
        success: bool
        local_path: str - Absolute path on the sub-agent host (safe to pass to
                    mapping_agent.parse_file). Caller is responsible for lifecycle
                    of the temp directory (tempfile.mkdtemp is used per call).
        file_id: str
        file_name: str
        mime_type: str - The ORIGINAL Drive mimeType (even when exported)
        exported_as: str or None - Export mimeType used for Google-native files
        size_bytes: int
        message: str
        error: str or None
    """
    try:
        service = get_service_from_creds(credentials_dict)

        file_id = inputs.get("file_id")
        drive_path = inputs.get("drive_path")

        if file_id:
            file_id = _extract_drive_file_id(file_id)
        elif drive_path:
            file_id = _resolve_drive_file_id_from_path(service, drive_path)
            if not file_id:
                return {
                    "success": False,
                    "error": f"File not found at drive_path: {drive_path}",
                    "message": f"Could not resolve '{drive_path}' to a Drive file ID",
                }

        if not file_id:
            return {
                "success": False,
                "error": "file_id or drive_path is required",
                "message": "Must provide either file_id or drive_path",
            }

        file_metadata = service.files().get(
            fileId=file_id, fields="name, mimeType"
        ).execute()
        mime_type = file_metadata.get("mimeType")
        file_name = file_metadata.get("name", "download")

        temp_dir = tempfile.mkdtemp(prefix="drive_download_")

        exported_as = None
        if mime_type in _GOOGLE_NATIVE_EXPORTS:
            export_mime, ext = _GOOGLE_NATIVE_EXPORTS[mime_type]
            exported_as = export_mime
            local_name = file_name if file_name.lower().endswith(ext) else f"{file_name}{ext}"
            local_path = os.path.join(temp_dir, local_name)
            request = service.files().export_media(fileId=file_id, mimeType=export_mime)
            with io.FileIO(local_path, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
        else:
            local_path = os.path.join(temp_dir, file_name)
            request = service.files().get_media(fileId=file_id)
            with io.FileIO(local_path, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()

        size_bytes = os.path.getsize(local_path)

        return {
            "success": True,
            "local_path": local_path,
            "file_id": file_id,
            "file_name": file_name,
            "mime_type": mime_type,
            "exported_as": exported_as,
            "size_bytes": size_bytes,
            "message": f"Downloaded '{file_name}' to {local_path} ({size_bytes} bytes)",
            "error": None,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "local_path": None,
            "error": str(e),
            "message": f"Download failed: {str(e)}",
        }


def copy_file_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    Copy an existing Drive file to a new name (and optional destination folder).

    Uses service.files().copy() under the hood — native Google files
    (Docs/Sheets/Slides) remain native on the copy side, binary files stay
    binary. No local disk round-trip.

    Inputs:
        source_file_id: str (required) - Drive ID or URL of the file to copy.
                        URL form is auto-normalized to the bare ID.
        new_name: str (required) - Name for the copied file.
        folder_id: str (optional) - Destination folder Drive ID (preferred
                   when known from a prior step).
        folder_path: str (optional) - Destination folder path (e.g.
                     'Operations/2024'). Find-or-created at Drive root.
                     Ignored when folder_id is supplied.

    When neither folder_id nor folder_path is provided, the copy lands next to
    the source in its existing parent folder (Drive API default).

    Returns:
        success: bool
        file_id: str - New file ID of the copy
        file_url: str - webViewLink of the copy
        new_name: str
        folder_id: str or None - Resolved destination folder ID (None => same as source)
        folder_path: str or None - Human-readable destination label
        message: str
        error: str or None
    """
    try:
        service = get_service_from_creds(credentials_dict)

        source_file_id = inputs.get("source_file_id")
        new_name = inputs.get("new_name")
        folder_id = inputs.get("folder_id")
        folder_path = inputs.get("folder_path")

        if not source_file_id:
            return {"success": False, "error": "source_file_id is required"}
        if not new_name:
            return {"success": False, "error": "new_name is required"}

        source_file_id = _extract_drive_file_id(source_file_id)

        target_folder_id = None
        location_label = None
        if folder_id:
            target_folder_id = folder_id
            location_label = folder_path or "(existing folder)"
        elif folder_path:
            resolved = resolve_folder_path_to_id(
                service, folder_path, create_if_missing=True
            )
            if not resolved:
                return {
                    "success": False,
                    "error": f"Could not resolve folder '{folder_path}'",
                    "message": f"Could not find or create destination folder '{folder_path}'",
                }
            target_folder_id = resolved
            location_label = folder_path

        body = {"name": new_name}
        if target_folder_id:
            body["parents"] = [target_folder_id]

        copied = service.files().copy(
            fileId=source_file_id,
            body=body,
            fields="id, name, webViewLink",
        ).execute()

        return {
            "success": True,
            "file_id": copied.get("id"),
            "file_url": copied.get("webViewLink"),
            "new_name": copied.get("name", new_name),
            "folder_id": target_folder_id,
            "folder_path": location_label,
            "message": (
                f"Copied source file to '{new_name}'"
                + (f" in {location_label}" if location_label else " in source folder")
            ),
            "error": None,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "file_id": None,
            "file_url": None,
            "error": str(e),
            "message": f"Copy failed: {str(e)}",
        }


# ============================================================
# TOOL REGISTRY (Maps tool names to functions)
# ============================================================

DRIVE_TOOLS = {
    "upload_file": upload_file_tool,
    "create_folder": create_folder_tool,
    "list_folders": list_folders_tool,
    "list_files": list_files_tool,
    "search_files": search_files_tool,
    "get_folder_info": get_folder_info_tool,
    "upload_template": upload_template_tool,
    "read_file_content": read_file_content_tool,
    "download_file": download_file_tool,
    "copy_file": copy_file_tool,
    "search_template_and_data": search_template_and_data_tool,
    "rename_file": rename_file_tool,
    "move_file": move_file_tool,
}


# ============================================================
# API ENDPOINTS
# ============================================================

@app.post("/execute_task")
async def execute_task(request: TaskRequest):
    """
    Main endpoint that supervisor calls.
    Executes Drive operations based on tool name.
    """
    try:
        tool_name = request.tool
        inputs = request.inputs
        credentials_dict = request.credentials_dict
        
        print(f"\n{'='*60}")
        print(f"DRIVE AGENT - Executing: {tool_name}")
        print(f"{'='*60}")
        print(f"Inputs: {json.dumps(inputs, indent=2)}")
        
        # Validate credentials
        if not credentials_dict:
            raise HTTPException(
                status_code=401,
                detail="credentials_dict is required for Drive operations"
            )
        
        # Get tool function
        tool_func = DRIVE_TOOLS.get(tool_name)
        if not tool_func:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown tool: {tool_name}. Available: {list(DRIVE_TOOLS.keys())}"
            )
        
        # Execute tool
        result = tool_func(inputs, credentials_dict)
        
        print(f"Result: {result.get('success')}")
        if result.get('error'):
            print(f"Error: {result.get('error')}")
        if result.get('file_id'):
            print(f"File ID: {result.get('file_id')}")
        if result.get('folder_id'):
            print(f"Folder ID: {result.get('folder_id')}")
        
        print(f"\nComplete Result:")
        print(json.dumps(result, indent=2, default=str))
        print(f"{'='*60}\n")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Drive Agent Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    

# NOTE: Dead-code duplicates of read_file_content_impl and read_file_content_tool
# used to live here (below the @app.post route). They were shadowed by the real
# definitions above and never reachable via DRIVE_TOOLS, so they were removed as
# part of the SafeExpress removal cleanup.


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "drive-agent",
        "available_tools": list(DRIVE_TOOLS.keys())
    }


@app.get("/")
async def root():
    """Root endpoint with available tools"""
    return {
        "service": "Google Drive Agent API",
        "version": "2.0.0",
        "available_tools": list(DRIVE_TOOLS.keys()),
        "tool_descriptions": {
            "upload_file": "Upload a LOCAL file to a Google Drive folder (by folder_id or folder_path)",
            "create_folder": "Find-or-create a folder (or nested chain) anywhere in Drive",
            "list_folders": "List folders under a parent (defaults to My Drive root)",
            "list_files": "List files in a Drive folder (by folder_id or folder_path)",
            "search_files": "Search files by name across the user's whole Drive",
            "get_folder_info": "Resolve a folder path to its ID (does NOT create missing folders)",
            "move_file": "Move (reparent) a file or folder to another folder",
            "rename_file": "Rename a file or folder in Drive",
            "read_file_content": "Read text content of a Drive file (Docs, Sheets→CSV, text, CSV)",
            "upload_template": "Upload a template into the Templates folder",
            "search_template_and_data": "Search for a template + matching data file together"
        },
        "improvements": [
            "Supervisor-compatible /execute_task endpoint",
            "Structured data output for all tools",
            "Proper error handling with success/error fields",
            "Credentials passed via request (no session storage)",
            "Direct file/folder URLs in responses",
            "Consistent return format across all tools"
        ],
        "endpoints": {
            "execute_task": "/execute_task (POST) - Execute Drive operations",
            "health": "/health (GET) - Health check"
        }
    }


# ============================================================
# RUN SERVER
# ============================================================

if __name__ == "__main__":
    port = int(os.getenv("DRIVE_AGENT_PORT", "8006"))
    print(f"Starting Google Drive Agent v2.0 on port {port}")
    print(f"Available tools: {list(DRIVE_TOOLS.keys())}")
    print(f"Ready to receive requests from Supervisor Agent")
    uvicorn.run(app, host="0.0.0.0", port=port)