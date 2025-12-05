import React from 'react';
import { 
  X, 
  AlertTriangle, 
  AlertCircle, 
  XCircle, 
  Clock,
  Zap,
  ServerOff,
  ShieldAlert,
  MessageSquareOff,
  RefreshCw
} from 'lucide-react';
import '../css/LLMErrorModal.css';

/**
 * LLMErrorModal - Universal modal for displaying AI/LLM service errors
 * 
 * Handles errors like:
 * - rate_limit: Too many requests
 * - quota_exceeded: Billing/quota limits reached
 * - service_unavailable: AI provider outage
 * - authentication: API key issues
 * - context_length: Message too long
 * - unknown: Generic AI errors
 */
const LLMErrorModal = ({ isOpen, onClose, error, onRetry }) => {
  if (!isOpen || !error) return null;

  const getIcon = (errorType) => {
    switch (errorType) {
      case 'rate_limit':
        return <Clock size={48} className="llm-error-icon rate-limit" />;
      case 'quota_exceeded':
        return <Zap size={48} className="llm-error-icon quota" />;
      case 'service_unavailable':
        return <ServerOff size={48} className="llm-error-icon unavailable" />;
      case 'authentication':
        return <ShieldAlert size={48} className="llm-error-icon auth" />;
      case 'context_length':
        return <MessageSquareOff size={48} className="llm-error-icon context" />;
      default:
        return <AlertCircle size={48} className="llm-error-icon unknown" />;
    }
  };

  const getColorClass = (errorType) => {
    switch (errorType) {
      case 'rate_limit':
        return 'warning';
      case 'quota_exceeded':
        return 'critical';
      case 'service_unavailable':
        return 'critical';
      case 'authentication':
        return 'critical';
      case 'context_length':
        return 'warning';
      default:
        return 'error';
    }
  };

  const getSuggestions = (errorType) => {
    switch (errorType) {
      case 'rate_limit':
        return [
          'Wait a few moments before trying again',
          'Reduce the frequency of your requests',
          'Try again in about 30 seconds'
        ];
      case 'quota_exceeded':
        return [
          'Contact your administrator about quota limits',
          'Wait for the quota to reset (usually monthly)',
          'Consider upgrading your plan for higher limits'
        ];
      case 'service_unavailable':
        return [
          'The AI provider may be experiencing issues',
          'Try again in a few minutes',
          'Check the status page of the AI service provider',
          'If the issue persists, contact support'
        ];
      case 'authentication':
        return [
          'Contact your administrator',
          'The API configuration may need to be updated'
        ];
      case 'context_length':
        return [
          'Start a new chat session',
          'Break your message into smaller parts',
          'Remove unnecessary details from your message'
        ];
      default:
        return [
          'Try again in a few moments',
          'If the issue persists, contact support'
        ];
    }
  };

  const colorClass = getColorClass(error.error_type);

  return (
    <div className="llm-error-modal-overlay" onClick={onClose}>
      <div className={`llm-error-modal ${colorClass}`} onClick={(e) => e.stopPropagation()}>
        <button className="llm-error-modal-close" onClick={onClose} aria-label="Close">
          <X size={24} />
        </button>
        
        <div className="llm-error-modal-header">
          {getIcon(error.error_type)}
          <h2 className="llm-error-modal-title">
            {error.title || 'AI Service Error'}
          </h2>
        </div>

        <div className="llm-error-modal-body">
          <div className="llm-error-modal-message">
            {error.user_message || error.message || 'An error occurred with the AI service.'}
          </div>

          {error.retry_after && (
            <div className="llm-error-retry-info">
              <RefreshCw size={16} />
              <span>You can try again in {error.retry_after} seconds</span>
            </div>
          )}

          <div className="llm-error-suggestions">
            <h3>What you can do:</h3>
            <ul>
              {getSuggestions(error.error_type).map((suggestion, index) => (
                <li key={index}>
                  <span className="suggestion-bullet">•</span>
                  <span>{suggestion}</span>
                </li>
              ))}
            </ul>
          </div>

          {error.error_type && (
            <div className="llm-error-code">
              <strong>Error Type:</strong> {error.error_type.replace('_', ' ').toUpperCase()}
            </div>
          )}
        </div>

        <div className="llm-error-modal-footer">
          <button className="llm-error-btn secondary" onClick={onClose}>
            Close
          </button>
          {onRetry && error.error_type !== 'quota_exceeded' && error.error_type !== 'authentication' && (
            <button 
              className="llm-error-btn primary" 
              onClick={() => {
                onRetry();
                onClose();
              }}
            >
              <RefreshCw size={16} />
              Try Again
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default LLMErrorModal;
