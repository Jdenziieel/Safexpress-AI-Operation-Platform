import { jwtDecode } from 'jwt-decode';
import { ACCESS_TOKEN } from '../token';

/**
 * Check if the JWT token is expired
 * @returns {boolean} true if token is expired or invalid
 */
export const isTokenExpired = () => {
  const token = localStorage.getItem(ACCESS_TOKEN);
  if (!token) return true;
  
  try {
    const decoded = jwtDecode(token);
    const currentTime = Date.now() / 1000;
    
    // Token is expired if exp time is less than current time
    return decoded.exp < currentTime;
  } catch (error) {
    console.error('Error decoding token:', error);
    return true;
  }
};

/**
 * Get user info from JWT token
 * @returns {object|null} decoded user info or null
 */
export const getUserFromToken = () => {
  const token = localStorage.getItem(ACCESS_TOKEN);
  if (!token) return null;
  
  try {
    return jwtDecode(token);
  } catch (error) {
    console.error('Error decoding token:', error);
    return null;
  }
};
