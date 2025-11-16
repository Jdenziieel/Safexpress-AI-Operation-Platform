from flask import Flask, request, jsonify, redirect, session
from flask_cors import CORS
from flask_session import Session
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
import os
import re
from google_auth_oauthlib.flow import Flow

app = Flask(__name__)
app.secret_key = "super_sigma_token_12345"

# === Session config ===
app.config.update(
    SESSION_TYPE="filesystem",
    SESSION_PERMANENT=False,
    SESSION_USE_SIGNER=True,
    SESSION_COOKIE_NAME="gdrive_session",
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_DOMAIN=None,
)
Session(app)

# === CORS ===
CORS(app, supports_credentials=True, origins=["http://localhost:5173"])

# === OAuth Config ===
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
CLIENT_SECRETS_FILE = "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# === OAuth Routes ===
@app.route("/authorize")
def authorize():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri="http://localhost:5000/oauth2callback",
    )
    auth_url, _ = flow.authorization_url(prompt="consent")
    return jsonify({"auth_url": auth_url})

@app.route("/oauth2callback")
def oauth2callback():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri="http://localhost:5000/oauth2callback",
    )
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    session["credentials"] = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }
    return redirect("http://localhost:5173/google-drive-agent?connected=true")

@app.route("/check_auth")
def check_auth():
    return jsonify({"authenticated": "credentials" in session})

# === Helper Functions ===
def parse_folder_path(message):
    """Extract folder path from natural language with advanced NLP"""
    original = message
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
    
    # Clean up extra spaces
    cleaned = ' '.join(cleaned.split())
    
    # Pattern 1: "named X" or "called X" - extracts name after these keywords
    named_pattern = r'(?:named?|called?|call it|name it)\s+([a-zA-Z0-9_\-\/\s]+?)(?:\s+in\s+|\s*$)'
    named_match = re.search(named_pattern, cleaned)
    if named_match:
        folder_name = named_match.group(1).strip()
        # Check if there's an "in" clause for parent
        in_pattern = r'\bin\s+([a-zA-Z0-9_\-\/]+)'
        in_match = re.search(in_pattern, cleaned)
        if in_match:
            parent = in_match.group(1).strip()
            return f"{parent}/{folder_name}".replace(' ', '_')
        return folder_name.replace(' ', '_')
    
    # Pattern 2: "create folder X in/within/inside/under Y" -> Y/X
    in_match = re.search(r'folder\s+([a-zA-Z0-9_\-\/\s]+?)\s+(?:in|within|inside|under)\s+(?:the\s+)?([a-zA-Z0-9_\-\/\s]+?)(?:\s+folder|\s*$)', cleaned)
    if in_match:
        folder_name = in_match.group(1).strip().replace(' ', '_')
        parent_path = in_match.group(2).strip().replace(' ', '_')
        return f"{parent_path}/{folder_name}"
    
    # Pattern 3: "create folder X/Y/Z" (with slashes - nested path)
    slash_match = re.search(r'folder\s+([a-zA-Z0-9_\-\/]+(?:/[a-zA-Z0-9_\-]+)*)', cleaned)
    if slash_match:
        path = slash_match.group(1).strip()
        if '/' in path:
            return path
    
    # Pattern 4: Extract quoted name "create folder 'X'" or 'create folder "X"'
    quote_match = re.search(r'folder\s+["\']([^"\']+)["\']', cleaned)
    if quote_match:
        return quote_match.group(1).strip().replace(' ', '_')
    
    # Pattern 5: Simple extraction after "folder" keyword
    # Get everything after "folder" until a preposition or end
    folder_match = re.search(r'folder\s+([a-zA-Z0-9_\-]+(?:\s+[a-zA-Z0-9_\-]+)*?)(?:\s+(?:in|within|inside|under|to|for|with|at|on)\s+|\s*$)', cleaned)
    if folder_match:
        folder_name = folder_match.group(1).strip()
        # Remove remaining filler words
        stopwords = ['new', 'my', 'your', 'our', 'this', 'that', 'these', 'those']
        words = folder_name.split()
        words = [w for w in words if w not in stopwords]
        if words:
            # Check if there's a parent folder specified
            parent_match = re.search(r'\b(?:in|within|inside|under)\s+(?:the\s+)?([a-zA-Z0-9_\-\/\s]+?)(?:\s+folder|\s*$)', cleaned)
            if parent_match:
                parent = parent_match.group(1).strip().replace(' ', '_')
                return f"{parent}/{('_'.join(words))}"
            return '_'.join(words)
    
    # Pattern 6: Last resort - get first meaningful word after folder
    if 'folder' in cleaned:
        parts = cleaned.split('folder', 1)
        if len(parts) > 1:
            remaining = parts[1].strip()
            # Get first word that's not a stopword
            words = remaining.split()
            stopwords = ['new', 'my', 'your', 'our', 'this', 'that', 'in', 'to', 'for']
            for word in words:
                if word and word not in stopwords and len(word) > 1:
                    return word
    
    return None

def extract_target_location(message):
    """Extract target folder from upload/move commands"""
    cleaned = message.lower().strip()
    
    # Remove filler words
    filler_patterns = [
        r'\bplease\b', r'\bcan you\b', r'\bcould you\b',
        r'\bthe folder\b', r'\ba folder\b', r'\bfolder\b'
    ]
    for pattern in filler_patterns:
        cleaned = re.sub(pattern, ' ', cleaned)
    cleaned = ' '.join(cleaned.split())
    
    # Extract after "to" or "in"
    to_pattern = r'\b(?:to|in)\s+([a-zA-Z0-9_\-\/]+)'
    match = re.search(to_pattern, cleaned)
    if match:
        return match.group(1).strip()
    
    return None
    """Extract folder path from natural language with advanced NLP"""
    original = message
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
    
    # Clean up extra spaces
    cleaned = ' '.join(cleaned.split())
    
    # Pattern 1: "named X" or "called X" - extracts name after these keywords
    named_pattern = r'(?:named?|called?|call it|name it)\s+([a-zA-Z0-9_\-\/\s]+?)(?:\s+in\s+|\s*$)'
    named_match = re.search(named_pattern, cleaned)
    if named_match:
        folder_name = named_match.group(1).strip()
        # Check if there's an "in" clause for parent
        in_pattern = r'\bin\s+([a-zA-Z0-9_\-\/]+)'
        in_match = re.search(in_pattern, cleaned)
        if in_match:
            parent = in_match.group(1).strip()
            return f"{parent}/{folder_name}".replace(' ', '_')
        return folder_name.replace(' ', '_')
    
    # Pattern 2: "create folder X in Y" -> Y/X
    in_match = re.search(r'folder\s+([a-zA-Z0-9_\-\/\s]+?)\s+in\s+([a-zA-Z0-9_\-\/\s]+)', cleaned)
    if in_match:
        folder_name = in_match.group(1).strip().replace(' ', '_')
        parent_path = in_match.group(2).strip().replace(' ', '_')
        return f"{parent_path}/{folder_name}"
    
    # Pattern 3: "create folder X/Y/Z" (with slashes - nested path)
    slash_match = re.search(r'folder\s+([a-zA-Z0-9_\-\/]+(?:/[a-zA-Z0-9_\-]+)*)', cleaned)
    if slash_match:
        path = slash_match.group(1).strip()
        if '/' in path:
            return path
    
    # Pattern 4: Extract quoted name "create folder 'X'" or 'create folder "X"'
    quote_match = re.search(r'folder\s+["\']([^"\']+)["\']', cleaned)
    if quote_match:
        return quote_match.group(1).strip().replace(' ', '_')
    
    # Pattern 5: Simple extraction after "folder" keyword
    # Get everything after "folder" until a preposition or end
    folder_match = re.search(r'folder\s+([a-zA-Z0-9_\-]+(?:\s+[a-zA-Z0-9_\-]+)*?)(?:\s+(?:in|to|for|with|at|on)\s+|\s*$)', cleaned)
    if folder_match:
        folder_name = folder_match.group(1).strip()
        # Remove remaining filler words
        stopwords = ['new', 'my', 'your', 'our', 'this', 'that', 'these', 'those']
        words = folder_name.split()
        words = [w for w in words if w not in stopwords]
        if words:
            return '_'.join(words)
    
    # Pattern 6: Last resort - get first meaningful word after folder
    if 'folder' in cleaned:
        parts = cleaned.split('folder', 1)
        if len(parts) > 1:
            remaining = parts[1].strip()
            # Get first word that's not a stopword
            words = remaining.split()
            stopwords = ['new', 'my', 'your', 'our', 'this', 'that', 'in', 'to', 'for']
            for word in words:
                if word and word not in stopwords and len(word) > 1:
                    return word
    
    return None

def format_folder_tree(folders):
    """Format folder structure as a readable tree"""
    if not folders:
        return "No folders found in SafeExpress."
    
    lines = ["📁 SafeExpress/"]
    for folder in folders:
        lines.append(folder["display"])
    return "\n".join(lines)

# === Agent Endpoint ===
@app.route("/agent", methods=["POST"])
def agent_chat():
    # Get message from JSON or form
    if request.content_type and request.content_type.startswith("application/json"):
        message = request.json.get("message", "").lower()
    else:
        message = request.form.get("message", "").lower()

    file = request.files.get("file", None)

    # Auth check
    if "credentials" not in session:
        return jsonify({"reply": "❌ Not authorized. Please log in first."}), 401
    
    service = get_session_drive_service(session["credentials"])

    try:
        # === FILE UPLOAD ===
        if file:
            folder_path = extract_target_location(message)
            
            file_id = upload_stream_to_folder(
                service, 
                file.stream, 
                file.filename, 
                file.mimetype, 
                folder_path
            )
            
            location = f" to SafeExpress/{folder_path}" if folder_path else " to SafeExpress"
            return jsonify({
                "reply": f"✅ Uploaded '{file.filename}'{location}!",
                "file_id": file_id
            })

        # === CREATE FOLDER ===
        elif "create" in message and "folder" in message:
            folder_path = parse_folder_path(message)
            
            if not folder_path:
                return jsonify({"reply": "❌ Please specify a folder name. Example: 'create folder Operations/2024'"})
            
            folder_id = create_nested_folder(service, folder_path)
            return jsonify({
                "reply": f"✅ Created folder: SafeExpress/{folder_path}",
                "folder_id": folder_id
            })

        # === LIST FOLDERS ===
        elif ("list" in message or "show" in message) and "folder" in message:
            structure = get_folder_structure(service)
            tree = format_folder_tree(structure)
            return jsonify({"reply": tree})

        # === LIST FILES IN FOLDER ===
        elif ("list" in message or "show" in message) and "file" in message:
            folder_name = extract_target_location(message)
            
            if folder_name:
                # Find folder and list files
                safeexpress_id = get_safeexpress_folder_id(service)
                folder_id = find_folder(service, folder_name, safeexpress_id)
                
                if not folder_id:
                    # Try nested search
                    folders = get_folder_structure(service)
                    matching = [f for f in folders if folder_name.lower() in f['name'].lower()]
                    if matching:
                        folder_id = matching[0]['id']
                
                if folder_id:
                    files = list_files_in_folder(service, folder_id)
                    if not files:
                        return jsonify({"reply": f"📭 No files in '{folder_name}'"})
                    
                    file_list = "\n".join([f"📄 {f['name']}" for f in files])
                    return jsonify({"reply": f"Files in '{folder_name}':\n{file_list}"})
                else:
                    return jsonify({"reply": f"❌ Folder '{folder_name}' not found"})
            else:
                # List all files in SafeExpress root
                safeexpress_id = get_safeexpress_folder_id(service)
                files = list_files_in_folder(service, safeexpress_id)
                
                if not files:
                    return jsonify({"reply": "📭 No files in SafeExpress root"})
                
                file_list = "\n".join([f"📄 {f['name']}" for f in files])
                return jsonify({"reply": f"Files in SafeExpress:\n{file_list}"})

        # === SEARCH ===
        elif "search" in message or "find" in message:
            # Extract search term
            search_term = message.replace("search", "").replace("find", "").replace("for", "").strip()
            
            if not search_term:
                return jsonify({"reply": "❌ Please specify what to search for"})
            
            results = search_files_in_safeexpress(service, search_term)
            
            if not results:
                return jsonify({"reply": f"🔍 No files found matching '{search_term}'"})
            
            result_list = "\n".join([f"📄 {f['name']}" for f in results])
            return jsonify({"reply": f"Found {len(results)} file(s):\n{result_list}"})

        # === HELP / DEFAULT ===
        else:
            return jsonify({
                "reply": "🤖 I can help you with:\n\n"
                        "📁 Folders:\n"
                        "  • 'create folder <name>' - Create folder\n"
                        "  • 'create folder <path/to/folder>' - Nested folders\n"
                        "  • 'list folders' - Show folder structure\n\n"
                        "📄 Files:\n"
                        "  • Upload files using the attachment button\n"
                        "  • 'list files' - Show files in SafeExpress\n"
                        "  • 'list files in <folder>' - Show files in folder\n"
                        "  • 'search <term>' - Find files\n\n"
                        "💡 Examples:\n"
                        "  • 'create folder Operations/2024/Reports'\n"
                        "  • 'list files in Operations'\n"
                        "  • 'search invoice'"
            })

    except Exception as e:
        return jsonify({"reply": f"❌ Error: {str(e)}"}), 500

@app.route('/logout', methods=['POST'])
def logout():
    try:
        session.clear()
        return jsonify({'success': True, 'message': 'Logged out successfully.'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

if __name__ == "__main__":
    app.run(port=5000, debug=True)