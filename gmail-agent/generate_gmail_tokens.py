import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv, set_key

load_dotenv()

SCOPES = [
    # Gmail
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.readonly',
    # Calendar
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.events',
    # Docs
    'https://www.googleapis.com/auth/documents',
    # Sheets
    'https://www.googleapis.com/auth/spreadsheets',
    # Drive
    'https://www.googleapis.com/auth/drive',
]

def generate_tokens():
    print("Google OAuth Token Generator")
    print("=" * 60)
    print("Scopes requested:")
    for scope in SCOPES:
        print(f"  ✓ {scope}")
    print("=" * 60)
    
    # Ask user which account to use
    print("\nWhich account do you want to authorize?")
    print("  1. admin@safexpressops.com")
    print("  2. Enter a different account")
    print("  3. Let me choose in the browser (no hint)")
    
    choice = input("\nEnter choice (1/2/3): ").strip()
    
    if choice == '1':
        login_hint = 'admin@safexpressops.com'
    elif choice == '2':
        login_hint = input("Enter email address: ").strip()
    else:
        login_hint = None
    
    if login_hint:
        print(f"\n→ Will pre-select account: {login_hint}")
    else:
        print("\n→ No account pre-selected, choose in browser")
    
    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
    
    # Build kwargs dynamically
    server_kwargs = {
        'port': 0,
        'prompt': 'select_account consent',  # Always show account picker + consent
    }
    if login_hint:
        server_kwargs['login_hint'] = login_hint
    
    creds = flow.run_local_server(**server_kwargs)
    
    if creds and creds.valid:
        env_path = '.env'
        set_key(env_path, 'GOOGLE_ACCESS_TOKEN', creds.token)
        set_key(env_path, 'GOOGLE_REFRESH_TOKEN', creds.refresh_token)
        
        with open('credentials.json', 'r') as f:
            cred_data = json.load(f)
            client_data = cred_data.get('installed', {})
            set_key(env_path, 'GOOGLE_CLIENT_ID', client_data['client_id'])
            set_key(env_path, 'GOOGLE_CLIENT_SECRET', client_data['client_secret'])
        
        print("\n✅ SUCCESS! Tokens saved to .env")
        if login_hint:
            print(f"   Account: {login_hint}")
        print(f"   Scopes granted: {len(SCOPES)}")
        return True
    
    print("❌ Failed to generate tokens")
    return False

if __name__ == '__main__':
    generate_tokens()