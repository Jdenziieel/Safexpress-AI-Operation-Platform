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

/**
 * Get the current user's role from JWT token
 * Role is extracted from the cryptographically signed JWT,
 * not from localStorage which can be tampered with.
 * 
 * @returns {string|null} user role ('admin', 'manager', 'user') or null
 */
export const getUserRole = () => {
  const decoded = getUserFromToken();
  if (!decoded) return null;
  
  return decoded.role?.toLowerCase() || null;
};

/**
 * Get the current user's UUID from JWT token
 * This is the unique identifier used for external services (quota, AI chat, etc.)
 * 
 * JWT claims (in order of preference):
 * - 'uuid': Custom claim we add (the user_id field from CustomUser model)
 * - 'user_id': SimpleJWT default (integer PK, for backward compatibility)
 * - 'sub': Standard JWT subject claim
 * 
 * @returns {string|null} user UUID or null
 */
export const getUserUUID = () => {
  const decoded = getUserFromToken();
  if (!decoded) return null;
  
  // Prefer 'uuid' (our custom UUID), fallback to user_id or sub
  return String(decoded.uuid || decoded.user_id || decoded.sub || null);
};

/**
 * Check if current user is an admin based on JWT token
 * Role is extracted from the cryptographically signed JWT,
 * not from localStorage which can be tampered with.
 * 
 * Note: This is for UI display purposes only.
 * Backend MUST validate the JWT on every protected API call.
 * 
 * @returns {boolean} true if user is admin
 */
export const isAdmin = () => {
  return getUserRole() === 'admin';
};

/**
 * Check if current user is a manager based on JWT token
 * 
 * @returns {boolean} true if user is manager
 */
export const isManager = () => {
  return getUserRole() === 'manager';
};

/**
 * Check if current user is a regular user based on JWT token
 * 
 * @returns {boolean} true if user is a regular user
 */
export const isUser = () => {
  return getUserRole() === 'user';
};

/**
 * Check if user has access to a specific feature based on their role
 * 
 * Role-based access rules:
 * - Admin: Full access to everything
 * - Manager: Cannot access Accounts, Token Quota, Logs & Analytics, KB Analytics
 * - User: Can ONLY access SFXBot, Dynamic Mapping, Analysis Reports
 * 
 * @param {string[]} allowedRoles - Array of roles that can access this feature
 * @returns {boolean} true if user has access
 */
export const hasAccess = (allowedRoles) => {
  const role = getUserRole();
  if (!role) return false;
  
  return allowedRoles.includes(role);
};

/**
 * Check if user is authenticated (has valid, non-expired token)
 * @returns {boolean} true if authenticated
 */
export const isAuthenticated = () => {
  return !isTokenExpired();
};
