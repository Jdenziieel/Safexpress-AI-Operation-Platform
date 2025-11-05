import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv, set_key

load_dotenv()

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.readonly'
]

def generate_tokens():
    print("Gmail OAuth Token Generator")
    print("=" * 60)
    
    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
    creds = flow.run_local_server(port=0)
    
    if creds and creds.valid:
        env_path = '.env'
        set_key(env_path, 'GOOGLE_ACCESS_TOKEN', creds.token)
        set_key(env_path, 'GOOGLE_REFRESH_TOKEN', creds.refresh_token)
        
        with open('credentials.json', 'r') as f:
            cred_data = json.load(f)
            client_data = cred_data.get('installed', {})
            set_key(env_path, 'GOOGLE_CLIENT_ID', client_data['client_id'])
            set_key(env_path, 'GOOGLE_CLIENT_SECRET', client_data['client_secret'])
        
        print("SUCCESS! Tokens saved to .env")
        return True
    return False

if __name__ == '__main__':
    generate_tokens()
