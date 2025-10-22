import os
import re
from typing import Optional, List
from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from tools import (
    get_session_drive_service,
    upload_stream_to_folder,
    create_nested_folder,
    list_folders_in_safeexpress,
    list_files_in_folder,
    get_folder_structure,
    get_safeexpress_folder_id,
    search_files_in_safeexpress,
    find_folder,
    get_folder_path
)

# Initialize FastAPI app
app = FastAPI(
    title="SafexpressOps Google Drive Agent API",
    description="AI-powered Google Drive file management API with natural language processing",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OAuth Config
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
CLIENT_SECRETS_FILE = "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
REDIRECT_URI = "http://localhost:8001/oauth2callback"

# In-memory session storage (use Redis/DB in production)
sessions = {}

# Pydantic models
class FolderCreate(BaseModel):
    folder_path: str = Field(..., description="Folder path (e.g., 'Operations/2024/Reports')")

class FileUpload(BaseModel):
    folder_path: Optional[str] = Field(None, description="Target folder path")

class FileSearch(BaseModel):
    search_term: str = Field(..., description="Search keywords")

class NaturalLanguageRequest(BaseModel):
    message: str = Field(..., description="Natural language request")
    session_id: Optional[str] = Field(None, description="Session ID for authentication")

class AuthResponse(BaseModel):
    auth_url: str
    session_id: str

# Helper Functions
def parse_folder_path(message: str) -> Optional[str]:
    """Extract folder path from natural language with advanced NLP"""
    cleaned = message.lower().strip()
    
    # Remove common filler words and phrases
    filler_patterns = [
        r'\bplease\b', r'\bcan you\b', r'\bcould you\b', r'\bwould you\b',
        r'\bi want to\b', r'\bi need to\b', r'\bi would like to\b',
        r'\bfor me\b', r'\bme a\b', r'\ba new\b', r'\bthe\b', r'\ba\b',
        r'\bhelp me\b'
    ]
    for pattern in filler_patterns:
        cleaned = re.sub(pattern, ' ', cleaned)
    
    cleaned = ' '.join(cleaned.split())
    
    # Pattern 1: "named X" or "called X"
    named_pattern = r'(?:named?|called?|call it|name it)\s+([a-zA-Z0-9_\-\/\s]+?)(?:\s+in\s+|\s*$)'
    named_match = re.search(named_pattern, cleaned)
    if named_match:
        folder_name = named_match.group(1).strip()
        in_pattern = r'\bin\s+([a-zA-Z0-9_\-\/]+)'
        in_match = re.search(in_pattern, cleaned)
        if in_match:
            parent = in_match.group(1).strip()
            return f"{parent}/{folder_name}".replace(' ', '_')
        return folder_name.replace(' ', '_')
    
    # Pattern 2: "create folder X in/within/inside/under Y"
    in_match = re.search(r'folder\s+([a-zA-Z0-9_\-\/\s]+?)\s+(?:in|within|inside|under)\s+(?:the\s+)?([a-zA-Z0-9_\-\/\s]+?)(?:\s+folder|\s*$)', cleaned)
    if in_match:
        folder_name = in_match.group(1).strip().replace(' ', '_')
        parent_path = in_match.group(2).strip().replace(' ', '_')
        return f"{parent_path}/{folder_name}"
    
    # Pattern 3: "create folder X/Y/Z" (with slashes)
    slash_match = re.search(r'folder\s+([a-zA-Z0-9_\-\/]+(?:/[a-zA-Z0-9_\-]+)*)', cleaned)
    if slash_match:
        path = slash_match.group(1).strip()
        if '/' in path:
            return path
    
    # Pattern 4: Extract quoted name
    quote_match = re.search(r'folder\s+["\']([^"\']+)["\']', cleaned)
    if quote_match:
        return quote_match.group(1).strip().replace(' ', '_')
    
    # Pattern 5: Simple extraction after "folder"
    folder_match = re.search(r'folder\s+([a-zA-Z0-9_\-]+(?:\s+[a-zA-Z0-9_\-]+)*?)(?:\s+(?:in|within|inside|under|to|for|with|at|on)\s+|\s*$)', cleaned)
    if folder_match:
        folder_name = folder_match.group(1).strip()
        stopwords = ['new', 'my', 'your', 'our', 'this', 'that', 'these', 'those']
        words = folder_name.split()
        words = [w for w in words if w not in stopwords]
        if words:
            parent_match = re.search(r'\b(?:in|within|inside|under)\s+(?:the\s+)?([a-zA-Z0-9_\-\/\s]+?)(?:\s+folder|\s*$)', cleaned)
            if parent_match:
                parent = parent_match.group(1).strip().replace(' ', '_')
                return f"{parent}/{('_'.join(words))}"
            return '_'.join(words)
    
    # Pattern 6: Last resort
    if 'folder' in cleaned:
        parts = cleaned.split('folder', 1)
        if len(parts) > 1:
            remaining = parts[1].strip()
            words = remaining.split()
            stopwords = ['new', 'my', 'your', 'our', 'this', 'that', 'in', 'to', 'for']
            for word in words:
                if word and word not in stopwords and len(word) > 1:
                    return word
    
    return None

def extract_target_location(message: str) -> Optional[str]:
    """Extract target folder from upload/move commands"""
    cleaned = message.lower().strip()
    
    filler_patterns = [
        r'\bplease\b', r'\bcan you\b', r'\bcould you\b',
        r'\bthe folder\b', r'\ba folder\b', r'\bfolder\b'
    ]
    for pattern in filler_patterns:
        cleaned = re.sub(pattern, ' ', cleaned)
    cleaned = ' '.join(cleaned.split())
    
    to_pattern = r'\b(?:to|in)\s+([a-zA-Z0-9_\-\/]+)'
    match = re.search(to_pattern, cleaned)
    if match:
        return match.group(1).strip()
    
    return None

def format_folder_tree(folders: list) -> str:
    """Format folder structure as a readable tree"""
    if not folders:
        return "No folders found in SafeExpress."
    
    lines = ["📁 SafeExpress/"]
    for folder in folders:
        lines.append(folder["display"])
    return "\n".join(lines)

def get_service_from_session(session_id: str):
    """Get Drive service from session ID"""
    if session_id not in sessions:
        raise HTTPException(status_code=401, detail="Not authenticated. Please authorize first.")
    
    creds_dict = sessions[session_id]
    return get_session_drive_service(creds_dict)

# OAuth Routes
@app.get("/authorize")
async def authorize():
    """Initiate OAuth flow and return authorization URL"""
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    auth_url, state = flow.authorization_url(prompt="consent")
    
    # Store state as session_id
    return AuthResponse(auth_url=auth_url, session_id=state)

@app.get("/oauth2callback")
async def oauth2callback(code: str, state: str):
    """Handle OAuth callback and store credentials"""
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
        state=state
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    
    # Store credentials in session
    sessions[state] = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }
    
    return JSONResponse({
        "success": True,
        "message": "Authentication successful!",
        "session_id": state
    })

@app.get("/check_auth")
async def check_auth(session_id: str):
    """Check if session is authenticated"""
    authenticated = session_id in sessions
    return {"authenticated": authenticated, "session_id": session_id if authenticated else None}

# Folder Management
@app.post("/folders")
async def create_folder(request: FolderCreate, session_id: str = Query(...)):
    """Create a folder or nested folder structure"""
    try:
        service = get_service_from_session(session_id)
        folder_id = create_nested_folder(service, request.folder_path)
        return {
            "success": True,
            "message": f"✅ Created folder: SafeExpress/{request.folder_path}",
            "folder_id": folder_id
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/folders")
async def list_folders(session_id: str = Query(...)):
    """List all folders in SafeExpress with tree structure"""
    try:
        service = get_service_from_session(session_id)
        structure = get_folder_structure(service)
        tree = format_folder_tree(structure)
        return {
            "success": True,
            "message": tree,
            "folders": structure
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/folders/{folder_path:path}")
async def get_folder_contents(folder_path: str, session_id: str = Query(...)):
    """Get contents of a specific folder"""
    try:
        service = get_service_from_session(session_id)
        safeexpress_id = get_safeexpress_folder_id(service)
        folder_id = find_folder(service, folder_path, safeexpress_id)
        
        if not folder_id:
            # Try nested search
            folders = get_folder_structure(service)
            matching = [f for f in folders if folder_path.lower() in f['name'].lower()]
            if matching:
                folder_id = matching[0]['id']
        
        if not folder_id:
            raise HTTPException(status_code=404, detail=f"Folder '{folder_path}' not found")
        
        files = list_files_in_folder(service, folder_id)
        return {
            "success": True,
            "folder_path": folder_path,
            "file_count": len(files),
            "files": files
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# File Management
@app.post("/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    folder_path: Optional[str] = None,
    session_id: str = Query(...)
):
    """Upload a file to SafeExpress or a specific folder"""
    try:
        service = get_service_from_session(session_id)
        
        file_id = upload_stream_to_folder(
            service,
            file.file,
            file.filename,
            file.content_type,
            folder_path
        )
        
        location = f" to SafeExpress/{folder_path}" if folder_path else " to SafeExpress"
        return {
            "success": True,
            "message": f"✅ Uploaded '{file.filename}'{location}!",
            "file_id": file_id
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/files")
async def list_files(folder_path: Optional[str] = None, session_id: str = Query(...)):
    """List files in SafeExpress root or a specific folder"""
    try:
        service = get_service_from_session(session_id)
        safeexpress_id = get_safeexpress_folder_id(service)
        
        if folder_path:
            folder_id = find_folder(service, folder_path, safeexpress_id)
            if not folder_id:
                # Try nested search
                folders = get_folder_structure(service)
                matching = [f for f in folders if folder_path.lower() in f['name'].lower()]
                if matching:
                    folder_id = matching[0]['id']
            
            if not folder_id:
                raise HTTPException(status_code=404, detail=f"Folder '{folder_path}' not found")
        else:
            folder_id = safeexpress_id
        
        files = list_files_in_folder(service, folder_id)
        
        if not files:
            location = folder_path or "SafeExpress root"
            return {
                "success": True,
                "message": f"📭 No files in {location}",
                "files": []
            }
        
        location = folder_path or "SafeExpress"
        return {
            "success": True,
            "message": f"Found {len(files)} file(s) in {location}",
            "files": files
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/files/search")
async def search_files(request: FileSearch, session_id: str = Query(...)):
    """Search for files in SafeExpress"""
    try:
        service = get_service_from_session(session_id)
        results = search_files_in_safeexpress(service, request.search_term)
        
        if not results:
            return {
                "success": True,
                "message": f"🔍 No files found matching '{request.search_term}'",
                "results": []
            }
        
        return {
            "success": True,
            "message": f"Found {len(results)} file(s)",
            "results": results
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Natural Language Agent Endpoint
@app.post("/agent")
async def agent_chat(request: NaturalLanguageRequest):
    """
    Process natural language requests for Drive operations.
    Supports: create folder, list folders, list files, search files, and more.
    """
    message = request.message.lower().strip()
    session_id = request.session_id
    
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401, detail="Not authenticated. Please authorize first.")
    
    try:
        service = get_service_from_session(session_id)
        
        # CREATE FOLDER
        if "create" in message and "folder" in message:
            folder_path = parse_folder_path(message)
            
            if not folder_path:
                return {
                    "reply": "❌ Please specify a folder name. Example: 'create folder Operations/2024'"
                }
            
            folder_id = create_nested_folder(service, folder_path)
            return {
                "reply": f"✅ Created folder: SafeExpress/{folder_path}",
                "folder_id": folder_id
            }
        
        # LIST FOLDERS
        elif ("list" in message or "show" in message) and "folder" in message:
            structure = get_folder_structure(service)
            tree = format_folder_tree(structure)
            return {"reply": tree, "folders": structure}
        
        # LIST FILES IN FOLDER
        elif ("list" in message or "show" in message) and "file" in message:
            folder_name = extract_target_location(message)
            
            if folder_name:
                safeexpress_id = get_safeexpress_folder_id(service)
                folder_id = find_folder(service, folder_name, safeexpress_id)
                
                if not folder_id:
                    folders = get_folder_structure(service)
                    matching = [f for f in folders if folder_name.lower() in f['name'].lower()]
                    if matching:
                        folder_id = matching[0]['id']
                
                if folder_id:
                    files = list_files_in_folder(service, folder_id)
                    if not files:
                        return {"reply": f"📭 No files in '{folder_name}'"}
                    
                    file_list = "\n".join([f"📄 {f['name']}" for f in files])
                    return {"reply": f"Files in '{folder_name}':\n{file_list}", "files": files}
                else:
                    return {"reply": f"❌ Folder '{folder_name}' not found"}
            else:
                safeexpress_id = get_safeexpress_folder_id(service)
                files = list_files_in_folder(service, safeexpress_id)
                
                if not files:
                    return {"reply": "📭 No files in SafeExpress root"}
                
                file_list = "\n".join([f"📄 {f['name']}" for f in files])
                return {"reply": f"Files in SafeExpress:\n{file_list}", "files": files}
        
        # SEARCH
        elif "search" in message or "find" in message:
            search_term = message.replace("search", "").replace("find", "").replace("for", "").strip()
            
            if not search_term:
                return {"reply": "❌ Please specify what to search for"}
            
            results = search_files_in_safeexpress(service, search_term)
            
            if not results:
                return {"reply": f"🔍 No files found matching '{search_term}'"}
            
            result_list = "\n".join([f"📄 {f['name']}" for f in results])
            return {
                "reply": f"Found {len(results)} file(s):\n{result_list}",
                "results": results
            }
        
        # HELP
        else:
            return {
                "reply": "🤖 I can help you with:\n\n"
                        "📁 Folders:\n"
                        "  • 'create folder <name>' - Create folder\n"
                        "  • 'create folder <path/to/folder>' - Nested folders\n"
                        "  • 'list folders' - Show folder structure\n\n"
                        "📄 Files:\n"
                        "  • Upload files using /files/upload endpoint\n"
                        "  • 'list files' - Show files in SafeExpress\n"
                        "  • 'list files in <folder>' - Show files in folder\n"
                        "  • 'search <term>' - Find files\n\n"
                        "💡 Examples:\n"
                        "  • 'create folder Operations/2024/Reports'\n"
                        "  • 'list files in Operations'\n"
                        "  • 'search invoice'"
            }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/logout")
async def logout(session_id: str = Query(...)):
    """Clear session and logout"""
    try:
        if session_id in sessions:
            del sessions[session_id]
        return {"success": True, "message": "Logged out successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Health check
@app.get("/")
async def root():
    """API health check"""
    return {
        "status": "online",
        "service": "SafexpressOps Google Drive Agent API",
        "version": "1.0.0",
        "endpoints": {
            "docs": "/docs",
            "redoc": "/redoc"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)