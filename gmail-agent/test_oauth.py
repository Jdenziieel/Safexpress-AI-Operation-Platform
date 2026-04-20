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
        # Mirror tools.py: do NOT pass scopes=, otherwise google-auth sends a
        # mismatched scope parameter on refresh and Google returns invalid_scope.
        # The refresh_token already carries its granted scope set.
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
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
        
        error_str = str(e).lower()
        if "invalid_scope" in error_str:
            print("\n💡 'invalid_scope' — the scopes requested on refresh don't match")
            print("   what the refresh_token was granted. Most common causes:")
            print("   1. The refresh_token was minted with a narrower scope set")
            print("      (e.g. only gmail.modify, missing gmail.send/gmail.readonly).")
            print("   2. Code downstream is passing a stale scopes=[...] list to")
            print("      Credentials(...) that no longer matches the grant.")
            print("   Fix: revoke the app at https://myaccount.google.com/permissions")
            print("        then run: python generate_gmail_tokens.py")
        elif "unauthorized_client" in error_str:
            print("\n💡 'unauthorized_client' — client_id/client_secret mismatch.")
            print("   Possible causes:")
            print("   1. .env GOOGLE_CLIENT_ID/SECRET don't match credentials.json.")
            print("   2. OAuth client was deleted or rotated in Google Cloud Console.")
            print("   Fix: rerun generate_gmail_tokens.py (it syncs all 4 keys).")
        elif "invalid_grant" in error_str:
            print("\n💡 Token expired or revoked. Run: python generate_gmail_tokens.py")
        elif "invalid_client" in error_str:
            print("\n💡 'invalid_client' — .env client_id/client_secret don't match")
            print("   the OAuth client that issued the refresh_token.")
            print("   Fix: run generate_gmail_tokens.py against the right credentials.json.")
        
        return False

if __name__ == "__main__":
    success = test_credentials()
    print("\n" + "=" * 60)
    if success:
        print("✅ All tests passed! Gmail OAuth is working correctly.")
    else:
        print("❌ Tests failed. Check the errors above.")
    print("=" * 60)
