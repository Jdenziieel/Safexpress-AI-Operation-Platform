# Frontend API Integration Audit & Fixes

## ✅ COMPLETED: SFXBot.jsx
- **Port**: 8009 (Chat Service)
- **Status**: ✅ Fully migrated to `chatApi` helper
- **Authentication**: ✅ JWT with automatic refresh
- **Changes Made**:
  - Imported `chatApi` from `apiHelpers.js`
  - Replaced all `fetch` calls with `chatApi` methods
  - Automatic token refresh on 401 errors
  - Consistent error handling

---

## 🔄 PENDING: AIChatNew.jsx
- **Port**: 8010 (Supervisor Agent)
- **Status**: ⚠️ Needs migration to `supervisorApi`
- **Current**: Uses raw `fetch` calls
- **Action Needed**:
  ```jsx
  // Add import
  import { supervisorApi } from "../apiHelpers";
  
  // Replace fetch calls:
  - fetch(`${API_BASE_URL}/threads?user_id=${userId}`)
  + supervisorApi.getThreads(userId)
  
  - fetch(`${API_BASE_URL}/threads/${threadId}`, { method: 'DELETE' })
  + supervisorApi.deleteThread(threadId)
  
  // And all other endpoints...
  ```

---

## 🔄 PENDING: DocumentExtraction.jsx
- **Port**: 8009 (Knowledge Base Service)
- **Status**: ⚠️ Needs migration to `kbApi`
- **Current**: Uses `axios` directly without auth interceptor
- **Issues**:
  1. No automatic token refresh
  2. Hardcoded URLs: `http://127.0.0.1:8009`
  3. Manual auth headers
- **Action Needed**:
  ```jsx
  // Add import
  import { kbApi, getAuthHeaders } from "../apiHelpers";
  
  // Replace axios calls:
  - axios.post('http://127.0.0.1:8009/kb/upload-to-kb', {...})
  + kbApi.uploadToKB(data)
  
  - axios.delete(`http://127.0.0.1:8009/kb/delete/${docId}`)
  + kbApi.deleteDocument(docId)
  
  // For other endpoints not in kbApi, use:
  - axios.get('http://127.0.0.1:8009/kb/documents', { headers: {...} })
  + fetchWithAuth('http://localhost:8009/kb/documents')
  ```

---

## 🔄 PENDING: DynamicMapping.jsx  
- **Port**: 8000 (Auth/Knowledge Base Service)
- **Status**: ⚠️ Needs migration
- **Current**: Uses raw `fetch` calls
- **Action Needed**:
  ```jsx
  // Add import
  import { fetchWithAuth } from "../apiHelpers";
  
  // Replace fetch calls:
  - fetch(`${API_BASE_URL}/knowledge-base/upload`, {
      headers: { 'Authorization': `Bearer ${token}` },
      ...
    })
  + fetchWithAuth(`http://localhost:8000/knowledge-base/upload`, {
      method: 'POST',
      body: formData
    })
  ```

---

## 📊 Summary of Ports

| Component | Port | Service | Status |
|-----------|------|---------|--------|
| Login.jsx | 8000 | Django Auth | ✅ Uses `api.js` |
| SFXBot.jsx | 8009 | Chat Service | ✅ Uses `chatApi` |
| AIChatNew.jsx | 8010 | Supervisor Agent | ⚠️ Needs `supervisorApi` |
| DocumentExtraction.jsx | 8009 | Knowledge Base | ⚠️ Needs `kbApi` |
| DynamicMapping.jsx | 8000 | KB Upload | ⚠️ Needs `fetchWithAuth` |

---

## 🎯 Benefits of Migration

### Before:
- ❌ No token refresh → Users logged out every 51 minutes
- ❌ Inconsistent error handling across components
- ❌ Manual auth header management
- ❌ Hardcoded URLs scattered everywhere
- ❌ Race conditions with multiple refresh attempts

### After:
- ✅ Automatic token refresh → Seamless 3-day sessions
- ✅ Centralized error handling
- ✅ Automatic auth headers
- ✅ Single source of truth for API URLs
- ✅ Request queuing during token refresh
---

## 🚀 Next Steps

1. **Update AIChatNew.jsx** - Migrate to `supervisorApi`
2. **Update DocumentExtraction.jsx** - Migrate to `kbApi` 
3. **Update DynamicMapping.jsx** - Use `fetchWithAuth`
4. **Test** - Verify token refresh works across all components
5. **Cleanup** - Remove `API_BASE_URL` constants
