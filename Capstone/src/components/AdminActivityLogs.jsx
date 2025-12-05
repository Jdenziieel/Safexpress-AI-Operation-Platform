import React, { useState, useEffect } from 'react';
import { Clock, User, Filter, RefreshCw, ChevronLeft, ChevronRight, Activity, UserPlus, UserCheck, UserX, Edit, Search } from 'lucide-react';
import api from '../api';
import '../css/AdminActivityLogs.css';

const ActionIcon = ({ action }) => {
  const iconProps = { size: 18, strokeWidth: 2 };
  switch (action) {
    case 'onboard':
      return <UserPlus {...iconProps} className="action-icon action-icon-onboard" />;
    case 'activate':
      return <UserCheck {...iconProps} className="action-icon action-icon-activate" />;
    case 'deactivate':
      return <UserX {...iconProps} className="action-icon action-icon-deactivate" />;
    case 'update':
    case 'update_role':
    case 'update_name':
      return <Edit {...iconProps} className="action-icon action-icon-update" />;
    default:
      return <Activity {...iconProps} className="action-icon" />;
  }
};

const ActionBadge = ({ action, actionDisplay }) => {
  const getBadgeClass = () => {
    switch (action) {
      case 'onboard':
        return 'action-badge-onboard';
      case 'activate':
        return 'action-badge-activate';
      case 'deactivate':
        return 'action-badge-deactivate';
      case 'update':
      case 'update_role':
      case 'update_name':
        return 'action-badge-update';
      default:
        return 'action-badge-default';
    }
  };

  return (
    <span className={`action-badge ${getBadgeClass()}`}>
      {actionDisplay}
    </span>
  );
};

function AdminActivityLogs() {
  const [logs, setLogs] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showFilters, setShowFilters] = useState(false);
  
  // Pagination
  const [currentPage, setCurrentPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const logsPerPage = 15;
  
  // Filters
  const [filters, setFilters] = useState({
    action: '',
    adminEmail: '',
    targetEmail: '',
    days: '30'
  });

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
      
      const response = await api.get(`/api/admin/activity-logs/?${params.toString()}`);
      
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
    setFilters(prev => ({ ...prev, [field]: value }));
    setCurrentPage(1);
  };

  const clearFilters = () => {
    setFilters({
      action: '',
      adminEmail: '',
      targetEmail: '',
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

  const formatDetails = (details) => {
    if (!details) return null;
    
    const items = [];
    
    if (details.old_values && details.new_values) {
      // Update action with old and new values
      Object.keys(details.new_values).forEach(key => {
        const oldVal = details.old_values[key];
        const newVal = details.new_values[key];
        items.push(
          <span key={key} className="detail-change">
            <strong>{key}:</strong> {String(oldVal)} → {String(newVal)}
          </span>
        );
      });
    } else if (details.role) {
      items.push(<span key="role"><strong>Role:</strong> {details.role}</span>);
    } else if (details.previous_status && details.new_status) {
      items.push(
        <span key="status">
          <strong>Status:</strong> {details.previous_status} → {details.new_status}
        </span>
      );
    }
    
    return items.length > 0 ? (
      <div className="log-details">
        {items}
      </div>
    ) : null;
  };

  const totalPages = Math.ceil(totalCount / logsPerPage);

  return (
    <div className="activity-logs-page">
      <div className="activity-logs-container">
        {/* Header */}
        <div className="activity-logs-header">
          <div className="header-title-section">
            <Activity size={28} />
            <div>
              <h1 className="header-title">Admin Activity Logs</h1>
              <p className="header-subtitle">Track all administrative actions on user accounts</p>
            </div>
          </div>
          <div className="header-actions">
            <button 
              className="header-btn filter-btn"
              onClick={() => setShowFilters(!showFilters)}
            >
              <Filter size={18} />
              {showFilters ? 'Hide Filters' : 'Show Filters'}
            </button>
            <button 
              className="header-btn refresh-btn"
              onClick={fetchLogs}
              disabled={isLoading}
            >
              <RefreshCw size={18} className={isLoading ? 'spin' : ''} />
              Refresh
            </button>
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
                <label className="filter-label">Admin Email</label>
                <div className="filter-input-wrapper">
                  <Search size={16} className="filter-input-icon" />
                  <input
                    type="text"
                    value={filters.adminEmail}
                    onChange={(e) => handleFilterChange('adminEmail', e.target.value)}
                    placeholder="Search by admin..."
                    className="filter-input"
                  />
                </div>
              </div>
              
              <div className="filter-group">
                <label className="filter-label">Target User Email</label>
                <div className="filter-input-wrapper">
                  <Search size={16} className="filter-input-icon" />
                  <input
                    type="text"
                    value={filters.targetEmail}
                    onChange={(e) => handleFilterChange('targetEmail', e.target.value)}
                    placeholder="Search by target..."
                    className="filter-input"
                  />
                </div>
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

        {/* Stats Bar */}
        <div className="stats-bar">
          <span className="stats-text">
            Showing {logs.length} of {totalCount} activity logs
          </span>
        </div>

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
              <Activity size={48} />
              <h3>No Activity Logs Found</h3>
              <p>No admin activity has been recorded yet, or no logs match your filters.</p>
            </div>
          ) : (
            <table className="logs-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Admin</th>
                  <th>Action</th>
                  <th>Target User</th>
                  <th>Details</th>
                  <th>IP Address</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id}>
                    <td className="timestamp-cell">
                      <Clock size={14} />
                      <span>{formatDate(log.created_at)}</span>
                    </td>
                    <td className="admin-cell">
                      <User size={14} />
                      <div className="user-info">
                        <span className="user-name">{log.admin_name}</span>
                        <span className="user-email">{log.admin_email}</span>
                      </div>
                    </td>
                    <td className="action-cell">
                      <ActionIcon action={log.action} />
                      <ActionBadge action={log.action} actionDisplay={log.action_display} />
                    </td>
                    <td className="target-cell">
                      <div className="user-info">
                        <span className="user-name">{log.target_user_name}</span>
                        <span className="user-email">{log.target_user_email}</span>
                      </div>
                    </td>
                    <td className="details-cell">
                      {formatDetails(log.details)}
                    </td>
                    <td className="ip-cell">
                      <span className="ip-address">{log.ip_address || '-'}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="pagination">
            <button
              className="pagination-btn"
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              disabled={currentPage === 1}
            >
              <ChevronLeft size={18} />
              Previous
            </button>
            
            <div className="pagination-info">
              Page {currentPage} of {totalPages}
            </div>
            
            <button
              className="pagination-btn"
              onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages}
            >
              Next
              <ChevronRight size={18} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default AdminActivityLogs;
