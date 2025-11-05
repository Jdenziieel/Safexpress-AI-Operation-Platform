# Quick Testing Guide for Denziel's Requirements

## 🎯 What Denziel Wants

1. **Test 1:** Simple Gmail search returning exactly 4 emails
2. **Test 2:** Multi-step workflow - search emails THEN forward one
3. **Documentation:** Screenshots of terminal + UI for both tests

---

## 🚀 Quick Start (Run These in Order)

### Step 1: Start Gmail Agent
```powershell
cd d:\Github\Ai-Agents\gmail-agent
python api.py
```
✅ Should see: "Starting Gmail Agent API Server" on port 8001

### Step 2: Start Supervisor Agent
```powershell
cd d:\Github\Ai-Agents\supervisor-agent
python supervisor_agent.py
```
✅ Should see: Server running on port 8000

### Step 3: Start Frontend
```powershell
cd d:\Github\Ai-Agents\Capstone
npm run dev
```
✅ Should see: Server running on http://localhost:5173

---

## 📝 Test Prompts to Use

### Test 1: Simple Search (4 Emails)
```
Search my emails and show me 4 recent emails
```
**Expected:**
- Supervisor agent creates plan to search emails
- Gmail agent executes search with max_results=4
- UI displays 4 emails with clean formatting
- No pending actions (safe operation)

---

### Test 2: Multi-Step (Search + Forward)
```
Search my recent emails, then forward the first one to test@example.com
```
**Expected:**
- Supervisor creates 2-step plan
- Step 1: Search executes automatically
- Step 2: Forward appears in "Pending Actions" widget (requires approval)
- Click "Approve" to forward the email
- Success message appears

---

## 📸 Screenshots to Capture

### For Test 1:
1. **Before:** Fresh chat screen
2. **Terminal 1:** Gmail agent showing search request
3. **Terminal 2:** Supervisor agent showing plan execution
4. **After:** UI showing 4 emails returned

### For Test 2:
1. **Before:** New chat or continue
2. **Terminal 1:** Gmail agent showing 2 requests (search, then forward)
3. **Terminal 2:** Supervisor agent showing multi-step plan
4. **During:** Pending Actions widget with forward action
5. **After:** Success message after approval

---

## 🖼️ How to Take Screenshots

**Windows Snipping Tool:**
- Press `Win + Shift + S`
- Select area to capture
- Paste into document with `Ctrl + V`

**Recommended Layout:**
- Left monitor: Both terminal windows (split screen)
- Right monitor: Browser with UI

---

## ✅ Checklist Before Testing

- [ ] All 3 services running (Gmail, Supervisor, Frontend)
- [ ] Browser open to http://localhost:5173
- [ ] Browser DevTools open (F12) to check for errors
- [ ] Google OAuth credentials configured
- [ ] Both terminal windows visible for screenshots

---

## 🐛 Quick Troubleshooting

### CORS Error
- Check supervisor_agent.py has CORS middleware configured
- Should see: `allow_origins=["http://localhost:5173"]`

### "Unknown Agent" in Pending Actions
- Already fixed! Backend returns flat structure, frontend now matches

### Frontend Not Loading
- Check all imports in AIChat.jsx are present
- Should have: `import { Sparkles, Send, Clock, CheckCircle, XCircle, Loader2 } from "lucide-react"`

---

## 📤 Deliverables for Denziel

1. ✅ TESTING_RESULTS.md (created)
2. ⏳ Screenshots of Test 1 (terminal + UI)
3. ⏳ Screenshots of Test 2 (terminal + UI)
4. ⏳ Update TESTING_RESULTS.md with actual results

---

## 💡 Tips

- **Test 1** should be quick (few seconds)
- **Test 2** will pause at the approval step - that's expected!
- If email forwarding is risky, you can use `test@example.com` (won't actually send)
- Save screenshots in a `screenshots/` folder for organization

---

Good luck with testing! 🎉
