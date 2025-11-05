# Gmail API Not Enabled - Quick Fix

## 🔴 Error
```
Gmail API has not been used in project 1099338872153 before or it is disabled
```

## ✅ Solution

### **Option 1: Direct Link (Fastest)**
Click this link and click "ENABLE":
👉 **https://console.developers.google.com/apis/api/gmail.googleapis.com/overview?project=1099338872153**

### **Option 2: Manual Steps**
1. Go to: https://console.cloud.google.com/
2. Select project: **ai-agents-477010**
3. Go to "APIs & Services" → "Library"
4. Search for "Gmail API"
5. Click on "Gmail API"
6. Click **"ENABLE"** button
7. Wait 1-2 minutes for changes to propagate

## After Enabling

Wait 2-3 minutes, then restart the Gmail agent:

```powershell
cd d:\Github\Ai-Agents\gmail-agent
python api.py
```

Then test again:
```powershell
python test_oauth.py
```

You should see:
```
✅ SUCCESS! Connected to Gmail
   Email: your-email@gmail.com
```

## Why This Happened

When you created the new **Desktop app** OAuth credentials, they were in a fresh project state. The Gmail API needs to be explicitly enabled for each Google Cloud project before it can be used.

Your old credentials had Gmail API enabled, but the new credentials are in a project that needs the API enabled.

---

**This is the final step to fix the "unauthorized_client" error!** 🎉
