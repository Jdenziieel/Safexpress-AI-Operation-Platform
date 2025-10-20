import os
import pickle
from flask import Flask, request, jsonify, redirect, session
from flask_cors import CORS
from google_auth_oauthlib.flow import Flow
from agent import handle_message

# ✅ ALLOW HTTP ONLY IN LOCAL DEVELOPMENT
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # change this to something random and secure
CORS(app, supports_credentials=True)

SCOPES = ['https://www.googleapis.com/auth/drive.file']

from tools import upload_file_to_safeexpress

# Place this after app initialization
@app.route('/logout', methods=['POST'])
def logout():
    try:
        if os.path.exists('token.pickle'):
            os.remove('token.pickle')
        return jsonify({'success': True, 'message': 'Logged out successfully.'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/check_auth')
def check_auth():
    import os
    authenticated = os.path.exists('token.pickle')
    return jsonify({'authenticated': authenticated})

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'response': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'response': 'No selected file'}), 400
    temp_dir = 'temp'
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, file.filename)
    file.save(temp_path)
    try:
        file_id = upload_file_to_safeexpress(file.filename, temp_path)
        os.remove(temp_path)
        return jsonify({'response': f"File '{file.filename}' uploaded to SafeExpress! File ID: {file_id}"})
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return jsonify({'response': f"Error uploading file: {str(e)}"}), 500

@app.route('/authorize')
def authorize():
    # Clear any existing session data to prevent conflicts
    session.clear()
    
    flow = Flow.from_client_secrets_file(
        'credentials.json',
        scopes=SCOPES,
        redirect_uri='http://localhost:5000/oauth2callback'
    )
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'  # Force fresh consent to avoid token reuse
    )
    session['state'] = state
    print(f"STATE STORED: {state}")
    return jsonify({'auth_url': authorization_url})

@app.route('/oauth2callback')
def oauth2callback():
    state = session.get('state') or request.args.get('state')
    if not state:
        return "Error: Missing state parameter.", 400

    try:
        flow = Flow.from_client_secrets_file(
            'credentials.json',
            scopes=SCOPES,
            state=state,
            redirect_uri='http://localhost:5000/oauth2callback'
        )

        # ✅ This will now work since we allowed insecure HTTP transport
        flow.fetch_token(authorization_response=request.url)

        creds = flow.credentials
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

        print("✅ Google OAuth2 token saved as token.pickle")
        
        # Clear session after successful authentication
        session.pop('state', None)
        
        return redirect('http://localhost:5173')
    except Exception as e:
        print(f"❌ OAuth error: {str(e)}")
        # Clear session on error
        session.clear()
        return redirect('http://localhost:5173?error=auth_failed')

@app.route('/agent', methods=['POST'])
def agent_chat():
    data = request.json
    message = data.get('message', '')
    response = handle_message(message)
    return jsonify({'response': response})

if __name__ == '__main__':
    app.run(port=5000, debug=True)
