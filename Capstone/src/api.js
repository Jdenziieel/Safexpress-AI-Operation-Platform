import axios from 'axios';
import { ACCESS_TOKEN } from './token';

const apiUrl = '/choreo-apis/awbo/backend/rest-api-be2/v1.0';

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

// Response interceptor - handle token expiration
api.interceptors.response.use(
    (response) => response,
    (error) => {
        // If we get a 401 Unauthorized, token is invalid/expired
        if (error.response?.status === 401) {
            console.log('Token expired or invalid, redirecting to login...');
            localStorage.removeItem(ACCESS_TOKEN);
            localStorage.removeItem('user');
            window.location.href = '/login';
        }
        return Promise.reject(error);
    }
);

export default api;