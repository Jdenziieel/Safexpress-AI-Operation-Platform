import React, { useState, useEffect } from 'react';
import { AlertTriangle, Zap } from 'lucide-react';
import { getUserUUID } from '../utils/tokenManager';
import { quotaApi } from '../api';
import '../css/QuotaExceededModal.css';

function QuotaExceededModal({ isOpen, onClose, quotaInfo }) {
  const [realQuotaData, setRealQuotaData] = useState(null);
  const [loading, setLoading] = useState(false);

  // Fetch real quota data when modal opens
  useEffect(() => {
    if (isOpen) {
      fetchRealQuotaData();
    }
  }, [isOpen]);

  const fetchRealQuotaData = async () => {
    setLoading(true);
    try {
      const userId = getUserUUID();
      if (!userId) {
        console.error('Cannot fetch quota - no user ID');
        setLoading(false);
        return;
      }

      const response = await quotaApi.get(`/api/quota/balance/${userId}`);
      if (response.data) {
        setRealQuotaData({
          current_usage: response.data.current_usage || 0,
          monthly_limit: response.data.monthly_limit || 0,
          tier: response.data.tier || 'free'
        });
      }
    } catch (error) {
      console.error('Error fetching real quota data:', error);
      // Fall back to passed quotaInfo if API call fails
      if (quotaInfo) {
        setRealQuotaData(quotaInfo);
      }
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  // Use real quota data if available, otherwise fall back to passed quotaInfo
  const displayData = realQuotaData || quotaInfo || {};
  const { current_usage, monthly_limit, tier } = displayData;

  return (
    <div className="quota-modal-overlay" onClick={onClose}>
      <div className="quota-modal" onClick={(e) => e.stopPropagation()}>
        <div className="quota-modal-header">
          <div className="quota-modal-icon">
            <AlertTriangle size={32} />
          </div>
          <h2>
            {quotaInfo?.reason === 'account_deactivated' 
              ? 'Account Deactivated' 
              : 'Token Quota Exceeded'}
          </h2>
        </div>

        <div className="quota-modal-body">
          {loading ? (
            <div className="quota-loading">
              <p>Loading your quota information...</p>
            </div>
          ) : (
            <>
              <p className="quota-modal-message">
                {quotaInfo?.reason === 'account_deactivated' 
                  ? 'Your account has been deactivated by an administrator. Please contact your system administrator to request reactivation.'
                  : 'You\'ve reached your monthly token limit. Your AI-powered features have been temporarily paused.'}
              </p>

              {realQuotaData && (
                <div className="quota-modal-stats">
                  <div className="quota-stat-row">
                    <span className="stat-label">Current Usage</span>
                    <span className="stat-value">{current_usage?.toLocaleString() || '0'} tokens</span>
                  </div>
                  <div className="quota-stat-row">
                    <span className="stat-label">Monthly Limit</span>
                    <span className="stat-value">{monthly_limit?.toLocaleString() || '0'} tokens</span>
                  </div>
                  <div className="quota-stat-row">
                    <span className="stat-label">Current Tier</span>
                    <span className={`tier-badge tier-${tier}`}>{tier || 'free'}</span>
                  </div>
                </div>
              )}
            </>
          )}

          <div className="quota-modal-options">
            <h3>What can you do?</h3>
            <ul>
              {quotaInfo?.reason === 'account_deactivated' ? (
                <>
                  <li>
                    <Zap size={16} />
                    <span>Contact your administrator to request account reactivation</span>
                  </li>
                  <li>
                    <Zap size={16} />
                    <span>Check with your team lead if you need continued access</span>
                  </li>
                </>
              ) : (
                <>
                  <li>
                    <Zap size={16} />
                    <span>Wait for your quota to reset at the start of next month</span>
                  </li>
                  <li>
                    <Zap size={16} />
                    <span>Contact your administrator to request a quota increase</span>
                  </li>
                  <li>
                    <Zap size={16} />
                    <span>Review your usage patterns to optimize token consumption</span>
                  </li>
                </>
              )}
            </ul>
          </div>
        </div>

        <div className="quota-modal-footer">
          <button className="quota-modal-btn secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

export default QuotaExceededModal;
