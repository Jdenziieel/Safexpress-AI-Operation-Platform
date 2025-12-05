import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Upload, Settings, Search, Filter, ArrowUpDown, ChevronRight } from 'lucide-react';
import '../css/AuditLogs.css';

const allLogs = [
  { name: 'Juan Miguel Dela Cruz', email: 'juanmigueldelacruz@example.com', action: 'Login', details: 'User logged into system', date: '2025-08-01', timestamp: '08:30 AM' },
  { name: 'Juan Miguel Dela Cruz', email: 'juanmigueldelacruz@example.com', action: 'View Report', details: 'Accessed sales report', date: '2025-08-01', timestamp: '09:15 AM' },
  { name: 'Juan Miguel Dela Cruz', email: 'juanmigueldelacruz@example.com', action: 'Update Profile', details: 'Changed contact information', date: '2025-08-01', timestamp: '10:45 AM' },
  { name: 'Maria Clara Ibarra', email: 'mariaclaraibarra@example.com', action: 'Login', details: 'User logged into system', date: '2025-08-01', timestamp: '07:00 AM' },
  { name: 'Maria Clara Ibarra', email: 'mariaclaraibarra@example.com', action: 'Create Document', details: 'Created new document', date: '2025-08-01', timestamp: '11:30 AM' },
  { name: 'Ana Santos', email: 'anasantos@example.com', action: 'Login', details: 'User logged into system', date: '2025-08-02', timestamp: '08:00 AM' },
  { name: 'Ana Santos', email: 'anasantos@example.com', action: 'Download File', details: 'Downloaded report.pdf', date: '2025-08-02', timestamp: '02:30 PM' },
  { name: 'Carlos Reyes', email: 'carlosreyes@example.com', action: 'Login', details: 'User logged into system', date: '2025-08-02', timestamp: '09:00 AM' },
  { name: 'Liza Gomez', email: 'lizagomez@example.com', action: 'Login', details: 'User logged into system', date: '2025-08-03', timestamp: '08:15 AM' },
  { name: 'Mark Lee', email: 'marklee@example.com', action: 'Login', details: 'User logged into system', date: '2025-08-03', timestamp: '10:00 AM' },
];

// Get unique users with their action count and last activity
const getUniqueUsers = () => {
  const userMap = new Map();
  
  allLogs.forEach(log => {
    if (!userMap.has(log.email)) {
      userMap.set(log.email, {
        name: log.name,
        email: log.email,
        actionCount: 0,
        lastActivity: log.date
      });
    }
    const user = userMap.get(log.email);
    user.actionCount++;
    // Update last activity if this log is more recent
    if (new Date(log.date) > new Date(user.lastActivity)) {
      user.lastActivity = log.date;
    }
  });
  
  return Array.from(userMap.values());
};


const ActionButton = ({ icon: Icon, children, className = '', ...props }) => (
  <div style={{ position: 'relative', display: 'inline-block' }}>
    <button className={`main-card-btn ${className}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '12px', fontSize: '1.1rem', fontWeight: 700 }} {...props}>
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


function AuditLogs() {
  const navigate = useNavigate();
  const [users] = useState(getUniqueUsers());
  const [searchTerm, setSearchTerm] = useState('');
  const [page, setPage] = useState(1);
  const [sortField, setSortField] = useState('name');
  const [sortOrder, setSortOrder] = useState('asc');
  const usersPerPage = 10;

  // Apply search filter
  const searchFilteredUsers = users.filter(user =>
    user.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    user.email.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Sort the filtered users
  const filteredUsers = [...searchFilteredUsers].sort((a, b) => {
    let aVal = a[sortField];
    let bVal = b[sortField];
    
    if (sortField === 'actionCount') {
      // For numbers, compare directly
      if (aVal < bVal) return sortOrder === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortOrder === 'asc' ? 1 : -1;
      return 0;
    } else if (sortField === 'lastActivity') {
      aVal = new Date(aVal);
      bVal = new Date(bVal);
      if (aVal < bVal) return sortOrder === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortOrder === 'asc' ? 1 : -1;
      return 0;
    } else {
      // For strings
      aVal = aVal.toLowerCase();
      bVal = bVal.toLowerCase();
      if (aVal < bVal) return sortOrder === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortOrder === 'asc' ? 1 : -1;
      return 0;
    }
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

  const totalPages = Math.ceil(filteredUsers.length / usersPerPage);
  const startIdx = (page - 1) * usersPerPage;
  const endIdx = startIdx + usersPerPage;
  const currentUsers = filteredUsers.slice(startIdx, endIdx);

  return (
    <div className="auditlogs-page">
      <div className="auditlogs-container">
        <div className="auditlogs-header-row">
          <div>
            <h1 className="auditlogs-header-title">Audit Logs - Users</h1>
            <div className="auditlogs-header-subtitle">Select a user to view their activity history.</div>
          </div>
          <div className="auditlogs-header-actions" >
            <ActionButton icon={Upload} className="action-button-export">Export</ActionButton>
            <ActionButton icon={Settings} className="action-button-settings">Settings</ActionButton>
          </div>
        </div>

        <div className="main-card" style={{ marginBottom: 32, minHeight: 'fit-content', paddingBottom: '24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 18 }}>
            <Search size={22} style={{ color: '#26326e', marginRight: 10 }} />
            <input
              type="text"
              placeholder="Search by name or email..."
              style={{ flex: 1, padding: '10px 16px', borderRadius: 8, border: '1px solid #26326e', fontSize: '1.1rem' }}
              value={searchTerm}
              onChange={(e) => {
                setSearchTerm(e.target.value);
                setPage(1);
              }}
            />
          </div>
          <div style={{ marginBottom: 24 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '1.05rem' }}>
              <colgroup>
                <col style={{ width: '40%' }} />
                <col style={{ width: '20%' }} />
                <col style={{ width: '25%' }} />
                <col style={{ width: '15%' }} />
              </colgroup>
              <thead>
                <tr style={{ background: '#f8fafc', color: '#26326e', fontWeight: 700 }}>
                  <th 
                    onClick={() => handleSort('name')} 
                    style={{ padding: '10px 16px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem', cursor: 'pointer', userSelect: 'none' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      User
                      <ArrowUpDown size={16} style={{ opacity: sortField === 'name' ? 1 : 0.3 }} />
                    </div>
                  </th>
                  <th 
                    onClick={() => handleSort('actionCount')} 
                    style={{ padding: '10px 8px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem', cursor: 'pointer', userSelect: 'none' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      Total Actions
                      <ArrowUpDown size={16} style={{ opacity: sortField === 'actionCount' ? 1 : 0.3 }} />
                    </div>
                  </th>
                  <th 
                    onClick={() => handleSort('lastActivity')} 
                    style={{ padding: '10px 8px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem', cursor: 'pointer', userSelect: 'none' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      Last Activity
                      <ArrowUpDown size={16} style={{ opacity: sortField === 'lastActivity' ? 1 : 0.3 }} />
                    </div>
                  </th>
                  <th style={{ padding: '10px 8px', fontWeight: 700, textAlign: 'center', fontSize: '1.05rem' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {currentUsers.length === 0 ? (
                  <tr>
                    <td colSpan="4" style={{ textAlign: 'center', color: '#64748b', fontStyle: 'italic', padding: '2rem' }}>
                      No users found.
                    </td>
                  </tr>
                ) : (
                  currentUsers.map((user, idx) => (
                    <tr 
                      key={startIdx + idx} 
                      style={{ 
                        borderBottom: '1px solid #e2e8f0', 
                        background: idx % 2 === 0 ? '#fff' : '#f8fafc',
                        cursor: 'pointer',
                        transition: 'background 0.2s'
                      }}
                      onMouseEnter={(e) => e.currentTarget.style.background = '#f0f4ff'}
                      onMouseLeave={(e) => e.currentTarget.style.background = idx % 2 === 0 ? '#fff' : '#f8fafc'}
                      onClick={() => navigate(`/audit-logs/user/${user.email}`)}
                    >
                      <td style={{ padding: '16px 16px', fontWeight: 600, color: '#26326e', textAlign: 'left' }}>
                        <div>{user.name}</div>
                        <div style={{ fontWeight: 400, color: '#6b7280', fontSize: '0.98rem' }}>{user.email}</div>
                      </td>
                      <td style={{ padding: '16px 16px', textAlign: 'left', color: '#475569', fontWeight: 600 }}>
                        {user.actionCount} {user.actionCount === 1 ? 'action' : 'actions'}
                      </td>
                      <td style={{ padding: '16px 16px', textAlign: 'left', color: '#475569' }}>{user.lastActivity}</td>
                      <td style={{ padding: '16px 16px', textAlign: 'center' }}>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/audit-logs/user/${user.email}`);
                          }}
                          style={{
                            background: '#26326e',
                            color: 'white',
                            border: 'none',
                            borderRadius: '6px',
                            padding: '8px 12px',
                            cursor: 'pointer',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '6px',
                            fontSize: '0.9rem',
                            fontWeight: 600
                          }}
                        >
                          View
                          <ChevronRight size={16} />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          <div className='auditlogs-pagination-row' style={{ marginTop: '20px', paddingTop: '12px', borderTop: '1px solid #e5e7eb' }}>
            <div className='auditlogs-pagination-info'>
              Showing <span style={{ fontWeight: 700 }}>{startIdx + 1}</span> to <span style={{ fontWeight: 700 }}>{Math.min(endIdx, filteredUsers.length)}</span> of <span style={{ fontWeight: 700 }}>{filteredUsers.length}</span> results
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
      </div>
    </div>
  );
}

export default AuditLogs;