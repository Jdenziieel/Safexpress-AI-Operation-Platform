import React, { useState, useEffect } from 'react';
import { Zap, AlertTriangle, TrendingUp, ChevronDown, ChevronUp, Calendar, Clock, Activity, X } from 'lucide-react';
import { getUserFromToken } from '../utils/tokenManager';
import '../css/QuotaWidget.css';

const QUOTA_API_URL = 'http://localhost:8011';

function QuotaWidget({ compact = false }) {
  const [quotaData, setQuotaData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isExpanded, setIsExpanded] = useState(false);

  // Get user info from JWT token
  const getUserInfo = () => {
    const decoded = getUserFromToken();
    // Use 'user_id' custom claim from JWT (the unique UUID field)
    // Fallback to 'sub' for backward compatibility with older tokens
    const userId = decoded?.user_id || decoded?.sub;
    console.log('QuotaWidget - Token decoded:', { user_id: decoded?.user_id, sub: decoded?.sub, resolved: userId });
    return {
      userId: userId ? String(userId) : 'default_user',
      userName: decoded?.fullname || decoded?.name || null
    };
  };

  const fetchQuotaBalance = async () => {
    try {
      const { userId, userName } = getUserInfo();
      const params = new URLSearchParams();
      if (userName) params.append('name', userName);
      
      const url = `${QUOTA_API_URL}/quota/balance/${userId}${params.toString() ? '?' + params.toString() : ''}`;
      const response = await fetch(url);
      
      if (!response.ok) {
        if (response.status === 404) {
          // User not onboarded in quota system
          setError('Quota not configured');
          setLoading(false);
          return;
        }
        throw new Error('Failed to fetch quota');
      }
      
      const data = await response.json();
      setQuotaData(data);
      setError(null);
    } catch (err) {
      console.error('Error fetching quota:', err);
      setError('Unable to load quota');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQuotaBalance();
    
    // Refresh every 30 seconds
    const interval = setInterval(fetchQuotaBalance, 30000);
    return () => clearInterval(interval);
  }, []);

  // Close expanded view when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (isExpanded && !event.target.closest('.quota-widget-container')) {
        setIsExpanded(false);
      }
    };

    if (isExpanded) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isExpanded]);

  // Determine status color based on usage percentage
  const getStatusColor = (percentage) => {
    if (percentage >= 90) return 'critical';
    if (percentage >= 75) return 'warning';
    return 'healthy';
  };

  // Format large numbers
  const formatNumber = (num) => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num?.toLocaleString() || '0';
  };

  // Format date
  const formatDate = (dateStr) => {
    if (!dateStr) return 'N/A';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  // Calculate days until reset
  const getDaysUntilReset = (resetDate) => {
    if (!resetDate) return null;
    const now = new Date();
    const reset = new Date(resetDate);
    const diffTime = reset - now;
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return diffDays > 0 ? diffDays : 0;
  };

  if (loading) {
    return (
      <div className={`quota-widget ${compact ? 'compact' : ''}`}>
        <div className="quota-widget-loading">
          <Zap size={16} className="loading-icon" />
          <span>Loading...</span>
        </div>
      </div>
    );
  }

  if (error || !quotaData) {
    return (
      <div className={`quota-widget ${compact ? 'compact' : ''} error`}>
        <AlertTriangle size={16} />
        <span>{error || 'Quota unavailable'}</span>
      </div>
    );
  }

  const { percentage_used, current_usage, monthly_limit, remaining_tokens, tier, resets_at } = quotaData;
  const status = getStatusColor(percentage_used || 0);
  const daysUntilReset = getDaysUntilReset(resets_at);
  const { userName } = getUserInfo();

  if (compact) {
    return (
      <div className="quota-widget-container">
        <div 
          className={`quota-widget compact ${status} clickable`}
          onClick={() => setIsExpanded(!isExpanded)}
          title="Click for details"
        >
          <Zap size={14} className="quota-icon" />
          <div className="quota-mini-bar">
            <div 
              className="quota-mini-fill" 
              style={{ width: `${Math.min(percentage_used || 0, 100)}%` }}
            />
          </div>
          <span className="quota-mini-text">{(percentage_used || 0).toFixed(0)}%</span>
          {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </div>

        {/* Expanded Panel */}
        {isExpanded && (
          <div className="quota-expanded-panel">
            <div className="quota-expanded-header">
              <div className="quota-expanded-title">
                <Zap size={20} className="quota-icon" />
                <div>
                  <h3>Your Token Quota</h3>
                  {userName && <span className="quota-user-name">{userName}</span>}
                </div>
              </div>
              <button className="quota-close-btn" onClick={(e) => { e.stopPropagation(); setIsExpanded(false); }}>
                <X size={18} />
              </button>
            </div>

            <div className="quota-expanded-tier">
              <span className={`quota-tier-badge tier-${tier}`}>{tier} Plan</span>
            </div>

            <div className="quota-expanded-progress">
              <div className="quota-expanded-progress-header">
                <span>Usage This Month</span>
                <span className={`quota-percentage ${status}`}>{(percentage_used || 0).toFixed(1)}%</span>
              </div>
              <div className="quota-expanded-bar">
                <div 
                  className={`quota-expanded-fill ${status}`}
                  style={{ width: `${Math.min(percentage_used || 0, 100)}%` }}
                />
              </div>
              <div className="quota-expanded-labels">
                <span>{formatNumber(current_usage)} used</span>
                <span>{formatNumber(monthly_limit)} limit</span>
              </div>
            </div>

            <div className="quota-expanded-stats">
              <div className="quota-stat-card">
                <Activity size={18} className="stat-icon remaining" />
                <div className="stat-content">
                  <span className="stat-value">{formatNumber(remaining_tokens)}</span>
                  <span className="stat-label">Tokens Remaining</span>
                </div>
              </div>

              <div className="quota-stat-card">
                <Calendar size={18} className="stat-icon reset" />
                <div className="stat-content">
                  <span className="stat-value">{daysUntilReset !== null ? `${daysUntilReset} days` : 'N/A'}</span>
                  <span className="stat-label">Until Reset</span>
                </div>
              </div>

              <div className="quota-stat-card">
                <Clock size={18} className="stat-icon date" />
                <div className="stat-content">
                  <span className="stat-value">{formatDate(resets_at)}</span>
                  <span className="stat-label">Reset Date</span>
                </div>
              </div>
            </div>

            {(percentage_used || 0) >= 75 && (
              <div className={`quota-expanded-warning ${status}`}>
                <AlertTriangle size={16} />
                <span>
                  {(percentage_used || 0) >= 90 
                    ? 'Critical: You\'re approaching your quota limit! Consider upgrading your plan.' 
                    : 'Warning: You\'ve used over 75% of your monthly quota.'}
                </span>
              </div>
            )}

            <div className="quota-expanded-footer">
              <p className="quota-tip">
                💡 Tokens reset automatically on the 1st of each month
              </p>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="quota-widget-container">
      <div 
        className={`quota-widget ${status} clickable`}
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="quota-widget-header">
          <div className="quota-title">
            <Zap size={18} className="quota-icon" />
            <span>Token Quota</span>
          </div>
          <div className="quota-header-right">
            <span className={`quota-tier tier-${tier}`}>{tier}</span>
            {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </div>
        </div>
        
        <div className="quota-progress-section">
          <div className="quota-progress-bar">
            <div 
              className="quota-progress-fill" 
              style={{ width: `${Math.min(percentage_used || 0, 100)}%` }}
            />
          </div>
          <div className="quota-progress-labels">
            <span className="quota-used">{formatNumber(current_usage)} used</span>
            <span className="quota-limit">{formatNumber(monthly_limit)} limit</span>
          </div>
        </div>

        <div className="quota-stats">
          <div className="quota-stat">
            <TrendingUp size={14} />
            <span>{formatNumber(remaining_tokens)} remaining</span>
          </div>
          <div className="quota-stat percentage">
            <span className={`percentage-value ${status}`}>{(percentage_used || 0).toFixed(1)}%</span>
            <span>used this month</span>
          </div>
        </div>

        {(percentage_used || 0) >= 75 && (
          <div className={`quota-warning ${status}`}>
            <AlertTriangle size={14} />
            <span>
              {(percentage_used || 0) >= 90 
                ? 'Critical: Approaching quota limit!' 
                : 'Warning: Usage above 75%'}
            </span>
          </div>
        )}
      </div>

      {/* Expanded Details Panel */}
      {isExpanded && (
        <div className="quota-expanded-inline">
          <div className="quota-expanded-stats">
            <div className="quota-stat-card">
              <Activity size={18} className="stat-icon remaining" />
              <div className="stat-content">
                <span className="stat-value">{formatNumber(remaining_tokens)}</span>
                <span className="stat-label">Tokens Remaining</span>
              </div>
            </div>

            <div className="quota-stat-card">
              <Calendar size={18} className="stat-icon reset" />
              <div className="stat-content">
                <span className="stat-value">{daysUntilReset !== null ? `${daysUntilReset} days` : 'N/A'}</span>
                <span className="stat-label">Until Reset</span>
              </div>
            </div>

            <div className="quota-stat-card">
              <Clock size={18} className="stat-icon date" />
              <div className="stat-content">
                <span className="stat-value">{formatDate(resets_at)}</span>
                <span className="stat-label">Reset Date</span>
              </div>
            </div>
          </div>

          <div className="quota-expanded-footer">
            <p className="quota-tip">
              💡 Tokens reset automatically on the 1st of each month
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

export default QuotaWidget;
