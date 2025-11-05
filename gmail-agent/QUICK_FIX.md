# Quick Fix Guide for "unauthorized_client" Error

## Problem
Your Google access token has expired (they last only 1 hour). You need to refresh it using your refresh token.

## Solution Steps

### **Step 1: Install Required Package**
```powershell
cd d:\Github\Ai-Agents\gmail-agent
pip install python-dotenv requests
```

### **Step 2: Run Token Refresh Script**
```powershell
python refresh_token.py
```

This script will:
- ✅ Use your existing refresh token
- ✅ Get a new access token from Google
- ✅ Automatically update your `.env` file
- ✅ No browser needed, no re-authorization required!

### **Step 3: Restart Your Backend**
```powershell
cd d:\Github\Ai-Agents\supervisor-agent
python supervisor_agent.py
```

### **Step 4: Test Email Sending**
Try sending an email through your AI chat interface!

---

## Why This Happened

- **Access tokens expire after 1 hour** (Google's security policy)
- Your refresh token is still valid and can get new access tokens
- The "unauthorized_client" error means your access token expired
- The refresh token doesn't expire (unless you revoke it)

---

## If Refresh Token Fails

If the refresh script fails with "invalid_grant", it means your refresh token is also expired/revoked. In that case:

1. Check your Google Cloud Console OAuth consent screen
2. Make sure your email is added as a test user
3. Verify the credentials.json has correct client_id and client_secret
4. You may need to regenerate tokens (but try the refresh script first!)

---

## Credentials Check

✅ **Client ID**: Present in .env  
✅ **Client Secret**: Present in .env  
✅ **Refresh Token**: Present in .env  
⚠️ **Access Token**: EXPIRED (needs refresh)

**Your credentials.json type**: `web` (this is fine, but redirect_uris should include `http://localhost:5001/oauth2callback` for token generation scripts)

---

## Quick Command Summary

```powershell
# 1. Navigate to gmail-agent folder
cd d:\Github\Ai-Agents\gmail-agent

# 2. Refresh the token
python refresh_token.py

# 3. Restart backend
cd ..\supervisor-agent
python supervisor_agent.py
```

That's it! 🎉
