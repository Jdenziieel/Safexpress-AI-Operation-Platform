import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Search, Upload, Settings, ArrowUpDown } from 'lucide-react';
import { jsPDF } from 'jspdf';
import autoTable from 'jspdf-autotable';
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

function UserActivityDetails() {
  const { userEmail } = useParams();
  const navigate = useNavigate();
  const [searchTerm, setSearchTerm] = useState('');
  const [page, setPage] = useState(1);
  const [sortField, setSortField] = useState('date');
  const [sortOrder, setSortOrder] = useState('desc');
  const logsPerPage = 10;

  // Filter logs for this specific user
  const userLogs = allLogs.filter(log => log.email === userEmail);
  const userName = userLogs.length > 0 ? userLogs[0].name : 'User';

  // Apply search filter
  const searchFilteredLogs = userLogs.filter(log =>
    log.action.toLowerCase().includes(searchTerm.toLowerCase()) ||
    log.details.toLowerCase().includes(searchTerm.toLowerCase()) ||
    log.date.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Sort the filtered logs
  const filteredLogs = [...searchFilteredLogs].sort((a, b) => {
    let aVal = a[sortField];
    let bVal = b[sortField];
    
    if (sortField === 'date') {
      aVal = new Date(aVal);
      bVal = new Date(bVal);
    } else if (sortField === 'action' || sortField === 'details') {
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

  const handleExportPDF = () => {
    const doc = new jsPDF();
    
    // Add title
    doc.setFontSize(18);
    doc.setFont('helvetica', 'bold');
    doc.text(`Activity Log: ${userName}`, 14, 20);
    
    // Add date
    doc.setFontSize(10);
    doc.setFont('helvetica', 'normal');
    const currentDate = new Date().toLocaleDateString('en-US', { 
      year: 'numeric', 
      month: 'long', 
      day: 'numeric' 
    });
    doc.text(`Generated on: ${currentDate}`, 14, 28);
    
    // Add user info
    doc.setFontSize(11);
    doc.setFont('helvetica', 'bold');
    doc.text(`User: ${userName}`, 14, 36);
    doc.text(`Email: ${userEmail}`, 14, 42);
    doc.text(`Total Records: ${filteredLogs.length}`, 14, 48);
    
    // Prepare table data
    const tableColumn = ['Action', 'Details', 'Date', 'Time'];
    const tableRows = filteredLogs.map(log => [
      log.action,
      log.details,
      log.date,
      log.timestamp
    ]);
    
    // Add table
    autoTable(doc, {
      head: [tableColumn],
      body: tableRows,
      startY: 56,
      theme: 'grid',
      headStyles: {
        fillColor: [38, 50, 110], // #26326e
        textColor: [255, 255, 255],
        fontStyle: 'bold',
        fontSize: 10
      },
      bodyStyles: {
        fontSize: 9
      },
      alternateRowStyles: {
        fillColor: [245, 247, 250]
      },
      columnStyles: {
        0: { cellWidth: 40 }, // Action
        1: { cellWidth: 70 }, // Details
        2: { cellWidth: 35 }, // Date
        3: { cellWidth: 35 }  // Time
      }
    });
    
    // Save the PDF
    const fileName = `activity-log-${userName.replace(/\s+/g, '-').toLowerCase()}-${new Date().toISOString().split('T')[0]}.pdf`;
    doc.save(fileName);
  };

  const totalPages = Math.ceil(filteredLogs.length / logsPerPage);
  const startIdx = (page - 1) * logsPerPage;
  const endIdx = startIdx + logsPerPage;
  const currentLogs = filteredLogs.slice(startIdx, endIdx);

  return (
    <div className="auditlogs-page">
      <div className="auditlogs-container">
        <div style={{ marginBottom: '16px' }}>
          <button 
            onClick={() => navigate('/audit-logs')}
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
            title="Back to Users"
          >
            <ArrowLeft size={20} />
          </button>
        </div>
        <div className="auditlogs-header-row">
          <div>
            <h1 className="auditlogs-header-title">Activity Log: {userName}</h1>
            <div className="auditlogs-header-subtitle">All actions performed by this user.</div>
          </div>
          <div className="auditlogs-header-actions">
            <ActionButton icon={Upload} className="action-button-export" onClick={handleExportPDF}>Export</ActionButton>
            <ActionButton icon={Settings} className="action-button-settings">Settings</ActionButton>
          </div>
        </div>

        <div className="main-card" style={{ marginBottom: 32, minHeight: 'fit-content', paddingBottom: '24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 18 }}>
            <Search size={22} style={{ color: '#26326e', marginRight: 10 }} />
            <input
              type="text"
              placeholder="Search by action or details..."
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
                <col style={{ width: '20%' }} />
                <col style={{ width: '40%' }} />
                <col style={{ width: '20%' }} />
                <col style={{ width: '20%' }} />
              </colgroup>
              <thead>
                <tr style={{ background: '#f8fafc', color: '#26326e', fontWeight: 700 }}>
                  <th 
                    onClick={() => handleSort('action')} 
                    style={{ padding: '10px 16px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem', cursor: 'pointer', userSelect: 'none' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      Action
                      <ArrowUpDown size={16} style={{ opacity: sortField === 'action' ? 1 : 0.3 }} />
                    </div>
                  </th>
                  <th 
                    onClick={() => handleSort('details')} 
                    style={{ padding: '10px 8px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem', cursor: 'pointer', userSelect: 'none' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      Details
                      <ArrowUpDown size={16} style={{ opacity: sortField === 'details' ? 1 : 0.3 }} />
                    </div>
                  </th>
                  <th 
                    onClick={() => handleSort('date')} 
                    style={{ padding: '10px 8px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem', cursor: 'pointer', userSelect: 'none' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      Date
                      <ArrowUpDown size={16} style={{ opacity: sortField === 'date' ? 1 : 0.3 }} />
                    </div>
                  </th>
                  <th style={{ padding: '10px 8px', fontWeight: 700, textAlign: 'left', fontSize: '1.05rem' }}>Time</th>
                </tr>
              </thead>
              <tbody>
                {currentLogs.length === 0 ? (
                  <tr>
                    <td colSpan="4" style={{ textAlign: 'center', color: '#64748b', fontStyle: 'italic', padding: '2rem' }}>
                      No activities found.
                    </td>
                  </tr>
                ) : (
                  currentLogs.map((log, idx) => (
                    <tr key={startIdx + idx} style={{ borderBottom: '1px solid #e2e8f0', background: idx % 2 === 0 ? '#fff' : '#f8fafc' }}>
                      <td style={{ padding: '16px 16px', fontWeight: 600, color: '#26326e', textAlign: 'left' }}>{log.action}</td>
                      <td style={{ padding: '16px 16px', textAlign: 'left', color: '#475569' }}>{log.details}</td>
                      <td style={{ padding: '16px 16px', textAlign: 'left' }}>{log.date}</td>
                      <td style={{ padding: '16px 16px', color: '#6b7280', fontFamily: 'monospace', textAlign: 'left', letterSpacing: '1px' }}>{log.timestamp}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          <div className='auditlogs-pagination-row' style={{ marginTop: '20px', paddingTop: '12px', borderTop: '1px solid #e5e7eb' }}>
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

export default UserActivityDetails;
