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
    console.log('No refresh token available, redirecting to login...');
    localStorage.removeItem(ACCESS_TOKEN);
    localStorage.removeItem('user');
    localStorage.removeItem('refresh');
    window.location.href = '/login';
    throw new Error('No refresh token');
  }

  try {
    console.log('Access token expired, attempting to refresh...');
    
    const response = await fetch('http://localhost:8001/api/token/refresh/', {
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
    console.log('Token refreshed successfully');
    
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

// Django Auth Service (Port 8001)
export const authApi = {
  baseURL: 'http://localhost:8001',
  
  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    return fetchWithAuth(url, options);
  }
};

// Chat Service (Port 8009)
export const chatApi = {
  baseURL: 'http://localhost:8009',
  
  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    return fetchWithAuth(url, options);
  },
  
  async getSessions() {
    const response = await this.request('/chat/sessions');
    return response.json();
  },
  
  async createSession(title) {
    const response = await this.request('/chat/session/new', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title })
    });
    return response.json();
  },
  
  async getSessionHistory(sessionId) {
    const response = await this.request(`/chat/session/${sessionId}/history`);
    return response.json();
  },
  
  async deleteSession(sessionId) {
    const response = await this.request(`/chat/session/${sessionId}`, {
      method: 'DELETE'
    });
    return response.json();
  },
  
  async sendMessage(sessionId, message, options = {}) {
    const response = await this.request('/chat/message', {
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
  
  async getSessionTokens(sessionId) {
    const response = await this.request(`/chat/session/${sessionId}/tokens`);
    return response.json();
  },
  
  async getUserTokens() {
    const response = await this.request('/chat/user/tokens');
    return response.json();
  }
};

// Supervisor Agent Service (Port 8010)
export const supervisorApi = {
  baseURL: 'http://localhost:8010',
  
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

// Knowledge Base Service (Port 8009)
export const kbApi = {
  baseURL: 'http://localhost:8009',
  
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
    
    const response = await this.request(`/kb/list-kb?${queryParams}`);
    return response.json();
  },
  
  /**
   * Upload document chunks to knowledge base
   */
  async uploadToKB(data) {
    const response = await this.request('/kb/upload-to-kb', {
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
    const response = await this.request(`/kb/delete/${docId}`, {
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
    const response = await fetch(`${this.baseURL}/pdf/parse-pdf`, {
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
        const retryResponse = await fetch(`${this.baseURL}/pdf/parse-pdf`, {
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
   */
  async getDocument(docId) {
    const response = await this.request(`/kb/document/${docId}`);
    return response.json();
  },
  
  /**
   * Search knowledge base
   */
  async search(query, params = {}) {
    const response = await this.request('/kb/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, ...params })
    });
    return response.json();
  }
};

export default {
  authApi,
  chatApi,
  supervisorApi,
  kbApi,
  fetchWithAuth,
  getAuthHeaders
};
