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
                print(f"Token refresh failed: {e}")
                print("Re-authenticating...")
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
        if creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                pass
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Error creating Drive service: {e}")
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
        print(f"Error finding folder '{folder_name}': {e}")
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
        print(f"Error creating folder '{folder_name}': {e}")
        return None


def get_or_create_folder(service, folder_name: str, parent_id: Optional[str] = None) -> Optional[str]:
    """Get or create a folder, optionally within a parent folder"""
    folder_id = find_folder(service, folder_name, parent_id)
    if folder_id:
        return folder_id
    return create_folder(service, folder_name, parent_id)


def get_safeexpress_folder_id(service) -> str:
    """LEGACY NAME — returns the user's Drive root.

    Kept under this name to avoid breaking imports. Previously this returned a
    dedicated 'SafeExpress' sandbox folder, which was a soft boundary enforced
    only by this agent (other agents like sheets/docs never respected it, and
    the OAuth scope is full `.../auth/drive` so the isolation was cosmetic).
    Now we operate on the user's whole Drive; callers pass 'root' to Drive API
    queries as the parent alias, which matches the user's My Drive root.
    """
    return "root"


def get_folder_path(service, parent_id: str) -> str:
    """Resolve a folder's full path from the Drive root down to parent_id."""
    path = []
    current_id = parent_id
    visited: set = set()

    while current_id and current_id not in ("root", "My Drive") and current_id not in visited:
        visited.add(current_id)
        try:
            folder = service.files().get(fileId=current_id, fields="name, parents").execute()
            path.insert(0, folder.get("name", ""))
            parents = folder.get("parents", [])
            current_id = parents[0] if parents else None
        except Exception:
            break

    return "/".join(path) if path else "/"


def resolve_folder_path_to_id(service, folder_path: str, create_if_missing: bool = False) -> Optional[str]:
    """
    Resolve a folder path (e.g. 'Finance/Q1') to its Google Drive folder ID.

    Searches from the Drive root downward. Returns None if any segment is missing
    and create_if_missing=False. Returns the resolved ID otherwise.
    When create_if_missing=True, missing segments are created (find-or-create
    at each level), matching the idempotent behaviour of create_nested_folder_impl.
    """
    if not folder_path or not folder_path.strip():
        return "root"

    segments = [s.strip() for s in folder_path.split("/") if s.strip()]
    current_parent = "root"

    for segment in segments:
        if create_if_missing:
            current_parent = get_or_create_folder(service, segment, current_parent)
        else:
            current_parent = find_folder(service, segment, current_parent)
        if not current_parent:
            return None

    return current_parent


# ============================================================
# SUPERVISOR-COMPATIBLE IMPLEMENTATIONS (Return Dict, not str)
# ============================================================

def create_nested_folder_impl(service, folder_path: str, parent_folder_id: Optional[str] = None) -> Dict:
    """
    Find-or-create a folder (or nested folder chain) in the user's Google Drive.

    folder_path: slash-separated path, e.g. 'Operations/2024/January' or 'Operations'.
    parent_folder_id: where to anchor the chain. Defaults to the Drive root.
                      Pass another folder's ID to create nested under a specific folder.

    Idempotent: each segment is find-or-created, so repeated calls with the same
    path return the same folder ID instead of creating duplicates.
    """
    try:
        current_parent = parent_folder_id or "root"

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
            "folder_path": folder_path,
            "message": f"Created folder: {folder_path}",
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
    """LEGACY NAME — now lists folders under any parent (default: Drive root).

    parent_id: Drive folder ID whose direct subfolders should be listed. Defaults
    to 'root' (the user's My Drive root). Pass a specific folder ID to list
    inside that folder.
    """
    try:
        if parent_id is None:
            parent_id = "root"

        query = (
            f"mimeType='application/vnd.google-apps.folder' "
            f"and '{parent_id}' in parents and trashed=false"
        )
        results = service.files().list(
            q=query,
            fields="files(id, name, createdTime)",
            orderBy="name",
            pageSize=200,
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
            fields="files(id, name, mimeType, size, createdTime, webViewLink)",
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
    """Get a folder tree starting from folder_id (default: Drive root)."""
    try:
        if level > max_level:
            return {
                "success": True,
                "folders": [],
                "message": "Max depth reached",
                "error": None
            }

        if folder_id is None:
            folder_id = "root"
        
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
                "display": f"{indent}{folder['name']}/",
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


def upload_file_to_folder_impl(service, filename: str, filepath: str, folder_path: Optional[str] = None, folder_id: Optional[str] = None) -> Dict:
    """Upload a LOCAL file to Google Drive.

    folder_id: target folder ID (preferred when already known from a prior step).
    folder_path: target folder path relative to Drive root (e.g. 'Operations/2024').
                 Find-or-created idempotently.
    If neither is provided, uploads to the user's My Drive root.
    """
    try:
        if not os.path.exists(filepath):
            return {
                "success": False,
                "file_id": None,
                "file_url": None,
                "message": f"File not found: {filepath}",
                "error": f"File not found: {filepath}"
            }

        if folder_id:
            target_folder_id = folder_id
            location = folder_path or "(existing folder)"
        elif folder_path:
            folder_result = create_nested_folder_impl(service, folder_path)
            if not folder_result.get("success"):
                return folder_result
            target_folder_id = folder_result.get("folder_id")
            location = folder_path
        else:
            target_folder_id = "root"
            location = "My Drive"

        metadata = {'name': filename, 'parents': [target_folder_id]}
        media = MediaFileUpload(filepath, resumable=True)
        file = service.files().create(body=metadata, media_body=media, fields='id').execute()
        file_id_out = file.get('id')
        file_url = f"https://drive.google.com/file/d/{file_id_out}/view"

        return {
            "success": True,
            "file_id": file_id_out,
            "file_url": file_url,
            "filename": filename,
            "folder_id": target_folder_id,
            "folder_path": location,
            "message": f"Uploaded '{filename}' to {location}",
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
    """Upload a file stream to a Drive folder (find-or-create by path).

    Default path is 'Templates' at Drive root (preserved for the template-upload
    endpoint which relied on this default).
    """
    try:
        if folder_path is None:
            folder_path = "Templates"
            print(f"No folder specified, using default: {folder_path}")

        folder_result = create_nested_folder_impl(service, folder_path)
        if not folder_result.get("success"):
            return folder_result
        folder_id = folder_result.get("folder_id")
        location = folder_path

        metadata = {'name': filename, 'parents': [folder_id]}

        if mimetype in [
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/msword'
        ]:
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
            "folder_id": folder_id,
            "folder_path": location,
            "message": f"Uploaded '{filename}' to {location}",
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
    """LEGACY NAME — search files by name across the user's whole Drive.

    Escapes single quotes in the search term to avoid Drive query syntax breakage.
    Excludes trashed files. Returns matching files (any owner the user has access to).
    """
    try:
        safe_term = (search_term or "").replace("'", "\\'")
        query = f"name contains '{safe_term}' and trashed=false"
        results = service.files().list(
            q=query,
            fields="files(id, name, mimeType, size, createdTime, webViewLink, parents)",
            pageSize=50,
        ).execute()

        files = results.get('files', [])

        if not files:
            return {
                "success": True,
                "results": [],
                "count": 0,
                "search_term": search_term,
                "message": f"No files found matching '{search_term}'",
                "error": None
            }

        output = [f"Found {len(files)} file(s) matching '{search_term}':"]
        for file in files:
            output.append(f"  {file['name']}")

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
    """Resolve folder_path (relative to Drive root) and return folder metadata.

    Tries strict nested path resolution first (via resolve_folder_path_to_id),
    then falls back to a fuzzy tree-scan where any segment of the path loosely
    matches a folder name. Returns 'not found' if neither strategy resolves.
    Does NOT create the folder — use create_nested_folder_impl for that.
    """
    try:
        folder_id = resolve_folder_path_to_id(service, folder_path, create_if_missing=False)

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

        files_result = list_files_in_folder_impl(service, folder_id)
        subfolders_result = list_folders_in_safeexpress_impl(service, folder_id)

        file_count = files_result.get("count", 0)
        subfolder_count = subfolders_result.get("count", 0)

        return {
            "success": True,
            "folder_id": folder_id,
            "folder_name": folder_path.split('/')[-1],
            "folder_path": folder_path,
            "file_count": file_count,
            "subfolder_count": subfolder_count,
            "message": f"{folder_path}: {file_count} file(s), {subfolder_count} subfolder(s)",
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "folder_id": None,
            "message": f"Failed to get folder info: {str(e)}",
            "error": str(e)
        }


def move_file_impl(service, file_id: str, folder_id: Optional[str] = None, folder_path: Optional[str] = None, create_if_missing: bool = False) -> Dict:
    """Move (reparent) a file or folder to a target folder.

    Provide exactly one of:
      - folder_id: destination folder's Drive ID (preferred when already known)
      - folder_path: destination folder path relative to Drive root; resolved
        to an ID.

    create_if_missing defaults to False so that a typo in folder_path (e.g.
    'Fiance' instead of 'Finance') fails loudly rather than silently creating
    a new folder the user never asked for. Callers that truly want the
    destination created on demand must set create_if_missing=True explicitly.

    Google Drive files can have multiple parents. This replaces all existing
    parents with the destination — matching the 'Move' UX in the web UI.
    """
    try:
        if not file_id:
            return {"success": False, "error": "file_id is required", "message": "file_id is required"}

        destination_id = folder_id
        if not destination_id:
            if not folder_path:
                return {"success": False, "error": "Provide folder_id or folder_path", "message": "No destination specified"}
            destination_id = resolve_folder_path_to_id(
                service, folder_path, create_if_missing=create_if_missing
            )
            if not destination_id:
                return {
                    "success": False,
                    "error": f"Destination folder '{folder_path}' not found",
                    "message": f"Destination folder '{folder_path}' not found (create_if_missing={create_if_missing})",
                }

        file_meta = service.files().get(fileId=file_id, fields="id, name, parents, mimeType").execute()
        current_parents = file_meta.get("parents", []) or []
        remove_parents = ",".join(current_parents) if current_parents else None

        updated = service.files().update(
            fileId=file_id,
            addParents=destination_id,
            removeParents=remove_parents,
            fields="id, name, parents",
        ).execute()

        is_folder = file_meta.get("mimeType") == "application/vnd.google-apps.folder"
        url_prefix = "folders" if is_folder else "file/d"
        new_url = f"https://drive.google.com/{url_prefix}/{file_id}" + ("" if is_folder else "/view")

        return {
            "success": True,
            "file_id": updated.get("id"),
            "file_name": updated.get("name"),
            "new_parents": updated.get("parents", []),
            "destination_folder_id": destination_id,
            "destination_folder_path": folder_path,
            "file_url": new_url,
            "message": f"Moved '{updated.get('name')}' to {folder_path or destination_id}",
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "file_id": None,
            "message": f"Move failed: {str(e)}",
            "error": str(e),
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


def rename_file_impl(service, file_id: str, new_name: str) -> Dict:
    """Rename a file or folder in Google Drive - RETURNS DICT"""
    try:
        updated = service.files().update(
            fileId=file_id,
            body={'name': new_name},
            fields='id, name'
        ).execute()
        return {
            "success": True,
            "file_id": updated['id'],
            "new_name": updated['name'],
            "message": f"Renamed to '{updated['name']}'",
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "file_id": None,
            "new_name": None,
            "message": f"Rename failed: {str(e)}",
            "error": str(e)
        }
