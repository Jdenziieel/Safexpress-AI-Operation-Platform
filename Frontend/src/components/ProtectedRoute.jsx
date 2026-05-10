import React from 'react';
import { Navigate } from 'react-router-dom';
import { hasAccess, getUserRole } from '../utils/tokenManager';

/**
 * ProtectedRoute component for role-based access control
 * 
 * Wraps routes that require specific role permissions.
 * Redirects to an appropriate page if user doesn't have access.
 * 
 * Role-based access rules:
 * - Admin: Full access to everything
 * - Manager: Cannot access Accounts, Token Quota, Logs & Analytics, KB Analytics
 * - User: Can ONLY access SFXBot, Dynamic Mapping, Analysis Reports
 * 
 * @param {React.ReactNode} children - The component to render if access is granted
 * @param {string[]} allowedRoles - Array of roles that can access this route
 * @param {string} redirectTo - Path to redirect to if access is denied (default: role-appropriate page)
 */
const ProtectedRoute = ({ children, allowedRoles, redirectTo }) => {
  const userRole = getUserRole();
  
  // Check if user has access based on their role
  if (hasAccess(allowedRoles)) {
    return children;
  }
  
  // Determine appropriate redirect based on user's role
  const getDefaultRedirect = () => {
    switch (userRole) {
      case 'user':
        // Users should go to SFX Bot (their primary accessible page)
        return '/sfx-bot';
      case 'manager':
        // Managers should go to Logs & Analytics
        return '/logs';
      default:
        // Fallback to the admin dashboard
        return '/dashboard';
    }
  };
  
  const targetRedirect = redirectTo || getDefaultRedirect();
  
  console.warn(`Access denied: User role '${userRole}' attempted to access restricted route. Redirecting to ${targetRedirect}`);
  
  return <Navigate to={targetRedirect} replace />;
};

export default ProtectedRoute;
