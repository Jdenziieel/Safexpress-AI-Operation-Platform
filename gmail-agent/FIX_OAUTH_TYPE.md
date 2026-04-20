# Fix for "unauthorized_client: Unauthorized" Error

## Root Cause
Your `credentials.json` is configured as **"web"** type OAuth client, but the refresh token flow requires a **"Desktop app"** type OAuth client.

## The Problem:
```json
{"web": {  // ❌ WRONG TYPE
  "client_id": "...",
  "redirect_uris": ["http://localhost"]  // ❌ WRONG REDIRECT
}}
```

## What You Need:
```json
{"installed": {  // ✅ CORRECT TYPE for desktop apps
  "client_id": "...",
  "redirect_uris": ["http://localhost", "urn:ietf:wg:oauth:2.0:oob"]
}}
```

---

## Solution: Create New OAuth Credentials

### **Step 1: Go to Google Cloud Console**
1. Visit: https://console.cloud.google.com/apis/credentials
2. Make sure you're in the correct project: **"ai-agents-477010"**

### **Step 2: Delete Old Credentials (Optional)**
1. Find your current OAuth 2.0 Client ID
2. Click the trash icon to delete it (this won't affect your project)

### **Step 3: Create New Desktop App Credentials**
1. Click **"+ CREATE CREDENTIALS"**
2. Select **"OAuth client ID"**
3. **Application type**: Choose **"Desktop app"** ⭐ (NOT "Web application")
4. **Name**: "Gmail Agent Desktop" (or any name you prefer)
5. Click **"CREATE"**

### **Step 4: Download New Credentials**
1. A popup will show your new credentials
2. Click **"DOWNLOAD JSON"**
3. Save the file as `credentials.json`
4. **IMPORTANT**: Move it to replace your existing file:
   ```
   d:\Github\Ai-Agents\gmail-agent\credentials.json
   ```

### **Step 5: Generate New Tokens**
Since you have new credentials, you need to re-authorize. **This is the only
script you ever need** — it grants the full scope superset used by every agent
(gmail, calendar, docs, sheets, drive) and auto-writes all four keys
(`GOOGLE_ACCESS_TOKEN`, `GOOGLE_REFRESH_TOKEN`, `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`) to BOTH `supervisor-agent/.env` and `gmail-agent/.env`.
No manual editing required.

```powershell
cd <repo>\gmail-agent
python generate_gmail_tokens.py
```

This will:
- Open your browser for Google login (pick the account you want in the prompt;
  press Enter at the email prompt to choose in the browser — nothing is hardcoded)
- Generate new `access_token` and `refresh_token` for **all** Google services
- Write all four OAuth keys to `supervisor-agent/.env` and `gmail-agent/.env`
  atomically (other variables in those files are preserved)

### **Step 6: Restart All Agents**
Every running agent process needs to be restarted so it reloads the new tokens.
The supervisor forwards credentials to sub-agents at request time, so if any
process started before Step 5, its in-memory copy is stale.

```powershell
# Stop every running agent terminal (Ctrl+C) then restart them:
# gmail-agent (port 8000), gdrive-agent (8001), gdocs-agent (8002),
# calendar-agent (8003), Sheets-agent, supervisor-agent.
```

---

## Why This Happened

**Web vs Desktop OAuth Flow:**

| Type | Use Case | Redirect URI | Refresh Tokens |
|------|----------|--------------|----------------|
| **Web** | Web servers, hosted apps | http://yourdomain.com/callback | Complex setup |
| **Desktop** | Local apps, scripts | http://localhost or urn:ietf:wg:oauth:2.0:oob | ✅ Simple & reliable |

Your credentials were created as "web" type, which has stricter requirements and doesn't work well with the simple refresh token flow used by desktop applications.

---

## Quick Checklist

Before creating new credentials, verify in Google Cloud Console:
- Gmail API, Calendar API, Drive API, Docs API, and Sheets API are all enabled
  in your project (the generator grants scopes for all of them in one flow)
- OAuth consent screen is configured
- Your email is added as a test user
- Scopes on the OAuth consent screen include every one of these:
  - `https://www.googleapis.com/auth/gmail.send`
  - `https://www.googleapis.com/auth/gmail.modify`
  - `https://www.googleapis.com/auth/gmail.readonly`
  - `https://www.googleapis.com/auth/calendar`
  - `https://www.googleapis.com/auth/calendar.events`
  - `https://www.googleapis.com/auth/documents`
  - `https://www.googleapis.com/auth/spreadsheets`
  - `https://www.googleapis.com/auth/drive`

---

## Alternative: Update Existing Credentials.json Manually

If you want to try updating your existing file structure (not recommended):

Replace your `credentials.json` content with:
```json
{
  "installed": {
    "client_id": "1099338872153-2fjg91se6tl3h95kg4e3tbsq799ak626.apps.googleusercontent.com",
    "project_id": "ai-agents-477010",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret": "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",
    "redirect_uris": ["http://localhost", "urn:ietf:wg:oauth:2.0:oob"]
  }
}
```

⚠️ **WARNING**: This might not work if Google already registered this client_id as "web" type. Creating a fresh "Desktop app" is more reliable.

---

## Need Help?

If you get stuck:
1. Make sure you're creating **Desktop app** type (not Web)
2. The downloaded JSON should have `"installed"` not `"web"`
3. After downloading, re-run `generate_gmail_tokens.py` to get new tokens
