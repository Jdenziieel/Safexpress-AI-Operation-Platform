import React from 'react';
import { 
  AlertTriangle, 
  AlertCircle, 
  XCircle, 
  Clock,
  Zap,
  ServerOff,
  ShieldAlert,
  MessageSquareOff,
  RefreshCw,
  CheckCircle,
  HelpCircle
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
    const size = 24;
    switch (errorType) {
      case 'rate_limit':
        return <Clock size={size} />;
      case 'quota_exceeded':
        return <Zap size={size} />;
      case 'service_unavailable':
        return <ServerOff size={size} />;
      case 'authentication':
        return <ShieldAlert size={size} />;
      case 'context_length':
        return <MessageSquareOff size={size} />;
      default:
        return <AlertCircle size={size} />;
    }
  };

  const getColorClass = (errorType) => {
    switch (errorType) {
      case 'rate_limit':
        return 'warning';
      case 'quota_exceeded':
        return 'quota';
      case 'service_unavailable':
        return 'error';
      case 'authentication':
        return 'error';
      case 'context_length':
        return 'warning';
      case 'unknown':
        return 'info';
      default:
        return 'default';
    }
  };

  const getSuggestions = (errorType) => {
    const suggestions = {
      rate_limit: [
        'Wait a few moments before trying again.',
        'Reduce the frequency of your requests.',
        'If this persists, try again in about 30 seconds.'
      ],
      quota_exceeded: [
        'Contact your administrator to review quota limits.',
        'Wait for the quota to reset (this is usually monthly).',
        'Consider upgrading your plan for higher limits.'
      ],
      service_unavailable: [
        'The AI provider may be experiencing temporary issues.',
        'Please try again in a few minutes.',
        'You can check the status page of the AI service provider.',
        'If the issue persists, contact support for assistance.'
      ],
      authentication: [
        'Please contact your administrator immediately.',
        'The API configuration for the AI service may be incorrect or outdated.'
      ],
      context_length: [
        'Try starting a new chat session to clear the history.',
        'Break your message into smaller, more focused parts.',
        'Summarize or remove unnecessary details from your message.'
      ],
      unknown: [
        'An unexpected error occurred. Please try again.',
        'If the issue continues, restarting the session may help.',
        'Contact support if you see this error repeatedly.'
      ]
    };
    return suggestions[errorType] || suggestions.unknown;
  };

  const colorClass = getColorClass(error.error_type);
  const suggestions = getSuggestions(error.error_type);

  return (
    <div className="llm-error-modal-backdrop" onClick={onClose}>
      <div className="llm-error-modal" onClick={(e) => e.stopPropagation()}>
        <div className="llm-error-modal-header">
          <h2>
            {error.title || 'AI Service Error'}
          </h2>
        </div>

        <div className="llm-error-modal-body">
          <div className="llm-error-content">
            <p>
              <strong>{error.user_message || error.message || 'An unexpected error occurred with the AI service.'}</strong>
            </p>
            {error.retry_after && (
              <p>You can try again in {error.retry_after} seconds.</p>
            )}
            {error.error_type && (
              <p>Error Type: <strong>{error.error_type.replace(/_/g, ' ').toUpperCase()}</strong></p>
            )}
          </div>

          {suggestions.length > 0 && (
            <div className="llm-error-suggestions">
              <h3>What you can do:</h3>
              <ul>
                {suggestions.map((suggestion, index) => (
                  <li key={index}>
                    <span>{suggestion}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="llm-error-modal-footer">
          <button className="llm-error-modal-button" onClick={onClose}>
            Close
          </button>
          {onRetry && error.error_type !== 'quota_exceeded' && error.error_type !== 'authentication' && (
            <button 
              className="llm-error-modal-button primary" 
              onClick={() => {
                onRetry();
                onClose();
              }}
            >
              Try Again
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default LLMErrorModal;
