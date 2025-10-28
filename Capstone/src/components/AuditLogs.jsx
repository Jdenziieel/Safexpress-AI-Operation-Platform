import React, { useState } from 'react';
import { Upload, Settings, Search } from 'lucide-react';
import '../css/AuditLogs.css';

const initialLogs = [
  { name: 'Juan Miguel Dela Cruz', email: 'juanmigueldelacruz@example.com', action: '1xxx', details: '1xxx', date: '2025-08-01', timestamp: '1xx:xx AM' },
  { name: 'Maria Clara Ibarra', email: 'mariaclaraibarra@example.com', action: '2xxx', details: '2xxx', date: '2025-08-01', timestamp: '2xx:xx AM' },
  { name: 'Ana Santos', email: 'anasantos@example.com', action: '3xxx', details: '3xxx', date: '2025-08-02', timestamp: '3xx:xx AM' },
  { name: 'Carlos Reyes', email: 'carlosreyes@example.com', action: '4xxx', details: '4xxx', date: '2025-08-02', timestamp: '4xx:xx AM' },
  { name: 'Liza Gomez', email: 'lizagomez@example.com', action: '5xxx', details: '5xxx', date: '2025-08-03', timestamp: '5xx:xx AM' },
  { name: 'Mark Lee', email: 'marklee@example.com', action: '6xxx', details: '6xxx', date: '2025-08-03', timestamp: '6xx:xx AM' },
  { name: 'Sofia Cruz', email: 'sofiacruz@example.com', action: '7xxx', details: '7xxx', date: '2025-08-04', timestamp: '7xx:xx AM' },
  { name: 'Miguel Ramos', email: 'miguelramos@example.com', action: '8xxx', details: '8xxx', date: '2025-08-04', timestamp: '8xx:xx AM' },
  { name: 'Paula Lim', email: 'paulalim@example.com', action: '9xxx', details: '9xxx', date: '2025-08-05', timestamp: '9xx:xx AM' },
  { name: 'Rico Tan', email: 'ricotan@example.com', action: '10xxx', details: '10xxx', date: '2025-08-05', timestamp: '10xx:xx AM' },
  { name: 'Grace Yu', email: 'graceyu@example.com', action: '11xxx', details: '11xxx', date: '2025-08-05', timestamp: '11xx:xx AM' },
  { name: 'Ben Torres', email: 'bentorres@example.com', action: '12xxx', details: '12xxx', date: '2025-08-05', timestamp: '12xx:xx AM' },
  { name: 'Kim dela Vega', email: 'kimdelavega@example.com', action: '13xxx', details: '13xxx', date: '2025-08-05', timestamp: '13xx:xx AM' },
];


const ActionButton = ({ icon: Icon, children, className = '', ...props }) => (
  <button className={`main-card-btn ${className}`} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 22px', fontSize: '1.1rem', fontWeight: 700 }} {...props}>
    <Icon size={20} style={{ marginRight: 6 }} />
    <span>{children}</span>
  </button>
);


function AuditLogs() {
  const [logs] = useState(initialLogs);
  const [searchTerm, setSearchTerm] = useState('');
  const [page, setPage] = useState(1);
  const logsPerPage = 10;

  const filteredLogs = logs.filter(log =>
    log.email.toLowerCase().includes(searchTerm.toLowerCase()) ||
    log.action.toLowerCase().includes(searchTerm.toLowerCase()) ||
    log.details.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const totalPages = Math.ceil(filteredLogs.length / logsPerPage);
  const startIdx = (page - 1) * logsPerPage;
  const endIdx = startIdx + logsPerPage;
  const currentLogs = filteredLogs.slice(startIdx, endIdx);

  return (
    <div className="auditlogs-page">
      <div className="auditlogs-container">
        <div className="auditlogs-header-row">
          <div>
            <h1 className="auditlogs-header-title">Audit Logs</h1>
            <div className="auditlogs-header-subtitle">Track all system actions and changes.</div>
          </div>
          <div className="auditlogs-header-actions" >
            <ActionButton icon={Upload} className="action-button-export">Export</ActionButton>
            <ActionButton icon={Settings} className="action-button-settings">Settings</ActionButton>
          </div>
        </div>

        <div className="main-card" style={{ marginBottom: 32 }}>
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 18 }}>
            <Search size={22} style={{ color: '#26326e', marginRight: 10 }} />
            <input
              type="text"
              placeholder="Search by email, action, or details..."
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
                  <th style={{ padding: '10px 8px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem' }}>Action</th>
                  <th style={{ padding: '10px 8px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem' }}>Details</th>
                  <th style={{ padding: '10px 8px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem' }}>Date</th>
                  <th style={{ padding: '10px 8px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem' }}>Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {currentLogs.map((log, idx) => (
                  <tr key={startIdx + idx} style={{ borderBottom: '1px solid #e2e8f0', background: idx % 2 === 0 ? '#fff' : '#f8fafc' }}>
                    <td style={{ padding: '16px 16px', fontWeight: 600, color: '#26326e', textAlign: 'left' }}>
                      <div>{log.name}</div>
                      <div style={{ fontWeight: 400, color: '#6b7280', fontSize: '0.98rem' }}>{log.email}</div>
                    </td>
                    <td style={{ padding: '16px 16px', textAlign: 'left' }}>{log.action}</td>
                    <td style={{ padding: '16px 16px', textAlign: 'left' }}>{log.details}</td>
                    <td style={{ padding: '16px 16px', textAlign: 'left' }}>{log.date}</td>
                    <td style={{ padding: '16px 16px', color: '#6b7280', fontFamily: 'monospace', textAlign: 'left', letterSpacing: '1px' }}>{log.timestamp}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className='auditlogs-pagination-row'>
            <div className='auditlogs-pagination-info'>
              Showing <span style={{ fontWeight: 700 }}>{startIdx + 1}</span> to <span style={{ fontWeight: 700 }}>{Math.min(endIdx, filteredLogs.length)}</span> of <span style={{ fontWeight: 700 }}>{filteredLogs.length}</span> results
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