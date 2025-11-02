"""
Quick test to verify OAuth credentials are working
"""
import os
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

def test_credentials():
    print("=" * 60)
    print("Testing Gmail OAuth Credentials")
    print("=" * 60)
    
    # Get credentials from .env
    access_token = os.getenv("GOOGLE_ACCESS_TOKEN")
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    
    print(f"\n✓ Access Token: {access_token[:20]}..." if access_token else "✗ Access Token: Missing")
    print(f"✓ Refresh Token: {refresh_token[:20]}..." if refresh_token else "✗ Refresh Token: Missing")
    print(f"✓ Client ID: {client_id[:30]}..." if client_id else "✗ Client ID: Missing")
    print(f"✓ Client Secret: {client_secret[:15]}..." if client_secret else "✗ Client Secret: Missing")
    
    if not all([access_token, refresh_token, client_id, client_secret]):
        print("\n❌ Missing credentials!")
        return False
    
    # Check for quotes in credentials (common issue)
    if any(val.startswith("'") or val.startswith('"') for val in [access_token, client_id, client_secret, refresh_token]):
        print("\n⚠️  WARNING: Credentials contain quotes! Remove quotes from .env file")
        return False
    
    print("\n🔐 Creating OAuth credentials object...")
    
    try:
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=[
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/gmail.readonly",
            ],
        )
        
        print("✓ Credentials object created")
        
        print("\n📧 Testing Gmail API connection...")
        service = build("gmail", "v1", credentials=creds)
        
        # Try to get user profile (lightweight test)
        profile = service.users().getProfile(userId="me").execute()
        
        print(f"\n✅ SUCCESS! Connected to Gmail")
        print(f"   Email: {profile.get('emailAddress')}")
        print(f"   Total Messages: {profile.get('messagesTotal')}")
        print(f"   Total Threads: {profile.get('threadsTotal')}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ FAILED: {e}")
        
        error_str = str(e)
        if "unauthorized_client" in error_str.lower():
            print("\n💡 This is the 'unauthorized_client' error!")
            print("   Possible causes:")
            print("   1. Token scopes don't match between tools.py and generated tokens")
            print("   2. Client ID/Secret don't match credentials.json")
            print("   3. OAuth client was deleted or changed in Google Cloud Console")
        elif "invalid_grant" in error_str.lower():
            print("\n💡 Token expired or revoked. Run: python generate_gmail_tokens.py")
        
        return False

if __name__ == "__main__":
    success = test_credentials()
    print("\n" + "=" * 60)
    if success:
        print("✅ All tests passed! Gmail OAuth is working correctly.")
    else:
        print("❌ Tests failed. Check the errors above.")
    print("=" * 60)
