"""
Generate a fresh token.json with correct Drive scopes AND refresh token
Works with organization accounts
"""
import os
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from pathlib import Path

# ALL SCOPES YOU NEED (add/remove as needed)
SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/spreadsheets',
]

CREDENTIALS_PATH = 'key/credentials.json'
TOKEN_PATH = 'key/token.json'

def generate_token():
    """Generate new token with correct scopes AND refresh token"""
    creds = None
    
    # Check if token exists
    if os.path.exists(TOKEN_PATH):
        print(f" Token already exists at {TOKEN_PATH}")
        response = input("Delete and regenerate? (yes/no): ")
        if response.lower() not in ('yes', 'y'):
            print(" Aborted")
            return
        os.remove(TOKEN_PATH)
        print(" Deleted old token")
    
    # Check credentials.json exists
    if not os.path.exists(CREDENTIALS_PATH):
        print(f" Error: {CREDENTIALS_PATH} not found!")
        return
    
    # Load credentials.json to check redirect URIs
    with open(CREDENTIALS_PATH, 'r') as f:
        creds_data = json.load(f)
        if 'web' in creds_data:
            redirect_uris = creds_data['web'].get('redirect_uris', [])
            print(f" Configured redirect URIs: {redirect_uris}")
            
            # Determine port from redirect URIs
            port = 8087  # default
            for uri in redirect_uris:
                if 'localhost:' in uri:
                    try:
                        port = int(uri.split(':')[-1].rstrip('/'))
                        break
                    except:
                        pass
            print(f" Using port: {port}")
        else:
            print(" Using 'installed' type credentials")
            port = 0  # Let Google choose
    
    print(f"\n Starting OAuth flow with scopes:")
    for scope in SCOPES:
        print(f"   - {scope}")
    print("\n Your browser will open - sign in with your ORGANIZATION account")
    print(" Make sure your organization allows this app!")
    print(" If you've authenticated before, you may need to revoke access first:")
    print("   https://myaccount.google.com/permissions\n")
    
    try:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
        
        # CRITICAL: Request offline access and force consent to get refresh token
        creds = flow.run_local_server(
            port=port,
            access_type='offline', # GET REFRESH TOKEN
            prompt='consent', # FORCE CONSENT SCREEN
            include_granted_scopes='true',
            success_message=' Authorization successful! You can close this window.',
            open_browser=True
        )
        
        # Verify we got both tokens
        print(f"\n Authentication successful!")
        print(f" Access token: {creds.token[:50]}..." if creds.token else " No access token")
        print(f" Refresh token: {' Received' if creds.refresh_token else ' NOT RECEIVED'}")
        
        if not creds.refresh_token:
            print("\n WARNING: No refresh token received!")
            print("   Possible reasons:")
            print("   1. You've authenticated with this app before")
            print("   2. Your organization's security policies block refresh tokens")
            print("\n   Solution:")
            print("   1. Go to: https://myaccount.google.com/permissions")
            print("   2. Find and remove this app")
            print("   3. Run this script again")
            
            response = input("\n   Continue saving token anyway? (yes/no): ")
            if response.lower() not in ('yes', 'y'):
                print(" Aborted - token not saved")
                return
        
        # Save token
        os.makedirs('key', exist_ok=True)
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())
        
        print(f"\n Token saved to {TOKEN_PATH}")
        print(f" Token scopes: {creds.scopes}")
        
        # Update .env files automatically (both local and supervisor-agent)
        script_dir = Path(__file__).resolve().parent
        supervisor_env_path = script_dir.parent / 'supervisor-agent' / '.env'
        local_env_path = Path('.env')

        env_paths_to_update = []
        if supervisor_env_path.exists():
            env_paths_to_update.append(('supervisor-agent', supervisor_env_path))
        if local_env_path.resolve() != supervisor_env_path.resolve() and local_env_path.exists():
            env_paths_to_update.append(('local', local_env_path))

        if not env_paths_to_update:
            print(" No .env files found to update")
            print("\n Add these to your .env file manually:")
            print("=" * 60)
            print(f"GOOGLE_ACCESS_TOKEN={creds.token}")
            if creds.refresh_token:
                print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
            else:
                print(f"# GOOGLE_REFRESH_TOKEN=NOT_RECEIVED")
            print("=" * 60)
        
        for label, env_path in env_paths_to_update:
            print(f"\n Updating {label} .env file ({env_path})...")
            with open(env_path, 'r') as f:
                lines = f.readlines()

            new_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith('GOOGLE_ACCESS_TOKEN=') or \
                   stripped.startswith('GOOGLE_REFRESH_TOKEN=') or \
                   stripped.startswith("# Google OAuth Tokens (auto-generated)"):
                    continue
                new_lines.append(line)

            while new_lines and new_lines[-1].strip() == '':
                new_lines.pop()
            new_lines.append('\n')

            new_lines.append(f'\n# Google OAuth Tokens (auto-generated)\n')
            new_lines.append(f'GOOGLE_ACCESS_TOKEN={creds.token}\n')

            if creds.refresh_token:
                new_lines.append(f'GOOGLE_REFRESH_TOKEN={creds.refresh_token}\n')
            else:
                new_lines.append(f'# GOOGLE_REFRESH_TOKEN=NOT_RECEIVED_SEE_WARNINGS_ABOVE\n')

            with open(env_path, 'w') as f:
                f.writelines(new_lines)

            print(f" {label} .env updated with tokens!")
        
        # Test Drive access
        print(f"\n Testing Drive access...")
        from googleapiclient.discovery import build
        
        try:
            service = build('drive', 'v3', credentials=creds)
            results = service.files().list(pageSize=5, fields="files(id, name)").execute()
            files = results.get('files', [])
            
            print(f" Drive access verified!")
            print(f" Found {len(files)} file(s):")
            for file in files[:3]:
                print(f"   - {file['name']}")
                
        except Exception as e:
            print(f" Drive access test failed: {e}")
            print("   Your token might not have proper Drive permissions")
        
        print("\n Setup complete!")
        print("   Next steps:")
        print("   1. Restart your Drive Agent and Supervisor")
        print("   2. Try creating a folder through the Supervisor")
        
    except Exception as e:
        print(f"\n Error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        print("\n Troubleshooting:")
        print("1. Check if 'web' OAuth client has correct redirect URIs:")
        print(f"   - http://localhost:{port}/")
        print("2. Wait 5-10 minutes after creating/modifying OAuth client")
        print("3. Check if your organization allows this app")
        print("4. Revoke previous access: https://myaccount.google.com/permissions")
        print("5. Make sure all scopes are enabled in OAuth consent screen")

if __name__ == "__main__":
    generate_token()