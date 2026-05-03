/**
 * API Helper Functions for Different Backend Services
 * Provides consistent authentication and token refresh across all microservices
 */

import { ACCESS_TOKEN } from './token';

/**
 * Get authorization headers with JWT token
 */
const getAuthHeaders = () => {
  const token = localStorage.getItem(ACCESS_TOKEN);
  return {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  };
};

/**
 * Handle token refresh when 401 error occurs
 */
const handleTokenRefresh = async () => {
  const refreshToken = localStorage.getItem('refresh');
  
  if (!refreshToken) {
    localStorage.removeItem(ACCESS_TOKEN);
    localStorage.removeItem('user');
    localStorage.removeItem('refresh');
    window.location.href = '/login';
    throw new Error('No refresh token');
  }

  try {
    // Updated to use AWS Lambda API Gateway endpoint (no trailing slash)
    const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8001';
    const response = await fetch(`${apiUrl}/api/token/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh: refreshToken })
    });

    if (!response.ok) {
      throw new Error('Token refresh failed');
    }

    const data = await response.json();
    const newAccessToken = data.access;
    localStorage.setItem(ACCESS_TOKEN, newAccessToken);
    
    return newAccessToken;
  } catch (error) {
    console.error('Token refresh failed:', error);
    localStorage.removeItem(ACCESS_TOKEN);
    localStorage.removeItem('user');
    localStorage.removeItem('refresh');
    window.location.href = '/login';
    throw error;
  }
};

/**
 * Enhanced fetch with automatic token refresh on 401
 */
export const fetchWithAuth = async (url, options = {}) => {
  const token = localStorage.getItem(ACCESS_TOKEN);
  
  // Add authorization header
  const headers = {
    ...options.headers,
    'Authorization': `Bearer ${token}`
  };

  // First attempt
  let response = await fetch(url, { ...options, headers });

  // If 401, try to refresh token and retry
  if (response.status === 401) {
    try {
      const newToken = await handleTokenRefresh();
      
      // Retry with new token
      headers['Authorization'] = `Bearer ${newToken}`;
      response = await fetch(url, { ...options, headers });
    } catch (refreshError) {
      throw refreshError;
    }
  }

  return response;
};

/**
 * API clients for different backend services
 */

// Django Auth Service (Port 8000) - Migrated to AWS Lambda
export const authApi = {
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8001',
  
  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    return fetchWithAuth(url, options);
  }
};

// Chat Service - Migrated to AWS Lambda (same API Gateway as KB)
export const chatApi = {
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8009',
  
  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    return fetchWithAuth(url, options);
  },
  
  async getSessions() {
    const response = await this.request('/api/chat/sessions');
    return response.json();
  },
  
  async createSession(title) {
    const response = await this.request('/api/chat/session/new', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title })
    });
    return response.json();
  },
  
  async getSessionHistory(sessionId) {
    const response = await this.request(`/api/chat/session/${sessionId}/history`);
    return response.json();
  },
  
  async deleteSession(sessionId) {
    const response = await this.request(`/api/chat/session/${sessionId}`, {
      method: 'DELETE'
    });
    return response.json();
  },
  
  async sendMessage(sessionId, message, options = {}) {
    const response = await this.request('/api/chat/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        message,
        options
      })
    });
    return response.json();
  },
  
  // DEPRECATED: Session tokens endpoint not implemented in Lambda
  // Use getUserQuota() instead for quota information
  async getSessionTokens(sessionId) {
    console.warn('getSessionTokens is deprecated. Use getUserQuota() instead.');
    const response = await this.request(`/api/chat/session/${sessionId}/tokens`);
    return response.json();
  },
  
  /**
   * Get user quota balance from quota service
   * Lambda endpoint: GET /api/chat/quota
   */
  async getUserQuota() {
    const response = await this.request('/api/chat/quota');
    return response.json();
  },
  
  // DEPRECATED: Use getUserQuota() instead
  async getUserTokens() {
    console.warn('getUserTokens is deprecated. Use getUserQuota() instead.');
    return this.getUserQuota();
  }
};

// Supervisor Agent Service (Port 8010)
export const supervisorApi = {
  baseURL: import.meta.env.VITE_SUPERVISOR_URL || 'http://localhost:8010',
  
  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    return fetchWithAuth(url, options);
  },
  
  async getThreads(userId) {
    const response = await this.request(`/threads?user_id=${userId}`);
    return response.json();
  },
  
  async deleteThread(threadId) {
    const response = await this.request(`/threads/${threadId}`, {
      method: 'DELETE'
    });
    return response.json();
  },
  
  async createThread(userId) {
    const response = await this.request('/threads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId })
    });
    return response.json();
  },
  
  async getThreadMessages(threadId) {
    const response = await this.request(`/threads/${threadId}/messages`);
    return response.json();
  },
  
  async sendMessage(threadId, message) {
    const response = await this.request(`/threads/${threadId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message })
    });
    return response.json();
  },
  
  async getPendingActions() {
    const response = await this.request('/actions/pending');
    return response.json();
  },
  
  async cleanupActions() {
    const response = await this.request('/actions/cleanup', {
      method: 'POST'
    });
    return response.json();
  },
  
  async approveAction(actionId, approved) {
    const response = await this.request(`/action/approve/${actionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved })
    });
    return response.json();
  }
};

// Knowledge Base Service - Migrated to AWS Lambda (same API Gateway)
export const kbApi = {
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8009',
  
  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    return fetchWithAuth(url, options);
  },
  
  /**
   * List all documents in knowledge base with pagination and sorting
   */
  async listDocuments(params = {}) {
    const { limit = 10, offset = 0, order_by = 'created_at', order_dir = 'DESC' } = params;
    const queryParams = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString(),
      order_by,
      order_dir
    });
    
    const response = await this.request(`/api/kb/list-kb?${queryParams}`);
    return response.json();
  },
  
  /**
   * Upload document chunks to knowledge base
   */
  async uploadToKB(data) {
    const response = await this.request('/api/kb/upload-to-kb', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    return response.json();
  },
  
  /**
   * Delete a document from knowledge base
   */
  async deleteDocument(docId) {
    const response = await this.request(`/api/kb/delete/${docId}`, {
      method: 'DELETE'
    });
    return response.json();
  },
  
  /**
   * Parse PDF file into chunks (doesn't require auth, but using for consistency)
   * Note: This endpoint accepts FormData, not JSON
   */
  async parsePDF(formData) {
    const token = localStorage.getItem(ACCESS_TOKEN);
    
    // For file uploads, we need to handle FormData specially
    // FIXED: Added /api prefix to match API Gateway route configuration
    const response = await fetch(`${this.baseURL}/api/pdf/parse-pdf`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`
        // Don't set Content-Type - browser will set it with boundary for FormData
      },
      body: formData
    });
    
    // Handle 401 with token refresh
    if (response.status === 401) {
      try {
        const newToken = await handleTokenRefresh();
        
        // Retry with new token
        const retryResponse = await fetch(`${this.baseURL}/api/pdf/parse-pdf`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${newToken}`
          },
          body: formData
        });
        
        return retryResponse.json();
      } catch (refreshError) {
        throw refreshError;
      }
    }
    
    return response.json();
  },
  
  /**
   * Get document details by ID
   * NOTE: Not implemented in current Lambda functions
   */
  async getDocument(docId) {
    console.warn('getDocument endpoint not implemented in Lambda. Use listDocuments with filter instead.');
    const response = await this.request(`/api/kb/document/${docId}`);
    return response.json();
  },
  
  /**
   * Query knowledge base with AI-generated answer
   * Lambda endpoint: POST /api/kb/query
   * Returns AI answer with sources and usage statistics
   */
  async query(query, params = {}) {
    const response = await this.request('/api/kb/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, ...params })
    });
    return response.json();
  },
  
  // DEPRECATED: Use query() instead (renamed to match Lambda endpoint)
  async search(query, params = {}) {
    console.warn('search is deprecated. Use query() instead.');
    return this.query(query, params);
  }
};

export const abcApi = {
  baseURL: import.meta.env.VITE_API_URL,  // same gateway, no fallback needed in prod

  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    return fetchWithAuth(url, options);
  },

  async runAnalysis(payload) {
    const response = await this.request('/api/abc/analysis', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    return response.json();
  }
};


export const oprApi = {
  baseURL: import.meta.env.VITE_API_URL,

  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    return fetchWithAuth(url, options);
  },

  async preview(payload) {
    const response = await this.request('/api/opr/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    return response.json();
  },

  async process(payload) {
    const response = await this.request('/api/opr/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    return response.json();
  }
};

export const dynamicMappingApi = {
  baseURL: import.meta.env.VITE_API_URL,

  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    return fetchWithAuth(url, options);
  },

  async upload(formData) {
    const token = localStorage.getItem(ACCESS_TOKEN);
    const response = await fetch(`${this.baseURL}/api/dynamic-mapping/upload`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`
        // No Content-Type — browser sets it with multipart boundary
      },
      body: formData
    });

    if (response.status === 401) {
      try {
        const newToken = await handleTokenRefresh();
        const retryResponse = await fetch(`${this.baseURL}/api/dynamic-mapping/upload`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${newToken}` },
          body: formData
        });
        return retryResponse.json();
      } catch (refreshError) {
        throw refreshError;
      }
    }

    return response.json();
  }
};

export default {
  authApi,
  chatApi,
  supervisorApi,
  kbApi,
  abcApi,
  dynamicMappingApi,
  fetchWithAuth,
  getAuthHeaders
};
