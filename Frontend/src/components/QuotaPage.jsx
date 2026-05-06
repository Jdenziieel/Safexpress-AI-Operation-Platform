import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Users, UserX, Search, Filter, Edit2, Trash2, RotateCcw, RefreshCw,
  Activity, X, TrendingUp, AlertCircle, AlertTriangle, Clock, BarChart3,
  Bot, DollarSign, Save
} from 'lucide-react';
import { isAdmin as checkIsAdmin, getUserFromToken, getUserUUID, isAuthenticated } from '../utils/tokenManager';
import { quotaApi, supervisorApi } from '../api';
import { dispatchQuotaRefresh } from '../hooks/useWebSocketQuota';
import '../css/QuotaPage.css';

const ActionButton = ({ icon: Icon, children, className = '', ...props }) => (
  <div style={{ position: 'relative', display: 'inline-block' }}>
    <button className={`main-card-btn ${className}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '12px', fontSize: '1.15rem', fontWeight: 800 }} {...props}>
      <Icon size={20} />
    </button>
    <span style={{ 
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
    }} className="button-tooltip">{children}</span>
  </div>
);

// Tier configuration
const TIER_CONFIG = {
  free: { limit: 100000, color: '#6b7280', label: 'Free' },
  pro: { limit: 1000000, color: '#6366f1', label: 'Pro' },
  enterprise: { limit: 10000000, color: '#f59e0b', label: 'Enterprise' }
};

// Compact USD formatter shared by the budget section. Mirrors what
// LogsPage.formatCost does so the two pages render identical values
// when an admin compares them. Prefer 4 decimal places for sub-$1
// values (matches Token & Cost cells on the Admin Dashboard) and
// fall back to "$0.00" for null/NaN so the UI never shows "undefined".
const formatBudgetCost = (value) => {
  const num = Number(value);
  if (!Number.isFinite(num)) return '$0.00';
  return `$${num.toFixed(4)}`;
};

// =============================================================================
// MONTHLY BUDGET — section component
// =============================================================================
//
// Self-contained section with its own banner + editor. Mounted near the
// top of the Token Management page (above User Quotas) so admins find
// it before scrolling through the user table. Saving here is the ONLY
// path that produces an "update_budget" row in the Admin Actions panel
// below; the corresponding control on the Admin Dashboard (LogsPage)
// was removed at the same time to avoid two-source-of-truth drift.
//
// Visual states (in priority order):
//   1. budgetError       → red banner, replaces success indicator
//   2. budget.over_budget → critical banner (>=100% spend)
//   3. budget.alert_triggered → warning banner (>=alert_threshold_pct)
//   4. budgetSavedAt set  → green "Saved" pill (auto-fades on next render)
const BudgetSection = ({
  budgetData,
  budgetInput, setBudgetInput,
  thresholdInput, setThresholdInput,
  savingBudget, budgetError, budgetSavedAt, onSave,
}) => {
  const overBudget = !!budgetData?.over_budget;
  const alertTriggered = !!budgetData?.alert_triggered;
  const showSaved = !!budgetSavedAt && !budgetError && (Date.now() - budgetSavedAt < 4000);

  return (
    <div className="users-section budget-card-section" style={{ marginBottom: 24 }}>
      <div className="users-header" style={{ alignItems: 'flex-start' }}>
        <div>
          <h2 className="section-title">
            <DollarSign size={20} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            Monthly Budget &amp; Alerts
          </h2>
          <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: '0.95rem' }}>
            Set the platform-wide spend ceiling for the current month and the
            percent at which an email alert is sent. Saved changes are recorded
            in the Admin Actions panel below.
          </p>
        </div>
      </div>

      {/* Status banner — same color semantics as the Admin Dashboard
          BudgetBanner so admins recognise the state at a glance. */}
      {overBudget && (
        <div className="quota-error-banner" style={{ background: '#fef2f2', borderColor: '#fecaca', color: '#991b1b', marginTop: 12 }}>
          <AlertCircle size={18} style={{ marginRight: 6, verticalAlign: 'middle' }} />
          <span>
            Over budget — spent {formatBudgetCost(budgetData?.current_month_cost_usd)}
            {' of '}
            {formatBudgetCost(budgetData?.monthly_budget_usd)}
            {' ('}{budgetData?.pct_used ?? 0}%)
          </span>
        </div>
      )}
      {!overBudget && alertTriggered && (
        <div className="quota-error-banner" style={{ background: '#fffbeb', borderColor: '#fde68a', color: '#92400e', marginTop: 12 }}>
          <AlertTriangle size={18} style={{ marginRight: 6, verticalAlign: 'middle' }} />
          <span>
            Budget warning — {budgetData?.pct_used ?? 0}% used
            {' ('}{formatBudgetCost(budgetData?.current_month_cost_usd)}
            {' of '}{formatBudgetCost(budgetData?.monthly_budget_usd)})
          </span>
        </div>
      )}
      {budgetError && (
        <div className="quota-error-banner" style={{ marginTop: 12 }}>
          <AlertCircle size={18} style={{ marginRight: 6, verticalAlign: 'middle' }} />
          <span>{budgetError}</span>
        </div>
      )}

      {/* Editor — laid out horizontally on wide screens, wraps on narrow.
          Inline styles keep this self-contained without touching
          QuotaPage.css; if a future redesign needs richer styles we can
          extract `.budget-controls` into the stylesheet then. */}
      <div
        style={{
          display: 'flex',
          gap: 16,
          alignItems: 'flex-end',
          flexWrap: 'wrap',
          padding: 20,
          background: '#f8fafc',
          border: '1px solid #e2e8f0',
          borderRadius: 8,
          marginTop: 16,
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 180 }}>
          <label style={{ fontSize: '0.85rem', color: '#475569', fontWeight: 600 }}>
            Monthly Budget (USD)
          </label>
          <input
            type="number"
            min="0"
            step="0.01"
            value={budgetInput}
            onChange={(e) => setBudgetInput(e.target.value)}
            placeholder="e.g. 50.00"
            style={{
              padding: '10px 12px',
              border: '1px solid #cbd5e1',
              borderRadius: 6,
              fontSize: '0.95rem',
            }}
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 180 }}>
          <label style={{ fontSize: '0.85rem', color: '#475569', fontWeight: 600 }}>
            Alert Threshold (%)
          </label>
          <input
            type="number"
            min="0"
            max="100"
            step="1"
            value={thresholdInput}
            onChange={(e) => setThresholdInput(e.target.value)}
            placeholder="80"
            style={{
              padding: '10px 12px',
              border: '1px solid #cbd5e1',
              borderRadius: 6,
              fontSize: '0.95rem',
            }}
          />
        </div>
        <button
          onClick={onSave}
          disabled={savingBudget}
          style={{
            padding: '10px 18px',
            background: savingBudget ? '#94a3b8' : '#26326e',
            color: 'white',
            border: 'none',
            borderRadius: 6,
            fontSize: '0.95rem',
            fontWeight: 600,
            cursor: savingBudget ? 'not-allowed' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <Save size={16} />
          {savingBudget ? 'Saving...' : 'Save Budget'}
        </button>
        {showSaved && (
          <span
            style={{
              padding: '6px 12px',
              background: '#dcfce7',
              color: '#166534',
              borderRadius: 999,
              fontSize: '0.85rem',
              fontWeight: 600,
            }}
          >
            Saved — see Admin Actions below
          </span>
        )}
        <div
          style={{
            marginLeft: 'auto',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'flex-end',
            gap: 4,
            minWidth: 180,
          }}
        >
          <span style={{ fontSize: '0.8rem', color: '#64748b', fontWeight: 600, textTransform: 'uppercase' }}>
            Current Month Spend
          </span>
          <span style={{ fontSize: '1.5rem', color: '#0f172a', fontWeight: 700 }}>
            {formatBudgetCost(budgetData?.current_month_cost_usd)}
          </span>
        </div>
      </div>
    </div>
  );
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
  const [logServiceFilter, setLogServiceFilter] = useState('');
  const [logSearchTerm, setLogSearchTerm] = useState('');
  const [logSortConfig, setLogSortConfig] = useState({ key: 'timestamp', direction: 'desc' });
  const [showInactive, setShowInactive] = useState(false);
  const [processingUser, setProcessingUser] = useState(null);
  const [showFilters, setShowFilters] = useState(false);
  const [showLogFilters, setShowLogFilters] = useState(false);
  const [showAdminFilters, setShowAdminFilters] = useState(false);
  const [tierFilter, setTierFilter] = useState('all');
  // Client-side pagination for the User Quotas table. The backend
  // (lambda_admin_list_users) already paginates the DynamoDB scan
  // up to 1000 items in a single response, so we already have all
  // rows in memory — no need to round-trip per page. We slice the
  // already-filtered+sorted `sortedUsers` list locally.
  const [usersPage, setUsersPage] = useState(1);
  const [usersPageSize, setUsersPageSize] = useState(10);
  const [showEditModal, setShowEditModal] = useState(false);
  const [selectedUser, setSelectedUser] = useState(null);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [userToDeactivate, setUserToDeactivate] = useState(null);
  const [adminSearchTerm, setAdminSearchTerm] = useState('');
  // Per-user history modal: opened from the row Action column. We keep
  // the target as a small `{user_id, fullname}` object instead of
  // resolving the full user row, because the modal fetches its own
  // canonical data from /api/quota/me/history?user_id=<target> and we
  // only need the identifier + a display label until that returns.
  const [historyTarget, setHistoryTarget] = useState(null);
  // Platform-level top users + per-day series. Both flow off the same
  // refresh cycle as the rest of Token Management, so they share the
  // global `loading` flag.
  const [topUsers, setTopUsers] = useState([]);
  // Window for both Top-N + daily area chart. Hours instead of days
  // because the existing `/admin/summary` and `/admin/top-users`
  // endpoints take an `hours` query param. 720h = 30d default.
  const [platformWindowHours, setPlatformWindowHours] = useState(720);

  // Monthly Budget — moved here from LogsPage (Admin Dashboard) per
  // user request 2026-05-04. The same supervisor REST endpoint
  // (PUT /admin/settings/budget on the supervisor API gateway, NOT
  // quotaApi) backs both views, but Token Management is the canonical
  // home now: saving here writes an audit row to QuotaAdminActions
  // (via the budget-update Lambda) which the Admin Actions panel
  // below picks up on refetch.
  const [budgetData, setBudgetData] = useState(null);
  const [budgetInput, setBudgetInput] = useState('');
  const [thresholdInput, setThresholdInput] = useState('');
  const [savingBudget, setSavingBudget] = useState(false);
  const [budgetError, setBudgetError] = useState(null);
  const [budgetSavedAt, setBudgetSavedAt] = useState(null);

  // Fetch all users (admin only)
  const fetchAllUsers = async () => {
    try {
      const params = {};
      if (showInactive) {
        params.include_inactive = 'true';
      }
      const response = await quotaApi.get('/api/quota/admin/users', { params });
      const data = response.data;
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

  // Fetch usage summary (admin only). The `hours` window is shared
  // with the Top-N chart so both render the same period.
  const fetchSummary = async () => {
    try {
      const response = await quotaApi.get('/api/quota/admin/summary', {
        params: { hours: platformWindowHours }
      });
      setSummary(response.data);
    } catch (err) {
      console.error('Error fetching summary:', err);
    }
  };

  // Fetch top N users by token usage for the same window. Re-uses the
  // existing /admin/top-users endpoint (lambda_admin_top_users.py) so
  // no new backend wiring is required for the chart.
  const fetchTopUsers = async () => {
    try {
      const response = await quotaApi.get('/api/quota/admin/top-users', {
        params: { hours: platformWindowHours, limit: 10 }
      });
      setTopUsers(response.data?.top_users || []);
    } catch (err) {
      console.error('Error fetching top users:', err);
    }
  };

  // Fetch usage logs
  const fetchLogs = async (page = 1) => {
    try {
      const params = { page, page_size: logsPageSize };
      if (logServiceFilter) {
        params.service = logServiceFilter;
      }
      
      const response = await quotaApi.get('/api/quota/admin/logs', { params });
      const data = response.data;
      setLogs(data.logs || []);
      setLogsTotal(data.total || 0);
      setLogsPage(page);
    } catch (err) {
      console.error('Error fetching logs:', err);
    }
  };

  // Fetch admin actions
  const fetchAdminActions = async (page = 1) => {
    try {
      const params = { page, page_size: 10 };
      
      const response = await quotaApi.get('/api/quota/admin/actions', { params });
      const data = response.data;
      setAdminActions(data.logs || []);
      setAdminActionsTotal(data.total || 0);
      setAdminActionsPage(page);
    } catch (err) {
      console.error('Error fetching admin actions:', err);
    }
  };

  // Fetch monthly budget — lives on the supervisor REST API (not the
  // quota API gateway). Failure is non-fatal: the Token & Cost section
  // below degrades to "loading" state and admins can still edit other
  // pages.
  const fetchBudget = async () => {
    try {
      const res = await supervisorApi.get('/admin/settings/budget');
      setBudgetData(res.data);
    } catch (err) {
      console.error('Error fetching budget:', err.response?.status, err);
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
        fetchTopUsers(),
        fetchLogs(logsPage),
        fetchAdminActions(adminActionsPage),
        fetchBudget()
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

  // Sync editable budget inputs whenever the server-side budget
  // refreshes (initial fetch + post-save). Without this the two
  // <input>s stay empty even though budgetData has values, which
  // looks broken to admins.
  useEffect(() => {
    if (budgetData) {
      if (budgetData.monthly_budget_usd != null) {
        setBudgetInput(String(budgetData.monthly_budget_usd));
      }
      if (budgetData.alert_threshold_pct != null) {
        setThresholdInput(String(budgetData.alert_threshold_pct));
      }
    }
  }, [budgetData]);

  // Save budget (PUT) → refresh both budget snapshot AND Admin
  // Actions table so the audit row appears immediately. The Lambda
  // (supervisor-admin-budget-update) writes to BOTH Sup_Logs and
  // QuotaAdminActions — the latter is what the Admin Actions panel
  // below reads from.
  const handleSaveBudget = async () => {
    const body = {};
    const b = parseFloat(budgetInput);
    const t = parseFloat(thresholdInput);
    if (!isNaN(b)) body.monthly_budget_usd = b;
    if (!isNaN(t)) body.alert_threshold_pct = t;
    if (Object.keys(body).length === 0) {
      setBudgetError('Enter a budget or threshold value to save.');
      return;
    }
    setBudgetError(null);
    setSavingBudget(true);
    try {
      const res = await supervisorApi.put('/admin/settings/budget', body);
      setBudgetData(res.data);
      setBudgetSavedAt(Date.now());
      // Refetch the Admin Actions panel so the new audit row appears
      // without requiring a full page refresh. Snap back to page 1
      // because the new row is the most recent.
      fetchAdminActions(1);
    } catch (err) {
      console.error('Error saving budget:', err.response?.status, err.response?.data ?? err);
      setBudgetError(
        err.response?.data?.error
        || err.response?.data?.message
        || 'Failed to save budget. Please try again.'
      );
    } finally {
      setSavingBudget(false);
    }
  };

  // When the platform window changes (24h / 7d / 30d), refetch only the
  // two affected datasets — Users / Logs / Admin Actions don't depend
  // on this window so we don't pay for those scans again.
  useEffect(() => {
    if (isAdmin) {
      fetchSummary();
      fetchTopUsers();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [platformWindowHours]);

  // Update user tier
  const handleUpdateTier = async (userId) => {
    if (!newTier) return;
    
    setSavingTier(true);
    try {
      const response = await quotaApi.put(`/api/quota/admin/user/${userId}`, { tier: newTier });
      
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
      
      // If the admin is editing their OWN row, the QuotaWidget mounted in
      // the topbar is showing stale numbers (it only refreshes on chat
      // completion or `quota:refresh` CustomEvents — see useWebSocketQuota.js).
      // Push a refresh ping so the widget picks up the new tier/limit
      // immediately. Other-user edits CANNOT be pushed cross-session
      // from the frontend; that requires a backend WS push from
      // quota-lambda → KB_WebSocketConnections (deferred — see message
      // to user 2026-05-03).
      if (String(userId) === String(getUserUUID())) {
        dispatchQuotaRefresh('admin-self-tier-update');
      }
      
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
    if (limitValue > 100000000) {
      setError('Monthly limit cannot exceed 100,000,000 tokens');
      return;
    }
    if (limitValue < 1000) {
      setError('Monthly limit must be at least 1,000 tokens');
      return;
    }
    
    setSavingLimit(true);
    try {
      const response = await quotaApi.put(`/api/quota/admin/user/${userId}`, { monthly_limit: limitValue });
      
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
      
      // Self-edit → ping the topbar QuotaWidget. See handleUpdateTier
      // for the full rationale.
      if (String(userId) === String(getUserUUID())) {
        dispatchQuotaRefresh('admin-self-limit-update');
      }
      
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
    
    const selectedDate = new Date(newResetDate);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    
    if (selectedDate < today) {
      setError('Reset date must be today or in the future');
      return;
    }
    
    const maxDate = new Date();
    maxDate.setFullYear(maxDate.getFullYear() + 1);
    if (selectedDate > maxDate) {
      setError('Reset date cannot be more than 1 year from now');
      return;
    }
    
    setSavingResetDate(true);
    try {
      const response = await quotaApi.put(`/api/quota/admin/user/${userId}`, { reset_date: newResetDate });
      
      // Update local state immediately
      setUsers(prevUsers => 
        prevUsers.map(user => 
          user.user_id === userId 
            ? { ...user, reset_date: newResetDate }
            : user
        )
      );
      
      // Self-edit → ping the topbar QuotaWidget. See handleUpdateTier.
      if (String(userId) === String(getUserUUID())) {
        dispatchQuotaRefresh('admin-self-reset-date-update');
      }
      
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
    setShowEditModal(false);
    setSelectedUser(null);
  };

  // Deactivate user
  const handleDeactivateUser = async (userId, userName) => {
    setUserToDeactivate({ userId, userName });
    setShowConfirmModal(true);
  };

  const confirmDeactivate = async () => {
    if (!userToDeactivate) return;
    
    const { userId } = userToDeactivate;
    setProcessingUser(userId);
    setShowConfirmModal(false);
    
    try {
      await quotaApi.post(`/api/quota/admin/user/${userId}/deactivate`);
      
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
      setUserToDeactivate(null);
    }
  };

  // Restore user
  const handleRestoreUser = async (userId, userName) => {
    setProcessingUser(userId);
    try {
      await quotaApi.post(`/api/quota/admin/user/${userId}/restore`);
      
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
  const handleStartEdit = (user) => {
    setSelectedUser(user);
    setNewTier(user.tier);
    setNewLimit(user.monthly_limit?.toString() || '0');
    const resetDate = user.reset_date ? new Date(user.reset_date).toISOString().split('T')[0] : '';
    setNewResetDate(resetDate);
    setShowEditModal(true);
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
    return diffDays;
  };

  // Format reset date
  const formatResetDate = (dateStr) => {
    if (!dateStr) return 'N/A';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  // Friendly service name for the analytics cards / filters.
  // Backend stores raw service ids (`knowledge-base`, `system`, etc.). The
  // `system` rows are NOT real API calls — they are bookkeeping snapshots
  // written by the quota lambdas at every monthly reset (see
  // lambda_quota_check.py / lambda_admin_reset_usage.py). Calling them
  // "system" in the UI confuses admins, so we relabel.
  const formatServiceName = (serviceName) => {
    if (!serviceName) return 'Unknown';
    if (serviceName === 'system') return 'Period Resets';
    return serviceName
      .split(/[-_]/)
      .map((w) => (w ? w.charAt(0).toUpperCase() + w.slice(1) : ''))
      .join(' ');
  };

  // ─────────────────────────────────────────────────────────────────────
  // Admin-actions Details cell formatting
  // ─────────────────────────────────────────────────────────────────────
  // The QuotaAdminActions table stores `details` as a free-form JSON
  // payload whose shape varies per action:
  //   create_user / restore_user → { tier }
  //   deactivate_user           → { tier, usage_at_deactivation }
  //   reset_user_usage          → { previous_usage, previous_cost_usd }
  //   update_user_quota         → { tier?: {from,to}, monthly_limit?: {from,to}, reset_date?: {from,to} }
  // The previous renderer just dumped raw key/value pairs, which produced
  // unreadable rows like
  //   "reset_date 2026-05-01T00:00:00+00:00 → 2026-05-01T00:00:00Z"
  // for what is actually a no-op cosmetic change. The helpers below
  // humanise keys, formats values per type, and collapses no-op date
  // changes into a "(no change)" hint.
  const DETAIL_KEY_LABELS = {
    tier: 'Tier',
    monthly_limit: 'Limit',
    reset_date: 'Reset Date',
    usage_at_deactivation: 'Usage at Deactivation',
    previous_usage: 'Previous Usage',
    previous_cost_usd: 'Previous Cost',
  };

  const isIsoTimestampLike = (val) =>
    typeof val === 'string' &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(val);

  const humanizeDetailKey = (key) =>
    DETAIL_KEY_LABELS[key] ||
    String(key)
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());

  const formatDetailValue = (key, val) => {
    if (val === null || val === undefined || val === '') return '—';

    const stringVal = String(val);
    if (isIsoTimestampLike(stringVal)) {
      const d = new Date(stringVal);
      if (!Number.isNaN(d.getTime())) {
        return d.toLocaleDateString('en-US', {
          year: 'numeric',
          month: 'short',
          day: 'numeric',
        });
      }
    }

    if (key === 'tier' && typeof val === 'string') {
      return val.charAt(0).toUpperCase() + val.slice(1);
    }

    if (
      key === 'monthly_limit' ||
      key === 'usage_at_deactivation' ||
      key === 'previous_usage'
    ) {
      const n = Number(val);
      if (!Number.isNaN(n)) return `${n.toLocaleString()} tokens`;
    }

    if (key === 'previous_cost_usd') {
      const n = Number(val);
      if (!Number.isNaN(n)) return `$${n.toFixed(4)}`;
    }

    return stringVal;
  };

  // True when a {from, to} pair represents the same logical value.
  // For ISO timestamps we compare the parsed `Date.getTime()` so that
  // "2026-05-01T00:00:00+00:00" and "2026-05-01T00:00:00Z" (which are
  // equal moments but unequal strings) are treated as no-op changes.
  const isEquivalentChange = (from, to) => {
    if (isIsoTimestampLike(String(from)) && isIsoTimestampLike(String(to))) {
      const a = new Date(from).getTime();
      const b = new Date(to).getTime();
      if (!Number.isNaN(a) && !Number.isNaN(b)) return a === b;
    }
    return String(from) === String(to);
  };

  // Sort users
  const sortedUsers = [...users]
    .filter(user => {
      // Active/Inactive status filter - when showInactive is true, show ONLY inactive users
      const matchesStatus = showInactive ? !user.is_active : true;
      // Tier filter
      const matchesTier = tierFilter === 'all' || user.tier.toLowerCase() === tierFilter.toLowerCase();
      // Search filter
      const matchesSearch = user.user_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (user.fullname && user.fullname.toLowerCase().includes(searchTerm.toLowerCase())) ||
        user.tier.toLowerCase().includes(searchTerm.toLowerCase());
      return matchesStatus && matchesTier && matchesSearch;
    })
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

  // ── User Quotas pagination derivations ────────────────────────────
  // sortedUsers is recomputed on every render (it's a derived const,
  // not state), so we don't memo it here. Keep these inexpensive —
  // a few arithmetic ops + one slice per render is fine.
  const usersTotalPages = Math.max(1, Math.ceil(sortedUsers.length / usersPageSize));
  // Clamp the page if the underlying data shrank (filter applied,
  // user deactivated, etc.) so we never render an empty page when
  // results actually exist.
  const safeUsersPage = Math.min(usersPage, usersTotalPages);
  const usersPageStart = (safeUsersPage - 1) * usersPageSize;
  const pagedUsers = sortedUsers.slice(usersPageStart, usersPageStart + usersPageSize);

  // Snap back to page 1 whenever the filter/search/sort/page-size
  // changes — same UX as the Recent activity table on Profile.
  // We don't include `users` in the deps because adding/removing one
  // user shouldn't drop the admin off their current page.
  useEffect(() => {
    setUsersPage(1);
  }, [searchTerm, tierFilter, showInactive, sortConfig.key, sortConfig.direction, usersPageSize]);

  if (loading && users.length === 0) {
    return (
      <div className="quota-page">
        <div className="quota-loading">
          <span>Loading token management data...</span>
        </div>
      </div>
    );
  }

  if (isAdmin === null) {
    return (
      <div className="quota-page">
        <div className="quota-loading">
          <span>Checking access...</span>
        </div>
      </div>
    );
  }

  if (isAdmin === false) {
    return (
      <div className="quota-page">
        <div className="quota-access-denied">
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
        <header className="quota-header-row">
          <div>
            <h1 className="quota-title">Token Management</h1>
            <p className="quota-subtitle">Monitor and manage AI token usage across the platform</p>
          </div>
          <div className="refresh-btn-wrapper">
            <button className="refresh-btn1" onClick={refreshData} disabled={loading}>
              <RefreshCw size={20} />
            </button>
            <span className="refresh-tooltip">Refresh</span>
          </div>
        </header>

        {error && (
          <div className="quota-error-banner">
            <span>{error}</span>
            <button onClick={() => setError(null)}>
              ×
            </button>
          </div>
        )}

        {/* Summary Cards */}
        {summary && (
          <div className="summary-section">
            <h2 className="section-title">
              Platform Overview 
            </h2>
            <div className="summary-cards">
              <div className="summary-card primary">
                <div className="summary-content">
                  <span className="summary-value">{summary.total_users || 0}</span>
                  <span className="summary-label">Active Users</span>
                </div>
              </div>

              <div className="summary-card">
                <div className="summary-content">
                  <span className="summary-value">{formatNumber(summary.total_tokens)}</span>
                  <span className="summary-label">Tokens Used</span>
                </div>
              </div>

              <div className="summary-card">
                <div className="summary-content">
                  <span className="summary-value">${(summary.total_cost_usd || 0).toFixed(2)}</span>
                  <span className="summary-label">Total Cost</span>
                </div>
              </div>

              <div className="summary-card">
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
                  {summary.by_service.map((service, idx) => {
                    const isSystem = service.service === 'system';
                    const systemTooltip =
                      'Internal bookkeeping rows. Written when a user\u2019s monthly quota auto-resets or an admin manually resets their usage \u2014 they snapshot the previous period\u2019s totals before zeroing out. These are NOT real API calls.';
                    const visibleModels = (service.models_used || []).filter(
                      (m) => m && m !== 'N/A'
                    );
                    return (
                      <div
                        key={idx}
                        className={`service-card${isSystem ? ' service-card-system' : ''}`}
                      >
                        <div className="service-header">
                          <span
                            className="service-name"
                            title={isSystem ? systemTooltip : undefined}
                          >
                            {formatServiceName(service.service)}
                            {isSystem && (
                              <span
                                className="service-info-icon"
                                title={systemTooltip}
                                aria-label="What is this?"
                              >
                                {' '}
                                &#9432;
                              </span>
                            )}
                          </span>
                          <span className="service-calls">
                            {service.call_count} {service.call_count === 1 ? 'call' : 'calls'}
                          </span>
                        </div>
                        <div className="service-stats">
                          <span>{formatNumber(service.total_tokens)} tokens</span>
                          <span>${(service.total_cost_usd || 0).toFixed(4)}</span>
                        </div>
                        {visibleModels.length > 0 ? (
                          <div className="service-models">
                            {visibleModels.map((model, i) => (
                              <span key={i} className="model-tag">{model}</span>
                            ))}
                          </div>
                        ) : isSystem ? (
                          <div className="service-models service-models-empty">
                            <span className="model-tag model-tag-muted">
                              auto / admin reset
                            </span>
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
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

            {/* Platform-level analytics (added 2026-05-01)
                ────────────────────────────────────────────
                Two side-by-side charts, both windowed by the same
                `platformWindowHours` selector so admins can pivot
                "last 24h" → "last 30d" without re-loading the whole
                page. Top users → horizontal bars driven by
                /admin/top-users; daily series → SVG area driven by
                summary.by_day (added by lambda_admin_summary in this
                same change). Both charts gracefully degrade when the
                respective dataset is empty — common right after a
                fresh deploy or for a brand-new tenant. */}
            <div className="platform-analytics">
              <div className="platform-analytics-header">
                <h3 className="subsection-title">Platform analytics</h3>
                <div className="platform-window-controls">
                  <select
                    className="platform-window-select"
                    value={platformWindowHours}
                    onChange={(e) => setPlatformWindowHours(Number(e.target.value))}
                    disabled={loading}
                    aria-label="Platform analytics window"
                  >
                    <option value={24}>Last 24 hours</option>
                    <option value={168}>Last 7 days</option>
                    <option value={720}>Last 30 days</option>
                  </select>
                </div>
              </div>

              <div className="platform-charts-row">
                <PlatformDailyChart byDay={summary.by_day || []} />
                <PlatformTopUsersChart users={topUsers} />
              </div>
            </div>
          </div>
        )}

        {/* Monthly Budget & Alerts (moved here from the Admin Dashboard
            on 2026-05-04). Saving here triggers an audit row in
            QuotaAdminActions which the Admin Actions panel below
            reflects on its next refetch (handleSaveBudget calls
            fetchAdminActions(1) immediately on success). The visual
            alert banner mirrors the one on the Admin Dashboard so an
            admin landing on either page sees the same warn/over-budget
            state without needing to cross-navigate. */}
        <BudgetSection
          budgetData={budgetData}
          budgetInput={budgetInput}
          setBudgetInput={setBudgetInput}
          thresholdInput={thresholdInput}
          setThresholdInput={setThresholdInput}
          savingBudget={savingBudget}
          budgetError={budgetError}
          budgetSavedAt={budgetSavedAt}
          onSave={handleSaveBudget}
        />

        {/* Users Table */}
        {users.length > 0 && (
          <div className="users-section">
            <div className="users-header">
              <h2 className="section-title">
                User Quotas
              </h2>
              <div className="users-controls">
                <ActionButton 
                  icon={Filter} 
                  className='accounts-header-action-button-filter'
                  onClick={() => setShowFilters(!showFilters)}
                >
                  {showFilters ? 'Hide Filters' : 'Show Filters'}
                </ActionButton>
                <ActionButton 
                  icon={showInactive ? Users : UserX} 
                  className='accounts-header-action-button-toggle'
                  onClick={() => setShowInactive(!showInactive)}
                >
                  {showInactive ? 'View Active' : 'View Inactive'}
                </ActionButton>
              </div>
            </div>

            {showFilters && (
              <div className="filter-panel">
                <div className="filter-panel-content">
                  <div className="filter-field">
                    <label className="filter-label">Tier</label>
                    <select 
                      value={tierFilter} 
                      onChange={(e) => setTierFilter(e.target.value)}
                      className="filter-select"
                    >
                      <option value="all">All Tiers</option>
                      <option value="free">Free</option>
                      <option value="pro">Pro</option>
                      <option value="enterprise">Enterprise</option>
                    </select>
                  </div>
                  <div className="filter-field">
                    <label className="filter-label">Sort By</label>
                    <select 
                      value={sortConfig.key} 
                      onChange={(e) => setSortConfig(prev => ({ ...prev, key: e.target.value }))}
                      className="filter-select"
                    >
                      <option value="user_id">User</option>
                      <option value="tier">Tier</option>
                      <option value="current_usage">Usage</option>
                      <option value="reset_date">Reset Date</option>
                    </select>
                  </div>
                  <div className="filter-field">
                    <label className="filter-label">Order</label>
                    <select 
                      value={sortConfig.direction} 
                      onChange={(e) => setSortConfig(prev => ({ ...prev, direction: e.target.value }))}
                      className="filter-select"
                    >
                      <option value="asc">Ascending</option>
                      <option value="desc">Descending</option>
                    </select>
                  </div>
                  <div>
                    <button 
                      onClick={() => { setTierFilter('all'); setSortConfig({ key: 'current_usage', direction: 'desc' }); }}
                      className="reset-filters-btn"
                    >
                      Reset Filters
                    </button>
                  </div>
                </div>
              </div>
            )}

            <div className="search-container" style={{ marginBottom: 24 }}>
              <Search size={22} className="search-icon" />
              <input
                type="text"
                placeholder="Search users..."
                className="search-input"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
            </div>

            <div className="users-table-container">
              <table className="users-table">
                <thead>
                  <tr>
                    <th onClick={() => handleSort('user_id')}>
                      User
                      {sortConfig.key === 'user_id' && (
                        sortConfig.direction === 'asc' ? ' ↑' : ' ↓'
                      )}
                    </th>
                    <th onClick={() => handleSort('tier')}>
                      Tier
                      {sortConfig.key === 'tier' && (
                        sortConfig.direction === 'asc' ? ' ↑' : ' ↓'
                      )}
                    </th>
                    <th onClick={() => handleSort('current_usage')}>
                      Usage
                      {sortConfig.key === 'current_usage' && (
                        sortConfig.direction === 'asc' ? ' ↑' : ' ↓'
                      )}
                    </th>
                    <th>Progress</th>
                    <th onClick={() => handleSort('reset_date')}>
                      Reset
                      {sortConfig.key === 'reset_date' && (
                        sortConfig.direction === 'asc' ? ' ↑' : ' ↓'
                      )}
                    </th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedUsers.length === 0 ? (
                    <tr>
                      <td colSpan="6" style={{ textAlign: 'center', color: '#64748b', fontStyle: 'italic', padding: '2rem' }}>
                        {showInactive ? 'No Inactive Users Found' : 'No Users Found'}
                      </td>
                    </tr>
                  ) : (
                    pagedUsers.map((user) => {
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
                        <td
                          className="clickable-cell"
                          onClick={() => {
                            if (!isInactive) {
                              setEditingUser(user.user_id);
                              setEditingField('tier');
                              setNewTier(user.tier);
                            }
                          }}
                          style={{ cursor: isInactive ? 'default' : 'pointer' }}
                        >
                          {isEditingThisUser && editingField === 'tier' ? (
                            <div className="inline-edit" onClick={(e) => e.stopPropagation()}>
                              <select
                                value={newTier}
                                onChange={(e) => setNewTier(e.target.value)}
                                className="inline-select"
                                autoFocus
                              >
                                <option value="free">Free</option>
                                <option value="pro">Pro</option>
                                <option value="enterprise">Enterprise</option>
                              </select>
                              <div className="inline-edit-actions">
                                <button
                                  className="inline-save-btn"
                                  onClick={() => handleUpdateTier(user.user_id)}
                                  disabled={savingTier || newTier === user.tier}
                                >
                                  {savingTier ? '...' : '✓'}
                                </button>
                                <button
                                  className="inline-cancel-btn"
                                  onClick={handleCancelEdit}
                                >
                                  ✕
                                </button>
                              </div>
                            </div>
                          ) : (
                            <span className="tier-text">{user.tier}</span>
                          )}
                        </td>
                        <td
                          className="clickable-cell"
                          onClick={() => {
                            if (!isInactive) {
                              setEditingUser(user.user_id);
                              setEditingField('limit');
                              setNewLimit(user.monthly_limit?.toString() || '0');
                            }
                          }}
                          style={{ cursor: isInactive ? 'default' : 'pointer' }}
                        >
                          {isEditingThisUser && editingField === 'limit' ? (
                            <div className="inline-edit" onClick={(e) => e.stopPropagation()}>
                              <input
                                type="number"
                                value={newLimit}
                                onChange={(e) => setNewLimit(e.target.value)}
                                className="inline-input"
                                autoFocus
                                min="1000"
                                max="100000000"
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') handleUpdateLimit(user.user_id);
                                  if (e.key === 'Escape') handleCancelEdit();
                                }}
                              />
                              <div className="inline-edit-actions">
                                <button
                                  className="inline-save-btn"
                                  onClick={() => handleUpdateLimit(user.user_id)}
                                  disabled={savingLimit}
                                >
                                  {savingLimit ? '...' : '✓'}
                                </button>
                                <button
                                  className="inline-cancel-btn"
                                  onClick={handleCancelEdit}
                                >
                                  ✕
                                </button>
                              </div>
                            </div>
                          ) : (
                            <span className="usage-text">
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
                            <span className={`table-progress-label ${status}`}>
                              {percentage.toFixed(1)}%
                            </span>
                          </div>
                        </td>
                        <td
                          className="reset-cell clickable-cell"
                          onClick={() => {
                            if (!isInactive) {
                              setEditingUser(user.user_id);
                              setEditingField('reset_date');
                              const resetDate = user.reset_date ? new Date(user.reset_date).toISOString().split('T')[0] : '';
                              setNewResetDate(resetDate);
                            }
                          }}
                          style={{ cursor: isInactive ? 'default' : 'pointer' }}
                        >
                          {isEditingThisUser && editingField === 'reset_date' ? (
                            <div className="inline-edit" onClick={(e) => e.stopPropagation()}>
                              <input
                                type="date"
                                value={newResetDate}
                                onChange={(e) => setNewResetDate(e.target.value)}
                                className="inline-input"
                                autoFocus
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') handleUpdateResetDate(user.user_id);
                                  if (e.key === 'Escape') handleCancelEdit();
                                }}
                              />
                              <div className="inline-edit-actions">
                                <button
                                  className="inline-save-btn"
                                  onClick={() => handleUpdateResetDate(user.user_id)}
                                  disabled={savingResetDate}
                                >
                                  {savingResetDate ? '...' : '✓'}
                                </button>
                                <button
                                  className="inline-cancel-btn"
                                  onClick={handleCancelEdit}
                                >
                                  ✕
                                </button>
                              </div>
                            </div>
                          ) : (
                            <span className={`reset-info ${getDaysUntilReset(user.reset_date) !== null && getDaysUntilReset(user.reset_date) <= 0 ? 'reset-overdue' : ''}`}>
                              {getDaysUntilReset(user.reset_date) !== null 
                                ? (getDaysUntilReset(user.reset_date) > 0 
                                    ? `${getDaysUntilReset(user.reset_date)}d` 
                                    : 'Overdue')
                                : 'N/A'}
                            </span>
                          )}
                        </td>
                        <td className="actions-cell">
                          <div className="action-buttons">
                            {/* History is available for inactive users
                                too — admins often need to audit a
                                deactivated account's last billing
                                period. The modal handles read-only
                                display of historical UsageLogs. */}
                            <div className="action-btn-wrapper">
                              <button
                                className="icon-btn history-btn"
                                onClick={() => setHistoryTarget({
                                  user_id: user.user_id,
                                  fullname: user.fullname || user.user_id
                                })}
                              >
                                <Activity size={18} />
                              </button>
                              <span className="action-tooltip">History</span>
                            </div>
                            {!isInactive && (
                              <div className="action-btn-wrapper">
                                <button 
                                  className="icon-btn edit-btn"
                                  onClick={() => handleStartEdit(user)}
                                >
                                  <Edit2 size={18} />
                                </button>
                                <span className="action-tooltip">Edit</span>
                              </div>
                            )}
                            {isInactive ? (
                              <div className="action-btn-wrapper">
                                <button 
                                  className="icon-btn restore-btn"
                                  onClick={() => handleRestoreUser(user.user_id, user.fullname || user.user_id)}
                                  disabled={processingUser === user.user_id}
                                >
                                  <RotateCcw size={18} />
                                </button>
                                <span className="action-tooltip">Restore</span>
                              </div>
                            ) : (
                              <div className="action-btn-wrapper">
                                <button 
                                  className="icon-btn deactivate-btn"
                                  onClick={() => handleDeactivateUser(user.user_id, user.fullname || user.user_id)}
                                  disabled={processingUser === user.user_id}
                                >
                                  <Trash2 size={18} />
                                </button>
                                <span className="action-tooltip">Deactivate</span>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })
                  )}
                </tbody>
              </table>
              {/* User Quotas pagination footer.
                  Always rendered when there's at least one match
                  (rather than only when total_pages > 1) so the page
                  size selector remains accessible — admins commonly
                  ask "show me 50 at once" even with fewer than 50
                  records right now. The Prev/Next buttons disable
                  themselves at the edges so single-page users still
                  get a clean look. */}
              {sortedUsers.length > 0 && (
                <div className="users-pagination">
                  <div className="users-pagination-info">
                    Showing{' '}
                    <strong>{usersPageStart + 1}</strong>
                    {'\u2013'}
                    <strong>{Math.min(usersPageStart + usersPageSize, sortedUsers.length)}</strong>
                    {' '}of <strong>{sortedUsers.length}</strong> user{sortedUsers.length === 1 ? '' : 's'}
                  </div>
                  <div className="users-pagination-controls">
                    <select
                      className="users-page-size-select"
                      value={usersPageSize}
                      onChange={(e) => setUsersPageSize(Number(e.target.value))}
                      aria-label="Rows per page"
                      title="Rows per page"
                    >
                      <option value={10}>10 / page</option>
                      <option value={25}>25 / page</option>
                      <option value={50}>50 / page</option>
                      <option value={100}>100 / page</option>
                    </select>
                    <button
                      type="button"
                      className="users-page-btn"
                      onClick={() => setUsersPage(p => Math.max(1, p - 1))}
                      disabled={safeUsersPage <= 1}
                    >
                      ‹ Prev
                    </button>
                    <span className="users-page-indicator">
                      Page {safeUsersPage} of {usersTotalPages}
                    </span>
                    <button
                      type="button"
                      className="users-page-btn"
                      onClick={() => setUsersPage(p => Math.min(usersTotalPages, p + 1))}
                      disabled={safeUsersPage >= usersTotalPages}
                    >
                      Next ›
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Admin Actions Panel */}

        <div className="users-section">
          <div className="users-header">
            <h2 className="section-title">
              Admin Actions
            </h2>
            <div className="users-controls">
              <ActionButton 
                icon={Filter} 
                className='accounts-header-action-button-filter'
                onClick={() => setShowAdminFilters(!showAdminFilters)}
              >
                {showAdminFilters ? 'Hide Filters' : 'Show Filters'}
              </ActionButton>
            </div>
          </div>

          {showAdminFilters && (
            <div className="filter-panel">
              <div className="filter-panel-content">
                <div className="filter-field">
                  <label className="filter-label">Action Type</label>
                  <select 
                    className="filter-select"
                  >
                    <option value="">All Actions</option>
                  </select>
                </div>
                <div>
                  <button 
                    onClick={() => {}}
                    className="reset-filters-btn"
                  >
                    Reset Filters
                  </button>
                </div>
              </div>
            </div>
          )}

          <div className="search-container" style={{ marginBottom: 24 }}>
            <Search size={22} className="search-icon" />
            <input
              type="text"
              placeholder="Search admin actions..."
              className="search-input"
              value={adminSearchTerm}
              onChange={(e) => setAdminSearchTerm(e.target.value)}
            />
          </div>

          <div className="users-table-container">
            <table className="users-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Admin</th>
                  <th>Action</th>
                  <th>Target User</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {adminActions.filter(action => {
                  if (!adminSearchTerm) return true;
                  const search = adminSearchTerm.toLowerCase();
                  return (
                    (action.admin_name && action.admin_name.toLowerCase().includes(search)) ||
                    (action.admin_email && action.admin_email.toLowerCase().includes(search)) ||
                    (action.admin_id && action.admin_id.toLowerCase().includes(search)) ||
                    (action.action && action.action.toLowerCase().includes(search)) ||
                    (action.target_user_name && action.target_user_name.toLowerCase().includes(search)) ||
                    (action.target_user_id && action.target_user_id.toLowerCase().includes(search))
                  );
                }).length === 0 ? (
                  <tr>
                    <td colSpan="5" style={{ textAlign: 'center', color: '#64748b', fontStyle: 'italic', padding: '2rem' }}>
                      No admin actions found
                    </td>
                  </tr>
                ) : (
                  adminActions.filter(action => {
                    if (!adminSearchTerm) return true;
                    const search = adminSearchTerm.toLowerCase();
                    return (
                      (action.admin_name && action.admin_name.toLowerCase().includes(search)) ||
                      (action.admin_email && action.admin_email.toLowerCase().includes(search)) ||
                      (action.admin_id && action.admin_id.toLowerCase().includes(search)) ||
                      (action.action && action.action.toLowerCase().includes(search)) ||
                      (action.target_user_name && action.target_user_name.toLowerCase().includes(search)) ||
                      (action.target_user_id && action.target_user_id.toLowerCase().includes(search))
                    );
                  }).map((action) => (
                    <tr key={action.action_id}>
                      <td>
                        {formatTimestamp(action.timestamp)}
                      </td>
                      <td title={action.admin_id || ''}>
                        {(action.admin_name && action.admin_name !== 'System') 
                          ? action.admin_name 
                          : (action.admin_email && action.admin_email !== 'system')
                            ? action.admin_email
                            : (action.admin_id && action.admin_id !== 'system')
                              ? action.admin_id
                              : 'System'}
                      </td>
                      <td>
                        <span className="tier-text">
                          {action.action.replace(/_/g, ' ')}
                        </span>
                      </td>
                      <td>
                        {action.target_user_name || action.target_user_id || '-'}
                      </td>
                      <td>
                        {action.details ? (
                          <span
                            className="details-preview"
                            title={
                              typeof action.details === 'string'
                                ? action.details
                                : JSON.stringify(action.details, null, 2)
                            }
                          >
                            {(() => {
                              let detailsObj;
                              try {
                                detailsObj =
                                  typeof action.details === 'string'
                                    ? JSON.parse(action.details)
                                    : action.details;
                              } catch (_e) {
                                return <span className="detail-item">{String(action.details)}</span>;
                              }

                              const entries = Object.entries(detailsObj || {});
                              if (entries.length === 0) {
                                return <span className="detail-item">—</span>;
                              }

                              return entries.map(([key, val]) => {
                                const label = humanizeDetailKey(key);

                                if (
                                  val &&
                                  typeof val === 'object' &&
                                  'from' in val &&
                                  'to' in val
                                ) {
                                  if (isEquivalentChange(val.from, val.to)) {
                                    return (
                                      <span
                                        key={key}
                                        className="detail-item detail-noop"
                                      >
                                        <span className="detail-label">{label}:</span>{' '}
                                        <span className="detail-value">
                                          {formatDetailValue(key, val.to)}
                                        </span>{' '}
                                        <span className="detail-noop-tag">(no change)</span>
                                      </span>
                                    );
                                  }
                                  return (
                                    <span key={key} className="detail-item detail-change">
                                      <span className="detail-label">{label}:</span>{' '}
                                      <span className="detail-from">
                                        {formatDetailValue(key, val.from)}
                                      </span>
                                      <span className="detail-arrow"> → </span>
                                      <span className="detail-to">
                                        {formatDetailValue(key, val.to)}
                                      </span>
                                    </span>
                                  );
                                }

                                return (
                                  <span key={key} className="detail-item">
                                    <span className="detail-label">{label}:</span>{' '}
                                    <span className="detail-value">
                                      {formatDetailValue(key, val)}
                                    </span>
                                  </span>
                                );
                              });
                            })()}
                          </span>
                        ) : (
                          '-'
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {Math.ceil(adminActionsTotal / 10) > 1 && (
            <div className="pagination-container">
              <button 
                className="pagination-btn"
                onClick={() => fetchAdminActions(adminActionsPage - 1)}
                disabled={adminActionsPage <= 1}
              >
                ←
              </button>
              {(() => {
                const totalPages = Math.ceil(adminActionsTotal / 10);
                const pages = [];
                let startPage = Math.max(1, adminActionsPage - 2);
                let endPage = Math.min(totalPages, startPage + 4);
                
                if (endPage - startPage < 4) {
                  startPage = Math.max(1, endPage - 4);
                }
                
                for (let i = startPage; i <= endPage; i++) {
                  pages.push(
                    <button
                      key={i}
                      className={`pagination-num-btn ${i === adminActionsPage ? 'active' : ''}`}
                      onClick={() => fetchAdminActions(i)}
                    >
                      {i}
                    </button>
                  );
                }
                return pages;
              })()}
              <button 
                className="pagination-btn"
                onClick={() => fetchAdminActions(adminActionsPage + 1)}
                disabled={adminActionsPage >= Math.ceil(adminActionsTotal / 10)}
              >
                →
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Edit User Modal */}
      {showEditModal && selectedUser && (
        <div className="modal-overlay" onClick={handleCancelEdit}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">Edit User Quota</h2>
              <button className="modal-close-btn" onClick={handleCancelEdit}>×</button>
            </div>

            <div className="modal-body">
              <div className="modal-user-info">
                <h3>{selectedUser.fullname || selectedUser.user_id}</h3>
                <p>{selectedUser.user_id}</p>
              </div>

              <div className="modal-form-group">
                <label className="modal-label">Tier</label>
                <select
                  value={newTier}
                  onChange={(e) => setNewTier(e.target.value)}
                  className="modal-select"
                >
                  <option value="free">Free</option>
                  <option value="pro">Pro</option>
                  <option value="enterprise">Enterprise</option>
                </select>
              </div>

              <div className="modal-form-group">
                <label className="modal-label">Monthly Limit (tokens)</label>
                <input
                  type="number"
                  value={newLimit}
                  className="modal-input"
                  disabled
                  style={{ backgroundColor: '#f3f4f6', cursor: 'not-allowed' }}
                />
              </div>

              <div className="modal-form-group">
                <label className="modal-label">Reset Date</label>
                <input
                  type="date"
                  value={newResetDate}
                  className="modal-input"
                  disabled
                  style={{ backgroundColor: '#f3f4f6', cursor: 'not-allowed' }}
                />
              </div>
            </div>

            <div className="modal-actions">
              <button
                type="button"
                className="modal-btn modal-btn-cancel"
                onClick={handleCancelEdit}
              >
                Cancel
              </button>
              <button
                type="button"
                className="modal-btn modal-btn-submit"
                onClick={async () => {
                  if (newTier !== selectedUser.tier) {
                    await handleUpdateTier(selectedUser.user_id);
                  }
                  handleCancelEdit();
                }}
                disabled={newTier === selectedUser.tier}
              >
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Confirmation Modal */}
      {showConfirmModal && userToDeactivate && (
        <div className="modal-overlay" onClick={() => setShowConfirmModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">Deactivate User</h2>
              <button className="modal-close-btn" onClick={() => setShowConfirmModal(false)}>×</button>
            </div>

            <div className="modal-form">
              <p style={{ fontSize: '1rem', color: '#374151', lineHeight: '1.6', margin: '0 0 16px 0' }}>
                Are you sure you want to deactivate <strong>{userToDeactivate.userName || userToDeactivate.userId}</strong>?
              </p>
              <p style={{ fontSize: '0.9rem', color: '#6b7280', lineHeight: '1.6', margin: 0 }}>
                Their quota will be soft-deleted and they will no longer be able to use the service.
              </p>
            </div>

            <div className="modal-actions">
              <button
                type="button"
                className="modal-btn modal-btn-cancel"
                onClick={() => {
                  setShowConfirmModal(false);
                  setUserToDeactivate(null);
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                className="modal-btn modal-btn-submit"
                style={{ backgroundColor: '#ef4444' }}
                onClick={confirmDeactivate}
              >
                Deactivate
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Per-user history modal — opened from the User Quotas row
          History button. Mounts only when a target is set so the
          /api/quota/me/history scan only runs on demand. */}
      {historyTarget && (
        <UserHistoryModal
          target={historyTarget}
          onClose={() => setHistoryTarget(null)}
        />
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Platform-level charts (rendered inside the Platform Overview section)
//
// Both charts are pure SVG so they match the donut/bar pattern already
// used by the per-user history modal — keeps the bundle dependency-free
// and the visual language consistent across the page. If you ever want
// hover/zoom/brush, swap to recharts: the data shape (`{date, total_tokens,
// total_cost_usd, call_count}` and `{user_id, fullname, total_tokens, ...}`)
// already matches what recharts <AreaChart> / <BarChart> expect.
// ─────────────────────────────────────────────────────────────────────────────

// Tiny helpers private to this section. The QuotaPage component already
// has its own `formatNumber`, but it lives inside the function closure;
// these are module-level so the chart components can use them.
const _platformFormatTokens = (n) => {
  const v = Number(n) || 0;
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toLocaleString();
};

const _platformFormatCost = (n) => {
  const v = Number(n) || 0;
  if (v === 0) return '$0.00';
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
};

const _platformFormatDateShort = (iso) => {
  if (!iso) return '';
  try {
    return new Date(iso + 'T00:00:00Z').toLocaleDateString('en-US', {
      month: 'short', day: 'numeric'
    });
  } catch {
    return iso;
  }
};

// ── PlatformDailyChart ──────────────────────────────────────────────────
// Area + line over time. Built with hand-rolled SVG <path d="..."> so we
// can keep the same gradient/colour story as the rest of the page without
// pulling in a charting library. The area path closes at the bottom
// baseline; the line path traces the same points.
function PlatformDailyChart({ byDay }) {
  const data = byDay || [];

  // Internal hover state: which point's tooltip to render. Using
  // `useState` instead of CSS-only :hover because we need to compute
  // tooltip *position* dynamically based on the point coordinates.
  const [hoverIdx, setHoverIdx] = useState(null);

  if (data.length === 0) {
    return (
      <div className="platform-chart-card platform-chart-empty">
        <div className="platform-chart-title">
          Tokens per day
        </div>
        <div className="platform-chart-empty-msg">
          No usage in this window.
        </div>
      </div>
    );
  }

  // Layout — fixed viewBox so the chart scales responsively while
  // keeping internal proportions stable across container widths.
  const VBW = 600;
  const VBH = 220;
  const PAD = { top: 16, right: 14, bottom: 28, left: 44 };
  const innerW = VBW - PAD.left - PAD.right;
  const innerH = VBH - PAD.top - PAD.bottom;

  const maxTokens = Math.max(...data.map(d => d.total_tokens || 0), 1);
  // Stride between points along the x-axis. With <2 points we'd
  // divide by 0; clamp so a single-day window still renders one
  // dot in the middle of the chart.
  const stride = data.length > 1 ? innerW / (data.length - 1) : 0;

  const points = data.map((d, i) => {
    const x = PAD.left + (data.length === 1 ? innerW / 2 : i * stride);
    const y = PAD.top + innerH - ((d.total_tokens / maxTokens) * innerH);
    return { x, y, ...d };
  });

  // Path strings.
  // - linePath: simple polyline through the data points.
  // - areaPath: same polyline closed back along the baseline so the
  //   gradient fill has something to colour.
  const linePath = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(' ');
  const areaPath = `${linePath} L${points[points.length - 1].x.toFixed(1)} ${(PAD.top + innerH).toFixed(1)} L${points[0].x.toFixed(1)} ${(PAD.top + innerH).toFixed(1)} Z`;

  // Y-axis ticks: 0, mid, max. Three is enough to read the chart
  // without crowding the very narrow vertical gutter.
  const yTicks = [0, Math.round(maxTokens / 2), maxTokens];

  // X-axis labels: first, middle, last. More than three labels look
  // crowded at typical container widths, and the tooltip on hover
  // gives the precise date for any individual day.
  const xTickIndices = data.length <= 1
    ? [0]
    : (data.length === 2
        ? [0, data.length - 1]
        : [0, Math.floor(data.length / 2), data.length - 1]);

  const totalTokens = data.reduce((acc, d) => acc + (d.total_tokens || 0), 0);
  const totalCost = data.reduce((acc, d) => acc + (d.total_cost_usd || 0), 0);

  return (
    <div className="platform-chart-card">
      <div className="platform-chart-header">
        <div className="platform-chart-title">Tokens per day</div>
        <div className="platform-chart-totals">
          <span>{_platformFormatTokens(totalTokens)} tokens</span>
          <span className="platform-chart-totals-sep">·</span>
          <span>{_platformFormatCost(totalCost)}</span>
        </div>
      </div>
      <svg
        viewBox={`0 0 ${VBW} ${VBH}`}
        className="platform-area-svg"
        preserveAspectRatio="none"
        role="img"
        aria-label="Platform tokens per day over the selected window"
      >
        <defs>
          <linearGradient id="platformAreaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor="#6366f1" stopOpacity="0.32" />
            <stop offset="100%" stopColor="#6366f1" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {/* Y-axis grid + labels */}
        {yTicks.map((tick) => {
          const y = PAD.top + innerH - ((tick / (maxTokens || 1)) * innerH);
          return (
            <g key={tick}>
              <line
                x1={PAD.left}
                x2={PAD.left + innerW}
                y1={y}
                y2={y}
                stroke="#e5e7eb"
                strokeDasharray="2 4"
              />
              <text
                x={PAD.left - 6}
                y={y + 3}
                textAnchor="end"
                className="platform-axis-label"
              >
                {_platformFormatTokens(tick)}
              </text>
            </g>
          );
        })}
        {/* Area fill */}
        <path d={areaPath} fill="url(#platformAreaGrad)" stroke="none" />
        {/* Line */}
        <path
          d={linePath}
          fill="none"
          stroke="#6366f1"
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {/* Hover targets — wider invisible circles for easier mouse
            capture, plus a smaller visible dot for the active point. */}
        {points.map((p, i) => (
          <g key={p.date}>
            <circle
              cx={p.x}
              cy={p.y}
              r={10}
              fill="transparent"
              onMouseEnter={() => setHoverIdx(i)}
              onMouseLeave={() => setHoverIdx(null)}
              style={{ cursor: 'crosshair' }}
            >
              <title>{`${p.date} · ${_platformFormatTokens(p.total_tokens)} tokens · ${_platformFormatCost(p.total_cost_usd)} · ${p.call_count} call(s)`}</title>
            </circle>
            {hoverIdx === i && (
              <circle
                cx={p.x}
                cy={p.y}
                r={4}
                fill="#6366f1"
                stroke="#ffffff"
                strokeWidth="2"
                pointerEvents="none"
              />
            )}
          </g>
        ))}
        {/* X-axis labels */}
        {xTickIndices.map((i) => (
          <text
            key={i}
            x={points[i].x}
            y={PAD.top + innerH + 18}
            textAnchor="middle"
            className="platform-axis-label"
          >
            {_platformFormatDateShort(points[i].date)}
          </text>
        ))}
      </svg>
      {hoverIdx !== null && points[hoverIdx] && (
        <div className="platform-area-tooltip">
          <strong>{_platformFormatDateShort(points[hoverIdx].date)}</strong>
          {' · '}
          {_platformFormatTokens(points[hoverIdx].total_tokens)} tokens
          {' · '}
          {_platformFormatCost(points[hoverIdx].total_cost_usd)}
          {' · '}
          {points[hoverIdx].call_count} call{points[hoverIdx].call_count === 1 ? '' : 's'}
        </div>
      )}
    </div>
  );
}

// ── PlatformTopUsersChart ───────────────────────────────────────────────
// Horizontal bar list — each user is a row with their name, a fill bar
// proportional to the top consumer, and the absolute token + cost
// numbers. Ten rows max (matches the backend `limit=10`). Designed
// to read like a leaderboard so admins can spot heavy users at a glance.
function PlatformTopUsersChart({ users }) {
  if (!users || users.length === 0) {
    return (
      <div className="platform-chart-card platform-chart-empty">
        <div className="platform-chart-title">Top 10 users</div>
        <div className="platform-chart-empty-msg">
          No usage in this window.
        </div>
      </div>
    );
  }
  const max = Math.max(...users.map(u => u.total_tokens || 0), 1);
  return (
    <div className="platform-chart-card">
      <div className="platform-chart-header">
        <div className="platform-chart-title">Top {users.length} users</div>
        <div className="platform-chart-totals">
          {users.length} active
        </div>
      </div>
      <ul className="platform-top-list">
        {users.map((u, i) => {
          const pct = (u.total_tokens / max) * 100;
          const display = u.fullname || u.user_id;
          return (
            <li key={u.user_id || i} className="platform-top-item">
              <div className="platform-top-rank">{i + 1}</div>
              <div className="platform-top-name" title={u.user_id}>
                <span className="platform-top-name-text">{display}</span>
                <span className="platform-top-meta">
                  {u.call_count} call{u.call_count === 1 ? '' : 's'}
                  {' · '}
                  {_platformFormatCost(u.total_cost_usd)}
                </span>
              </div>
              <div className="platform-top-bar-track">
                <div
                  className="platform-top-bar-fill"
                  style={{ width: `${Math.max(2, pct)}%` }}
                />
              </div>
              <div className="platform-top-num">
                {_platformFormatTokens(u.total_tokens)}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// UserHistoryModal — admin per-user token consumption viewer.
//
// Backed by GET /api/quota/me/history?user_id=<target>&days=<window>
// (the lambda enforces admin/staff role for the ?user_id= override —
//  see quota-lambda/lambda_user_history.py).
//
// Charts are hand-rolled SVG (donut + bar). Reasons:
//   - Datasets are tiny (≤365 days, ~10 services).
//   - No new dependency; matches the inline bar style already used in
//     ProfilePage.jsx.
//   - Full theming control with the existing QuotaPage CSS palette.
// If the dashboard later needs zoom / brush / animated transitions,
// swap to recharts — the data shape (totals / per_day / per_service)
// already matches recharts' expected props.
// ─────────────────────────────────────────────────────────────────────────────

const HISTORY_OPERATION_LABELS = {
  chat: 'Chat',
  chat_stream: 'SFXbot Chat',
  classify: 'Classification',
  classification: 'Classification',
  pdf_parse: 'PDF processing',
  parse: 'PDF processing',
  enhance: 'Query enhancement',
  rerank: 'Rerank',
  title: 'Title generation',
  search_embed: 'Embedding lookup',
  auto_reset: 'Period reset',
  admin_reset: 'Admin manual reset',
  period_reset: 'Period reset',
  // Supervisor (AI Assistant) operations — these are the per-LLM-call
  // tier names emitted by shared/logging_config.py.  Visible in raw
  // ("Show details") mode; in collapsed mode they're rolled up into
  // a single "AI Assistant Chat" row per request_id.
  'tier_0.5_unified_check': 'Intent classify (Tier 0.5)',
  'tier_1_full_analysis':   'Request analysis (Tier 1)',
  agent_tool_classification: 'Tool selection',
  plan_generation:           'Plan generation',
  confirmation_formatter:    'Response formatting',
  transform:                 'Text transform',
  summarization:             'Summarization',
};

// Display labels for the `service` field on UsageLogs rows.
//
// The raw service tags come from quota-lambda/lambda_quota_report.py via the
// SERVICE_NAME env on each Lambda OR an explicit `service` arg on the
// /quota/report POST. Audited 2026-05-03:
//   - supervisor               → AA-lambda/* default (env unset → fallback in
//                                logging_config.py:342 → "supervisor")
//   - knowledge-base           → kb-lambda/functions/ws_chat_stream
//   - supervisor-agent-gmail   → agent-gmail Lambda (LLM signature pass on
//                                outgoing emails — see api.py:109-143)
//   - supervisor-agent-docs    → agent-docs Lambda (template understanding)
//   - supervisor-agent-mapping → agent-mapping Lambda (smart_mapping_engine)
//   - supervisor-agent-sheets/calendar/drive — env not set today, so they
//                                report under "supervisor"; if you ever set
//                                their SERVICE_NAME they'll appear here.
//   - classifier               → reserved sub-tier of supervisor (currently
//                                rolled into the parent)
//   - system                   → period-reset audit rows (NOT real usage)
const HISTORY_SERVICE_LABELS = {
  'knowledge-base': 'Knowledge Base',
  'knowledge_base': 'Knowledge Base',
  'classifier': 'Classifier',
  'system': 'Period Resets',
  'supervisor': 'AI Assistant',
  'supervisor-agent-gmail':    'Gmail Agent',
  'supervisor-agent-docs':     'Docs Agent',
  'supervisor-agent-sheets':   'Sheets Agent',
  'supervisor-agent-calendar': 'Calendar Agent',
  'supervisor-agent-drive':    'Drive Agent',
  'supervisor-agent-mapping':  'Mapping Agent',
};

// Centralised predicates so the modal and the Profile panel use the
// exact same definition of "is this a reset row?" / "is this a KB
// chat operation we should group?". If a future quota lambda starts
// emitting a different audit-only `service`, only this list changes.
const HISTORY_KB_SERVICES = new Set(['knowledge-base', 'knowledge_base']);

// Supervisor service tag used by AI Assistant chat turns.  Every
// LLM call inside one chat turn shares the same request_id (set in
// supervisor-agent shared/logging_config.py.StructuredLogger.llm_call),
// so request_id is the natural grouping key for the collapsed view —
// no time-window heuristics needed.
const HISTORY_SUPERVISOR_SERVICES = new Set(['supervisor']);
const isHistoryResetService = (svc) => (svc || '').toLowerCase() === 'system';
const isHistoryResetOperation = (op) =>
  ['auto_reset', 'admin_reset', 'period_reset'].includes((op || '').toLowerCase());

// ── Bucketing for the daily/weekly/monthly chart (Fix A) ────────────────
//
// The lambda hands us per-day `by_day` rows. For 7/14/30-day windows
// that's exactly what we want; for 90/180/365-day windows we'd be
// rendering 90+ bars that visually disappear. So we re-bucket once we
// know the window length. See comment in ProfilePage for full rationale
// — same rules and label format on purpose so the two views feel like
// the same product.
const HISTORY_CHART_GRAIN = {
  DAILY: 'daily',
  WEEKLY: 'weekly',
  BIWEEKLY: 'biweekly',
  MONTHLY: 'monthly',
};

const historyGrainForWindow = (windowDays) => {
  if (windowDays <= 30) return HISTORY_CHART_GRAIN.DAILY;
  if (windowDays <= 90) return HISTORY_CHART_GRAIN.WEEKLY;
  if (windowDays <= 180) return HISTORY_CHART_GRAIN.BIWEEKLY;
  return HISTORY_CHART_GRAIN.MONTHLY;
};

const historyGrainLabel = (grain) => ({
  [HISTORY_CHART_GRAIN.DAILY]: 'Daily',
  [HISTORY_CHART_GRAIN.WEEKLY]: 'Weekly',
  [HISTORY_CHART_GRAIN.BIWEEKLY]: 'Bi-weekly',
  [HISTORY_CHART_GRAIN.MONTHLY]: 'Monthly',
}[grain] || 'Daily');

const historyFormatBucketLabel = (key, grain) => {
  if (!key) return '';
  try {
    if (grain === HISTORY_CHART_GRAIN.MONTHLY) {
      return new Date(key + '-01T00:00:00Z')
        .toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
    }
    return new Date(key + 'T00:00:00Z')
      .toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch {
    return key;
  }
};

const historyBucketByGrain = (days, grain) => {
  if (!days || days.length === 0) return [];
  if (grain === HISTORY_CHART_GRAIN.DAILY) {
    return days.map(d => ({
      key: d.date,
      label: historyFormatBucketLabel(d.date, HISTORY_CHART_GRAIN.DAILY),
      total_tokens: d.total_tokens || 0,
      cost_usd: d.cost_usd || 0,
      calls: d.calls || 0,
    }));
  }
  const stride = grain === HISTORY_CHART_GRAIN.WEEKLY ? 7
               : grain === HISTORY_CHART_GRAIN.BIWEEKLY ? 14
               : null;
  if (stride) {
    const buckets = [];
    for (let i = 0; i < days.length; i += stride) {
      const slice = days.slice(i, i + stride);
      const startKey = slice[0].date;
      buckets.push({
        key: startKey,
        label: historyFormatBucketLabel(startKey, HISTORY_CHART_GRAIN.WEEKLY),
        total_tokens: slice.reduce((a, d) => a + (d.total_tokens || 0), 0),
        cost_usd:    slice.reduce((a, d) => a + (d.cost_usd     || 0), 0),
        calls:       slice.reduce((a, d) => a + (d.calls        || 0), 0),
      });
    }
    return buckets;
  }
  // Monthly grain.
  const byMonth = new Map();
  days.forEach(d => {
    const month = (d.date || '').slice(0, 7);
    if (!month) return;
    const cur = byMonth.get(month) || {
      key: month,
      label: historyFormatBucketLabel(month, HISTORY_CHART_GRAIN.MONTHLY),
      total_tokens: 0, cost_usd: 0, calls: 0,
    };
    cur.total_tokens += d.total_tokens || 0;
    cur.cost_usd    += d.cost_usd     || 0;
    cur.calls       += d.calls        || 0;
    byMonth.set(month, cur);
  });
  return Array.from(byMonth.values());
};

// ── Monthly history (Fix B) — same algorithm as ProfilePage ─────────
const buildHistoryMonthly = (logs, summary) => {
  const months = new Map();
  (logs || []).forEach(row => {
    if (!isHistoryResetOperation(row.operation)) return;
    if (!row.timestamp || row.timestamp.length < 7) return;
    const resetDate = new Date(row.timestamp);
    const periodEnd = new Date(Date.UTC(
      resetDate.getUTCFullYear(),
      resetDate.getUTCMonth() - 1,
      1
    ));
    const key = `${periodEnd.getUTCFullYear()}-${String(periodEnd.getUTCMonth() + 1).padStart(2, '0')}`;
    months.set(key, {
      key,
      label: historyFormatBucketLabel(key, HISTORY_CHART_GRAIN.MONTHLY),
      total_tokens: row.total_tokens || 0,
      cost_usd:     row.cost_usd     || 0,
      source: 'reset',
    });
  });
  if (summary) {
    const now = new Date();
    const curKey = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, '0')}`;
    months.set(curKey, {
      key: curKey,
      label: historyFormatBucketLabel(curKey, HISTORY_CHART_GRAIN.MONTHLY),
      total_tokens: summary.current_usage || 0,
      cost_usd:     summary.current_cost_usd || 0,
      source: 'live',
    });
  }
  return Array.from(months.values()).sort((a, b) => a.key.localeCompare(b.key));
};

// ── Activity grouping — collapse chat_stream + matching search_embed.
//
// Policy (STRICT session_id match, no fallback):
//   1. Both rows MUST carry session_id, and the values MUST match.
//      Anything else stays separate. This makes grouping deterministic
//      and impossible to "accidentally merge across sessions" —
//      different chat sessions can never collide regardless of how
//      close their timestamps are.
//   2. The 60-second time window is kept as a sanity guard for the
//      same-session case. With identical session_id but |Δt| > 60s
//      something weird is going on (orphaned embedding from a chat
//      that timed out, late retry, clock skew) — better to render
//      separately than create a misleading group.
//   3. Each embedding is paired with its NEAREST chat_stream
//      (smallest |Δt|) inside the window, so two chat turns inside
//      one session don't steal each other's embedding lookups.
//
// Backend contract this depends on:
//   - ws_chat_stream → search_knowledge_base → hybrid_search →
//     _report_embedding_usage now threads session_id all the way
//     into the /quota/report payload (see kb-lambda/shared/
//     weaviate_utils.py and functions/ws_chat_stream/...). The
//     chat_stream anchor row already carried session_id.
//
// Known limitation: rows written BEFORE the session_id-threading
// deploy have session_id=null on search_embed and will never group.
// They render as their own "AUDIT" row. New rows group correctly.
const HISTORY_TURN_WINDOW_MS = 60_000;

const groupHistoryChatTurns = (logs) => {
  if (!logs || logs.length === 0) return [];

  const isKb         = (r) => HISTORY_KB_SERVICES.has((r.service || '').toLowerCase());
  const isSupervisor = (r) => HISTORY_SUPERVISOR_SERVICES.has((r.service || '').toLowerCase());
  const ts           = (r) => new Date(r.timestamp || 0).getTime();

  // Index chat_stream anchors so the embedding-pairing pass below
  // is O(N·M) instead of O(N²) — N embeddings × M anchors, where
  // M is small in practice.
  const anchorIdxs = [];
  for (let i = 0; i < logs.length; i++) {
    const r = logs[i];
    if (isKb(r) && r.operation === 'chat_stream') anchorIdxs.push(i);
  }

  // ── Pass 1: SFXbot KB chat — pair each embedding-style child to its
  // NEAREST chat_stream anchor within the time window.
  // Returns: childIdx → anchorIdx.
  const pairedAnchorOf = new Map();
  for (let j = 0; j < logs.length; j++) {
    const c = logs[j];
    if (!isKb(c)) continue;
    if (c.operation === 'chat_stream') continue;
    // Only collapse "internal" lookups generated by the chat turn
    // (embedding/search). Non-record_only rows that aren't
    // chat_stream remain visible as their own line — they're real
    // user-facing operations (PDF parse, kb_query from REST, etc.).
    if (!c.record_only) continue;

    const cTs = ts(c);
    let bestI = -1;
    let bestDelta = Infinity;
    for (const ai of anchorIdxs) {
      const a = logs[ai];
      // STRICT: both sides MUST have session_id and they MUST match.
      // Legacy embedding rows without session_id render separately
      // (acceptable — they age out of the default window).
      if (!a.session_id || !c.session_id) continue;
      if (a.session_id !== c.session_id) continue;
      const delta = Math.abs(ts(a) - cTs);
      // 60s window guards against orphaned embeddings inside the same
      // session (e.g. chat that timed out before logging chat_stream).
      if (delta > HISTORY_TURN_WINDOW_MS) continue;
      if (delta < bestDelta) {
        bestDelta = delta;
        bestI = ai;
      }
    }
    if (bestI !== -1) pairedAnchorOf.set(j, bestI);
  }

  // ── Pass 2: Supervisor (AI Assistant) chat — group by request_id.
  //
  // Every LLM call from one chat turn (Tier 0.5 quick-check, Tier 1
  // analysis, agent/tool classifier, plan generation, response
  // formatter, …) is tagged with the SAME request_id by
  // supervisor-agent shared/logging_config.py.StructuredLogger.llm_call.
  // We pick the EARLIEST row in each group as the visible anchor (so
  // the row's timestamp matches "when the chat turn started"), absorb
  // the rest as children, and render the cluster as "AI Assistant
  // Chat".  Single-call request_ids stay as their own row — there's
  // no benefit to wrapping a 1-call group in a cluster.
  //
  // No time-window guard is needed here: request_id collisions across
  // turns are impossible (the format is `req_<UTC>_<8-hex>` and the
  // 8-hex random suffix has 2^32 possible values per second).  Time-
  // window logic is reserved for the SFXbot pairing above where the
  // child rows can lack session_id on legacy data.
  const supByReq = new Map();
  for (let i = 0; i < logs.length; i++) {
    const r = logs[i];
    if (!isSupervisor(r))   continue;
    if (!r.request_id)      continue; // can't group; render as-is
    if (!supByReq.has(r.request_id)) supByReq.set(r.request_id, []);
    supByReq.get(r.request_id).push(i);
  }
  const supChildOf  = new Set();          // indexes that get merged in
  const supAnchorOf = new Map();          // anchorIdx → [childIdx, ...]
  for (const idxs of supByReq.values()) {
    if (idxs.length < 2) continue;        // single LLM call: no rollup
    idxs.sort((a, b) => ts(logs[a]) - ts(logs[b]));
    const anchor = idxs[0];
    const kids   = idxs.slice(1);
    supAnchorOf.set(anchor, kids);
    for (const k of kids) supChildOf.add(k);
  }

  // Build the output stream in original log order so the table still
  // reads chronologically.  Anchors absorb their paired children;
  // orphaned children (KB rows without a matching chat_stream, or
  // single-call supervisor turns) render as their own row.
  const consumed = new Set(pairedAnchorOf.keys());
  const grouped  = [];
  for (let i = 0; i < logs.length; i++) {
    const row = logs[i];
    if (consumed.has(i))  continue;       // SFXbot child
    if (supChildOf.has(i)) continue;      // supervisor child

    // ── SFXbot anchor?
    if (isKb(row) && row.operation === 'chat_stream') {
      const cluster = { kind: 'cluster', clusterLabel: 'sfxbot', row: { ...row }, children: [] };
      for (const [childIdx, anchorIdx] of pairedAnchorOf.entries()) {
        if (anchorIdx !== i) continue;
        const c = logs[childIdx];
        cluster.children.push(c);
        cluster.row.input_tokens  = (cluster.row.input_tokens  || 0) + (c.input_tokens  || 0);
        cluster.row.output_tokens = (cluster.row.output_tokens || 0) + (c.output_tokens || 0);
        cluster.row.total_tokens  = (cluster.row.total_tokens  || 0) + (c.total_tokens  || 0);
        cluster.row.cost_usd      = (cluster.row.cost_usd      || 0) + (c.cost_usd      || 0);
      }
      grouped.push(cluster);
      continue;
    }

    // ── Supervisor anchor?
    if (supAnchorOf.has(i)) {
      const cluster = { kind: 'cluster', clusterLabel: 'ai_assistant', row: { ...row }, children: [] };
      for (const ci of supAnchorOf.get(i)) {
        const c = logs[ci];
        cluster.children.push(c);
        cluster.row.input_tokens  = (cluster.row.input_tokens  || 0) + (c.input_tokens  || 0);
        cluster.row.output_tokens = (cluster.row.output_tokens || 0) + (c.output_tokens || 0);
        cluster.row.total_tokens  = (cluster.row.total_tokens  || 0) + (c.total_tokens  || 0);
        cluster.row.cost_usd      = (cluster.row.cost_usd      || 0) + (c.cost_usd      || 0);
      }
      // Anchor model is the per-step model (e.g. gpt-4o-mini for the
      // first quick-check). The cluster spans multiple models so
      // showing one is misleading — wipe it; the rendering layer
      // will show "—" or a "mixed" indicator instead.
      cluster.row.model = null;
      grouped.push(cluster);
      continue;
    }

    grouped.push({ kind: 'single', row, children: [] });
  }
  return grouped;
};

// Service colour palette — used by the donut and the per-service legend.
//
// Picked so adjacent slices in the donut never share a hue (the previous
// palette only declared 4 colors with `default` catching everything else,
// which made AI Assistant + supervisor-agent-* slices indistinguishable —
// reported by user 2026-05-03 with screenshot showing "AI Assist..." and
// "supervisor..." rendering in nearly-identical slate gray).
//
// The brand navy (#26326e) is reserved for AI Assistant since it's the
// primary surface; the agent-* family uses warmer / cooler accents that
// stay legible against navy in the donut center label.
const SERVICE_COLORS = {
  'supervisor':                '#26326e',  // AI Assistant — brand navy
  'knowledge-base':            '#6366f1',  // SFXBot — indigo
  'knowledge_base':            '#6366f1',
  'classifier':                '#10b981',  // green — sub-tier of supervisor
  'supervisor-agent-gmail':    '#ef4444',  // red — Gmail's signature pass
  'supervisor-agent-docs':     '#3b82f6',  // blue — Docs
  'supervisor-agent-sheets':   '#22c55e',  // green — Sheets
  'supervisor-agent-calendar': '#f97316',  // orange — Calendar
  'supervisor-agent-drive':    '#eab308',  // amber — Drive
  'supervisor-agent-mapping':  '#a855f7',  // purple — Mapping
  'system':                    '#94a3b8',  // slate — audit/reset
  'unknown':                   '#f59e0b',
  'default':                   '#64748b',
};

const colorForService = (svc) => SERVICE_COLORS[svc] || SERVICE_COLORS.default;

const formatTokensShort = (n) => {
  const v = Number(n) || 0;
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toLocaleString();
};

const formatCostShort = (n) => {
  const v = Number(n) || 0;
  if (v === 0) return '$0.00';
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
};

const formatHistoryTimestamp = (ts) => {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString('en-US', {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
  } catch {
    return ts;
  }
};

const formatResetCountdown = (resetDate) => {
  if (!resetDate) return null;
  try {
    const diff = new Date(resetDate) - new Date();
    return Math.ceil(diff / 86_400_000);
  } catch {
    return null;
  }
};

// ── Donut chart ──────────────────────────────────────────────────────────
// Pure SVG. Slices are arc-segments computed manually (atan2 + describeArc)
// so we can label slices on the legend without a chart library.
function HistoryDonut({ slices, total, size = 180, stroke = 28 }) {
  if (!slices || slices.length === 0 || total <= 0) {
    return <div className="history-donut-empty">No data</div>;
  }
  const cx = size / 2;
  const cy = size / 2;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  let offset = 0;
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="history-donut"
      role="img"
      aria-label="Token usage by service"
    >
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill="none"
        stroke="#e5e7eb"
        strokeWidth={stroke}
      />
      {slices.map((s, i) => {
        const fraction = s.total_tokens / total;
        const dash = fraction * circumference;
        const gap = circumference - dash;
        const segment = (
          <circle
            key={s.service || i}
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke={colorForService(s.service)}
            strokeWidth={stroke}
            strokeDasharray={`${dash} ${gap}`}
            strokeDashoffset={-offset}
            transform={`rotate(-90 ${cx} ${cy})`}
            style={{ transition: 'stroke-dasharray 250ms ease' }}
          >
            <title>{`${HISTORY_SERVICE_LABELS[s.service] || s.service}: ${formatTokensShort(s.total_tokens)} (${(fraction * 100).toFixed(1)}%)`}</title>
          </circle>
        );
        offset += dash;
        return segment;
      })}
      {/* Centre label */}
      <text
        x={cx}
        y={cy - 6}
        textAnchor="middle"
        className="history-donut-center-num"
      >
        {formatTokensShort(total)}
      </text>
      <text
        x={cx}
        y={cy + 14}
        textAnchor="middle"
        className="history-donut-center-cap"
      >
        tokens
      </text>
    </svg>
  );
}

// ── Daily bar chart ──────────────────────────────────────────────────────
// Bars are <div>s instead of SVG so they can use the existing tile
// styling. Renders ≤365 columns; widths flex to fit container.
function HistoryDailyBars({ days }) {
  if (!days || days.length === 0) {
    return <div className="history-bars-empty">No daily activity</div>;
  }
  const maxTokens = Math.max(...days.map(d => d.total_tokens || 0), 1);
  return (
    <div className="history-bars">
      {days.map((d) => {
        const pct = Math.max(2, Math.round((d.total_tokens / maxTokens) * 100));
        return (
          <div
            key={d.date}
            className="history-bar-col"
            title={`${d.date} · ${formatTokensShort(d.total_tokens)} tokens · ${formatCostShort(d.cost_usd)} · ${d.calls} call(s)`}
          >
            <div className="history-bar-fill" style={{ height: `${pct}%` }} />
          </div>
        );
      })}
    </div>
  );
}

function UserHistoryModal({ target, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [windowDays, setWindowDays] = useState(30);
  const [includeResets, setIncludeResets] = useState(false);
  // Detail toggle for the activity table — same semantics as the
  // Profile panel. Off = chat_stream + search_embed grouped into a
  // single "SFXbot Chat" row. On = raw row stream.
  const [showDetails, setShowDetails] = useState(false);
  // Chart-only window (default 7d), independent from the data
  // window. See ProfilePage.TokenConsumptionPanel for the rationale —
  // mirrored here on purpose so admins recognise the same widget.
  const [chartWindowDays, setChartWindowDays] = useState(7);
  // Server-side pagination — same semantics + defaults as the
  // Profile panel. Aggregates remain full-window; only `logs` is paged.
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await quotaApi.get('/api/quota/me/history', {
        params: {
          user_id: target.user_id,
          days: windowDays,
          // Real pagination — same scheme as Profile. Aggregates
          // (totals/by_service/by_day) come back full-window so the
          // donut, monthly history, and KPI tiles stay stable across
          // pages.
          page,
          page_size: pageSize,
          // Always pull resets — the Monthly history needs them. The
          // Include-resets toggle is now a UI-only filter on the
          // activity table.
          include_resets: 'true',
        },
      });
      setData(response.data);
    } catch (err) {
      const status = err?.response?.status;
      const apiMsg = err?.response?.data?.error;
      let msg = apiMsg || err?.message || 'Failed to load history';
      // Friendly hints for the most likely failure modes.
      if (status === 403) {
        msg = 'You do not have permission to view this user\u2019s history.';
      } else if (status === 404) {
        msg = `User ${target.user_id} was not found in the quota table.`;
      }
      setError(msg);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [target.user_id, windowDays, page, pageSize]);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  // Snap back to page 1 whenever the data window or page size
  // changes — otherwise the user can be left on a phantom page.
  useEffect(() => {
    setPage(1);
  }, [windowDays, pageSize]);

  // Close on ESC — matches the existing QuotaPage modal interaction.
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const summary = data?.summary;
  const totals = data?.totals;
  // Fix C: filter Period Resets out of the donut + legend. They aren't
  // a service category — they're audit markers — so counting them
  // would double-credit the user's prior consumption. The tiny "n
  // period reset(s) excluded" hint shown in the legend keeps this
  // transparent rather than silent.
  const allByService = data?.by_service || [];
  const byService = useMemo(
    () => allByService.filter(s => !isHistoryResetService(s.service)),
    [allByService]
  );
  const resetServiceCount = useMemo(
    () => allByService.filter(s => isHistoryResetService(s.service))
      .reduce((a, s) => a + (s.calls || 0), 0),
    [allByService]
  );

  // Recent activity table still respects the user's preference, but
  // the toggle is now a UI filter — backend always returns resets.
  const allLogs = data?.logs || [];
  const logs = useMemo(
    () => (includeResets ? allLogs : allLogs.filter(r => !isHistoryResetOperation(r.operation))),
    [allLogs, includeResets]
  );
  const truncated = !!data?.truncated;

  // Fix A: choose chart grain based on the chart-window selector,
  // clamped to whatever data we actually have. Slicing the by_day
  // tail keeps the chart honest when chartWindowDays > windowDays.
  const effectiveChartDays = Math.min(chartWindowDays, windowDays);
  const grain = historyGrainForWindow(effectiveChartDays);
  const byDayBuckets = useMemo(() => {
    const allDays = data?.by_day || [];
    const days = effectiveChartDays >= allDays.length
      ? allDays
      : allDays.slice(-effectiveChartDays);
    return historyBucketByGrain(days, grain);
  }, [data, grain, effectiveChartDays]);

  // Fix B: derive Monthly history from reset snapshots + live usage.
  const monthlyHistory = useMemo(
    () => buildHistoryMonthly(allLogs, summary),
    [allLogs, summary]
  );
  const monthlyMax = useMemo(
    () => Math.max(...monthlyHistory.map(m => m.total_tokens || 0), 1),
    [monthlyHistory]
  );

  // Activity grouping (chat_stream + search_embed → "SFXbot Chat").
  const groupedRows = useMemo(
    () => (showDetails ? null : groupHistoryChatTurns(logs)),
    [logs, showDetails]
  );

  // Title prefers the backend's canonical fullname (latest from
  // UserQuotas) and falls back to whatever the row passed in.
  const headerName = (summary && summary.fullname)
    ? summary.fullname
    : (target.fullname || target.user_id);

  const pct = summary?.percentage_used ?? 0;
  const tone = pct >= 90 ? 'critical' : pct >= 75 ? 'warning' : 'healthy';
  const resetIn = formatResetCountdown(summary?.reset_date);

  // Sum of by_service total_tokens: the donut needs this for fractions
  // and it can differ from `totals.total_tokens` if include_resets
  // toggles change the row set.
  const donutTotal = useMemo(
    () => byService.reduce((acc, s) => acc + (s.total_tokens || 0), 0),
    [byService]
  );

  return (
    <div className="modal-overlay history-modal-overlay" onClick={onClose}>
      <div
        className="modal-content history-modal-content"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Token consumption history for ${headerName}`}
      >
        {/* ── Header ────────────────────────────────────────────────── */}
        <div className="history-modal-header">
          <div className="history-modal-title-block">
            <div className="history-modal-eyebrow">
              <Activity size={14} /> Token consumption history
            </div>
            {/* The raw user_id is intentionally NOT rendered as a
                visible subtitle. It used to show as e.g.
                "0479846c-832…0e476322" which is noise to admins
                looking at a name. Still kept on the title attribute
                of the heading so it's discoverable on hover, and
                returned in the modal's aria-label for screen readers. */}
            <h2 className="history-modal-title" title={`User ID: ${target.user_id}`}>
              {headerName}
            </h2>
            {summary && summary.is_active === false && (
              <div className="history-modal-subtitle">
                <span className="history-pill history-pill-inactive">Inactive</span>
              </div>
            )}
          </div>
          <div className="history-modal-controls">
            <select
              className="history-window-select"
              value={windowDays}
              onChange={(e) => setWindowDays(Number(e.target.value))}
              disabled={loading}
              aria-label="History window"
            >
              <option value={7}>Last 7 days</option>
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
              <option value={180}>Last 180 days</option>
              <option value={365}>Last 365 days</option>
            </select>
            <label className="history-toggle">
              <input
                type="checkbox"
                checked={includeResets}
                onChange={(e) => setIncludeResets(e.target.checked)}
                disabled={loading}
              />
              <span>Include resets</span>
            </label>
            <button
              className="history-refresh-btn"
              onClick={fetchHistory}
              disabled={loading}
              title="Refresh history"
              aria-label="Refresh history"
            >
              <RefreshCw size={18} className={loading ? 'spin' : ''} />
              <span className="history-btn-text">Refresh</span>
            </button>
            <button
              className="history-close-btn"
              onClick={onClose}
              title="Close"
              aria-label="Close history"
            >
              <X size={18} />
              <span className="history-btn-text">Close</span>
            </button>
          </div>
        </div>

        {/* ── Body ─────────────────────────────────────────────────── */}
        <div className="history-modal-body">
          {error && (
            <div className="history-error">
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}

          {loading && !data && (
            <div className="history-loading">
              <RefreshCw size={18} className="spin" />
              <span>Loading history…</span>
            </div>
          )}

          {/* KPI tiles — current period + window cost */}
          {summary && (
            <div className="history-kpi-grid">
              <div className={`history-kpi-tile tone-${tone}`}>
                <div className="history-kpi-label">Current period</div>
                <div className="history-kpi-value">
                  {formatTokensShort(summary.current_usage)}
                  <span className="history-kpi-divider"> / </span>
                  <span className="history-kpi-limit">
                    {formatTokensShort(summary.monthly_limit)}
                  </span>
                </div>
                <div className="history-kpi-bar-track">
                  <div
                    className={`history-kpi-bar-fill tone-${tone}`}
                    style={{ width: `${Math.min(100, pct)}%` }}
                  />
                </div>
                <div className="history-kpi-meta">
                  {pct.toFixed(1)}% used · {formatTokensShort(summary.remaining_tokens)} left
                </div>
              </div>

              <div className="history-kpi-tile">
                <div className="history-kpi-label">
                  <Clock size={12} /> Resets
                </div>
                <div className="history-kpi-value">
                  {resetIn !== null && resetIn > 0
                    ? `${resetIn}d`
                    : (resetIn !== null ? 'Now' : '—')}
                </div>
                <div className="history-kpi-meta">
                  {summary.reset_date
                    ? new Date(summary.reset_date).toLocaleDateString('en-US', {
                        month: 'short', day: 'numeric', year: 'numeric'
                      })
                    : 'No reset scheduled'}
                </div>
              </div>

              <div className="history-kpi-tile">
                <div className="history-kpi-label">Tier</div>
                <div className="history-kpi-value history-kpi-value-text">
                  {summary.tier || 'free'}
                </div>
                <div className="history-kpi-meta">
                  {formatCostShort(summary.current_cost_usd || 0)} this period
                </div>
              </div>

              {totals && (
                <div className="history-kpi-tile">
                  <div className="history-kpi-label">
                    <BarChart3 size={12} /> Last {data.window_days}d
                  </div>
                  <div className="history-kpi-value">
                    {formatTokensShort(totals.total_tokens)}
                  </div>
                  <div className="history-kpi-meta">
                    {totals.call_count} call{totals.call_count === 1 ? '' : 's'} · {formatCostShort(totals.cost_usd)}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* AI Assistant activity — per-user mirror of the admin LogsPage
              "Conversation Threads & Requests" block. Always rendered when
              the new field is present so the section appears even at zero
              counts (which is itself useful info: "this user never used
              the AI Assistant in the last 30 days"). The 24h/7d/30d windows
              are independent of the chart-window selector above — same
              rolling totals discipline as the admin view. */}
          {data?.ai_assistant_activity && (
            <div className="history-ai-activity">
              <div className="history-ai-activity-header">
                <Activity size={14} /> AI Assistant activity
                <span className="history-ai-activity-hint">
                  · rolling totals for THIS user, independent of the window selector
                </span>
              </div>
              <div className="history-ai-activity-grid">
                {[
                  { key: 'today',      label: 'Today (24h)' },
                  { key: 'this_week',  label: 'This Week (7d)' },
                  { key: 'this_month', label: 'This Month (30d)' },
                ].map((p) => {
                  const a = data.ai_assistant_activity[p.key] || {};
                  return (
                    <div key={p.key} className="history-ai-activity-tile">
                      <div className="history-ai-activity-period">{p.label}</div>
                      <div className="history-ai-activity-row">
                        <span className="history-ai-activity-num">
                          {(a.conversations || 0).toLocaleString()}
                        </span>
                        <span className="history-ai-activity-lbl">
                          conversation{(a.conversations || 0) === 1 ? '' : 's'}
                        </span>
                      </div>
                      <div className="history-ai-activity-row">
                        <span className="history-ai-activity-num">
                          {(a.requests || 0).toLocaleString()}
                        </span>
                        <span className="history-ai-activity-lbl">
                          request{(a.requests || 0) === 1 ? '' : 's'}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* SFXBot activity — exact same shape/layout as the AI Assistant
              block above, just sourced from the `sfxbot_activity` field
              (service=knowledge-base in UsageLogs). The `--sfxbot`
              modifier shifts the icon + accent to indigo so the two
              blocks read as related-but-distinct surfaces; the matching
              indigo also lines up with the SFXBot pie-chart slice color
              (SERVICE_COLORS['knowledge-base']) for consistency across
              the page. */}
          {data?.sfxbot_activity && (
            <div className="history-ai-activity history-ai-activity--sfxbot">
              <div className="history-ai-activity-header">
                <Bot size={14} /> SFX Bot activity
                <span className="history-ai-activity-hint">
                  · rolling totals for THIS user, independent of the window selector
                </span>
              </div>
              <div className="history-ai-activity-grid">
                {[
                  { key: 'today',      label: 'Today (24h)' },
                  { key: 'this_week',  label: 'This Week (7d)' },
                  { key: 'this_month', label: 'This Month (30d)' },
                ].map((p) => {
                  const a = data.sfxbot_activity[p.key] || {};
                  return (
                    <div key={p.key} className="history-ai-activity-tile">
                      <div className="history-ai-activity-period">{p.label}</div>
                      <div className="history-ai-activity-row">
                        <span className="history-ai-activity-num">
                          {(a.conversations || 0).toLocaleString()}
                        </span>
                        <span className="history-ai-activity-lbl">
                          conversation{(a.conversations || 0) === 1 ? '' : 's'}
                        </span>
                      </div>
                      <div className="history-ai-activity-row">
                        <span className="history-ai-activity-num">
                          {(a.requests || 0).toLocaleString()}
                        </span>
                        <span className="history-ai-activity-lbl">
                          request{(a.requests || 0) === 1 ? '' : 's'}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Charts — donut (by service, resets excluded) + auto-grain
              bar strip. The donut intentionally drops Period Resets so
              the breakdown reflects what the user actually consumed
              against; the legend hint surfaces how many reset rows
              exist in the window so the omission isn't silent. */}
          {data && (totals?.call_count > 0 || byService.length > 0) && (
            <div className="history-charts-row">
              <div className="history-chart-card">
                <div className="history-chart-title">
                  Tokens by service
                  {resetServiceCount > 0 && (
                    <span className="history-chart-hint">
                      · {resetServiceCount} period reset{resetServiceCount === 1 ? '' : 's'} excluded
                    </span>
                  )}
                </div>
                <div className="history-donut-wrap">
                  <HistoryDonut slices={byService} total={donutTotal} />
                  <ul className="history-donut-legend">
                    {byService.map((s) => {
                      const fraction = donutTotal > 0
                        ? (s.total_tokens / donutTotal) * 100
                        : 0;
                      return (
                        <li key={s.service}>
                          <span
                            className="history-legend-swatch"
                            style={{ background: colorForService(s.service) }}
                          />
                          <span className="history-legend-name">
                            {HISTORY_SERVICE_LABELS[s.service] || s.service}
                          </span>
                          <span className="history-legend-pct">
                            {fraction.toFixed(1)}%
                          </span>
                          <span className="history-legend-meta">
                            {formatTokensShort(s.total_tokens)} · {formatCostShort(s.cost_usd)}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              </div>

              <div className="history-chart-card history-chart-card-bars">
                <div className="history-chart-title">
                  <TrendingUp size={14} /> {historyGrainLabel(grain)} usage
                  <span className="history-chart-hint">
                    {byDayBuckets.length} bar{byDayBuckets.length === 1 ? '' : 's'} · {effectiveChartDays}d window
                  </span>
                  <select
                    className="history-chart-window-select"
                    value={chartWindowDays}
                    onChange={(e) => setChartWindowDays(Number(e.target.value))}
                    disabled={loading}
                    aria-label="Chart window"
                    title="Bar chart window — independent from the data window above"
                  >
                    <option value={7}   disabled={windowDays < 7}>7d</option>
                    <option value={14}  disabled={windowDays < 14}>14d</option>
                    <option value={30}  disabled={windowDays < 30}>30d</option>
                    <option value={90}  disabled={windowDays < 90}>90d</option>
                    <option value={180} disabled={windowDays < 180}>180d</option>
                    <option value={365} disabled={windowDays < 365}>365d</option>
                  </select>
                </div>
                <HistoryDailyBars days={byDayBuckets.map(b => ({
                  date: b.label,
                  total_tokens: b.total_tokens,
                  cost_usd: b.cost_usd,
                  calls: b.calls,
                }))} />
                <div className="history-chart-axis">
                  {byDayBuckets.length > 0 && <span>{byDayBuckets[0].label}</span>}
                  {byDayBuckets.length > 1 && <span>{byDayBuckets[byDayBuckets.length - 1].label}</span>}
                </div>
              </div>
            </div>
          )}

          {/* Monthly history — Fix B. Authoritative per-month view
              built from period_reset snapshots + live current usage.
              Always renders when there's at least one month of data
              so admins can sanity-check the user's billing pattern
              regardless of which window they picked above. */}
          {monthlyHistory.length > 0 && (
            <div className="history-section history-monthly-section">
              <div className="history-section-title">
                <BarChart3 size={14} />
                Monthly history
                <span className="history-chart-hint">
                  · from period resets · {monthlyHistory.length} month{monthlyHistory.length === 1 ? '' : 's'}
                </span>
              </div>
              {/* Same horizontal layout as the daily-usage chart:
                  flex:1 columns that stretch to fill the card so a
                  small number of months read as a confident chart
                  (not as decoration), with the same softly dashed
                  baseline. The value + month label sit BELOW each
                  bar (vs floating above) because months are
                  multi-character labels and need horizontal room. */}
              <div className="history-monthly-grid">
                {monthlyHistory.map(m => {
                  const pct = Math.max(2, Math.round((m.total_tokens / monthlyMax) * 100));
                  return (
                    <div
                      key={m.key}
                      className={`history-monthly-col ${m.source === 'live' ? 'is-live' : ''}`}
                      title={`${m.label}${m.source === 'live' ? ' (in progress)' : ''} · ${formatTokensShort(m.total_tokens)} tokens · ${formatCostShort(m.cost_usd)}`}
                    >
                      <div className="history-monthly-bar-track">
                        <div className="history-monthly-bar-fill" style={{ height: `${pct}%` }} />
                      </div>
                      <div className="history-monthly-num">{formatTokensShort(m.total_tokens)}</div>
                      <div className="history-monthly-label">
                        {m.label}
                        {m.source === 'live' && <span className="history-monthly-live-pill">now</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Recent activity table — same render strategy as Profile:
              default mode collapses chat_stream + matching search_embed
              into "SFXbot Chat" rows; "Show details" exposes the raw
              row stream (useful for debugging billing or audit chains). */}
          {data && (
            <div className="history-section">
              <div className="history-section-title">
                Recent activity
                <span className="history-section-hint">
                  {showDetails
                    ? '\u00b7 raw events (every LLM call shown separately)'
                    : '\u00b7 1 row per chat turn (KB embedding lookups + AI Assistant LLM steps merged in)'}
                </span>
                <label
                  className="history-toggle history-toggle-inline"
                  title={
                    showDetails
                      ? 'Uncheck to roll up each chat turn into a single row (SFXbot embedding lookups + AI Assistant Tier-0.5/Tier-1/classifier/planner/formatter calls).'
                      : 'Check to expand each chat turn into its raw events (chat + embedding lookups for SFXbot; per-LLM-call rows for AI Assistant).'
                  }
                >
                  <input
                    type="checkbox"
                    checked={showDetails}
                    onChange={(e) => setShowDetails(e.target.checked)}
                    disabled={loading}
                  />
                  <span>Show details</span>
                </label>
                {truncated && (
                  <span className="history-truncated-hint">
                    showing latest {allLogs.length} of {data.logs_total_in_window}
                  </span>
                )}
              </div>
              {logs.length === 0 ? (
                <div className="history-empty">
                  {loading ? 'Loading…' : 'No usage recorded in this window.'}
                </div>
              ) : (
                <div className="history-log-table-wrap">
                  <table className="history-log-table">
                    <thead>
                      <tr>
                        <th>When</th>
                        <th>Service</th>
                        <th>Operation</th>
                        <th className="num">Input</th>
                        <th className="num">Output</th>
                        <th className="num">Total</th>
                        <th className="num">Cost</th>
                        <th>Model</th>
                      </tr>
                    </thead>
                    <tbody>
                      {showDetails
                        ? logs.map((row) => {
                            const opLabel = HISTORY_OPERATION_LABELS[row.operation] || row.operation || '—';
                            const isReset = isHistoryResetOperation(row.operation);
                            return (
                              <tr
                                key={row.id}
                                className={isReset ? 'row-reset' : (row.record_only ? 'row-record-only' : '')}
                              >
                                <td className="cell-when">{formatHistoryTimestamp(row.timestamp)}</td>
                                <td>{HISTORY_SERVICE_LABELS[row.service] || row.service || '—'}</td>
                                <td>
                                  <span>{opLabel}</span>
                                  {row.record_only && (
                                    <span
                                      className="history-badge history-badge-audit"
                                      title="Audit only — this event (e.g. an embedding lookup performed during a chat turn) is logged for cost analytics but is NOT deducted from the user’s monthly token quota."
                                    >
                                      audit
                                    </span>
                                  )}
                                  {isReset && (
                                    <span className="history-badge history-badge-reset" title="Period reset snapshot — captured the moment the previous billing period closed.">
                                      reset
                                    </span>
                                  )}
                                </td>
                                <td className="num">{formatTokensShort(row.input_tokens)}</td>
                                <td className="num">{formatTokensShort(row.output_tokens)}</td>
                                <td className="num strong">{formatTokensShort(row.total_tokens)}</td>
                                <td className="num cost">{formatCostShort(row.cost_usd)}</td>
                                <td className="cell-model">{row.model || '—'}</td>
                              </tr>
                            );
                          })
                        : (groupedRows || []).map((entry, idx) => {
                            const row = entry.row;
                            const isCluster = entry.kind === 'cluster';
                            const isAiCluster  = isCluster && entry.clusterLabel === 'ai_assistant';
                            const isSfxCluster = isCluster && entry.clusterLabel !== 'ai_assistant'; // default = sfxbot for legacy clusters
                            const isReset = isHistoryResetOperation(row.operation);
                            const opLabel = isAiCluster
                              ? 'AI Assistant Chat'
                              : isSfxCluster
                                ? 'SFXbot Chat'
                                : (HISTORY_OPERATION_LABELS[row.operation] || row.operation || '—');
                            const childCount = entry.children?.length || 0;
                            // Per-cluster rollup-badge wording: SFXbot
                            // bundles "internal embedding lookups";
                            // AI Assistant bundles "LLM steps" (Tier 0.5,
                            // Tier 1, classifier, planner, formatter, …).
                            const rollupBadgeText = isAiCluster
                              ? `+${childCount} step${childCount === 1 ? '' : 's'}`
                              : `+${childCount} internal`;
                            const rollupBadgeTitle = isAiCluster
                              ? `This row already includes the tokens from ${childCount + 1} LLM call${childCount === 0 ? '' : 's'} that ran for this AI Assistant chat turn (Tier 0.5 quick-check, Tier 1 analysis, agent/tool classifier, plan generation, response formatter, etc.). Toggle "Show details" to see each step as a separate row.`
                              : `This row already includes the tokens from ${childCount} internal embedding lookup${childCount === 1 ? '' : 's'} that ran for this chat turn. Toggle "Show details" if you want to see them as separate rows.`;
                            return (
                              <tr
                                key={row.id || `${entry.kind}-${idx}`}
                                className={isReset ? 'row-reset' : (row.record_only ? 'row-record-only' : '')}
                              >
                                <td className="cell-when">{formatHistoryTimestamp(row.timestamp)}</td>
                                <td>{HISTORY_SERVICE_LABELS[row.service] || row.service || '—'}</td>
                                <td>
                                  <span>{opLabel}</span>
                                  {isCluster && childCount > 0 && (
                                    <span
                                      className="history-badge history-badge-rollup"
                                      title={rollupBadgeTitle}
                                    >
                                      {rollupBadgeText}
                                    </span>
                                  )}
                                  {!isCluster && row.record_only && (
                                    <span
                                      className="history-badge history-badge-audit"
                                      title="Audit only — this event (e.g. an embedding lookup performed during a chat turn) is logged for cost analytics but is NOT deducted from the user’s monthly token quota."
                                    >
                                      audit
                                    </span>
                                  )}
                                  {isReset && (
                                    <span className="history-badge history-badge-reset" title="Period reset snapshot — captured the moment the previous billing period closed.">
                                      reset
                                    </span>
                                  )}
                                </td>
                                <td className="num">{formatTokensShort(row.input_tokens)}</td>
                                <td className="num">{formatTokensShort(row.output_tokens)}</td>
                                <td className="num strong">{formatTokensShort(row.total_tokens)}</td>
                                <td className="num cost">{formatCostShort(row.cost_usd)}</td>
                                <td className="cell-model">
                                  {isAiCluster
                                    ? <span className="history-cell-mixed" title="This chat turn ran across multiple LLMs (e.g. gpt-4o-mini for quick-check + classifier, gpt-4.1-mini for Tier 1 analysis, gpt-4.1 for plan generation). Expand &ldquo;Show details&rdquo; to see the per-step model.">mixed</span>
                                    : (row.model || '—')}
                                </td>
                              </tr>
                            );
                          })
                      }
                    </tbody>
                  </table>
                  {/* Pagination footer — same shape as Profile so the
                      two views feel like one component. Hidden when
                      the response is single-page so single-event users
                      get no visual noise. */}
                  {data?.pagination?.mode === 'paginated' && data.pagination.total_pages > 1 && (
                    <div className="history-pagination">
                      <div className="history-pagination-info">
                        Showing{' '}
                        <strong>{(data.pagination.page - 1) * data.pagination.page_size + 1}</strong>
                        {'\u2013'}
                        <strong>{Math.min(data.pagination.page * data.pagination.page_size, data.pagination.total)}</strong>
                        {' '}of <strong>{data.pagination.total}</strong> events
                      </div>
                      <div className="history-pagination-controls">
                        <select
                          className="history-page-size-select"
                          value={pageSize}
                          onChange={(e) => setPageSize(Number(e.target.value))}
                          disabled={loading}
                          aria-label="Rows per page"
                          title="Rows per page"
                        >
                          <option value={10}>10 / page</option>
                          <option value={25}>25 / page</option>
                          <option value={50}>50 / page</option>
                          <option value={100}>100 / page</option>
                        </select>
                        <button
                          type="button"
                          className="history-page-btn"
                          onClick={() => setPage(p => Math.max(1, p - 1))}
                          disabled={loading || data.pagination.page <= 1}
                        >
                          ‹ Prev
                        </button>
                        <span className="history-page-indicator">
                          Page {data.pagination.page} of {data.pagination.total_pages}
                        </span>
                        <button
                          type="button"
                          className="history-page-btn"
                          onClick={() => setPage(p => Math.min(data.pagination.total_pages, p + 1))}
                          disabled={loading || !data.pagination.has_more}
                        >
                          Next ›
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default QuotaPage;
