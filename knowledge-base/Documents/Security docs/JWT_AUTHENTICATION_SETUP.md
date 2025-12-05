# JWT Authentication Setup - Complete

## What Was Implemented

### 1. Backend Changes

#### Files Created:
- `backend/middleware/__init__.py` - Middleware package
- `backend/middleware/jwt_middleware.py` - JWT authentication middleware

#### Files Modified:
- `backend/requirements.txt` - Added Flask-JWT-Extended
- `backend/.env` - Added JWT_SECRET_KEY placeholder
- `backend/config.py` - Added JWT_SECRET_KEY configuration
- `backend/app.py` - Initialized JWTManager
- `backend/api/chat_routes.py` - Added @jwt_required_custom to all routes
- `backend/services/chat_service.py` - Added user_id validation for all operations

### 2. How It Works

**Authentication Flow:**
1. User logs in via Django → receives JWT token with user_id
2. Frontend stores token and sends it in `Authorization: Bearer <token>` header
3. Flask middleware (`@jwt_required_custom`) validates token
4. User ID is extracted and attached to `request.user_id`
5. All chat operations use this user_id for access control

**Protected Endpoints:**
- `POST /chat/session/new` - Create session (uses JWT user_id)
- `POST /chat/message` - Send message (validates session ownership)
- `GET /chat/session/<id>/history` - Get history (validates ownership)
- `GET /chat/sessions` - Get user sessions (uses JWT user_id)
- `GET /chat/session/<id>` - Get session details (validates ownership)
- `DELETE /chat/session/<id>` - Delete session (validates ownership)

### 3. Security Features

✅ **User Isolation** - Users can only access their own sessions
✅ **Session Validation** - All operations validate session ownership
✅ **Token Required** - All chat endpoints require valid JWT
✅ **Access Control** - Can't read/modify other users' chats

### 4. What You Need To Do

#### Step 1: Update .env file
Replace the placeholder in `backend/.env`:
```env
JWT_SECRET_KEY="your-actual-django-secret-key-here"
```
**Important:** Use the SAME secret key that Django uses to generate tokens!

#### Step 2: Install Dependencies
```bash
cd backend
pip install -r requirements.txt
```

#### Step 3: Frontend Changes Needed

Update your ChatInterface.jsx to send JWT token:

```javascript
// Example: Creating a session
const createSession = async () => {
  const token = localStorage.getItem('jwt_token'); // or wherever you store it
  
  const response = await fetch('http://localhost:8009/chat/session/new', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      title: 'New Chat',
      initial_message: 'Hello'
    })
  });
  
  const data = await response.json();
  return data;
};

// Example: Sending a message
const sendMessage = async (sessionId, message) => {
  const token = localStorage.getItem('jwt_token');
  
  const response = await fetch('http://localhost:8009/chat/message', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      session_id: sessionId,
      message: message
    })
  });
  
  return response.json();
};

// Example: Getting sessions
const getSessions = async () => {
  const token = localStorage.getItem('jwt_token');
  
  const response = await fetch('http://localhost:8009/chat/sessions', {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });
  
  return response.json();
};
```

### 5. Testing

#### Without Token (Should Fail):
```bash
curl http://localhost:8009/chat/sessions
# Response: {"success": false, "error": "Unauthorized - Invalid or missing token"}
```

#### With Token (Should Work):
```bash
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" http://localhost:8009/chat/sessions
# Response: {"success": true, "sessions": [...], ...}
```

### 6. Error Responses

**401 Unauthorized:**
```json
{
  "success": false,
  "error": "Unauthorized - Invalid or missing token"
}
```

**404 Not Found / Access Denied:**
```json
{
  "success": false,
  "error": "Session not found or access denied"
}
```

### 7. Token Format

Django should generate tokens with user_id as the identity:
```python
# Django example (for reference)
from rest_framework_simplejwt.tokens import RefreshToken

def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }
```

The token payload should contain:
```json
{
  "sub": "user_id_here",  // or "identity"
  "exp": 1234567890,
  "iat": 1234567890
}
```

### 8. Troubleshooting

**Problem:** "Invalid or missing token"
- Check token is being sent in header
- Verify format: `Authorization: Bearer <token>`
- Ensure JWT_SECRET_KEY matches Django's secret

**Problem:** "Session not found or access denied"
- User trying to access someone else's session
- Session ID is invalid
- Session belongs to different user_id

**Problem:** "Secret key not configured"
- Update JWT_SECRET_KEY in .env
- Restart Flask server

---

## Summary

Your chat system is now fully secured with JWT authentication:
- ✅ All routes require valid JWT token
- ✅ User ID extracted from token automatically
- ✅ Session ownership validated on every operation
- ✅ No way to access other users' data
- ✅ Compatible with Django-generated tokens

Just update your `.env` with the real secret key and modify the frontend to include the JWT token in requests!
