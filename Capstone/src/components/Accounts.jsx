
import React, { useState } from 'react';
import { Search, Upload, Settings, Pencil, Trash2 } from 'lucide-react';
import '../css/Accounts.css';

const initialAccounts = [
  { id: 'acc-001', name: 'Maria Clara Ibarra', email: 'mariaclara.ibarra@example.com', role: 'User', status: 'Active', memberId: '123456789012' },
  { id: 'acc-002', name: 'Juan Dela Cruz', email: 'juan.delacruz@example.com', role: 'Admin', status: 'Inactive', memberId: '987654321098' },
  { id: 'acc-003', name: 'Ana Santos', email: 'ana.santos@example.com', role: 'User', status: 'Active', memberId: '111222333444' },
  { id: 'acc-004', name: 'Carlos Reyes', email: 'carlos.reyes@example.com', role: 'User', status: 'Active', memberId: '555666777888' },
  { id: 'acc-005', name: 'Liza Gomez', email: 'liza.gomez@example.com', role: 'Admin', status: 'Active', memberId: '999888777666' },
  { id: 'acc-006', name: 'Mark Lee', email: 'mark.lee@example.com', role: 'User', status: 'Inactive', memberId: '444333222111' },
  { id: 'acc-007', name: 'Sofia Cruz', email: 'sofia.cruz@example.com', role: 'User', status: 'Active', memberId: '222333444555' },
  { id: 'acc-008', name: 'Miguel Ramos', email: 'miguel.ramos@example.com', role: 'Admin', status: 'Active', memberId: '333444555666' },
  { id: 'acc-009', name: 'Paula Lim', email: 'paula.lim@example.com', role: 'User', status: 'Inactive', memberId: '666555444333' },
  { id: 'acc-010', name: 'Rico Tan', email: 'rico.tan@example.com', role: 'User', status: 'Active', memberId: '777888999000' },
  { id: 'acc-011', name: 'Grace Yu', email: 'grace.yu@example.com', role: 'Admin', status: 'Active', memberId: '888999000111' },
  { id: 'acc-012', name: 'Ben Torres', email: 'ben.torres@example.com', role: 'User', status: 'Inactive', memberId: '999000111222' },
  { id: 'acc-013', name: 'Kim dela Vega', email: 'kim.delavega@example.com', role: 'User', status: 'Active', memberId: '000111222333' },
];

const ActionButton = ({ icon: Icon, children, className = '', ...props }) => (
  <button className={`main-card-btn ${className}`} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 22px', fontSize: '1.1rem', fontWeight: 700 }} {...props}>
    <Icon size={20} style={{ marginRight: 6 }} />
    <span>{children}</span>
  </button>
);

const StatusBadge = ({ status }) => {
  const statusClass = status === 'Active' ? 'status-badge-active' : 'status-badge-inactive';
  return <span className={`status-badge ${statusClass}`}>{status}</span>;
};

function Accounts() {
  const [accounts] = useState(initialAccounts);
  const [searchTerm, setSearchTerm] = useState('');
  const [page, setPage] = useState(1);
  const accountsPerPage = 10;

  const filteredAccounts = accounts.filter(
    (account) =>
      account.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      account.email.toLowerCase().includes(searchTerm.toLowerCase()) ||
      account.role.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const totalPages = Math.ceil(filteredAccounts.length / accountsPerPage);
  const startIdx = (page - 1) * accountsPerPage;
  const endIdx = startIdx + accountsPerPage;
  const currentAccounts = filteredAccounts.slice(startIdx, endIdx);

  return (
    <div className="accounts-page">
      <div className="accounts-container">
        <div className="accounts-header-row">
          <div>
            <h1 className="accounts-header-title">Accounts</h1>
            <div className="accounts-header-subtitle">Manage all user accounts in the system.</div>
          </div>
          <div className="accounts-header-actions">
            <ActionButton icon={Upload} className='accounts-header-action-button-export'>Export</ActionButton>
            <ActionButton icon={Settings} className='accounts-header-action-button-settings'>Settings</ActionButton>
          </div>
        </div>

        <div className="main-card" style={{ marginBottom: 32 }}>
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 18 }}>
            <Search size={22} style={{ color: '#26326e', marginRight: 10 }} />
            <input
              type="text"
              placeholder="Search by name, email, or role..."
              style={{ flex: 1, padding: '10px 16px', borderRadius: 8, border: '1px solid #26326e', fontSize: '1.1rem' }}
              value={searchTerm}
              onChange={(e) => {
                setSearchTerm(e.target.value);
                setPage(1);
              }}
            />
          </div>
          <div style={{ overflowX: 'auto', marginBottom: 18 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '1.05rem', tableLayout: 'fixed' }}>
              <colgroup>
                <col style={{ width: '30%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '10%' }} />
              </colgroup>
              <thead>
                <tr style={{ background: '#f8fafc', color: '#26326e', fontWeight: 700 }}>
                  <th style={{ padding: '10px 16px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem' }}>Name</th>
                  <th style={{ padding: '10px 8px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem' }}>Status</th>
                  <th style={{ padding: '10px 8px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem' }}>Role</th>
                  <th style={{ padding: '10px 8px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem' }}>Member ID</th>
                  <th style={{ padding: '10px 8px', fontWeight: 700, textAlign: 'center', fontSize: '1.05rem' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {currentAccounts.length === 0 ? (
                  <tr>
                    <td colSpan="5" style={{ textAlign: 'center', color: '#64748b', fontStyle: 'italic', padding: '2rem' }}>
                      No Account/s found.
                    </td>
                  </tr>
                ) : (
                  currentAccounts.map((account, idx) => (
                    <tr key={startIdx + idx} style={{ borderBottom: '1px solid #e2e8f0', background: idx % 2 === 0 ? '#fff' : '#f8fafc' }}>
                      <td style={{ padding: '16px 16px', fontWeight: 600, color: '#26326e', textAlign: 'left' }}>
                        <div>{account.name}</div>
                        <div style={{ fontWeight: 400, color: '#6b7280', fontSize: '0.98rem' }}>{account.email}</div>
                      </td>
                      <td style={{ padding: '16px 16px', textAlign: 'left' }}>
                        <StatusBadge status={account.status} />
                      </td>
                      <td style={{ padding: '16px 16px', textAlign: 'left', color: '#475569' }}>{account.role}</td>
                      <td style={{ padding: '16px 16px', textAlign: 'left', color: '#64748b', fontFamily: 'monospace' }}>{account.memberId}</td>
                      <td style={{ padding: '16px 16px', textAlign: 'center' }}>
                        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 10 }}>
                          <button style={{ padding: '8px', borderRadius: '9999px', background: '#fff', color: '#64748b', border: '1px solid #e2e8f0', cursor: 'pointer', transition: 'all 0.2s' }} aria-label="Edit">
                            <Pencil size={18} />
                          </button>
                          <button style={{ padding: '8px', borderRadius: '9999px', background: '#fff', color: '#64748b', border: '1px solid #e2e8f0', cursor: 'pointer', transition: 'all 0.2s' }} aria-label="Delete">
                            <Trash2 size={18} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
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
      </div>
    </div>
  );
}

export default Accounts;
