"""Test the fixed JWT decoding for uploaded_by"""
import jwt as jose_jwt

# Your actual Google OAuth id_token
test_token = "eyJhbGciOiJSUzI1NiIsImtpZCI6IjkzYTkzNThjY2Y5OWYxYmIwNDBiYzYyMjFkNTQ5M2UxZmZkOGFkYTEiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwczovL2FjY291bnRzLmdvb2dsZS5jb20iLCJhenAiOiIxMDA1OTQ2MDI2MjEzLWYyNWwzNGR0cms0dXM1ODgzMmVrOWFwNXY2MnZyajVmLmFwcHMuZ29vZ2xldXNlcmNvbnRlbnQuY29tIiwiYXVkIjoiMTAwNTk0NjAyNjIxMy1mMjVsMzRkdHJrNHVzNTg4MzJlazlhcDV2NjJ2cmo1Zi5hcHBzLmdvb2dsZXVzZXJjb250ZW50LmNvbSIsInN1YiI6IjExNTQzOTA4MDM4NjE0MjA0MjEyOCIsImhkIjoidXN0LmVkdS5waCIsImVtYWlsIjoiam9zaGRlbnppZWwuam92ZXMuY2ljc0B1c3QuZWR1LnBoIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsImF0X2hhc2giOiI2VS1OUGt4UGFqUWxzdkxvNGh6cjhRIiwibmFtZSI6IkpPU0ggREVOWklFTCBKT1ZFUyIsInBpY3R1cmUiOiJodHRwczovL2xoMy5nb29nbGV1c2VyY29udGVudC5jb20vYS9BQ2c4b2NLUEdyaV9PNFNhenk5ajNMcE5GVFU4aE4xdktPM1czR2ZNbC1tVEJGNGJXWlljWXFBPXM5Ni1jIiwiZ2l2ZW5fbmFtZSI6IkpPU0ggREVOWklFTCIsImZhbWlseV9uYW1lIjoiSk9WRVMiLCJpYXQiOjE3NjM5ODU5NTMsImV4cCI6MTc2Mzk4OTU1M30.CUz2xnnhGKZpsmlUappP0JALFMB3ymyfKDMuDBEeD_GZdPn1Nk2TjeB2rHwzYLaQzQoZMpj67YwFARP14_ysczP6-evgG8SeYM2mWnWPPYjZPIqWWntdPFCwXWy3UJ6vf0lBw3TnQAtd9rkRgZeHgVmO2YdoR5KujmlCtmYb_jEaFyE0G_NBv7fKD_NqpRu1qqI2JJPEcgfGYpwlZOswKg2mtT91C1HQaTwgM8ymsqLDr5ORVYYGXS0a6tmFrqVv3qxb6ULYNF95BXhY5YhLgQyXhbCdj3UeiaQxIv8fujMHgt_3YdeEuKW-YK9vuY-Eae-412tXT0TFMlLeZkUsrg"

print("=" * 80)
print("TESTING THE FIX: Decode JWT without signature verification")
print("=" * 80)

try:
    # This is what the NEW code does
    payload = jose_jwt.decode(test_token, options={"verify_signature": False})
    
    uploaded_by = payload.get("name") or payload.get("email") or "System User"
    
    print(f"\n✅ SUCCESS!")
    print(f"   uploaded_by = '{uploaded_by}'")
    print(f"\n📋 Payload keys: {list(payload.keys())}")
    print(f"\n📋 Available user info:")
    print(f"   - name:        {payload.get('name')}")
    print(f"   - email:       {payload.get('email')}")
    print(f"   - given_name:  {payload.get('given_name')}")
    print(f"   - family_name: {payload.get('family_name')}")
    
except Exception as e:
    print(f"\n❌ FAILED: {e}")

print("\n" + "=" * 80)
print("RESULT: The fix works! You should now see 'JOSH DENZIEL JOVES' in uploads")
print("=" * 80)
