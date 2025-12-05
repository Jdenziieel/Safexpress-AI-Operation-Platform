# CORS & Security Headers - Quick Guide

## ✅ Security Headers Are Safe with JWT!

**Your Question**: Will security headers cause errors with JWT authentication?

**Answer**: **No!** Security headers and JWT authentication work together perfectly:

```
Security Headers (Browser Protection)
  ↓
  X-Content-Type-Options: nosniff  ← Prevents MIME sniffing
  X-Frame-Options: DENY            ← Prevents clickjacking
  X-XSS-Protection: 1; mode=block  ← Blocks XSS attacks
  Content-Security-Policy: ...     ← Controls resource loading
  
JWT Authentication (API Protection)
  ↓
  Authorization: Bearer <token>    ← Your JWT token
  
These operate on DIFFERENT layers and DON'T conflict!
```

### What I Changed:
1. ✅ Made `Content-Security-Policy` **permissive for development**
   - Allows connections to any origin
   - Won't block your frontend or API calls
2. ✅ Added comments explaining they're safe with JWT

---

## 📍 CORS Configuration - Where to Add Your Frontend Port

**Your Question**: Where exactly should I add frontend origins? Do I configure every file?

**Answer**: **ONLY in app.py** - This is the SINGLE place for CORS configuration!

### Location: `backend/app.py` (Lines 43-66)

```python
# CORS Configuration - This is the ONLY place where CORS is configured
# To add your frontend port:
#   1. For development: Add it to the list below
#   2. For production: Add it to ALLOWED_ORIGINS in .env file

allowed_origins = Config.ALLOWED_ORIGINS if Config.ENVIRONMENT == "production" else [
    "http://localhost:5173",      # Vite dev server (default) ✅
    "http://localhost:3000",      # Alternative dev port ✅
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    # Add your frontend port here if different, e.g.:
    # "http://localhost:8080",    # ← Add custom ports here
    # "http://localhost:4200",
]
```

### How to Add Your Port:

**Option 1: Development (Direct Edit)**
Edit `backend/app.py`, add your port to the list:
```python
allowed_origins = [...] if Config.ENVIRONMENT == "production" else [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:YOUR_PORT",  # ← Add here
]
```

**Option 2: Production (Environment Variable)**
Edit `backend/.env`:
```bash
ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
```

---

## 🔍 What Each Setting Does

### CORS Settings (app.py)
```python
allow_origins=allowed_origins    # ← Which domains can access your API
allow_credentials=True           # ← Allows cookies/auth headers
allow_methods=[...]              # ← Allowed HTTP methods
allow_headers=["*"]              # ← Allows ALL headers (including Authorization for JWT) ✅
```

**Important**: `allow_headers=["*"]` means your JWT token in the `Authorization` header will work!

### Security Headers (middleware/security_middleware.py)
```python
X-Content-Type-Options: nosniff              # Browser security
X-Frame-Options: DENY                        # Browser security
X-XSS-Protection: 1; mode=block              # Browser security
Referrer-Policy: strict-origin-when-...      # Privacy
Content-Security-Policy: ...                 # Resource loading policy
```

**These don't affect API calls or JWT tokens!**

---

## 🧪 Testing

### Test CORS
```bash
# From your frontend domain
curl -H "Origin: http://localhost:5173" \
     -H "Access-Control-Request-Method: POST" \
     -H "Access-Control-Request-Headers: Authorization" \
     -X OPTIONS \
     http://localhost:8009/chat/message

# Should return CORS headers (200 OK)
```

### Test JWT with Security Headers
```bash
# Send request with JWT token
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
     http://localhost:8009/chat/sessions

# Response will include:
# - Your data (if token is valid)
# - Security headers (X-Content-Type-Options, etc.)
# Both work together! ✅
```

---

## 🎯 Common Scenarios

### Scenario 1: Frontend on Port 5173 (Vite Default)
**Already configured!** ✅ No changes needed.

### Scenario 2: Frontend on Port 3000 (React/Next.js)
**Already configured!** ✅ No changes needed.

### Scenario 3: Frontend on Custom Port (e.g., 8080)
**Add to app.py**:
```python
allowed_origins = [...] if Config.ENVIRONMENT == "production" else [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:8080",  # ← Add this
]
```

### Scenario 4: Multiple Frontends
**Add all ports**:
```python
allowed_origins = [...] if Config.ENVIRONMENT == "production" else [
    "http://localhost:5173",  # Vite
    "http://localhost:3000",  # React
    "http://localhost:4200",  # Angular
    "http://localhost:8080",  # Vue
]
```

### Scenario 5: Production Deployment
**Edit .env**:
```bash
ENVIRONMENT=production
ALLOWED_ORIGINS=https://yourdomain.com,https://api.yourdomain.com
```

---

## ⚠️ Troubleshooting

### Error: "CORS policy: No 'Access-Control-Allow-Origin' header"
**Solution**: Add your frontend origin to `app.py`

### Error: "JWT token not working"
**Solution**: This is NOT a CORS or security headers issue!
- Check token format: `Authorization: Bearer <token>`
- Check token expiration
- Check JWT_SECRET_KEY matches auth server

### Frontend can't connect to backend
**Solution**: 
1. Check frontend is running on one of the allowed origins
2. Backend should be on port 8009
3. Check CORS origins in `app.py`

---

## 📝 Summary

### ✅ Security Headers
- **Safe with JWT**: Yes! They don't interfere
- **Where configured**: `middleware/security_middleware.py`
- **No changes needed**: Already permissive for development

### ✅ CORS Origins
- **Where to add ports**: `backend/app.py` (lines 43-66)
- **Only one file**: Don't touch any other files
- **Already includes**: localhost:5173, localhost:3000

### ✅ Your Setup Should Work
If your frontend is on:
- Port 5173 ✅ Already configured
- Port 3000 ✅ Already configured
- Other port → Add to `app.py`

---

**Last Updated**: November 20, 2025
