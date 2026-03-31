"""
Google Drive Agent API - Supervisor-Compatible Version
Handles Google Drive operations via /execute_task endpoint
"""

from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import os
import json
import uvicorn
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

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
    # Legacy compatibility
    create_nested_folder,
    upload_stream_to_folder,
    list_folders_in_safeexpress,
    list_files_in_folder,
    get_folder_structure,
    search_files_in_safeexpress,
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
            print(f"⚠️ Warning: Could not load credentials.json: {e}")
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
        return "No folders found in SafeExpress."
    
    lines = ["📁 SafeExpress/"]
    for folder in folders:
        lines.append(folder["display"])
    return "\n".join(lines)


def format_file_list(files: list, location: str = "SafeExpress") -> str:
    """Format file list as readable text"""
    if not files:
        return f"📭 No files in {location}"
    
    lines = [f"Files in {location}:"]
    for file in files:
        size = file.get('size', 'N/A')
        if size != 'N/A' and size.isdigit():
            size_mb = round(int(size) / (1024 * 1024), 2)
            size = f"{size_mb} MB"
        lines.append(f"📄 {file['name']} ({size})")
    
    return "\n".join(lines)


# ============================================================
# TOOL IMPLEMENTATIONS
# ============================================================

def upload_file_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    Upload a file to Google Drive (SafeExpress folder or specific path)
    
    Inputs:
        file_path: str (required) - Local file path to upload
        filename: str (required) - Name for the uploaded file
        folder_path: str (optional) - Target folder path (e.g., 'Operations/2024')
        mime_type: str (optional) - MIME type of the file
    
    Returns:
        success: bool
        file_id: str - Google Drive file ID
        file_url: str - Direct link to file
        folder_path: str - Where file was uploaded
        message: str
    """
    try:
        service = get_service_from_creds(credentials_dict)
        
        file_path = inputs.get("file_path")
        filename = inputs.get("filename")
        folder_path = inputs.get("folder_path")
        mime_type = inputs.get("mime_type", "application/octet-stream")
        
        if not file_path:
            return {"success": False, "error": "file_path is required"}
        if not filename:
            return {"success": False, "error": "filename is required"}
        
        if not os.path.exists(file_path):
            return {"success": False, "error": f"File not found: {file_path}"}
        
        # Upload file
        with open(file_path, 'rb') as f:
            file_id = upload_stream_to_folder(
                service, f, filename, mime_type, folder_path
            )
        
        location = f"SafeExpress/{folder_path}" if folder_path else "SafeExpress"
        file_url = f"https://drive.google.com/file/d/{file_id}/view"
        
        return {
            "success": True,
            "file_id": file_id,
            "file_url": file_url,
            "filename": filename,
            "folder_path": location,
            "message": f"✅ Uploaded '{filename}' to {location}",
            "error": None
        }
        
    except Exception as e:
        return {
            "success": False,
            "file_id": None,
            "error": str(e),
            "message": f"❌ Upload failed: {str(e)}"
        }


def create_folder_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    Create a folder or nested folder structure in SafeExpress
    
    Inputs:
        folder_path: str (required) - Folder path (e.g., 'Operations/2024/Reports')
    
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
        if not folder_path:
            return {"success": False, "error": "folder_path is required"}
        
        # Create nested folders
        folder_id = create_nested_folder(service, folder_path)
        folder_url = f"https://drive.google.com/drive/folders/{folder_id}"
        
        return {
            "success": True,
            "folder_id": folder_id,
            "folder_url": folder_url,
            "folder_path": f"SafeExpress/{folder_path}",
            "message": f"✅ Created folder: SafeExpress/{folder_path}",
            "error": None
        }
        
    except Exception as e:
        return {
            "success": False,
            "folder_id": None,
            "error": str(e),
            "message": f"❌ Folder creation failed: {str(e)}"
        }


def list_folders_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    List all folders in SafeExpress with tree structure
    
    Inputs: (none required)
    
    Returns:
        success: bool
        folders: list - Array of folder objects with id, name, display, level
        count: int - Number of folders
        tree: str - Tree structure as string
        message: str
    """
    try:
        service = get_service_from_creds(credentials_dict)
        
        # Get folder structure
        structure = get_folder_structure(service)
        tree = format_folder_tree(structure)
        
        return {
            "success": True,
            "folders": structure,
            "count": len(structure),
            "tree": tree,
            "message": f"Found {len(structure)} folder(s) in SafeExpress",
            "error": None
        }
        
    except Exception as e:
        return {
            "success": False,
            "folders": [],
            "count": 0,
            "error": str(e),
            "message": f"❌ Failed to list folders: {str(e)}"
        }


def list_files_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    List files in SafeExpress root or specific folder
    
    Inputs:
        folder_path: str (optional) - Folder path to list files from
    
    Returns:
        success: bool
        files: list - Array of file objects with id, name, mimeType, size, createdTime
        count: int - Number of files
        folder_path: str - Location where files were listed
        message: str
    """
    try:
        service = get_service_from_creds(credentials_dict)
        
        folder_path = inputs.get("folder_path")
        safeexpress_id = get_safeexpress_folder_id(service)
        
        # Find folder if path specified
        if folder_path:
            folder_id = find_folder(service, folder_path, safeexpress_id)
            
            # Try nested search if not found
            if not folder_id:
                folders = get_folder_structure(service)
                matching = [f for f in folders if folder_path.lower() in f['name'].lower()]
                if matching:
                    folder_id = matching[0]['id']
            
            if not folder_id:
                return {
                    "success": False,
                    "files": [],
                    "count": 0,
                    "error": f"Folder '{folder_path}' not found",
                    "message": f"❌ Folder '{folder_path}' not found"
                }
            
            location = folder_path
        else:
            folder_id = safeexpress_id
            location = "SafeExpress"
        
        # List files
        files = list_files_in_folder(service, folder_id)
        
        return {
            "success": True,
            "files": files,
            "count": len(files),
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
            "message": f"❌ Failed to list files: {str(e)}"
        }


def search_files_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    Search for files in SafeExpress
    
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
        
        # Search files
        results = search_files_in_safeexpress(service, search_term)
        
        if not results:
            return {
                "success": True,
                "results": [],
                "count": 0,
                "search_term": search_term,
                "message": f"🔍 No files found matching '{search_term}'",
                "error": None
            }
        
        # Format results
        result_lines = [f"Found {len(results)} file(s) matching '{search_term}':"]
        for file in results:
            result_lines.append(f"📄 {file['name']}")
        
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
            "message": f"❌ Search failed: {str(e)}"
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
        
        print(f"🔍 Searching for template: '{template_name}'")
        print(f"🔍 Searching for data: '{data_name}'")
        
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
                "message": f"❌ Template file '{template_name}' not found"
            }
        
        if not data_files:
            return {
                "success": False,
                "error": f"Data file '{data_name}' not found in Google Drive",
                "message": f"❌ Data file '{data_name}' not found"
            }
        
        # Use first match for each
        template_file = template_files[0]
        data_file = data_files[0]
        
        print(f"✅ Found template: {template_file['name']} (ID: {template_file['id']})")
        print(f"✅ Found data: {data_file['name']} (ID: {data_file['id']})")
        
        return {
            "success": True,
            "template_file_id": template_file['id'],
            "template_file_name": template_file['name'],
            "data_file_id": data_file['id'],
            "data_file_name": data_file['name'],
            "message": f"✅ Found template '{template_file['name']}' and data '{data_file['name']}'",
            "error": None
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            "message": f"❌ Search failed: {str(e)}"
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
        
        print(f"📄 Detected format: {detected_format}")
        
        # ✅ FIX 1: Use correct function names from your tools.py
        # Get or create Templates folder using create_nested_folder_impl
        folder_path = "Templates"
        folder_result = create_nested_folder_impl(service, folder_path)
        
        if not folder_result.get("success"):
            return {
                "success": False,
                "file_id": None,
                "error": folder_result.get("error"),
                "message": f"❌ Failed to create Templates folder: {folder_result.get('error')}"
            }
        
        templates_folder_id = folder_result.get("folder_id")
        
        # Determine if we should convert to Google Docs
        should_convert = not preserve_format and detected_format in ['PDF', 'DOCX', 'DOC']
        
        if should_convert:
            print(f"🔄 Converting {detected_format} to Google Docs format for editing...")
            target_mime = 'application/vnd.google-apps.document'
            conversion_note = f"Converted from {detected_format} to Google Docs (editable)"
        else:
            print(f"📌 Preserving original {detected_format} format...")
            target_mime = file_type
            conversion_note = f"Preserved original {detected_format} format"
        
        # Upload with conversion
        file_metadata = {
            'name': template_name,
            'parents': [templates_folder_id],
            'mimeType': target_mime,
            'description': f"Original format: {detected_format}"
        }
        
        # ✅ FIX 2: MediaFileUpload is already imported in your tools.py
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
            "folder_path": "SafeExpress/Templates",
            "message": f"✅ Template '{template_name}' uploaded to SafeExpress/Templates. {conversion_note}",
            "error": None
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "file_id": None,
            "error": str(e),
            "message": f"❌ Upload failed: {str(e)}"
        }

def get_folder_info_tool(inputs: dict, credentials_dict: CredentialsDict) -> dict:
    """
    Get detailed information about a specific folder
    
    Inputs:
        folder_path: str (required) - Folder path to get info for
    
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
        
        safeexpress_id = get_safeexpress_folder_id(service)
        folder_id = find_folder(service, folder_path, safeexpress_id)
        
        # Try nested search if not found
        if not folder_id:
            folders = get_folder_structure(service)
            matching = [f for f in folders if folder_path.lower() in f['name'].lower()]
            if matching:
                folder_id = matching[0]['id']
        
        if not folder_id:
            return {
                "success": False,
                "error": f"Folder '{folder_path}' not found",
                "message": f"❌ Folder '{folder_path}' not found"
            }
        
        # Get files and subfolders
        files = list_files_in_folder(service, folder_id)
        subfolders = list_folders_in_safeexpress(service, folder_id)
        
        return {
            "success": True,
            "folder_id": folder_id,
            "folder_name": folder_path.split('/')[-1],
            "folder_path": f"SafeExpress/{folder_path}",
            "file_count": len(files),
            "subfolder_count": len(subfolders),
            "message": f"📁 {folder_path}: {len(files)} file(s), {len(subfolders)} subfolder(s)",
            "error": None
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"❌ Failed to get folder info: {str(e)}"
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
            "message": f"✅ Read {len(content)} characters from '{file_name}'",
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
    Read content from a file in Google Drive
    
    Inputs:
        file_id: str (required) - Google Drive file ID
        OR
        file_path: str (required) - Path to file in SafeExpress (e.g., 'Data/customer_info.txt')
    
    Returns:
        success: bool
        file_id: str
        file_name: str
        mime_type: str
        content: str - File content as text
        content_length: int
        message: str
    """
    try:
        service = get_service_from_creds(credentials_dict)
        
        file_id = inputs.get("file_id")
        file_path = inputs.get("file_path")
        
        # If file_path provided, search for the file
        if not file_id and file_path:
            safeexpress_id = get_safeexpress_folder_id(service)
            
            # Split path to get folder and filename
            path_parts = file_path.split('/')
            filename = path_parts[-1]
            folder_path = '/'.join(path_parts[:-1]) if len(path_parts) > 1 else None
            
            # Find the folder
            if folder_path:
                folder_id = find_folder(service, folder_path, safeexpress_id)
                if not folder_id:
                    # Try nested search
                    folders = get_folder_structure(service)
                    matching = [f for f in folders if folder_path.lower() in f['name'].lower()]
                    if matching:
                        folder_id = matching[0]['id']
            else:
                folder_id = safeexpress_id
            
            if not folder_id:
                return {
                    "success": False,
                    "error": f"Folder not found: {folder_path}",
                    "message": f"❌ Could not find folder '{folder_path}'"
                }
            
            # Search for file in folder
            query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
            results = service.files().list(q=query, fields="files(id)").execute()
            files = results.get('files', [])
            
            if not files:
                return {
                    "success": False,
                    "error": f"File not found: {filename}",
                    "message": f"❌ Could not find file '{filename}' in {folder_path or 'SafeExpress'}"
                }
            
            file_id = files[0]['id']
        
        if not file_id:
            return {
                "success": False,
                "error": "file_id or file_path is required",
                "message": "❌ Must provide either file_id or file_path"
            }
        
        # Read file content
        result = read_file_content_impl(service, file_id)
        return result
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "content": None,
            "error": str(e),
            "message": f"❌ Failed to read file: {str(e)}"
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
    "search_template_and_data": search_template_and_data_tool
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
        print(f"💾 DRIVE AGENT - Executing: {tool_name}")
        print(f"{'='*60}")
        print(f"📥 Inputs: {json.dumps(inputs, indent=2)}")
        
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
        
        print(f"✅ Result: {result.get('success')}")
        if result.get('error'):
            print(f"❌ Error: {result.get('error')}")
        if result.get('file_id'):
            print(f"🆔 File ID: {result.get('file_id')}")
        if result.get('folder_id'):
            print(f"📁 Folder ID: {result.get('folder_id')}")
        
        # Print complete result before returning
        print(f"\n📤 Complete Result:")
        print(json.dumps(result, indent=2, default=str))
        print(f"{'='*60}\n")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Drive Agent Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    

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
            "message": f"✅ Read {len(content)} characters from '{file_name}'",
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
    Read content from a file in Google Drive
    
    Inputs:
        file_id: str (required) - Google Drive file ID
        OR
        file_path: str (required) - Path to file in SafeExpress (e.g., 'Data/customer_info.txt')
    
    Returns:
        success: bool
        file_id: str
        file_name: str
        mime_type: str
        content: str - File content as text
        content_length: int
        message: str
    """
    try:
        service = get_service_from_creds(credentials_dict)
        
        file_id = inputs.get("file_id")
        file_path = inputs.get("file_path")
        
        # If file_path provided, search for the file
        if not file_id and file_path:
            safeexpress_id = get_safeexpress_folder_id(service)
            
            # Split path to get folder and filename
            path_parts = file_path.split('/')
            filename = path_parts[-1]
            folder_path = '/'.join(path_parts[:-1]) if len(path_parts) > 1 else None
            
            # Find the folder
            if folder_path:
                folder_id = find_folder(service, folder_path, safeexpress_id)
                if not folder_id:
                    # Try nested search
                    folders = get_folder_structure(service)
                    matching = [f for f in folders if folder_path.lower() in f['name'].lower()]
                    if matching:
                        folder_id = matching[0]['id']
            else:
                folder_id = safeexpress_id
            
            if not folder_id:
                return {
                    "success": False,
                    "error": f"Folder not found: {folder_path}",
                    "message": f"❌ Could not find folder '{folder_path}'"
                }
            
            # Search for file in folder
            query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
            results = service.files().list(q=query, fields="files(id)").execute()
            files = results.get('files', [])
            
            if not files:
                return {
                    "success": False,
                    "error": f"File not found: {filename}",
                    "message": f"❌ Could not find file '{filename}' in {folder_path or 'SafeExpress'}"
                }
            
            file_id = files[0]['id']
        
        if not file_id:
            return {
                "success": False,
                "error": "file_id or file_path is required",
                "message": "❌ Must provide either file_id or file_path"
            }
        
        # Read file content
        result = read_file_content_impl(service, file_id)
        return result
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "content": None,
            "error": str(e),
            "message": f"❌ Failed to read file: {str(e)}"
        }


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
            "upload_file": "Upload a file to SafeExpress or specific folder path",
            "create_folder": "Create folder or nested folder structure",
            "list_folders": "List all folders in SafeExpress with tree structure",
            "list_files": "List files in SafeExpress root or specific folder",
            "search_files": "Search for files in SafeExpress",
            "get_folder_info": "Get detailed info about a specific folder"
        },
        "improvements": [
            "✅ Supervisor-compatible /execute_task endpoint",
            "✅ Structured data output for all tools",
            "✅ Proper error handling with success/error fields",
            "✅ Credentials passed via request (no session storage)",
            "✅ Direct file/folder URLs in responses",
            "✅ Consistent return format across all tools"
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
    print(f"🚀 Starting Google Drive Agent v2.0 on port {port}")
    print(f"📚 Available tools: {list(DRIVE_TOOLS.keys())}")
    print(f"✨ New features: Supervisor integration, structured outputs, better error handling")
    print(f"📋 Ready to receive requests from Supervisor Agent")
    uvicorn.run(app, host="0.0.0.0", port=port)