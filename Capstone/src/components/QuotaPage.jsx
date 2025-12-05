import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Zap,
  Users,
  TrendingUp,
  AlertTriangle,
  RefreshCw,
  Search,
  ChevronUp,
  ChevronDown,
  DollarSign,
  Activity,
  Calendar,
  Shield,
  Edit3,
  Check,
  X,
  Lock,
  FileText,
  Clock,
  ChevronLeft,
  ChevronRight,
  UserX,
  UserCheck,
  Eye,
  EyeOff,
  Settings
} from 'lucide-react';
import { isAdmin as checkIsAdmin, getUserFromToken, isAuthenticated } from '../utils/tokenManager';
import '../css/QuotaPage.css';

const QUOTA_API_URL = 'http://localhost:8011';

// Tier configuration
const TIER_CONFIG = {
  free: { limit: 100000, color: '#6b7280', label: 'Free' },
  pro: { limit: 1000000, color: '#6366f1', label: 'Pro' },
  enterprise: { limit: 10000000, color: '#f59e0b', label: 'Enterprise' }
};

function QuotaPage() {
  const navigate = useNavigate();
  
  // State
  const [users, setUsers] = useState([]);
  const [summary, setSummary] = useState(null);
  const [logs, setLogs] = useState([]);
  const [logsTotal, setLogsTotal] = useState(0);
  const [logsPage, setLogsPage] = useState(1);
  const [logsPageSize] = useState(15);
  const [adminActions, setAdminActions] = useState([]);
  const [adminActionsTotal, setAdminActionsTotal] = useState(0);
  const [adminActionsPage, setAdminActionsPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [sortConfig, setSortConfig] = useState({ key: 'current_usage', direction: 'desc' });
  const [editingUser, setEditingUser] = useState(null);
  const [editingField, setEditingField] = useState(null); // 'tier', 'limit', 'reset_date'
  const [newTier, setNewTier] = useState('');
  const [newLimit, setNewLimit] = useState('');
  const [newResetDate, setNewResetDate] = useState('');
  const [savingTier, setSavingTier] = useState(false);
  const [savingLimit, setSavingLimit] = useState(false);
  const [savingResetDate, setSavingResetDate] = useState(false);
  const [isAdmin, setIsAdmin] = useState(null);
  const [activeTab, setActiveTab] = useState('users'); // 'users', 'logs', or 'actions'
  const [logServiceFilter, setLogServiceFilter] = useState('');
  const [logSearchTerm, setLogSearchTerm] = useState('');
  const [logSortConfig, setLogSortConfig] = useState({ key: 'timestamp', direction: 'desc' });
  const [showInactive, setShowInactive] = useState(false);
  const [processingUser, setProcessingUser] = useState(null);

  // Get auth token for API calls
  const getAuthHeaders = () => {
    const token = localStorage.getItem('access');
    if (token) {
      return { 
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}` 
      };
    }
    return { 'Content-Type': 'application/json' };
  };

  // Fetch all users (admin only)
  const fetchAllUsers = async () => {
    try {
      const params = new URLSearchParams();
      if (showInactive) {
        params.append('include_inactive', 'true');
      }
      const response = await fetch(`${QUOTA_API_URL}/quota/admin/users?${params}`);
      if (!response.ok) throw new Error('Failed to fetch users');
      const data = await response.json();
      // Calculate percentage_used for each user
      const usersWithPercentage = (data.users || []).map(user => ({
        ...user,
        percentage_used: user.monthly_limit > 0 
          ? (user.current_usage / user.monthly_limit) * 100 
          : 0
      }));
      setUsers(usersWithPercentage);
    } catch (err) {
      console.error('Error fetching users:', err);
    }
  };

  // Fetch usage summary (admin only)
  const fetchSummary = async () => {
    try {
      const response = await fetch(`${QUOTA_API_URL}/quota/admin/summary?hours=720`);
      if (!response.ok) throw new Error('Failed to fetch summary');
      const data = await response.json();
      setSummary(data);
    } catch (err) {
      console.error('Error fetching summary:', err);
    }
  };

  // Fetch usage logs
  const fetchLogs = async (page = 1) => {
    console.log('Fetching logs, page:', page);
    try {
      const params = new URLSearchParams({
        page: page.toString(),
        page_size: logsPageSize.toString()
      });
      if (logServiceFilter) {
        params.append('service', logServiceFilter);
      }
      
      const response = await fetch(`${QUOTA_API_URL}/quota/admin/logs?${params}`);
      console.log('Logs response status:', response.status);
      if (!response.ok) throw new Error('Failed to fetch logs');
      const data = await response.json();
      console.log('Logs data:', data);
      setLogs(data.logs || []);
      setLogsTotal(data.total || 0);
      setLogsPage(page);
    } catch (err) {
      console.error('Error fetching logs:', err);
    }
  };

  // Fetch admin actions
  const fetchAdminActions = async (page = 1) => {
    console.log('Fetching admin actions, page:', page);
    try {
      const params = new URLSearchParams({
        page: page.toString(),
        page_size: '20'
      });
      
      const response = await fetch(`${QUOTA_API_URL}/quota/admin/actions?${params}`);
      console.log('Admin actions response status:', response.status);
      if (!response.ok) throw new Error('Failed to fetch admin actions');
      const data = await response.json();
      console.log('Admin actions data:', data);
      setAdminActions(data.logs || []);
      setAdminActionsTotal(data.total || 0);
      setAdminActionsPage(page);
    } catch (err) {
      console.error('Error fetching admin actions:', err);
    }
  };

  // Refresh all data
  const refreshData = async () => {
    setLoading(true);
    setError(null);
    try {
      await Promise.all([
        fetchAllUsers(),
        fetchSummary(),
        fetchLogs(logsPage),
        fetchAdminActions(adminActionsPage)
      ]);
    } catch (err) {
      setError('Failed to load data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!isAuthenticated()) {
      navigate('/login', { replace: true });
      return;
    }
    
    const adminStatus = checkIsAdmin();
    setIsAdmin(adminStatus);
    
    if (!adminStatus) {
      navigate('/dashboard', { replace: true });
    }
  }, [navigate]);

  useEffect(() => {
    if (isAdmin) {
      refreshData();
      const interval = setInterval(refreshData, 60000);
      return () => clearInterval(interval);
    }
  }, [isAdmin]);

  useEffect(() => {
    if (isAdmin) {
      fetchLogs(1);
    }
  }, [logServiceFilter]);

  // Refetch users when showInactive toggle changes
  useEffect(() => {
    if (isAdmin) {
      fetchAllUsers();
    }
  }, [showInactive]);

  // Update user tier
  const handleUpdateTier = async (userId) => {
    if (!newTier) return;
    
    setSavingTier(true);
    try {
      const response = await fetch(`${QUOTA_API_URL}/quota/admin/user/${userId}`, {
        method: 'PUT',
        headers: getAuthHeaders(),
        body: JSON.stringify({ tier: newTier })
      });
      
      if (response.status === 403) {
        setError('Admin access required to modify user tiers');
        return;
      }
      
      if (!response.ok) throw new Error('Failed to update tier');
      
      // Update local state immediately
      setUsers(prevUsers => 
        prevUsers.map(user => 
          user.user_id === userId 
            ? { 
                ...user, 
                tier: newTier, 
                monthly_limit: TIER_CONFIG[newTier]?.limit || user.monthly_limit 
              }
            : user
        )
      );
      
      setEditingUser(null);
      setEditingField(null);
      setNewTier('');
    } catch (err) {
      console.error('Error updating tier:', err);
      setError('Failed to update user tier');
    } finally {
      setSavingTier(false);
    }
  };

  // Update user monthly limit
  const handleUpdateLimit = async (userId) => {
    const limitValue = parseInt(newLimit, 10);
    if (isNaN(limitValue) || limitValue < 0) {
      setError('Please enter a valid positive number for monthly limit');
      return;
    }
    
    setSavingLimit(true);
    try {
      const response = await fetch(`${QUOTA_API_URL}/quota/admin/user/${userId}`, {
        method: 'PUT',
        headers: getAuthHeaders(),
        body: JSON.stringify({ monthly_limit: limitValue })
      });
      
      if (response.status === 403) {
        setError('Admin access required to modify user limits');
        return;
      }
      
      if (!response.ok) throw new Error('Failed to update monthly limit');
      
      // Update local state immediately
      setUsers(prevUsers => 
        prevUsers.map(user => 
          user.user_id === userId 
            ? { 
                ...user, 
                monthly_limit: limitValue,
                percentage_used: limitValue > 0 ? (user.current_usage / limitValue) * 100 : 0
              }
            : user
        )
      );
      
      setEditingUser(null);
      setEditingField(null);
      setNewLimit('');
    } catch (err) {
      console.error('Error updating monthly limit:', err);
      setError('Failed to update monthly limit');
    } finally {
      setSavingLimit(false);
    }
  };

  // Update user reset date
  const handleUpdateResetDate = async (userId) => {
    if (!newResetDate) {
      setError('Please select a valid reset date');
      return;
    }
    
    setSavingResetDate(true);
    try {
      const response = await fetch(`${QUOTA_API_URL}/quota/admin/user/${userId}`, {
        method: 'PUT',
        headers: getAuthHeaders(),
        body: JSON.stringify({ reset_date: newResetDate })
      });
      
      if (response.status === 403) {
        setError('Admin access required to modify reset date');
        return;
      }
      
      if (!response.ok) throw new Error('Failed to update reset date');
      
      // Update local state immediately
      setUsers(prevUsers => 
        prevUsers.map(user => 
          user.user_id === userId 
            ? { ...user, reset_date: newResetDate }
            : user
        )
      );
      
      setEditingUser(null);
      setEditingField(null);
      setNewResetDate('');
    } catch (err) {
      console.error('Error updating reset date:', err);
      setError('Failed to update reset date');
    } finally {
      setSavingResetDate(false);
    }
  };

  // Cancel editing
  const handleCancelEdit = () => {
    setEditingUser(null);
    setEditingField(null);
    setNewTier('');
    setNewLimit('');
    setNewResetDate('');
  };

  // Deactivate user
  const handleDeactivateUser = async (userId, userName) => {
    if (!confirm(`Are you sure you want to deactivate ${userName || userId}? Their quota will be soft-deleted.`)) {
      return;
    }
    
    setProcessingUser(userId);
    try {
      const response = await fetch(`${QUOTA_API_URL}/quota/admin/user/${userId}/deactivate`, {
        method: 'POST',
        headers: getAuthHeaders()
      });
      
      if (!response.ok) throw new Error('Failed to deactivate user');
      
      // Update local state
      setUsers(prevUsers => 
        prevUsers.map(user => 
          user.user_id === userId 
            ? { ...user, is_active: false, deactivated_at: new Date().toISOString() }
            : user
        )
      );
    } catch (err) {
      console.error('Error deactivating user:', err);
      setError('Failed to deactivate user');
    } finally {
      setProcessingUser(null);
    }
  };

  // Restore user
  const handleRestoreUser = async (userId, userName) => {
    setProcessingUser(userId);
    try {
      const response = await fetch(`${QUOTA_API_URL}/quota/admin/user/${userId}/restore`, {
        method: 'POST',
        headers: getAuthHeaders()
      });
      
      if (!response.ok) throw new Error('Failed to restore user');
      
      // Update local state
      setUsers(prevUsers => 
        prevUsers.map(user => 
          user.user_id === userId 
            ? { ...user, is_active: true, deactivated_at: null }
            : user
        )
      );
    } catch (err) {
      console.error('Error restoring user:', err);
      setError('Failed to restore user');
    } finally {
      setProcessingUser(null);
    }
  };

  // Start editing
  const handleStartEdit = (user, field = 'tier') => {
    setEditingUser(user.user_id);
    setEditingField(field);
    if (field === 'tier') {
      setNewTier(user.tier);
    } else if (field === 'limit') {
      setNewLimit(user.monthly_limit?.toString() || '0');
    } else if (field === 'reset_date') {
      // Format date for input[type="date"]
      const resetDate = user.reset_date ? new Date(user.reset_date).toISOString().split('T')[0] : '';
      setNewResetDate(resetDate);
    }
  };

  // Handle log sort
  const handleLogSort = (key) => {
    setLogSortConfig(prev => ({
      key,
      direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc'
    }));
  };

  // Filter and sort logs
  const filteredAndSortedLogs = [...logs]
    .filter(log => {
      if (!logSearchTerm) return true;
      const search = logSearchTerm.toLowerCase();
      return (
        (log.fullname && log.fullname.toLowerCase().includes(search)) ||
        (log.user_id && log.user_id.toLowerCase().includes(search)) ||
        (log.service && log.service.toLowerCase().includes(search)) ||
        (log.operation && log.operation.toLowerCase().includes(search)) ||
        (log.model && log.model.toLowerCase().includes(search))
      );
    })
    .sort((a, b) => {
      let aVal = a[logSortConfig.key];
      let bVal = b[logSortConfig.key];
      
      if (logSortConfig.key === 'timestamp') {
        aVal = new Date(aVal || 0).getTime();
        bVal = new Date(bVal || 0).getTime();
      } else if (logSortConfig.key === 'total_tokens' || logSortConfig.key === 'cost_usd') {
        aVal = aVal || 0;
        bVal = bVal || 0;
      } else {
        if (aVal === null || aVal === undefined) aVal = '';
        if (bVal === null || bVal === undefined) bVal = '';
        if (typeof aVal === 'string') {
          aVal = aVal.toLowerCase();
          bVal = bVal.toLowerCase();
        }
      }
      
      if (aVal < bVal) return logSortConfig.direction === 'asc' ? -1 : 1;
      if (aVal > bVal) return logSortConfig.direction === 'asc' ? 1 : -1;
      return 0;
    });
  
  // Debug: log filtered results
  console.log('Logs state:', logs.length, 'Filtered logs:', filteredAndSortedLogs.length);

  // Format numbers
  const formatNumber = (num) => {
    if (num === null || num === undefined) return '0';
    if (num >= 1000000) return `${(num / 1000000).toFixed(2)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toLocaleString();
  };

  // Get status color
  const getStatusColor = (percentage) => {
    if (percentage >= 90) return 'critical';
    if (percentage >= 75) return 'warning';
    return 'healthy';
  };

  // Format timestamp
  const formatTimestamp = (timestamp) => {
    if (!timestamp) return 'N/A';
    const date = new Date(timestamp);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
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

  // Format reset date
  const formatResetDate = (dateStr) => {
    if (!dateStr) return 'N/A';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  // Sort users
  const sortedUsers = [...users]
    .filter(user => 
      user.user_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (user.fullname && user.fullname.toLowerCase().includes(searchTerm.toLowerCase())) ||
      user.tier.toLowerCase().includes(searchTerm.toLowerCase())
    )
    .sort((a, b) => {
      let aVal = a[sortConfig.key];
      let bVal = b[sortConfig.key];
      
      if (aVal === null || aVal === undefined) aVal = '';
      if (bVal === null || bVal === undefined) bVal = '';
      
      if (typeof aVal === 'string') {
        aVal = aVal.toLowerCase();
        bVal = bVal.toLowerCase();
      }
      
      if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1;
      return 0;
    });

  // Handle sort
  const handleSort = (key) => {
    setSortConfig(prev => ({
      key,
      direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc'
    }));
  };

  // Pagination
  const totalPages = Math.ceil(logsTotal / logsPageSize);

  if (loading && users.length === 0) {
    return (
      <div className="quota-page">
        <div className="quota-loading">
          <RefreshCw size={32} className="loading-spinner" />
          <span>Loading token management data...</span>
        </div>
      </div>
    );
  }

  if (isAdmin === null) {
    return (
      <div className="quota-page">
        <div className="quota-loading">
          <RefreshCw size={32} className="loading-spinner" />
          <span>Checking access...</span>
        </div>
      </div>
    );
  }

  if (isAdmin === false) {
    return (
      <div className="quota-page">
        <div className="quota-access-denied">
          <Lock size={48} className="access-denied-icon" />
          <h2>Access Denied</h2>
          <p>This page is restricted to administrators only.</p>
          <button className="back-btn" onClick={() => navigate('/dashboard')}>
            Return to Dashboard
          </button>
        </div>
      </div>
    );
  }

  // Get unique services from logs for filter dropdown
  const uniqueServices = [...new Set(logs.map(log => log.service).filter(Boolean))];

  return (
    <div className="quota-page">
      <div className="quota-container">
        {/* Header */}
        <div className="quota-header">
          <div className="quota-header-left">
            <h1 className="quota-title">
              <Zap size={28} className="title-icon" />
              Token Management
            </h1>
            <p className="quota-subtitle">Monitor and manage AI token usage across the platform</p>
          </div>
          <button className="refresh-btn" onClick={refreshData} disabled={loading}>
            <RefreshCw size={18} className={loading ? 'spinning' : ''} />
            Refresh
          </button>
        </div>

        {error && (
          <div className="quota-error-banner">
            <AlertTriangle size={18} />
            <span>{error}</span>
            <button onClick={() => setError(null)}>
              <X size={16} />
            </button>
          </div>
        )}

        {/* Summary Cards */}
        {summary && (
          <div className="summary-section">
            <h2 className="section-title">
              <Shield size={20} className="admin-icon" />
              Platform Overview (Last 30 Days)
            </h2>
            <div className="summary-cards">
              <div className="summary-card">
                <div className="summary-icon users">
                  <Users size={24} />
                </div>
                <div className="summary-content">
                  <span className="summary-value">{summary.total_users || 0}</span>
                  <span className="summary-label">Active Users</span>
                </div>
              </div>

              <div className="summary-card">
                <div className="summary-icon tokens">
                  <Zap size={24} />
                </div>
                <div className="summary-content">
                  <span className="summary-value">{formatNumber(summary.total_tokens)}</span>
                  <span className="summary-label">Tokens Used</span>
                </div>
              </div>

              <div className="summary-card">
                <div className="summary-icon cost">
                  <DollarSign size={24} />
                </div>
                <div className="summary-content">
                  <span className="summary-value">${(summary.total_cost_usd || 0).toFixed(2)}</span>
                  <span className="summary-label">Total Cost</span>
                </div>
              </div>

              <div className="summary-card">
                <div className="summary-icon operations">
                  <Activity size={24} />
                </div>
                <div className="summary-content">
                  <span className="summary-value">{summary.total_operations || 0}</span>
                  <span className="summary-label">Operations</span>
                </div>
              </div>
            </div>

            {/* Service Breakdown */}
            {summary.by_service && summary.by_service.length > 0 && (
              <div className="service-breakdown">
                <h3 className="subsection-title">Usage by Service</h3>
                <div className="service-cards">
                  {summary.by_service.map((service, idx) => (
                    <div key={idx} className="service-card">
                      <div className="service-header">
                        <span className="service-name">{service.service}</span>
                        <span className="service-calls">{service.call_count} calls</span>
                      </div>
                      <div className="service-stats">
                        <span><Zap size={12} /> {formatNumber(service.total_tokens)}</span>
                        <span><DollarSign size={12} /> ${(service.total_cost_usd || 0).toFixed(4)}</span>
                      </div>
                      {service.models_used && (
                        <div className="service-models">
                          {service.models_used.map((model, i) => (
                            <span key={i} className="model-tag">{model}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Tier Distribution */}
            {summary.by_tier && (
              <div className="tier-distribution">
                <h3 className="subsection-title">Users by Tier</h3>
                <div className="tier-bars">
                  {Object.entries(summary.by_tier).map(([tier, count]) => (
                    <div key={tier} className="tier-bar-item">
                      <div className="tier-bar-label">
                        <span className={`tier-dot tier-${tier}`}></span>
                        <span className="tier-name">{tier}</span>
                        <span className="tier-count">{count}</span>
                      </div>
                      <div className="tier-bar-track">
                        <div 
                          className={`tier-bar-fill tier-${tier}`}
                          style={{ 
                            width: `${Math.max((count / (summary.total_users || 1)) * 100, 5)}%` 
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tab Navigation */}
        <div className="tab-navigation">
          <button 
            className={`tab-btn ${activeTab === 'users' ? 'active' : ''}`}
            onClick={() => setActiveTab('users')}
          >
            <Users size={18} />
            User Quotas
          </button>
          <button 
            className={`tab-btn ${activeTab === 'logs' ? 'active' : ''}`}
            onClick={() => {
              setActiveTab('logs');
              fetchLogs(1);
            }}
          >
            <FileText size={18} />
            Usage Logs
          </button>
          <button 
            className={`tab-btn ${activeTab === 'actions' ? 'active' : ''}`}
            onClick={() => {
              setActiveTab('actions');
              fetchAdminActions(1);
            }}
          >
            <Settings size={18} />
            Admin Actions
          </button>
        </div>

        {/* Users Table */}
        {activeTab === 'users' && users.length > 0 && (
          <div className="users-section">
            <div className="users-header">
              <h2 className="section-title">
                <Users size={20} />
                User Quotas ({users.length} users)
              </h2>
              <div className="users-controls">
                <button 
                  className={`toggle-inactive-btn ${showInactive ? 'active' : ''}`}
                  onClick={() => setShowInactive(!showInactive)}
                  title={showInactive ? 'Hide inactive users' : 'Show inactive users'}
                >
                  {showInactive ? <EyeOff size={16} /> : <Eye size={16} />}
                  {showInactive ? 'Hide Inactive' : 'Show Inactive'}
                </button>
                <div className="users-search">
                  <Search size={16} />
                  <input
                    type="text"
                    placeholder="Search users..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                  />
                </div>
              </div>
            </div>

            <div className="users-table-container">
              <table className="users-table">
                <thead>
                  <tr>
                    <th onClick={() => handleSort('user_id')}>
                      User
                      {sortConfig.key === 'user_id' && (
                        sortConfig.direction === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />
                      )}
                    </th>
                    <th onClick={() => handleSort('tier')}>
                      Tier
                      {sortConfig.key === 'tier' && (
                        sortConfig.direction === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />
                      )}
                    </th>
                    <th onClick={() => handleSort('current_usage')}>
                      Usage
                      {sortConfig.key === 'current_usage' && (
                        sortConfig.direction === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />
                      )}
                    </th>
                    <th>Progress</th>
                    <th onClick={() => handleSort('reset_date')}>
                      Reset
                      {sortConfig.key === 'reset_date' && (
                        sortConfig.direction === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />
                      )}
                    </th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedUsers.map((user) => {
                    const percentage = user.percentage_used || 0;
                    const status = getStatusColor(percentage);
                    const isInactive = user.is_active === false;
                    const isEditingThisUser = editingUser === user.user_id;
                    
                    return (
                      <tr key={user.user_id} className={`${status} ${isInactive ? 'inactive-row' : ''}`}>
                        <td className="user-cell">
                          <div className="user-info">
                            <span className="user-name" title={user.user_id}>
                              {user.fullname || (user.user_id.length > 12 ? `${user.user_id.slice(0, 8)}...` : user.user_id)}
                            </span>
                            {isInactive && <span className="inactive-badge">Inactive</span>}
                          </div>
                        </td>
                        <td>
                          {isEditingThisUser && editingField === 'tier' ? (
                            <div className="inline-edit">
                              <select
                                value={newTier}
                                onChange={(e) => setNewTier(e.target.value)}
                                className="tier-select"
                                autoFocus
                              >
                                <option value="free">Free</option>
                                <option value="pro">Pro</option>
                                <option value="enterprise">Enterprise</option>
                              </select>
                              <div className="inline-actions">
                                <button 
                                  className="action-btn save"
                                  onClick={() => handleUpdateTier(user.user_id)}
                                  disabled={savingTier || newTier === user.tier}
                                  title="Save"
                                >
                                  {savingTier ? <RefreshCw size={12} className="spinning" /> : <Check size={12} />}
                                </button>
                                <button 
                                  className="action-btn cancel"
                                  onClick={handleCancelEdit}
                                  title="Cancel"
                                >
                                  <X size={12} />
                                </button>
                              </div>
                            </div>
                          ) : (
                            <span 
                              className={`tier-badge tier-${user.tier} editable`}
                              onClick={() => !isInactive && handleStartEdit(user, 'tier')}
                              title={isInactive ? 'Inactive user' : 'Click to edit tier'}
                            >
                              {user.tier}
                            </span>
                          )}
                        </td>
                        <td>
                          {isEditingThisUser && editingField === 'limit' ? (
                            <div className="inline-edit">
                              <input
                                type="number"
                                value={newLimit}
                                onChange={(e) => setNewLimit(e.target.value)}
                                className="limit-input"
                                min="0"
                                autoFocus
                              />
                              <div className="inline-actions">
                                <button 
                                  className="action-btn save"
                                  onClick={() => handleUpdateLimit(user.user_id)}
                                  disabled={savingLimit}
                                  title="Save"
                                >
                                  {savingLimit ? <RefreshCw size={12} className="spinning" /> : <Check size={12} />}
                                </button>
                                <button 
                                  className="action-btn cancel"
                                  onClick={handleCancelEdit}
                                  title="Cancel"
                                >
                                  <X size={12} />
                                </button>
                              </div>
                            </div>
                          ) : (
                            <span 
                              className="usage-text editable"
                              onClick={() => !isInactive && handleStartEdit(user, 'limit')}
                              title={isInactive ? 'Inactive user' : 'Click to edit monthly limit'}
                            >
                              {formatNumber(user.current_usage)} / {formatNumber(user.monthly_limit)}
                            </span>
                          )}
                        </td>
                        <td>
                          <div 
                            className="table-progress-wrapper"
                            title={`${formatNumber(user.current_usage)} of ${formatNumber(user.monthly_limit)} tokens (${percentage.toFixed(1)}%)`}
                          >
                            <div className="table-progress-bar">
                              <div 
                                className={`table-progress-fill ${status}`}
                                style={{ width: `${Math.min(percentage, 100)}%` }}
                              />
                            </div>
                          </div>
                        </td>
                        <td className="reset-cell">
                          {isEditingThisUser && editingField === 'reset_date' ? (
                            <div className="inline-edit">
                              <input
                                type="date"
                                value={newResetDate}
                                onChange={(e) => setNewResetDate(e.target.value)}
                                className="date-input"
                                autoFocus
                              />
                              <div className="inline-actions">
                                <button 
                                  className="action-btn save"
                                  onClick={() => handleUpdateResetDate(user.user_id)}
                                  disabled={savingResetDate}
                                  title="Save"
                                >
                                  {savingResetDate ? <RefreshCw size={12} className="spinning" /> : <Check size={12} />}
                                </button>
                                <button 
                                  className="action-btn cancel"
                                  onClick={handleCancelEdit}
                                  title="Cancel"
                                >
                                  <X size={12} />
                                </button>
                              </div>
                            </div>
                          ) : (
                            <span 
                              className="reset-info editable" 
                              title={`Resets on ${formatResetDate(user.reset_date)} - Click to edit`}
                              onClick={() => !isInactive && handleStartEdit(user, 'reset_date')}
                            >
                              {getDaysUntilReset(user.reset_date) !== null 
                                ? `${getDaysUntilReset(user.reset_date)}d` 
                                : 'N/A'}
                            </span>
                          )}
                        </td>
                        <td className="actions-cell">
                          <div className="action-buttons">
                            {isInactive ? (
                              <button 
                                className="action-btn restore"
                                onClick={() => handleRestoreUser(user.user_id, user.fullname || user.user_id)}
                                title="Restore user"
                                disabled={processingUser === user.user_id}
                              >
                                {processingUser === user.user_id ? (
                                  <RefreshCw size={14} className="spinning" />
                                ) : (
                                  <UserCheck size={14} />
                                )}
                              </button>
                            ) : (
                              <button 
                                className="action-btn deactivate"
                                onClick={() => handleDeactivateUser(user.user_id, user.fullname || user.user_id)}
                                title="Deactivate user"
                                disabled={processingUser === user.user_id}
                              >
                                {processingUser === user.user_id ? (
                                  <RefreshCw size={14} className="spinning" />
                                ) : (
                                  <UserX size={14} />
                                )}
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Usage Logs */}
        {activeTab === 'logs' && (
          <div className="logs-section">
            <div className="logs-header">
              <h2 className="section-title">
                <FileText size={20} />
                Usage Logs ({logsTotal} entries)
              </h2>
              <div className="logs-filters">
                <div className="logs-search">
                  <Search size={16} />
                  <input
                    type="text"
                    placeholder="Search logs by user, service, operation..."
                    value={logSearchTerm}
                    onChange={(e) => setLogSearchTerm(e.target.value)}
                  />
                </div>
                <select 
                  value={logServiceFilter}
                  onChange={(e) => setLogServiceFilter(e.target.value)}
                  className="service-filter"
                >
                  <option value="">All Services</option>
                  {uniqueServices.map(service => (
                    <option key={service} value={service}>{service}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="logs-table-container">
              <table className="logs-table">
                <thead>
                  <tr>
                    <th onClick={() => handleLogSort('timestamp')} className="sortable-header">
                      <Clock size={14} /> Time
                      {logSortConfig.key === 'timestamp' && (
                        logSortConfig.direction === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />
                      )}
                    </th>
                    <th onClick={() => handleLogSort('fullname')} className="sortable-header">
                      User
                      {logSortConfig.key === 'fullname' && (
                        logSortConfig.direction === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />
                      )}
                    </th>
                    <th onClick={() => handleLogSort('service')} className="sortable-header">
                      Service
                      {logSortConfig.key === 'service' && (
                        logSortConfig.direction === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />
                      )}
                    </th>
                    <th onClick={() => handleLogSort('operation')} className="sortable-header">
                      Operation
                      {logSortConfig.key === 'operation' && (
                        logSortConfig.direction === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />
                      )}
                    </th>
                    <th>Model</th>
                    <th onClick={() => handleLogSort('total_tokens')} className="sortable-header">
                      Tokens
                      {logSortConfig.key === 'total_tokens' && (
                        logSortConfig.direction === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />
                      )}
                    </th>
                    <th onClick={() => handleLogSort('cost_usd')} className="sortable-header">
                      Cost
                      {logSortConfig.key === 'cost_usd' && (
                        logSortConfig.direction === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />
                      )}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {/* Debug info */}
                  <tr><td colSpan="7" style={{background: '#fef3c7', color: '#92400e', fontWeight: 'bold'}}>
                    DEBUG: logs={logs.length}, filtered={filteredAndSortedLogs.length}
                  </td></tr>
                  {filteredAndSortedLogs.length === 0 ? (
                    <tr>
                      <td colSpan="7" className="no-logs">
                        No usage logs found
                      </td>
                    </tr>
                  ) : (
                    filteredAndSortedLogs.map((log) => (
                      <tr key={log.id}>
                        <td className="timestamp-cell">
                          {formatTimestamp(log.timestamp)}
                        </td>
                        <td className="user-cell" title={log.user_id}>
                          {log.fullname || (log.user_id && log.user_id.length > 12 ? `${log.user_id.slice(0, 8)}...` : log.user_id)}
                        </td>
                        <td>
                          <span className="service-tag">{log.service}</span>
                        </td>
                        <td className="operation-cell">
                          {log.operation}
                        </td>
                        <td>
                          <span className="model-tag">{log.model}</span>
                        </td>
                        <td className="tokens-cell">
                          <div className="tokens-breakdown">
                            <span className="total-tokens">{formatNumber(log.total_tokens)}</span>
                            <span className="token-detail">
                              ({formatNumber(log.input_tokens)} in / {formatNumber(log.output_tokens)} out)
                            </span>
                          </div>
                        </td>
                        <td className="cost-cell">
                          ${(log.cost_usd || 0).toFixed(4)}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="logs-pagination">
                <button 
                  className="pagination-btn"
                  onClick={() => fetchLogs(logsPage - 1)}
                  disabled={logsPage <= 1}
                >
                  <ChevronLeft size={16} />
                  Previous
                </button>
                <span className="pagination-info">
                  Page {logsPage} of {totalPages}
                </span>
                <button 
                  className="pagination-btn"
                  onClick={() => fetchLogs(logsPage + 1)}
                  disabled={logsPage >= totalPages}
                >
                  Next
                  <ChevronRight size={16} />
                </button>
              </div>
            )}
          </div>
        )}

        {/* Admin Actions Log */}
        {activeTab === 'actions' && (
          <div className="actions-section">
            <div className="actions-header">
              <h2 className="section-title">
                <Settings size={20} />
                Admin Actions ({adminActionsTotal} entries)
              </h2>
            </div>

            <div className="actions-table-container">
              <table className="actions-table">
                <thead>
                  <tr>
                    <th><Clock size={14} /> Time</th>
                    <th>Admin</th>
                    <th>Action</th>
                    <th>Target User</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {adminActions.length === 0 ? (
                    <tr>
                      <td colSpan="5" className="no-logs">
                        No admin actions recorded yet
                      </td>
                    </tr>
                  ) : (
                    adminActions.map((action) => (
                      <tr key={action.id}>
                        <td className="timestamp-cell">
                          {formatTimestamp(action.timestamp)}
                        </td>
                        <td className="admin-cell">
                          {action.admin_name || action.admin_id || 'System'}
                        </td>
                        <td>
                          <span className={`action-tag action-${action.action}`}>
                            {action.action.replace(/_/g, ' ')}
                          </span>
                        </td>
                        <td className="user-cell">
                          {action.target_user_name || action.target_user_id || '-'}
                        </td>
                        <td className="details-cell">
                          {action.details ? (
                            <span className="details-preview" title={JSON.stringify(action.details, null, 2)}>
                              {Object.entries(action.details).map(([key, val]) => (
                                <span key={key} className="detail-item">
                                  {key}: {typeof val === 'object' ? `${val.from} → ${val.to}` : val}
                                </span>
                              ))}
                            </span>
                          ) : '-'}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {Math.ceil(adminActionsTotal / 20) > 1 && (
              <div className="logs-pagination">
                <button 
                  className="pagination-btn"
                  onClick={() => fetchAdminActions(adminActionsPage - 1)}
                  disabled={adminActionsPage <= 1}
                >
                  <ChevronLeft size={16} />
                  Previous
                </button>
                <span className="pagination-info">
                  Page {adminActionsPage} of {Math.ceil(adminActionsTotal / 20)}
                </span>
                <button 
                  className="pagination-btn"
                  onClick={() => fetchAdminActions(adminActionsPage + 1)}
                  disabled={adminActionsPage >= Math.ceil(adminActionsTotal / 20)}
                >
                  Next
                  <ChevronRight size={16} />
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default QuotaPage;
