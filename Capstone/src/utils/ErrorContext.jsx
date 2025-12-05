import React, { createContext, useContext, useState, useCallback } from 'react';

/**
 * ErrorContext for global error handling
 * 
 * Usage in components:
 * 
 * import { useError } from '../utils/ErrorContext';
 * 
 * function MyComponent() {
 *   const { showError } = useError();
 *   
 *   const handleAction = async () => {
 *     try {
 *       // Your code here
 *       const response = await fetch('/api/endpoint');
 *       if (!response.ok) throw new Error('Request failed');
 *     } catch (error) {
 *       showError({
 *         title: 'Operation Failed',
 *         message: error.message,
 *         severity: 'error', // 'error', 'warning', or 'critical'
 *         details: error.stack,
 *         onRetry: () => handleAction() // Optional retry function
 *       });
 *     }
 *   };
 * }
 */

const ErrorContext = createContext();

export const useError = () => {
  const context = useContext(ErrorContext);
  if (!context) {
    throw new Error('useError must be used within an ErrorProvider');
  }
  return context;
};

export const ErrorProvider = ({ children }) => {
  const [error, setError] = useState(null);
  const [showErrorModal, setShowErrorModal] = useState(false);

  const showError = useCallback((errorData) => {
    // Normalize error data
    const normalizedError = {
      title: errorData?.title || 'Error',
      message: errorData?.message || 'An unexpected error occurred',
      severity: errorData?.severity || 'error',
      details: errorData?.details,
      code: errorData?.code,
      timestamp: errorData?.timestamp || new Date().toISOString(),
      onRetry: errorData?.onRetry,
    };
    
    setError(normalizedError);
    setShowErrorModal(true);
  }, []);

  const hideError = useCallback(() => {
    setShowErrorModal(false);
    setTimeout(() => setError(null), 300); // Clear after animation
  }, []);

  return (
    <ErrorContext.Provider value={{ error, showError, hideError, showErrorModal }}>
      {children}
    </ErrorContext.Provider>
  );
};
