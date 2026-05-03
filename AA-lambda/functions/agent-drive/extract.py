# extract_tokens.py
import json

with open('key/token.json', 'r') as f:
    token_data = json.load(f)

print(" Copy these lines to your .env file:")
print("=" * 60)
print(f"GOOGLE_ACCESS_TOKEN={token_data.get('token', 'NOT_FOUND')}")
print(f"GOOGLE_REFRESH_TOKEN={token_data.get('refresh_token', 'NOT_FOUND')}")
print("=" * 60)