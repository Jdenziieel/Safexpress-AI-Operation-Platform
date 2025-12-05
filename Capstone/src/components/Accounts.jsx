
import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Search, UserPlus, Pencil, UserX, UserCheck, Users, Filter, ArrowUpDown, X, RefreshCw, ClipboardList } from 'lucide-react';
import api from '../api';
import '../css/Accounts.css';

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

const StatusBadge = ({ status }) => {
  const statusClass = status === 'Active' ? 'status-badge-active' : 'status-badge-inactive';
  return <span className={`status-badge ${statusClass}`}>{status}</span>;
};

function Accounts() {
  const navigate = useNavigate();
  const location = useLocation();
  const [accounts, setAccounts] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [page, setPage] = useState(1);
  const [showDeactivated, setShowDeactivated] = useState(false);
  const [sortField, setSortField] = useState('fullname');
  const [sortOrder, setSortOrder] = useState('asc');
  const [roleFilter, setRoleFilter] = useState('all');
  const [showFilters, setShowFilters] = useState(false);
  const [showOnboardingModal, setShowOnboardingModal] = useState(false);
  const [onboardingData, setOnboardingData] = useState({
    fullName: '',
    gmail: '',
    role: 'user'
  });
  const [onboardingLoading, setOnboardingLoading] = useState(false);
  const [onboardingMessage, setOnboardingMessage] = useState({ type: '', text: '' });
  const accountsPerPage = 10;

  // Fetch accounts from the database
  const fetchAccounts = async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const response = await api.get('/api/users/');
      if (response.data?.users) {
        setAccounts(response.data.users);
      }
    } catch (error) {
      console.error('Error fetching accounts:', error);
      setLoadError(error.response?.data?.error || 'Failed to load accounts. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  // Load accounts on mount
  useEffect(() => {
    fetchAccounts();
  }, []);

  // Handle updated account from EditAccount page
  useEffect(() => {
    if (location.state?.updatedAccount) {
      const updatedAccount = location.state.updatedAccount;
      setAccounts(prevAccounts =>
        prevAccounts.map(account =>
          account.id === updatedAccount.id ? updatedAccount : account
        )
      );
      
      // Show success message
      if (location.state.message) {
        alert(location.state.message);
      }
      
      // Clear the state
      window.history.replaceState({}, document.title);
    }
  }, [location.state]);

  const handleDeactivate = async (accountId, accountName) => {
    if (window.confirm(`Are you sure you want to deactivate this account?\n\n${accountName}`)) {
      try {
        await api.delete(`/api/users/${accountId}/deactivate/`);
        setAccounts(prevAccounts =>
          prevAccounts.map(account =>
            account.id === accountId
              ? { ...account, is_active: false }
              : account
          )
        );
        console.log(`Account ${accountId} deactivated`);
      } catch (error) {
        console.error('Error deactivating account:', error);
        alert(error.response?.data?.error || 'Failed to deactivate account.');
      }
    }
  };

  const handleActivate = async (accountId, accountName) => {
    if (window.confirm(`Are you sure you want to activate this account?\n\n${accountName}`)) {
      try {
        await api.patch(`/api/users/${accountId}/`, { is_active: true });
        setAccounts(prevAccounts =>
          prevAccounts.map(account =>
            account.id === accountId
              ? { ...account, is_active: true }
              : account
          )
        );
        console.log(`Account ${accountId} activated`);
      } catch (error) {
        console.error('Error activating account:', error);
        alert(error.response?.data?.error || 'Failed to activate account.');
      }
    }
  };

  const handleEdit = (account) => {
    navigate('/edit-account', { state: { account } });
  };

  const handleOnboardingSubmit = async (e) => {
    e.preventDefault();
    setOnboardingLoading(true);
    setOnboardingMessage({ type: '', text: '' });

    try {
      const response = await api.post('/api/users/onboard/', {
        gmail: onboardingData.gmail,
        fullname: onboardingData.fullName,
        role: onboardingData.role.toLowerCase()  // Convert to lowercase for backend
      });

      setOnboardingMessage({
        type: 'success',
        text: `✅ User ${onboardingData.fullName} created successfully!`
      });

      // Add new account to the list (use the user data from response)
      if (response.data.user) {
        setAccounts(prevAccounts => [...prevAccounts, response.data.user]);
      }

      // Reset form after 2 seconds
      setTimeout(() => {
        setOnboardingData({ fullName: '', gmail: '', role: 'user' });
        setShowOnboardingModal(false);
        setOnboardingMessage({ type: '', text: '' });
      }, 2000);
    } catch (error) {
      console.error('Error creating user:', error);
      setOnboardingMessage({
        type: 'error',
        text: error.response?.data?.error || 'Failed to create user. Please try again.'
      });
    } finally {
      setOnboardingLoading(false);
    }
  };

  // Filter by active/inactive status first (use is_active from database)
  const statusFilteredAccounts = accounts.filter(account => 
    showDeactivated ? !account.is_active : account.is_active
  );

  // Then apply role filter
  const roleFilteredAccounts = roleFilter === 'all' 
    ? statusFilteredAccounts 
    : statusFilteredAccounts.filter(account => account.role?.toLowerCase() === roleFilter.toLowerCase());

  // Then apply search filter (use fullname and gmail from database)
  const searchFilteredAccounts = roleFilteredAccounts.filter(
    (account) =>
      (account.fullname?.toLowerCase() || '').includes(searchTerm.toLowerCase()) ||
      (account.gmail?.toLowerCase() || '').includes(searchTerm.toLowerCase()) ||
      (account.role?.toLowerCase() || '').includes(searchTerm.toLowerCase())
  );

  // Sort the filtered accounts
  const filteredAccounts = [...searchFilteredAccounts].sort((a, b) => {
    let aVal = a[sortField] || '';
    let bVal = b[sortField] || '';
    
    if (sortField === 'fullname' || sortField === 'gmail' || sortField === 'role') {
      aVal = aVal.toLowerCase();
      bVal = bVal.toLowerCase();
    }
    
    if (aVal < bVal) return sortOrder === 'asc' ? -1 : 1;
    if (aVal > bVal) return sortOrder === 'asc' ? 1 : -1;
    return 0;
  });

  const handleSort = (field) => {
    if (sortField === field) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortOrder('asc');
    }
    setPage(1);
  };

  const totalPages = Math.ceil(filteredAccounts.length / accountsPerPage);
  const startIdx = (page - 1) * accountsPerPage;
  const endIdx = startIdx + accountsPerPage;
  const currentAccounts = filteredAccounts.slice(startIdx, endIdx);

  return (
    <div className="accounts-page">
      <div className="accounts-container">
        <div className="accounts-header-row">
          <div>
            <h1 className="accounts-header-title">
              {showDeactivated ? 'Deactivated Accounts' : 'Accounts'}
            </h1>
            <div className="accounts-header-subtitle">
              {showDeactivated 
                ? 'View and manage deactivated accounts.' 
                : 'Manage all active user accounts in the system.'}
            </div>
          </div>
          <div className="accounts-header-actions">
            <ActionButton 
              icon={ClipboardList} 
              className='accounts-header-action-button-logs'
              onClick={() => navigate('/admin-activity-logs')}
            >
              Activity Logs
            </ActionButton>
            <ActionButton 
              icon={Filter} 
              className='accounts-header-action-button-filter'
              onClick={() => setShowFilters(!showFilters)}
            >
              {showFilters ? 'Hide Filters' : 'Show Filters'}
            </ActionButton>
            <ActionButton 
              icon={showDeactivated ? Users : UserX} 
              className='accounts-header-action-button-toggle'
              onClick={() => {
                setShowDeactivated(!showDeactivated);
                setPage(1);
                setSearchTerm('');
              }}
            >
              {showDeactivated ? 'View Active' : 'View Deactivated'}
            </ActionButton>
            <ActionButton 
              icon={UserPlus} 
              className='accounts-header-action-button-onboarding'
              onClick={() => setShowOnboardingModal(true)}
            >
              Onboard Account
            </ActionButton>
          </div>
        </div>

        {showFilters && (
          <div className="filter-panel">
            <div className="filter-panel-content">
              <div className="filter-field">
                <label className="filter-label">Role</label>
                <select 
                  value={roleFilter} 
                  onChange={(e) => { setRoleFilter(e.target.value); setPage(1); }}
                  className="filter-select"
                >
                  <option value="all">All Roles</option>
                  <option value="admin">Admin</option>
                  <option value="manager">Manager</option>
                  <option value="user">User</option>
                </select>
              </div>
              <div className="filter-field">
                <label className="filter-label">Sort By</label>
                <select 
                  value={sortField} 
                  onChange={(e) => { setSortField(e.target.value); setPage(1); }}
                  className="filter-select"
                >
                  <option value="fullname">Name</option>
                  <option value="gmail">Email</option>
                  <option value="role">Role</option>
                  <option value="created_at">Date Created</option>
                </select>
              </div>
              <div className="filter-field">
                <label className="filter-label">Order</label>
                <select 
                  value={sortOrder} 
                  onChange={(e) => { setSortOrder(e.target.value); setPage(1); }}
                  className="filter-select"
                >
                  <option value="asc">Ascending</option>
                  <option value="desc">Descending</option>
                </select>
              </div>
              <div>
                <button 
                  onClick={() => { setRoleFilter('all'); setSortField('fullname'); setSortOrder('asc'); setPage(1); }}
                  className="reset-filters-btn"
                >
                  Reset Filters
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Search Bar - Outside Card */}
        <div className="search-container" style={{ marginBottom: 24 }}>
          <Search size={22} className="search-icon" />
          <input
            type="text"
            placeholder="Search by name, email, or role..."
            className="search-input"
            value={searchTerm}
            onChange={(e) => {
              setSearchTerm(e.target.value);
              setPage(1);
            }}
          />
        </div>

        {/* Table */}
        <div style={{ marginBottom: 24 }}>
          {isLoading ? (
            <div style={{ textAlign: 'center', padding: '2rem', color: '#64748b' }}>
              <RefreshCw size={24} className="spin" style={{ animation: 'spin 1s linear infinite' }} />
              <p>Loading accounts...</p>
            </div>
          ) : loadError ? (
            <div style={{ textAlign: 'center', padding: '2rem', color: '#ef4444' }}>
              <p>{loadError}</p>
              <button onClick={fetchAccounts} style={{ marginTop: '1rem', padding: '8px 16px', background: '#26326e', color: '#fff', border: 'none', borderRadius: '6px', cursor: 'pointer' }}>
                Retry
              </button>
            </div>
          ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '1.05rem' }}>
              <colgroup>
                <col style={{ width: '35%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '20%' }} />
                <col style={{ width: '15%' }} />
              </colgroup>
              <thead>
                <tr style={{ background: '#f8fafc', color: '#26326e', fontWeight: 700 }}>
                  <th 
                    onClick={() => handleSort('fullname')} 
                    style={{ padding: '10px 16px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem', cursor: 'pointer', userSelect: 'none' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      Name
                      <ArrowUpDown size={16} style={{ opacity: sortField === 'fullname' ? 1 : 0.3 }} />
                    </div>
                  </th>
                  <th style={{ padding: '10px 8px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem' }}>Status</th>
                  <th 
                    onClick={() => handleSort('role')} 
                    style={{ padding: '10px 8px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem', cursor: 'pointer', userSelect: 'none' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      Role
                      <ArrowUpDown size={16} style={{ opacity: sortField === 'role' ? 1 : 0.3 }} />
                    </div>
                  </th>
                  <th style={{ padding: '10px 8px', fontWeight: 700, textAlign: 'center', fontSize: '1.05rem' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {currentAccounts.length === 0 ? (
                  <tr>
                    <td colSpan="4" style={{ textAlign: 'center', color: '#64748b', fontStyle: 'italic', padding: '2rem' }}>
                      {showDeactivated ? 'No Deactivated Accounts' : 'No Active Accounts'}
                    </td>
                  </tr>
                ) : (
                  currentAccounts.map((account, idx) => (
                    <tr key={startIdx + idx} style={{ borderBottom: '1px solid #e2e8f0', background: idx % 2 === 0 ? '#fff' : '#f8fafc' }}>
                      <td style={{ padding: '16px 16px', fontWeight: 600, color: '#26326e', textAlign: 'left' }}>
                        <div>{account.fullname}</div>
                        <div style={{ fontWeight: 400, color: '#6b7280', fontSize: '0.98rem' }}>{account.gmail}</div>
                      </td>
                      <td style={{ padding: '16px 16px', textAlign: 'left' }}>
                        <StatusBadge status={account.is_active ? 'Active' : 'Inactive'} />
                      </td>
                      <td style={{ padding: '16px 16px', textAlign: 'left', color: '#475569', textTransform: 'capitalize' }}>{account.role}</td>
                      <td style={{ padding: '16px 16px', textAlign: 'center' }}>
                        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 10 }}>
                          <button 
                            style={{ padding: '8px', borderRadius: '9999px', background: '#fff', color: '#64748b', border: '1px solid #e2e8f0', cursor: 'pointer', transition: 'all 0.2s' }} 
                            aria-label="Edit"
                            title="Edit account"
                            onClick={() => handleEdit(account)}
                          >
                            <Pencil size={18} />
                          </button>
                          {showDeactivated ? (
                            <button 
                              style={{ 
                                padding: '8px', 
                                borderRadius: '9999px', 
                                background: '#fff', 
                                color: '#16a34a', 
                                border: '1px solid #e2e8f0', 
                                cursor: 'pointer', 
                                transition: 'all 0.2s'
                              }} 
                              aria-label="Activate"
                              title="Activate account"
                              onClick={() => handleActivate(account.id, account.fullname)}
                            >
                              <UserCheck size={18} />
                            </button>
                          ) : (
                            <button 
                              style={{ 
                                padding: '8px', 
                                borderRadius: '9999px', 
                                background: '#fff', 
                                color: '#ef4444', 
                                border: '1px solid #e2e8f0', 
                                cursor: 'pointer', 
                                transition: 'all 0.2s'
                              }} 
                              aria-label="Deactivate"
                              title="Deactivate account"
                              onClick={() => handleDeactivate(account.id, account.fullname)}
                            >
                              <UserX size={18} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}  
        </div>

        {/* Pagination - Outside Card */}
        <div className='auditlogs-pagination-row'>
          <div className='auditlogs-pagination-info'>
            Showing <span style={{ fontWeight: 700 }}>{startIdx + 1}</span> to <span style={{ fontWeight: 700 }}>{Math.min(endIdx, filteredAccounts.length)}</span> of <span style={{ fontWeight: 700 }}>{filteredAccounts.length}</span> results
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <button
              className="auditlogs-pagination-btn"
              disabled={page === 1}
              onClick={() => setPage(page - 1)}
            >
              <span className="auditlogs-pagination-arrow">
                <svg width="18" height="18" viewBox="0 0 18 18" stroke="currentColor" fill="none">
                  <path d="M12 3l-6 6 6 6" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </span>
            </button>
            <span className="auditlogs-pagination-info">Page {page} of {totalPages}</span>
            <button
              className="auditlogs-pagination-btn"
              disabled={page === totalPages || totalPages === 0}
              onClick={() => setPage(page + 1)}
            >
              <span className="auditlogs-pagination-arrow">
                <svg width="18" height="18" viewBox="0 0 18 18" stroke="currentColor" fill="none">
                  <path d="M6 3l6 6-6 6" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </span>
            </button>
          </div>
        </div>
      </div>

      {/* Onboarding Modal */}
      {showOnboardingModal && (
        <div className="modal-overlay" onClick={() => setShowOnboardingModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">Onboard New Account</h2>
              <button 
                className="modal-close-btn" 
                onClick={() => {
                  setShowOnboardingModal(false);
                  setOnboardingData({ fullName: '', gmail: '', role: 'user' });
                  setOnboardingMessage({ type: '', text: '' });
                }}
              >
                <X size={20} />
              </button>
            </div>

            {onboardingMessage.text && (
              <div className={`modal-message ${onboardingMessage.type === 'success' ? 'modal-message-success' : 'modal-message-error'}`}>
                {onboardingMessage.text}
              </div>
            )}

            <form onSubmit={handleOnboardingSubmit} className="modal-form">
              <div className="modal-form-group">
                <label className="modal-label">Full Name</label>
                <input
                  type="text"
                  className="modal-input"
                  value={onboardingData.fullName}
                  onChange={(e) => setOnboardingData({ ...onboardingData, fullName: e.target.value })}
                  required
                  placeholder="Enter full name"
                  disabled={onboardingLoading}
                />
              </div>

              <div className="modal-form-group">
                <label className="modal-label">Gmail</label>
                <input
                  type="email"
                  className="modal-input"
                  value={onboardingData.gmail}
                  onChange={(e) => setOnboardingData({ ...onboardingData, gmail: e.target.value })}
                  required
                  placeholder="Enter Gmail address"
                  disabled={onboardingLoading}
                />
              </div>

              <div className="modal-form-group">
                <label className="modal-label">Role</label>
                <select
                  className="modal-select"
                  value={onboardingData.role}
                  onChange={(e) => setOnboardingData({ ...onboardingData, role: e.target.value })}
                  required
                  disabled={onboardingLoading}
                >
                  <option value="user">User</option>
                  <option value="manager">Manager</option>
                  <option value="admin">Admin</option>
                </select>
              </div>

              <div className="modal-actions">
                <button
                  type="button"
                  className="modal-btn modal-btn-cancel"
                  onClick={() => {
                    setShowOnboardingModal(false);
                    setOnboardingData({ fullName: '', gmail: '', role: 'user' });
                    setOnboardingMessage({ type: '', text: '' });
                  }}
                  disabled={onboardingLoading}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="modal-btn modal-btn-submit"
                  disabled={onboardingLoading}
                >
                  {onboardingLoading ? 'Creating...' : 'Create Account'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default Accounts;
