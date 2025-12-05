import React from 'react';
import { AlertTriangle, Zap, ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import '../css/QuotaExceededModal.css';

function QuotaExceededModal({ isOpen, onClose, quotaInfo }) {
  if (!isOpen) return null;

  const { current_usage, monthly_limit, tier } = quotaInfo || {};

  return (
    <div className="quota-modal-overlay" onClick={onClose}>
      <div className="quota-modal" onClick={(e) => e.stopPropagation()}>
        <div className="quota-modal-header">
          <div className="quota-modal-icon">
            <AlertTriangle size={32} />
          </div>
          <h2>Token Quota Exceeded</h2>
        </div>

        <div className="quota-modal-body">
          <p className="quota-modal-message">
            You've reached your monthly token limit. Your AI requests have been paused
            to prevent unexpected usage.
          </p>

          <div className="quota-modal-stats">
            <div className="quota-stat-row">
              <span className="stat-label">Current Usage</span>
              <span className="stat-value">{current_usage?.toLocaleString() || 'N/A'}</span>
            </div>
            <div className="quota-stat-row">
              <span className="stat-label">Monthly Limit</span>
              <span className="stat-value">{monthly_limit?.toLocaleString() || 'N/A'}</span>
            </div>
            <div className="quota-stat-row">
              <span className="stat-label">Current Tier</span>
              <span className={`tier-badge tier-${tier}`}>{tier || 'free'}</span>
            </div>
          </div>

          <div className="quota-modal-options">
            <h3>What can you do?</h3>
            <ul>
              <li>
                <Zap size={16} />
                <span>Wait for your quota to reset at the start of next month</span>
              </li>
              <li>
                <Zap size={16} />
                <span>Upgrade your plan for higher limits</span>
              </li>
              <li>
                <Zap size={16} />
                <span>Contact support for enterprise options</span>
              </li>
            </ul>
          </div>
        </div>

        <div className="quota-modal-footer">
          <button className="quota-modal-btn secondary" onClick={onClose}>
            Close
          </button>
          <Link to="/quota" className="quota-modal-btn primary" onClick={onClose}>
            View Quota Details
            <ArrowRight size={16} />
          </Link>
        </div>
      </div>
    </div>
  );
}

export default QuotaExceededModal;
