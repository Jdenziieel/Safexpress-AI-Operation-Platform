import React from 'react';
import { X, AlertTriangle, AlertCircle, XCircle } from 'lucide-react';
import '../css/ErrorModal.css';

const ErrorModal = ({ isOpen, onClose, error }) => {
  if (!isOpen) return null;

  const getSeverityIcon = (severity) => {
    switch (severity) {
      case 'critical':
        return <XCircle size={48} />;
      case 'warning':
        return <AlertTriangle size={48} />;
      default:
        return <AlertCircle size={48} />;
    }
  };

  const getSeverityColor = (severity) => {
    switch (severity) {
      case 'critical':
        return '#ef4444';
      case 'warning':
        return '#f59e0b';
      default:
        return '#fcb117';
    }
  };

  return (
    <div className="error-modal-overlay" onClick={onClose}>
      <div className="error-modal" onClick={(e) => e.stopPropagation()}>
        <button className="error-modal-close" onClick={onClose}>
          <X size={24} />
        </button>
        
        <div className="error-modal-header" style={{ color: getSeverityColor(error?.severity || 'error') }}>
          {getSeverityIcon(error?.severity || 'error')}
          <h2 className="error-modal-title">
            {error?.title || 'An Error Occurred'}
          </h2>
        </div>

        <div className="error-modal-body">
          <div className="error-modal-message">
            {error?.message || 'An unexpected error has occurred. Please try again.'}
          </div>

          {error?.details && (
            <div className="error-modal-details">
              <h3>Details:</h3>
              <p>{error.details}</p>
            </div>
          )}

          {error?.timestamp && (
            <div className="error-modal-timestamp">
              <strong>Time:</strong> {new Date(error.timestamp).toLocaleString()}
            </div>
          )}

          {error?.code && (
            <div className="error-modal-code">
              <strong>Error Code:</strong> {error.code}
            </div>
          )}
        </div>

        <div className="error-modal-footer">
          <button className="error-modal-btn primary" onClick={onClose}>
            Close
          </button>
          {error?.onRetry && (
            <button 
              className="error-modal-btn secondary" 
              onClick={() => {
                error.onRetry();
                onClose();
              }}
            >
              Retry
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default ErrorModal;
