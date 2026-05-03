import axios from 'axios';
import { ACCESS_TOKEN } from './token';

// =============================================================================
// API Base URLs for all services
// =============================================================================
// Auth API now points to AWS Lambda via API Gateway
const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8001';

// KB Service - migrated to AWS Lambda (same API Gateway)
// Uses /api/kb/*, /api/chat/*, /api/pdf/*, /api/kb-admin/* endpoints
const kbServerUrl = import.meta.env.VITE_API_URL || 'http://localhost:8009';

// Supervisor agent - still on localhost (not migrated yet)
// When the supervisor migrates to its own API Gateway, set
// VITE_SUPERVISOR_URL=https://<your-supervisor-api>.execute-api.<region>.amazonaws.com/<stage>
// in the Frontend .env (or change the fallback below). This is the single
// switch every supervisor-facing component (LogsPage, etc.) reads from.
const supervisorUrl = import.meta.env.VITE_SUPERVISOR_URL || 'http://localhost:8010';

// Re-exported as a named const so non-axios consumers (e.g. LogsPage which
// uses fetch) can hit the same base URL without hardcoding it. Keep this in
// sync with the supervisorApi instance below — they MUST share the same URL.
export const SUPERVISOR_API_URL = supervisorUrl;

// Quota service migrated to Lambda - now uses same API Gateway as auth
// If VITE_API_URL is set (production), quota endpoints are at {VITE_API_URL}/api/quota/*
// If running locally, points to localhost:8011 for backward compatibility
const quotaUrl = import.meta.env.VITE_API_URL || 'http://localhost:8011';

// =============================================================================
// Create axios instances for each service
// =============================================================================
const api = axios.create({
    baseURL: apiUrl,
});

// KB API instance - now uses Lambda via API Gateway
export const kbApi = axios.create({
    baseURL: kbServerUrl,
});

// Supervisor API instance (port 8010) - still localhost
export const supervisorApi = axios.create({
    baseURL: supervisorUrl,
});

// Quota API instance (uses same API Gateway)
export const quotaApi = axios.create({
    baseURL: quotaUrl,
});

// Shared token refresh state (to prevent multiple simultaneous refreshes)
let isRefreshing = false;
let failedQueue = [];

const processQueue = (error, token = null) => {
    failedQueue.forEach(prom => {
        if (error) {
            prom.reject(error);
        } else {
            prom.resolve(token);
        }
    });
    failedQueue = [];
};

// Function to setup interceptors for any axios instance
const setupInterceptors = (axiosInstance) => {
    // Request interceptor - add JWT token to requests
    axiosInstance.interceptors.request.use(
        (config) => {    
            const accessToken = localStorage.getItem(ACCESS_TOKEN);
            if (accessToken) {
                config.headers.Authorization = `Bearer ${accessToken}`;
            }
            return config;
        },
        (error) => {
            return Promise.reject(error);
        }
    );

    // Response interceptor - handle token expiration with refresh
    axiosInstance.interceptors.response.use(
        (response) => response,
        async (error) => {
            const originalRequest = error.config;

            // If we get a 401 Unauthorized and haven't retried yet
            if (error.response?.status === 401 && !originalRequest._retry) {
                if (isRefreshing) {
                    // If already refreshing, queue this request
                    return new Promise((resolve, reject) => {
                        failedQueue.push({ resolve, reject });
                    }).then(token => {
                        originalRequest.headers['Authorization'] = 'Bearer ' + token;
                        return axiosInstance(originalRequest);
                    }).catch(err => {
                        return Promise.reject(err);
                    });
                }

                originalRequest._retry = true;
                isRefreshing = true;

                const refreshToken = localStorage.getItem('refresh');
                
                if (!refreshToken) {
                    localStorage.removeItem(ACCESS_TOKEN);
                    localStorage.removeItem('user');
                    localStorage.removeItem('refresh');
                    window.location.href = '/login';
                    return Promise.reject(error);
                }

                try {
                    // Call AWS Lambda token refresh endpoint (no trailing slash)
                    const response = await axios.post(
                        `${apiUrl}/api/token/refresh`,
                        { refresh: refreshToken }
                    );

                    const newAccessToken = response.data.access;
                    localStorage.setItem(ACCESS_TOKEN, newAccessToken);

                    // Update authorization header for all api instances
                    api.defaults.headers.common['Authorization'] = 'Bearer ' + newAccessToken;
                    kbApi.defaults.headers.common['Authorization'] = 'Bearer ' + newAccessToken;
                    supervisorApi.defaults.headers.common['Authorization'] = 'Bearer ' + newAccessToken;
                    quotaApi.defaults.headers.common['Authorization'] = 'Bearer ' + newAccessToken;
                    originalRequest.headers['Authorization'] = 'Bearer ' + newAccessToken;

                    processQueue(null, newAccessToken);
                    isRefreshing = false;

                    // Retry the original request
                    return axiosInstance(originalRequest);
                } catch (refreshError) {
                    console.error('Token refresh failed:', refreshError);
                    processQueue(refreshError, null);
                    isRefreshing = false;
                    
                    // Refresh token is also expired/invalid, redirect to login
                    localStorage.removeItem(ACCESS_TOKEN);
                    localStorage.removeItem('user');
                    localStorage.removeItem('refresh');
                    window.location.href = '/login';
                    return Promise.reject(refreshError);
                }
            }

            return Promise.reject(error);
        }
    );
};

// Setup interceptors for all API instances
setupInterceptors(api);
setupInterceptors(kbApi);
setupInterceptors(supervisorApi);
setupInterceptors(quotaApi);

export default api;