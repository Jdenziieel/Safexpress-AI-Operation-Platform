"""
Simple script to refresh Google OAuth access token using existing refresh token
"""
import os
import json
import requests
from dotenv import load_dotenv, set_key

# Load environment variables
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
        # Make the request
        print("📡 Requesting new access token from Google...")
        response = requests.post(token_url, data=data)
        
        if response.status_code == 200:
            token_data = response.json()
            new_access_token = token_data.get("access_token")
            
            if new_access_token:
                # Update the .env file
                env_path = os.path.join(os.path.dirname(__file__), ".env")
                set_key(env_path, "GOOGLE_ACCESS_TOKEN", new_access_token)
                
                print("✅ Success! New access token obtained and saved to .env")
                print(f"   Token (first 20 chars): {new_access_token[:20]}...")
                print(f"   Expires in: {token_data.get('expires_in', 3600)} seconds (~1 hour)")
                
                return True
            else:
                print("❌ No access token in response")
                print(f"   Response: {token_data}")
                return False
        else:
            print(f"❌ Failed to refresh token. Status code: {response.status_code}")
            print(f"   Error: {response.text}")
            
            # Check for common errors
            error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
            error = error_data.get('error', '')
            error_desc = error_data.get('error_description', '')
            
            if error == 'invalid_grant':
                print("\n⚠️  The refresh token is invalid or expired!")
                print("   This usually means you need to re-authorize the app.")
                print("   Run the generate_gmail_tokens.py script to get new tokens.")
            elif error == 'invalid_client':
                print("\n⚠️  Invalid client credentials!")
                print("   Check that GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are correct.")
            
            return False
            
    except Exception as e:
        print(f"❌ Error during token refresh: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Google OAuth Token Refresher")
    print("=" * 60)
    print()
    
    success = refresh_access_token()
    
    print()
    print("=" * 60)
    if success:
        print("✅ Token refresh complete!")
        print("   Your access token has been updated in .env")
        print("   You can now use the Gmail agent.")
    else:
        print("❌ Token refresh failed!")
        print("   You may need to re-authorize with generate_gmail_tokens.py")
    print("=" * 60)
