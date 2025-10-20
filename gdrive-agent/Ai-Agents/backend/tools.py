import os
import pickle
import io
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# === Config ===
SCOPES = ['https://www.googleapis.com/auth/drive.file']
TOKEN_PATH = 'token.pickle'
CREDENTIALS_PATH = 'credentials.json'

# === Auth: Token-based (for CLI or persistent agent use) ===
def get_token_drive_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, 'wb') as token:
            pickle.dump(creds, token)
    return build('drive', 'v3', credentials=creds)

# === Auth: Session-based (for Flask apps) ===
def get_session_drive_service(session_creds):
    creds = Credentials(**session_creds)
    return build('drive', 'v3', credentials=creds)

# === Folder Utilities ===
def find_folder(service, folder_name, parent_id=None):
    """Find a folder by name, optionally within a parent folder"""
    query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    folders = results.get("files", [])
    return folders[0]["id"] if folders else None

def create_folder(service, folder_name, parent_id=None):
    """Create a folder, optionally within a parent folder"""
    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]

def get_or_create_folder(service, folder_name, parent_id=None):
    """Get or create a folder, optionally within a parent folder"""
    folder_id = find_folder(service, folder_name, parent_id)
    if folder_id:
        return folder_id
    return create_folder(service, folder_name, parent_id)

def get_safeexpress_folder_id(service):
    """Get or create the root SafeExpress folder"""
    return get_or_create_folder(service, "SafeExpress")

def get_folder_path(service, parent_id):
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

def create_nested_folder(service, folder_path):
    """
    Create nested folders under SafeExpress
    folder_path can be like "Operations/2024/January" or just "Operations"
    Returns the final folder ID
    """
    safeexpress_id = get_safeexpress_folder_id(service)
    current_parent = safeexpress_id
    
    # Split path and create each folder
    folders = [f.strip() for f in folder_path.split('/') if f.strip()]
    
    for folder_name in folders:
        current_parent = get_or_create_folder(service, folder_name, current_parent)
    
    return current_parent

def list_folders_in_safeexpress(service, parent_id=None):
    """List all folders within SafeExpress or a specific parent folder"""
    if parent_id is None:
        parent_id = get_safeexpress_folder_id(service)
    
    query = f"mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false"
    results = service.files().list(
        q=query, 
        fields="files(id, name, createdTime)",
        orderBy="name"
    ).execute()
    return results.get('files', [])

def list_files_in_folder(service, folder_id):
    """List all files (non-folders) in a specific folder"""
    query = f"'{folder_id}' in parents and mimeType!='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType, size, createdTime)",
        orderBy="name"
    ).execute()
    return results.get('files', [])

def get_folder_structure(service, folder_id=None, level=0, max_level=3):
    """Get the entire folder structure as a tree (limited depth)"""
    if level > max_level:
        return []
    
    if folder_id is None:
        folder_id = get_safeexpress_folder_id(service)
    
    folders = list_folders_in_safeexpress(service, folder_id)
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
            subfolders = get_folder_structure(service, folder["id"], level + 1, max_level)
            structure.extend(subfolders)
    
    return structure

# === File Listing ===
def list_files():
    """List recent files (legacy function)"""
    service = get_token_drive_service()
    results = service.files().list(pageSize=10, fields="files(id, name)").execute()
    return results.get('files', [])

# === File Uploads ===
def upload_file(filename, filepath):
    """Upload file to root (legacy)"""
    service = get_token_drive_service()
    metadata = {'name': filename}
    media = MediaFileUpload(filepath, resumable=True)
    file = service.files().create(body=metadata, media_body=media, fields='id').execute()
    return file.get('id')

def upload_file_to_folder(service, filename, filepath, folder_path):
    """Upload file to a specific folder path in SafeExpress"""
    folder_id = create_nested_folder(service, folder_path)
    metadata = {'name': filename, 'parents': [folder_id]}
    media = MediaFileUpload(filepath, resumable=True)
    file = service.files().create(body=metadata, media_body=media, fields='id').execute()
    return file.get('id')

def upload_stream_to_folder(service, file_stream, filename, mimetype, folder_path=None):
    """Upload a file stream to SafeExpress or a specific folder path"""
    if folder_path:
        folder_id = create_nested_folder(service, folder_path)
    else:
        folder_id = get_safeexpress_folder_id(service)
    
    metadata = {'name': filename, 'parents': [folder_id]}
    media = MediaIoBaseUpload(file_stream, mimetype=mimetype)
    file = service.files().create(body=metadata, media_body=media, fields='id').execute()
    return file.get('id')

def search_files_in_safeexpress(service, search_term):
    """Search for files within SafeExpress folder"""
    safeexpress_id = get_safeexpress_folder_id(service)
    query = f"name contains '{search_term}' and '{safeexpress_id}' in parents and trashed=false"
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType)",
        pageSize=20
    ).execute()
    return results.get('files', [])