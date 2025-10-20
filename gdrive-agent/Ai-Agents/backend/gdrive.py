from flask import Flask, request, jsonify, redirect, session
from flask_cors import CORS
from flask_session import Session
from tools import (
    get_session_drive_service,
    upload_stream_to_folder,
    get_or_create_folder,
    list_files,
    upload_file,
    create_folder_in_safeexpress,
    upload_file_to_folder
)
import os
import re
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

app = Flask(__name__)
app.secret_key = "replace_this_with_a_strong_secret"

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

# === Agent Endpoint ===
@app.route("/agent", methods=["POST"])
def agent_chat():
    message = request.form.get("message", "").lower()
    file = request.files.get("file", None)

    # Session-based service
    if "credentials" not in session:
        return jsonify({"error": "Not authorized"}), 401
    service = get_session_drive_service(session["credentials"])

    # === File Upload ===
    if "upload" in message and file:
        folder_name = None
        if "to" in message:
            parts = message.split("to")
            folder_name = parts[-1].strip()
        file_id = upload_stream_to_folder(file.stream, file.filename, file.mimetype, folder_name, session["credentials"])
        reply = f"Uploaded '{file.filename}' to Google Drive!"
        if folder_name:
            reply += f" (in folder '{folder_name}')"
        return jsonify({"reply": reply, "file_id": file_id})

    # === Folder Creation ===
    elif "create folder" in message:
        folder_name = message.split("create folder")[-1].strip() or "New Folder"
        folder_id = get_or_create_folder(service, folder_name)
        return jsonify({"reply": f"📁 Folder '{folder_name}' created!", "folder_id": folder_id})

    # === Text-based Commands ===
    elif "list files" in message:
        files = list_files()
        if not files:
            return jsonify({"reply": "No files found in your Google Drive."})
        return jsonify({"reply": "Files:\n" + "\n".join([f"{f['name']} (ID: {f['id']})" for f in files])})

    elif "upload" in message and "to folder" in message:
        match = re.search(r"upload ([\w\.\- ]+) from ([^ ]+) to folder ([\w\- ]+)", message)
        if match:
            filename = match.group(1).strip()
            filepath = match.group(2).strip()
            folder_name = match.group(3).strip()
            try:
                file_id = upload_file_to_folder(filename, filepath, folder_name)
                return jsonify({"reply": f"📤 File '{filename}' uploaded to folder '{folder_name}'!", "file_id": file_id})
            except Exception as e:
                return jsonify({"reply": f"Error uploading file: {str(e)}"})

    elif "upload" in message:
        parts = message.split("from")
        if len(parts) == 2:
            filename = parts[0].replace("upload", "").strip()
            filepath = parts[1].strip()
            try:
                file_id = upload_file(filename, filepath)
                return jsonify({"reply": f"📤 File '{filename}' uploaded successfully!", "file_id": file_id})
            except Exception as e:
                return jsonify({"reply": f"Error uploading file: {str(e)}"})

    return jsonify({"reply": "Try 'upload file <file> to <folder>' or 'create folder <name>'."})

if __name__ == "__main__":
    app.run(port=5000, debug=True)
