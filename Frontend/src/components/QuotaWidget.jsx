import React, { useState, useEffect, useMemo } from 'react';
import { Coins, AlertCircle, TrendingUp, ChevronDown, ChevronUp, Calendar, Clock, BarChart3, X, Wifi, WifiOff } from 'lucide-react';
import { getUserFromToken, getUserUUID } from '../utils/tokenManager';
import { useWebSocketQuota } from '../hooks/useWebSocketQuota';
import '../css/QuotaWidget.css';

function QuotaWidget({ compact = false }) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Get user info from JWT token (memoized to prevent unnecessary re-renders)
  const userInfo = useMemo(() => {
    const decoded = getUserFromToken();
    const userId = getUserUUID();
    return {
      userId: userId || 'default_user',
      userName: decoded?.fullname || decoded?.name || null
    };
  }, []);

  // ── WebSocket-driven quota data ──
  const { quotaData, loading, error, isConnected, connectionStatus, refresh } = useWebSocketQuota(
    userInfo.userId,
    userInfo.userName
  );

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
          <Coins size={16} className="loading-icon" />
          <span>Loading...</span>
        </div>
      </div>
    );
  }

  if (error || !quotaData) {
    return (
      <div className={`quota-widget ${compact ? 'compact' : ''} error`}>
        <AlertCircle size={16} />
        <span>{error || 'Quota unavailable'}</span>
        <button
          className="quota-retry-btn"
          onClick={(e) => { e.stopPropagation(); refresh(); }}
          title="Retry"
          style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', fontSize: '0.75rem', textDecoration: 'underline' }}
        >
          Retry
        </button>
      </div>
    );
  }

  const { percentage_used, current_usage, monthly_limit, remaining_tokens, tier, resets_at } = quotaData;
  const status = getStatusColor(percentage_used || 0);
  const daysUntilReset = getDaysUntilReset(resets_at);

  if (compact) {
    return (
      <div className="quota-widget-container">
        <div 
          className={`quota-widget compact ${status}`}
          onClick={() => setIsExpanded(!isExpanded)}
        >
          <div className="quota-compact-header">
            <span className="quota-compact-label">
              Token Usage
              <span
                className={`quota-ws-dot ${isConnected ? 'connected' : 'disconnected'}`}
                title={isConnected ? 'Live (WebSocket)' : `Offline (${connectionStatus})`}
              />
            </span>
            <span className="quota-compact-percentage">{(percentage_used || 0).toFixed(0)}%</span>
          </div>
          <div className="quota-mini-bar">
            <div 
              className="quota-mini-fill" 
              style={{ width: `${Math.min(percentage_used || 0, 100)}%` }}
            />
          </div>
          <div className="quota-compact-footer">
            <span className="quota-compact-usage">{formatNumber(current_usage)} / {formatNumber(monthly_limit)}</span>
            {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </div>
        </div>

        {/* Expanded Panel */}
        {isExpanded && (
          <div className="quota-expanded-panel">
            <div className="quota-expanded-header">
              <div className="quota-expanded-title">
                <h3>Token Quota</h3>
                <span className={`quota-tier-badge tier-${tier}`}>{tier}</span>
                {isConnected ? (
                  <Wifi size={14} className="quota-ws-icon connected" title="Live updates active" />
                ) : (
                  <WifiOff size={14} className="quota-ws-icon disconnected" title={`Disconnected (${connectionStatus})`} />
                )}
              </div>
              <div className="quota-expanded-actions">
                <button
                  className="quota-refresh-btn"
                  onClick={(e) => { e.stopPropagation(); refresh(); }}
                  title="Refresh quota"
                >
                  🔄
                </button>
                <button className="quota-close-btn" onClick={(e) => { e.stopPropagation(); setIsExpanded(false); }}>
                  <X size={16} />
                </button>
              </div>
            </div>

            <div className="quota-expanded-progress">
              <div className="quota-expanded-bar">
                <div 
                  className={`quota-expanded-fill ${status}`}
                  style={{ width: `${Math.min(percentage_used || 0, 100)}%` }}
                />
              </div>
              <div className="quota-expanded-labels">
                <span>{formatNumber(current_usage)} used</span>
                <span>{(percentage_used || 0).toFixed(0)}% of {formatNumber(monthly_limit)}</span>
              </div>
            </div>

            <div className="quota-expanded-stats">
              <div className="quota-stat-item">
                <span className="stat-label">Remaining</span>
                <span className="stat-value">{formatNumber(remaining_tokens)}</span>
              </div>
              <div className="quota-stat-item">
                <span className="stat-label">Resets In</span>
                <span className="stat-value">{daysUntilReset !== null ? `${daysUntilReset}d` : 'N/A'}</span>
              </div>
              <div className="quota-stat-item">
                <span className="stat-label">Reset Date</span>
                <span className="stat-value">{formatDate(resets_at)}</span>
              </div>
            </div>

            {(percentage_used || 0) >= 75 && (
              <div className={`quota-expanded-warning ${status}`}>
                <AlertCircle size={16} />
                <span>
                  {(percentage_used || 0) >= 90 
                    ? 'Critical: You\'re approaching your quota limit! Consider upgrading your plan.' 
                    : 'Warning: You\'ve used over 75% of your monthly quota.'}
                </span>
              </div>
            )}

            <div className="quota-expanded-footer">
              <p className="quota-tip">
                {isConnected
                  ? '🟢 Live updates active — quota refreshes automatically'
                  : '🔴 Offline — using periodic refresh'}
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
            <Coins size={18} className="quota-icon" />
            <span>Token Quota</span>
            <span
              className={`quota-ws-dot ${isConnected ? 'connected' : 'disconnected'}`}
              title={isConnected ? 'Live (WebSocket)' : `Offline (${connectionStatus})`}
            />
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
            <AlertCircle size={14} />
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
              <BarChart3 size={18} className="stat-icon remaining" />
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
