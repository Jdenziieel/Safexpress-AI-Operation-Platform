import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Filter, RefreshCw, ChevronLeft, ChevronRight, Activity, Search, ArrowLeft } from 'lucide-react';
import api from '../api';
import '../css/AdminActivityLogs.css';

// Helper to get friendly action label
const getActionLabel = (action, actionDisplay) => {
  const labels = {
    'onboard': 'Created Account',
    'activate': 'Activated Account',
    'deactivate': 'Deactivated Account',
    'update': 'Updated Account',
    'update_role': 'Changed Role',
    'update_name': 'Changed Name'
  };
  return labels[action] || actionDisplay || action;
};

// Helper to get action badge style
const getActionClass = (action) => {
  switch (action) {
    case 'onboard':
      return 'action-created';
    case 'activate':
      return 'action-activated';
    case 'deactivate':
      return 'action-deactivated';
    case 'update':
    case 'update_role':
    case 'update_name':
      return 'action-updated';
    default:
      return 'action-default';
  }
};

const ActionButton = ({ icon: Icon, children, className = '', ...props }) => (
  <div style={{ position: 'relative', display: 'inline-block' }}>
    <button
      className={`main-card-btn ${className}`}
      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '12px', fontSize: '1.15rem', fontWeight: 800 }}
      {...props}
    >
      <Icon size={20} />
    </button>
    <span
      style={{
        position: 'absolute',
        top: '100%',
        left: '50%',
        transform: 'translateX(-50%)',
        marginTop: '8px',
        padding: '6px 12px',
        background: '#26326e',
        color: 'white',
        borderRadius: '6px',
        fontSize: '0.85rem',
        fontWeight: 600,
        whiteSpace: 'nowrap',
        opacity: 0,
        pointerEvents: 'none',
        transition: 'opacity 0.2s',
        zIndex: 1000
      }}
      className="button-tooltip"
    >
      {children}
    </span>
  </div>
);

function AdminActivityLogs() {
  const navigate = useNavigate();
  const location = useLocation();
  const searchParams = new URLSearchParams(location.search);
  const scopedAccountEmail = searchParams.get('scope') === 'account'
    ? (searchParams.get('target_email') || '')
    : '';
  const isAccountScoped = Boolean(scopedAccountEmail);

  const getFiltersFromSearch = () => {
    const params = new URLSearchParams(location.search);
    return {
      action: params.get('action') || '',
      adminEmail: params.get('admin_email') || '',
      targetEmail: scopedAccountEmail || params.get('target_email') || '',
      days: params.get('days') ?? '30'
    };
  };

  const [logs, setLogs] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showFilters, setShowFilters] = useState(() => {
    const initial = getFiltersFromSearch();
    return Boolean(initial.action || initial.adminEmail || initial.targetEmail || initial.days !== '30');
  });
  
  // Pagination
  const [currentPage, setCurrentPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const logsPerPage = 10;
  
  // Filters
  const [filters, setFilters] = useState(() => getFiltersFromSearch());

  useEffect(() => {
    const nextFilters = getFiltersFromSearch();
    setFilters(nextFilters);
    if (nextFilters.action || nextFilters.adminEmail || nextFilters.targetEmail || nextFilters.days !== '30') {
      setShowFilters(true);
    }
    setCurrentPage(1);
  }, [location.search]);

  const fetchLogs = async () => {
    setIsLoading(true);
    setError(null);
    
    try {
      const params = new URLSearchParams();
      
      if (filters.action) params.append('action', filters.action);
      if (filters.adminEmail) params.append('admin_email', filters.adminEmail);
      if (filters.targetEmail) params.append('target_email', filters.targetEmail);
      if (filters.days) params.append('days', filters.days);
      
      params.append('limit', logsPerPage);
      params.append('offset', (currentPage - 1) * logsPerPage);
      
      // AWS Lambda endpoint - no trailing slash
      const response = await api.get(`/api/admin/activity-logs?${params.toString()}`);
      
      if (response.data) {
        setLogs(response.data.logs || []);
        setTotalCount(response.data.count || 0);
      }
    } catch (err) {
      console.error('Error fetching activity logs:', err);
      setError(err.response?.data?.error || 'Failed to load activity logs');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, [currentPage, filters]);

  const handleFilterChange = (field, value) => {
    if (isAccountScoped && field === 'targetEmail') {
      return;
    }
    setFilters(prev => ({ ...prev, [field]: value }));
    setCurrentPage(1);
  };

  const clearFilters = () => {
    setFilters({
      action: '',
      adminEmail: '',
      targetEmail: scopedAccountEmail,
      days: '30'
    });
    setCurrentPage(1);
  };

  const formatDate = (isoDate) => {
    const date = new Date(isoDate);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  // Format details in a human-friendly way
  const formatDetails = (details, action) => {
    if (!details) return <span className="no-details">—</span>;
    
    // Create human-readable descriptions
    const formatFieldName = (key) => {
      const fieldLabels = {
        'role': 'Role',
        'is_active': 'Account Status',
        'first_name': 'First Name',
        'last_name': 'Last Name',
        'fullname': 'Full Name',
        'email': 'Email',
        'gmail': 'Gmail Address'
      };
      return fieldLabels[key] || key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    };

    const formatValue = (key, value) => {
      if (key === 'is_active') {
        return value === true || value === 'true' ? 'Active' : 'Inactive';
      }
      if (value === null || value === undefined || value === '') {
        return '(empty)';
      }
      return String(value);
    };

    // Handle different detail structures
    if (details.old_values && details.new_values) {
      const changes = Object.keys(details.new_values).map(key => {
        const oldVal = formatValue(key, details.old_values[key]);
        const newVal = formatValue(key, details.new_values[key]);
        return `${formatFieldName(key)}: "${oldVal}" → "${newVal}"`;
      });
      return (
        <div className="details-text">
          {changes.map((change, idx) => (
            <div key={idx} className="detail-line">{change}</div>
          ))}
        </div>
      );
    }
    
    if (details.role) {
      return <span className="details-text">Assigned role: <strong>{details.role}</strong></span>;
    }
    
    if (details.previous_status && details.new_status) {
      const oldStatus = details.previous_status === 'active' ? 'Active' : 'Inactive';
      const newStatus = details.new_status === 'active' ? 'Active' : 'Inactive';
      return (
        <div className="details-text">
          <div className="detail-line">Account Status: "{oldStatus}" → "{newStatus}"</div>
        </div>
      );
    }

    // Fallback for any other detail structure
    return <span className="no-details">—</span>;
  };

  const totalPages = Math.ceil(totalCount / logsPerPage);

  return (
    <div className="activity-logs-page">
      <div className="activity-logs-container">
        {/* Back Button */}
        <div style={{ marginBottom: '16px' }}>
          <button 
            onClick={() => navigate('/accounts')}
            style={{ 
              background: '#26326e', 
              color: 'white', 
              border: 'none', 
              borderRadius: '8px', 
              padding: '10px', 
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}
            title="Back to Accounts"
          >
            <ArrowLeft size={20} />
          </button>
        </div>

        {/* Header - Matching Accounts page style */}
        <div className="activity-logs-header">
          <div>
            <h1 className="aal-header-title">Activity Logs</h1>
            <div className="aal-header-subtitle">
              {isAccountScoped
                ? `Viewing administrative activity for ${scopedAccountEmail}`
                : 'Track all administrative actions on user accounts'}
            </div>
          </div>
          <div className="header-actions activity-logs-header-actions">
            <ActionButton
              icon={Filter}
              className={`activity-logs-header-action-button-filter ${showFilters ? 'is-active' : ''}`}
              onClick={() => setShowFilters(!showFilters)}
            >
              {showFilters ? 'Hide Filters' : 'Show Filters'}
            </ActionButton>
            <ActionButton
              icon={RefreshCw}
              className="activity-logs-header-action-button-refresh"
              onClick={fetchLogs}
              disabled={isLoading}
            >
              Refresh
            </ActionButton>
          </div>
        </div>

        {/* Filters Panel */}
        {showFilters && (
          <div className="filters-panel">
            <div className="filters-row">
              <div className="filter-group">
                <label className="filter-label">Action Type</label>
                <select
                  value={filters.action}
                  onChange={(e) => handleFilterChange('action', e.target.value)}
                  className="filter-select"
                >
                  <option value="">All Actions</option>
                  <option value="onboard">Onboard User</option>
                  <option value="activate">Activate User</option>
                  <option value="deactivate">Deactivate User</option>
                  <option value="update">Update User</option>
                </select>
              </div>
              
              
              <div className="filter-group">
                <label className="filter-label">Time Range</label>
                <select
                  value={filters.days}
                  onChange={(e) => handleFilterChange('days', e.target.value)}
                  className="filter-select"
                >
                  <option value="7">Last 7 days</option>
                  <option value="30">Last 30 days</option>
                  <option value="90">Last 90 days</option>
                  <option value="365">Last year</option>
                  <option value="">All time</option>
                </select>
              </div>
              
              <button className="clear-filters-btn" onClick={clearFilters}>
                Clear Filters
              </button>
            </div>
          </div>
        )}

        {/* Logs Table */}
        <div className="logs-table-container">
          {isLoading ? (
            <div className="loading-state">
              <RefreshCw size={32} className="spin" />
              <p>Loading activity logs...</p>
            </div>
          ) : error ? (
            <div className="error-state">
              <p>{error}</p>
              <button onClick={fetchLogs}>Try Again</button>
            </div>
          ) : logs.length === 0 ? (
            <div className="empty-state">
              <h3>No Activity Logs Found</h3>
              <p>No admin activity has been recorded yet, or no logs match your filters.</p>
            </div>
          ) : (
            <table className="logs-table">
              <thead>
                <tr>
                  <th>Date & Time</th>
                  <th>Performed By</th>
                  <th>Action Taken</th>
                  <th>Affected User</th>
                  <th>What Changed</th>
                  <th>IP Address</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id}>
                    <td className="timestamp-cell">
                      <span className="date-time">{formatDate(log.created_at)}</span>
                    </td>
                    <td className="admin-cell">
                      <div className="admin-info">
                        <span className="admin-name">{log.admin_name}</span>
                        <span className="admin-email">{log.admin_email}</span>
                      </div>
                    </td>
                    <td className="action-cell">
                      <span className={`action-label ${getActionClass(log.action)}`}>
                        {getActionLabel(log.action, log.action_display)}
                      </span>
                    </td>
                    <td className="target-cell">
                      <div className="target-info">
                        <span className="target-name">{log.target_user_name}</span>
                        <span className="target-email">{log.target_user_email}</span>
                      </div>
                    </td>
                    <td className="details-cell">
                      {formatDetails(log.details, log.action)}
                    </td>
                    <td className="ip-cell">
                      <span className="ip-address">{log.ip_address || '—'}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        {(totalCount > 0 || totalPages > 1) && (
          <div className="auditlogs-pagination-row">
            <div className="auditlogs-pagination-info">
              Showing <span style={{ fontWeight: 700 }}>{Math.min((currentPage - 1) * logsPerPage + 1, totalCount)}</span> to <span style={{ fontWeight: 700 }}>{Math.min(currentPage * logsPerPage, totalCount)}</span> of <span style={{ fontWeight: 700 }}>{totalCount}</span> activity logs
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <button
                className="auditlogs-pagination-btn"
                onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                disabled={currentPage === 1}
              >
                <span className="auditlogs-pagination-arrow">
                  <svg width="18" height="18" viewBox="0 0 18 18" stroke="currentColor" fill="none">
                    <path d="M12 3l-6 6 6 6" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </span>
              </button>

              <div className="auditlogs-pagination-info">
                Page {currentPage} of {Math.max(totalPages, 1)}
              </div>

              <button
                className="auditlogs-pagination-btn"
                onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                disabled={currentPage === totalPages || totalPages === 0}
              >
                <span className="auditlogs-pagination-arrow">
                  <svg width="18" height="18" viewBox="0 0 18 18" stroke="currentColor" fill="none">
                    <path d="M6 3l6 6-6 6" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </span>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default AdminActivityLogs;
