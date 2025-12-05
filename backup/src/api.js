import axios from 'axios';
import { ACCESS_TOKEN } from './token';

// Django backend runs on port 8000 for authentication
const apiUrl = 'http://localhost:8000';

const api = axios.create({
    baseURL: import.meta.env.VITE_API_URL ? import.meta.env.VITE_API_URL : apiUrl,
})

// Request interceptor - add JWT token to requests
api.interceptors.request.use(
    (config) => {    
        const accessToken = localStorage.getItem(ACCESS_TOKEN);
        if (accessToken) {
            config.headers.Authorization = `Bearer ${accessToken}`
        }
        return config
    },
    (error) => {
        return Promise.reject(error);
    }
);

// Response interceptor - handle token expiration with refresh
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

api.interceptors.response.use(
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
                    return api(originalRequest);
                }).catch(err => {
                    return Promise.reject(err);
                });
            }

            originalRequest._retry = true;
            isRefreshing = true;

            const refreshToken = localStorage.getItem('refresh');
            
            if (!refreshToken) {
                console.log('No refresh token available, redirecting to login...');
                localStorage.removeItem(ACCESS_TOKEN);
                localStorage.removeItem('user');
                localStorage.removeItem('refresh');
                window.location.href = '/login';
                return Promise.reject(error);
            }

            try {
                console.log('Access token expired, attempting to refresh...');
                
                // Call Django's token refresh endpoint
                const response = await axios.post(
                    `${apiUrl}/api/token/refresh/`,
                    { refresh: refreshToken }
                );

                const newAccessToken = response.data.access;
                localStorage.setItem(ACCESS_TOKEN, newAccessToken);
                console.log('Token refreshed successfully');

                // Update authorization header
                api.defaults.headers.common['Authorization'] = 'Bearer ' + newAccessToken;
                originalRequest.headers['Authorization'] = 'Bearer ' + newAccessToken;

                processQueue(null, newAccessToken);
                isRefreshing = false;

                // Retry the original request
                return api(originalRequest);
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

export default api;