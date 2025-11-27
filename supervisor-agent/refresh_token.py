"""
Refresh Google OAuth access token for supervisor agent
"""
import os
import requests
from dotenv import load_dotenv, set_key

load_dotenv()

def refresh_access_token():
    """Refresh the access token using the refresh token"""
    
    print("🔄 Refreshing Google OAuth Access Token...")
    
    # Get credentials from .env
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")
    
    if not all([client_id, client_secret, refresh_token]):
        print("❌ Missing credentials in .env file!")
        print(f"   Client ID: {'✓' if client_id else '✗'}")
        print(f"   Client Secret: {'✓' if client_secret else '✗'}")
        print(f"   Refresh Token: {'✓' if refresh_token else '✗'}")
        return False
    
    # Google's token endpoint
    token_url = "https://oauth2.googleapis.com/token"
    
    # Prepare the request
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    
    try:
        print("📡 Requesting new access token from Google...")
        response = requests.post(token_url, data=data)
        
        if response.status_code == 200:
            token_data = response.json()
            new_access_token = token_data.get("access_token")
            
            if new_access_token:
                # Update the .env file
                env_file = ".env"
                set_key(env_file, "GOOGLE_ACCESS_TOKEN", new_access_token)
                
                print("✅ Success! New access token saved to .env")
                print(f"   Token: {new_access_token[:50]}...")
                print(f"   Expires in: {token_data.get('expires_in', 'N/A')} seconds")
                return True
            else:
                print("❌ No access token in response")
                return False
        else:
            print(f"❌ Failed to refresh token: {response.status_code}")
            print(f"   Error: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Google OAuth Token Refresher - Supervisor Agent")
    print("=" * 60)
    print()
    
    success = refresh_access_token()
    
    print()
    print("=" * 60)
    if success:
        print("✅ Token refresh successful!")
        print("   Restart the supervisor agent to use the new token.")
    else:
        print("❌ Token refresh failed!")
    print("=" * 60)
