"""
Google Drive Agent Tools - SUPERVISOR-COMPATIBLE OUTPUT
Similar structure to Calendar Agent tools.py
All functions return Dict instead of raising exceptions
"""

import os
import pickle
import io
import json
from typing import Optional, List, Dict, Any
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# === Config ===
SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/drive.file'
]



# ============================================================
# AUTH FUNCTIONS
# ============================================================
TOKEN_PATH = 'key/token.json'
CREDENTIALS_PATH = 'key/credentials.json'
def get_token_drive_service():
    """Get Drive service using token.json (for standalone use)"""
    creds = None
    TOKEN_PATH = 'key/token.json'
    CREDENTIALS_PATH = 'key/credentials.json'
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"⚠️ Token refresh failed: {e}")
                print("🔄 Re-authenticating...")
                creds = None  # Force re-auth
        
        if not creds:  # Re-auth needed
            if not os.path.exists(CREDENTIALS_PATH):
                raise FileNotFoundError(f"credentials.json not found at {CREDENTIALS_PATH}")
            
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save refreshed/new token
        os.makedirs('key', exist_ok=True)
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())
    
    return build('drive', 'v3', credentials=creds)


def get_session_drive_service(session_creds: Dict):
    """Get Drive service from session credentials (for API use)"""
    try:
        # Add client_id and client_secret from credentials.json if missing
        if not session_creds.get('client_id') or not session_creds.get('client_secret'):
            if os.path.exists(CREDENTIALS_PATH):
                with open(CREDENTIALS_PATH, 'r') as f:
                    creds_file = json.load(f)
                    if 'installed' in creds_file:
                        session_creds['client_id'] = creds_file['installed']['client_id']
                        session_creds['client_secret'] = creds_file['installed']['client_secret']
                    elif 'web' in creds_file:
                        session_creds['client_id'] = creds_file['web']['client_id']
                        session_creds['client_secret'] = creds_file['web']['client_secret']
        
        creds = Credentials(**session_creds)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"❌ Error creating Drive service: {e}")
        raise


# ============================================================
# FOLDER UTILITY FUNCTIONS
# ============================================================

def find_folder(service, folder_name: str, parent_id: Optional[str] = None) -> Optional[str]:
    """Find a folder by name, optionally within a parent folder"""
    try:
        query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        
        results = service.files().list(q=query, fields="files(id, name)").execute()
        folders = results.get("files", [])
        return folders[0]["id"] if folders else None
    except Exception as e:
        print(f"❌ Error finding folder '{folder_name}': {e}")
        return None


def create_folder(service, folder_name: str, parent_id: Optional[str] = None) -> Optional[str]:
    """Create a folder, optionally within a parent folder"""
    try:
        metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            metadata["parents"] = [parent_id]
        
        folder = service.files().create(body=metadata, fields="id").execute()
        return folder["id"]
    except Exception as e:
        print(f"❌ Error creating folder '{folder_name}': {e}")
        return None


def get_or_create_folder(service, folder_name: str, parent_id: Optional[str] = None) -> Optional[str]:
    """Get or create a folder, optionally within a parent folder"""
    folder_id = find_folder(service, folder_name, parent_id)
    if folder_id:
        return folder_id
    return create_folder(service, folder_name, parent_id)


def get_safeexpress_folder_id(service) -> str:
    """Get or create the root SafeExpress folder"""
    return get_or_create_folder(service, "SafeExpress")


def get_folder_path(service, parent_id: str) -> str:
    """Get full path of folders from SafeExpress root"""
    path = []
    current_id = parent_id
    safeexpress_id = get_safeexpress_folder_id(service)
    
    while current_id and current_id != safeexpress_id:
        try:
            folder = service.files().get(fileId=current_id, fields="name, parents").execute()
            path.insert(0, folder['name'])
            current_id = folder.get('parents', [None])[0]
        except:
            break
    
    return '/'.join(path) if path else 'SafeExpress'


# ============================================================
# SUPERVISOR-COMPATIBLE IMPLEMENTATIONS (Return Dict, not str)
# ============================================================

def create_nested_folder_impl(service, folder_path: str) -> Dict:
    """
    Create nested folders under SafeExpress - RETURNS DICT
    folder_path can be like "Operations/2024/January" or just "Operations"
    """
    try:
        safeexpress_id = get_safeexpress_folder_id(service)
        current_parent = safeexpress_id
        
        # Split path and create each folder
        folders = [f.strip() for f in folder_path.split('/') if f.strip()]
        
        if not folders:
            return {
                "success": False,
                "folder_id": None,
                "folder_url": None,
                "folder_path": None,
                "message": "Empty folder path provided",
                "error": "Empty folder path"
            }
        
        for folder_name in folders:
            current_parent = get_or_create_folder(service, folder_name, current_parent)
            if not current_parent:
                return {
                    "success": False,
                    "folder_id": None,
                    "folder_url": None,
                    "folder_path": None,
                    "message": f"Failed to create folder '{folder_name}' in path '{folder_path}'",
                    "error": f"Folder creation failed at '{folder_name}'"
                }
        
        folder_url = f"https://drive.google.com/drive/folders/{current_parent}"
        
        return {
            "success": True,
            "folder_id": current_parent,
            "folder_url": folder_url,
            "folder_path": f"SafeExpress/{folder_path}",
            "message": f"✅ Created folder: SafeExpress/{folder_path}",
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "folder_id": None,
            "folder_url": None,
            "folder_path": None,
            "message": f"Failed to create nested folders: {str(e)}",
            "error": str(e)
        }


def list_folders_in_safeexpress_impl(service, parent_id: Optional[str] = None) -> Dict:
    """List all folders within SafeExpress - RETURNS DICT"""
    try:
        if parent_id is None:
            parent_id = get_safeexpress_folder_id(service)
        
        query = f"mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false"
        results = service.files().list(
            q=query, 
            fields="files(id, name, createdTime)",
            orderBy="name"
        ).execute()
        
        folders = results.get('files', [])
        
        return {
            "success": True,
            "folders": folders,
            "count": len(folders),
            "parent_id": parent_id,
            "message": f"Found {len(folders)} folder(s)",
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "folders": [],
            "count": 0,
            "message": f"Failed to list folders: {str(e)}",
            "error": str(e)
        }


def list_files_in_folder_impl(service, folder_id: str) -> Dict:
    """List all files (non-folders) in a specific folder - RETURNS DICT"""
    try:
        query = f"'{folder_id}' in parents and mimeType!='application/vnd.google-apps.folder' and trashed=false"
        results = service.files().list(
            q=query,
            fields="files(id, name, mimeType, size, createdTime)",
            orderBy="name"
        ).execute()
        
        files = results.get('files', [])
        
        return {
            "success": True,
            "files": files,
            "count": len(files),
            "folder_id": folder_id,
            "message": f"Found {len(files)} file(s)",
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "files": [],
            "count": 0,
            "message": f"Failed to list files: {str(e)}",
            "error": str(e)
        }


def get_folder_structure_impl(service, folder_id: Optional[str] = None, level: int = 0, max_level: int = 3) -> Dict:
    """Get the entire folder structure as a tree - RETURNS DICT"""
    try:
        if level > max_level:
            return {
                "success": True,
                "folders": [],
                "message": "Max depth reached",
                "error": None
            }
        
        if folder_id is None:
            folder_id = get_safeexpress_folder_id(service)
        
        folders_result = list_folders_in_safeexpress_impl(service, folder_id)
        
        if not folders_result.get("success"):
            return folders_result
        
        folders = folders_result.get("folders", [])
        structure = []
        
        for folder in folders:
            indent = "  " * level
            structure.append({
                "id": folder["id"],
                "name": folder["name"],
                "display": f"{indent}📁 {folder['name']}",
                "level": level
            })
            
            # Recursively get subfolders
            if level < max_level:
                subfolders_result = get_folder_structure_impl(service, folder["id"], level + 1, max_level)
                if subfolders_result.get("success"):
                    structure.extend(subfolders_result.get("folders", []))
        
        return {
            "success": True,
            "folders": structure,
            "count": len(structure),
            "message": f"Found {len(structure)} folder(s) in tree",
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "folders": [],
            "count": 0,
            "message": f"Failed to get folder structure: {str(e)}",
            "error": str(e)
        }


def upload_file_to_folder_impl(service, filename: str, filepath: str, folder_path: Optional[str] = None) -> Dict:
    """Upload file to a specific folder path in SafeExpress - RETURNS DICT"""
    try:
        if not os.path.exists(filepath):
            return {
                "success": False,
                "file_id": None,
                "file_url": None,
                "message": f"File not found: {filepath}",
                "error": f"File not found: {filepath}"
            }
        
        # Get or create folder
        if folder_path:
            folder_result = create_nested_folder_impl(service, folder_path)
            if not folder_result.get("success"):
                return folder_result
            folder_id = folder_result.get("folder_id")
            location = f"SafeExpress/{folder_path}"
        else:
            folder_id = get_safeexpress_folder_id(service)
            location = "SafeExpress"
        
        metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaFileUpload(filepath, resumable=True)
        file = service.files().create(body=metadata, media_body=media, fields='id').execute()
        file_id = file.get('id')
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
            "file_url": None,
            "message": f"Failed to upload file: {str(e)}",
            "error": str(e)
        }


def upload_stream_to_folder_impl(service, file_stream, filename: str, mimetype: str, folder_path: Optional[str] = None) -> Dict:
    """Upload a file stream to SafeExpress or a specific folder path - RETURNS DICT"""
    try:
        # ✅ DEFAULT: Use "Templates" folder if no path specified
        if folder_path is None:
            folder_path = "Templates"
            print(f"📁 No folder specified, using default: SafeExpress/{folder_path}")
        
        # Get or create folder structure
        folder_result = create_nested_folder_impl(service, folder_path)
        if not folder_result.get("success"):
            return folder_result
        folder_id = folder_result.get("folder_id")
        location = f"SafeExpress/{folder_path}"
        
        # Handle .docx files - convert to Google Docs
        metadata = {'name': filename, 'parents': [folder_id]}
        
        if mimetype in [
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
            'application/msword'  # .doc
        ]:
            # Convert to Google Docs format
            metadata['mimeType'] = 'application/vnd.google-apps.document'
            media = MediaIoBaseUpload(file_stream, mimetype=mimetype, resumable=True)
        else:
            media = MediaIoBaseUpload(file_stream, mimetype=mimetype)
        
        file = service.files().create(body=metadata, media_body=media, fields='id').execute()
        file_id = file.get('id')
        file_url = f"https://docs.google.com/document/d/{file_id}/edit"
        
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
            "file_url": None,
            "message": f"Failed to upload file: {str(e)}",
            "error": str(e)
        }

def search_files_in_safeexpress_impl(service, search_term: str) -> Dict:
    """Search for files within SafeExpress folder - RETURNS DICT"""
    try:
        safeexpress_id = get_safeexpress_folder_id(service)
        query = f"name contains '{search_term}' and '{safeexpress_id}' in parents and trashed=false"
        results = service.files().list(
            q=query,
            fields="files(id, name, mimeType, size, createdTime)",
            pageSize=20
        ).execute()
        
        files = results.get('files', [])
        
        if not files:
            return {
                "success": True,
                "results": [],
                "count": 0,
                "search_term": search_term,
                "message": f"🔍 No files found matching '{search_term}'",
                "error": None
            }
        
        # Format results
        output = [f"Found {len(files)} file(s) matching '{search_term}':"]
        for file in files:
            output.append(f"📄 {file['name']}")
        
        return {
            "success": True,
            "results": files,
            "count": len(files),
            "search_term": search_term,
            "message": "\n".join(output),
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "results": [],
            "count": 0,
            "message": f"Failed to search files: {str(e)}",
            "error": str(e)
        }


def get_folder_info_impl(service, folder_path: str) -> Dict:
    """Get detailed information about a specific folder - RETURNS DICT"""
    try:
        safeexpress_id = get_safeexpress_folder_id(service)
        folder_id = find_folder(service, folder_path, safeexpress_id)
        
        # Try nested search if not found
        if not folder_id:
            structure_result = get_folder_structure_impl(service)
            if structure_result.get("success"):
                folders = structure_result.get("folders", [])
                matching = [f for f in folders if folder_path.lower() in f['name'].lower()]
                if matching:
                    folder_id = matching[0]['id']
        
        if not folder_id:
            return {
                "success": False,
                "folder_id": None,
                "message": f"Folder '{folder_path}' not found",
                "error": f"Folder '{folder_path}' not found"
            }
        
        # Get files and subfolders
        files_result = list_files_in_folder_impl(service, folder_id)
        subfolders_result = list_folders_in_safeexpress_impl(service, folder_id)
        
        file_count = files_result.get("count", 0)
        subfolder_count = subfolders_result.get("count", 0)
        
        return {
            "success": True,
            "folder_id": folder_id,
            "folder_name": folder_path.split('/')[-1],
            "folder_path": f"SafeExpress/{folder_path}",
            "file_count": file_count,
            "subfolder_count": subfolder_count,
            "message": f"📁 {folder_path}: {file_count} file(s), {subfolder_count} subfolder(s)",
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "folder_id": None,
            "message": f"Failed to get folder info: {str(e)}",
            "error": str(e)
        }


# ============================================================
# LEGACY COMPATIBILITY FUNCTIONS
# ============================================================

def create_nested_folder(service, folder_path: str) -> str:
    """Legacy wrapper - returns folder_id or raises exception"""
    result = create_nested_folder_impl(service, folder_path)
    if not result.get("success"):
        raise Exception(result.get("error"))
    return result.get("folder_id")


def upload_stream_to_folder(service, file_stream, filename: str, mimetype: str, folder_path: Optional[str] = None) -> str:
    """Legacy wrapper - returns file_id or raises exception"""
    result = upload_stream_to_folder_impl(service, file_stream, filename, mimetype, folder_path)
    if not result.get("success"):
        raise Exception(result.get("error"))
    return result.get("file_id")


def list_folders_in_safeexpress(service, parent_id: Optional[str] = None) -> List[Dict]:
    """Legacy wrapper - returns list of folders or raises exception"""
    result = list_folders_in_safeexpress_impl(service, parent_id)
    if not result.get("success"):
        raise Exception(result.get("error"))
    return result.get("folders", [])


def list_files_in_folder(service, folder_id: str) -> List[Dict]:
    """Legacy wrapper - returns list of files or raises exception"""
    result = list_files_in_folder_impl(service, folder_id)
    if not result.get("success"):
        raise Exception(result.get("error"))
    return result.get("files", [])


def get_folder_structure(service, folder_id: Optional[str] = None, level: int = 0, max_level: int = 3) -> List[Dict]:
    """Legacy wrapper - returns folder structure or raises exception"""
    result = get_folder_structure_impl(service, folder_id, level, max_level)
    if not result.get("success"):
        raise Exception(result.get("error"))
    return result.get("folders", [])


def search_files_in_safeexpress(service, search_term: str) -> List[Dict]:
    """Legacy wrapper - returns list of files or raises exception"""
    result = search_files_in_safeexpress_impl(service, search_term)
    if not result.get("success"):
        raise Exception(result.get("error"))
    return result.get("results", [])