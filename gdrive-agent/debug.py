# debug_credentials.py
import os
import json
from dotenv import load_dotenv

load_dotenv()

print("=" * 60)
print("🔍 CREDENTIAL FLOW DEBUG")
print("=" * 60)

# Step 1: Check .env credentials
print("\n📄 STEP 1: Checking .env file")
print("-" * 60)
env_creds = {
    "CLIENT_ID": os.getenv("GOOGLE_CLIENT_ID"),
    "CLIENT_SECRET": os.getenv("GOOGLE_CLIENT_SECRET"),
    "ACCESS_TOKEN": os.getenv("GOOGLE_ACCESS_TOKEN"),
    "REFRESH_TOKEN": os.getenv("GOOGLE_REFRESH_TOKEN"),
}

for key, value in env_creds.items():
    if value:
        display = value[:30] + "..." if len(value) > 30 else value
        print(f"✅ {key}: {display}")
    else:
        print(f"❌ {key}: NOT FOUND")

# Step 2: Check credentials.json
print("\n📄 STEP 2: Checking credentials.json")
print("-" * 60)
creds_path = "key/credentials.json"
if os.path.exists(creds_path):
    with open(creds_path, 'r') as f:
        creds_data = json.load(f)
        if 'web' in creds_data:
            print(f"✅ Type: web")
            print(f"✅ client_id: {creds_data['web']['client_id'][:30]}...")
            print(f"✅ client_secret: {creds_data['web']['client_secret']}")
        elif 'installed' in creds_data:
            print(f"✅ Type: installed")
            print(f"✅ client_id: {creds_data['installed']['client_id'][:30]}...")
            print(f"✅ client_secret: {creds_data['installed']['client_secret']}")
else:
    print(f"❌ credentials.json not found at {creds_path}")

# Step 3: Check token.json
print("\n📄 STEP 3: Checking token.json")
print("-" * 60)
token_path = "key/token.json"
if os.path.exists(token_path):
    with open(token_path, 'r') as f:
        token_data = json.load(f)
        print(f"✅ token exists (first 30 chars): {token_data.get('token', '')[:30]}...")
        print(f"✅ refresh_token exists: {bool(token_data.get('refresh_token'))}")
        print(f"✅ client_id: {token_data.get('client_id', 'NOT FOUND')[:30]}...")
        print(f"📋 Scopes in token:")
        for scope in token_data.get('scopes', []):
            print(f"   - {scope}")
        
        # Check if token matches .env
        if token_data.get('client_id') != env_creds['CLIENT_ID']:
            print(f"\n⚠️ WARNING: token.json client_id doesn't match .env!")
            print(f"   token.json: {token_data.get('client_id')[:30]}...")
            print(f"   .env:       {env_creds['CLIENT_ID'][:30] if env_creds['CLIENT_ID'] else 'NOT SET'}...")
else:
    print(f"❌ token.json not found at {token_path}")

# Step 4: Simulate what Supervisor sends
print("\n📤 STEP 4: What Supervisor will send to Drive Agent")
print("-" * 60)
supervisor_payload = {
    "access_token": env_creds['ACCESS_TOKEN'][:30] + "..." if env_creds['ACCESS_TOKEN'] else "NOT SET",
    "refresh_token": env_creds['REFRESH_TOKEN'][:30] + "..." if env_creds['REFRESH_TOKEN'] else "NOT SET",
    "client_id": env_creds['CLIENT_ID'][:30] + "..." if env_creds['CLIENT_ID'] else "NOT SET",
    "client_secret": env_creds['CLIENT_SECRET'] if env_creds['CLIENT_SECRET'] else "NOT SET",
}
print(json.dumps(supervisor_payload, indent=2))

# Step 5: Check what scope the access token actually has
print("\n🔐 STEP 5: Checking actual token scopes (via Google API)")
print("-" * 60)
if env_creds['ACCESS_TOKEN']:
    import requests
    try:
        response = requests.get(
            'https://www.googleapis.com/oauth2/v1/tokeninfo',
            params={'access_token': env_creds['ACCESS_TOKEN']}
        )
        if response.status_code == 200:
            token_info = response.json()
            print(f"✅ Token is valid")
            print(f"📋 Actual scopes in access token:")
            scope_string = token_info.get('scope', '')
            for scope in scope_string.split():
                print(f"   - {scope}")
            
            # Check for Drive scope
            if 'https://www.googleapis.com/auth/drive' in scope_string:
                print(f"\n✅ Token HAS Drive scope")
            else:
                print(f"\n❌ Token MISSING Drive scope!")
                print(f"   This is why you're getting 'invalid_scope' error!")
        else:
            print(f"❌ Token validation failed: {response.status_code}")
            print(f"   Response: {response.text}")
    except Exception as e:
        print(f"❌ Error checking token: {e}")
else:
    print("❌ No access token to check")

print("\n" + "=" * 60)
print("🎯 DIAGNOSIS")
print("=" * 60)
print("""
If you see "Token MISSING Drive scope" above, that's your problem!
The access token in your .env doesn't have Drive permissions.

SOLUTION: You need to regenerate the tokens with Drive scope.
Run the reauth.py script to fix this.
""")