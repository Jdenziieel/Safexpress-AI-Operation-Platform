"""Test JWT decoding to see actual token structure"""
import json
import base64

# Your actual id_token from the logs
id_token = "eyJhbGciOiJSUzI1NiIsImtpZCI6IjkzYTkzNThjY2Y5OWYxYmIwNDBiYzYyMjFkNTQ5M2UxZmZkOGFkYTEiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwczovL2FjY291bnRzLmdvb2dsZS5jb20iLCJhenAiOiIxMDA1OTQ2MDI2MjEzLWYyNWwzNGR0cms0dXM1ODgzMmVrOWFwNXY2MnZyajVmLmFwcHMuZ29vZ2xldXNlcmNvbnRlbnQuY29tIiwiYXVkIjoiMTAwNTk0NjAyNjIxMy1mMjVsMzRkdHJrNHVzNTg4MzJlazlhcDV2NjJ2cmo1Zi5hcHBzLmdvb2dsZXVzZXJjb250ZW50LmNvbSIsInN1YiI6IjExNTQzOTA4MDM4NjE0MjA0MjEyOCIsImhkIjoidXN0LmVkdS5waCIsImVtYWlsIjoiam9zaGRlbnppZWwuam92ZXMuY2ljc0B1c3QuZWR1LnBoIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsImF0X2hhc2giOiI2VS1OUGt4UGFqUWxzdkxvNGh6cjhRIiwibmFtZSI6IkpPU0ggREVOWklFTCBKT1ZFUyIsInBpY3R1cmUiOiJodHRwczovL2xoMy5nb29nbGV1c2VyY29udGVudC5jb20vYS9BQ2c4b2NLUEdyaV9PNFNhenk5ajNMcE5GVFU4aE4xdktPM1czR2ZNbC1tVEJGNGJXWlljWXFBPXM5Ni1jIiwiZ2l2ZW5fbmFtZSI6IkpPU0ggREVOWklFTCIsImZhbWlseV9uYW1lIjoiSk9WRVMiLCJpYXQiOjE3NjM5ODU5NTMsImV4cCI6MTc2Mzk4OTU1M30.CUz2xnnhGKZpsmlUappP0JALFMB3ymyfKDMuDBEeD_GZdPn1Nk2TjeB2rHwzYLaQzQoZMpj67YwFARP14_ysczP6-evgG8SeYM2mWnWPPYjZPIqWWntdPFCwXWy3UJ6vf0lBw3TnQAtd9rkRgZeHgVmO2YdoR5KujmlCtmYb_jEaFyE0G_NBv7fKD_NqpRu1qqI2JJPEcgfGYpwlZOswKg2mtT91C1HQaTwgM8ymsqLDr5ORVYYGXS0a6tmFrqVv3qxb6ULYNF95BXhY5YhLgQyXhbCdj3UeiaQxIv8fujMHgt_3YdeEuKW-YK9vuY-Eae-412tXT0TFMlLeZkUsrg"

# JWT structure: header.payload.signature
parts = id_token.split('.')

if len(parts) >= 2:
    # Decode header
    header = parts[0]
    # Add padding if needed
    header += '=' * (4 - len(header) % 4)
    header_decoded = json.loads(base64.urlsafe_b64decode(header))
    
    # Decode payload
    payload = parts[1]
    # Add padding if needed
    payload += '=' * (4 - len(payload) % 4)
    payload_decoded = json.loads(base64.urlsafe_b64decode(payload))
    
    print("=" * 80)
    print("JWT TOKEN STRUCTURE ANALYSIS")
    print("=" * 80)
    print("\n🔍 HEADER:")
    print(json.dumps(header_decoded, indent=2))
    
    print("\n🔍 PAYLOAD (This is what your backend receives):")
    print(json.dumps(payload_decoded, indent=2))
    
    print("\n" + "=" * 80)
    print("📋 AVAILABLE FIELDS FOR 'uploaded_by':")
    print("=" * 80)
    print(f"✅ name:         {payload_decoded.get('name')}")
    print(f"✅ email:        {payload_decoded.get('email')}")
    print(f"✅ given_name:   {payload_decoded.get('given_name')}")
    print(f"✅ family_name:  {payload_decoded.get('family_name')}")
    print(f"✅ sub:          {payload_decoded.get('sub')}")
    
    print("\n" + "=" * 80)
    print("🎯 CURRENT CODE IN kb_routes.py:")
    print("=" * 80)
    print("uploaded_by = payload.get('name') or 'System User'")
    
    print("\n" + "=" * 80)
    print("✅ EXPECTED RESULT:")
    print("=" * 80)
    print(f"uploaded_by should be: '{payload_decoded.get('name')}'")
    print("\nIf you're getting 'System User', the issue is NOT the field name.")
    print("The issue is likely:")
    print("  1. JWT_SECRET_KEY mismatch (Google uses RS256, not HS256)")
    print("  2. Token not being sent in Authorization header")
    print("  3. Token being sent but decode_jwt() is failing")
