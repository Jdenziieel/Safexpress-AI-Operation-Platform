import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { 
  History, 
  ArrowLeft, 
  Clock, 
  X, 
  Copy, 
  AlertTriangle,
  FileText,
  Eye
} from "lucide-react";
import Swal from 'sweetalert2';
import "../css/OPRHistory.css";

function OPRHistory() {
  const navigate = useNavigate();
  
  const [history, setHistory] = useState([]);
  const [conflictModal, setConflictModal] = useState(null);
  const [viewFilesModal, setViewFilesModal] = useState(null);

  // Function to load history from localStorage
  const loadHistory = () => {
    const savedHistory = localStorage.getItem('opr_history');
    if (savedHistory) {
      setHistory(JSON.parse(savedHistory));
    } else {
      setHistory([]);
    }
  };

  // Load history on mount and whenever component becomes visible
  useEffect(() => {
    loadHistory();

    // Set up an interval to check for updates every second
    const interval = setInterval(() => {
      loadHistory();
    }, 1000);

    // Also listen for storage events (in case of updates from other tabs)
    const handleStorageChange = (e) => {
      if (e.key === 'opr_history') {
        loadHistory();
      }
    };
    window.addEventListener('storage', handleStorageChange);

    // Cleanup
    return () => {
      clearInterval(interval);
      window.removeEventListener('storage', handleStorageChange);
    };
  }, []);

  // Load from history and navigate back
  const loadFromHistory = (historyEntry) => {
    // Store the selected history entry for the OPR page to load
    // Mark this entry as being edited so updates will change it
    localStorage.setItem('opr_load_entry', JSON.stringify(historyEntry));
    localStorage.setItem('opr_editing_entry_id', historyEntry.id);
    navigate('/analysis-one-page', { state: { loadEntry: historyEntry } });
  };

  // Clear history with SweetAlert
  const clearHistory = () => {
    Swal.fire({
      title: 'Clear All History?',
      html: '<p style="color: #6b7280; font-size: 0.95rem;">This will permanently delete all upload history entries. This action cannot be undone!</p>',
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: '#ef4444',
      cancelButtonColor: '#6b7280',
      confirmButtonText: '<strong>Yes, clear all!</strong>',
      cancelButtonText: 'Cancel',
      customClass: {
        popup: 'opr-swal-popup',
        title: 'opr-swal-title',
        htmlContainer: 'opr-swal-text',
        confirmButton: 'opr-swal-confirm',
        cancelButton: 'opr-swal-cancel'
      },
      buttonsStyling: false
    }).then((result) => {
      if (result.isConfirmed) {
        setHistory([]);
        localStorage.removeItem('opr_history');
        Swal.fire({
          title: 'Cleared!',
          html: '<p style="color: #6b7280; font-size: 0.95rem;">All history has been deleted.</p>',
          icon: 'success',
          confirmButtonColor: '#26326e',
          confirmButtonText: '<strong>OK</strong>',
          customClass: {
            popup: 'opr-swal-popup',
            title: 'opr-swal-title',
            htmlContainer: 'opr-swal-text',
            confirmButton: 'opr-swal-confirm-success'
          },
          buttonsStyling: false
        });
      }
    });
  };

  // Delete single history entry with SweetAlert
  const deleteHistoryEntry = (entryId) => {
    Swal.fire({
      title: 'Delete History Entry?',
      html: '<p style="color: #6b7280; font-size: 0.95rem;">This entry will be permanently removed from your history.</p>',
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: '#ef4444',
      cancelButtonColor: '#6b7280',
      confirmButtonText: '<strong>Yes, delete it!</strong>',
      cancelButtonText: 'Cancel',
      customClass: {
        popup: 'opr-swal-popup',
        title: 'opr-swal-title',
        htmlContainer: 'opr-swal-text',
        confirmButton: 'opr-swal-confirm',
        cancelButton: 'opr-swal-cancel'
      },
      buttonsStyling: false
    }).then((result) => {
      if (result.isConfirmed) {
        const updatedHistory = history.filter(entry => entry.id !== entryId);
        setHistory(updatedHistory);
        localStorage.setItem('opr_history', JSON.stringify(updatedHistory));
        Swal.fire({
          title: 'Deleted!',
          html: '<p style="color: #6b7280; font-size: 0.95rem;">History entry has been removed.</p>',
          icon: 'success',
          confirmButtonColor: '#26326e',
          confirmButtonText: '<strong>OK</strong>',
          customClass: {
            popup: 'opr-swal-popup',
            title: 'opr-swal-title',
            htmlContainer: 'opr-swal-text',
            confirmButton: 'opr-swal-confirm-success'
          },
          buttonsStyling: false
        });
      }
    });
  };

  // View all files in a history entry
  const viewAllFiles = (entry) => {
    setViewFilesModal(entry);
  };

  return (
    <div className="opr-history-page">
      <div className="opr-history-container">
        {/* Header */}
        <div className="opr-history-header-row">
          <div>
            <button 
              className="opr-history-back-button"
              onClick={() => navigate('/analysis-one-page')}
            >
              <ArrowLeft size={20} />
              Back to One Page Report
            </button>
            <h1 className="opr-history-header-title">
              <History size={40} />
              Upload History
            </h1>
            <div className="opr-history-header-subtitle">
              View and restore previous upload sessions
            </div>
          </div>
          <div>
            {history.length > 0 && (
              <button
                className="opr-clear-all-btn"
                onClick={clearHistory}
              >
                <X size={18} />
                Clear All History
              </button>
            )}
          </div>
        </div>

        {/* History Stats */}
        <div className="opr-history-stats">
          <div className="opr-stat-card">
            <div className="opr-stat-icon">
              <History size={24} />
            </div>
            <div className="opr-stat-content">
              <div className="opr-stat-value">{history.length}</div>
              <div className="opr-stat-label">Total Entries</div>
            </div>
          </div>
          <div className="opr-stat-card">
            <div className="opr-stat-icon">
              <FileText size={24} />
            </div>
            <div className="opr-stat-content">
              <div className="opr-stat-value">
                {history.reduce((sum, entry) => sum + entry.fileCount, 0)}
              </div>
              <div className="opr-stat-label">Total Files</div>
            </div>
          </div>
          <div className="opr-stat-card">
            <div className="opr-stat-icon">
              <Clock size={24} />
            </div>
            <div className="opr-stat-content">
              <div className="opr-stat-value">
                {history.length > 0 ? history[0].timestamp.split(',')[0] : 'N/A'}
              </div>
              <div className="opr-stat-label">Last Activity</div>
            </div>
          </div>
        </div>

        {/* History Content */}
        {history.length === 0 ? (
          <div className="opr-history-empty">
            <Clock size={64} color="#9ca3af" />
            <h3>No Upload History</h3>
            <p>Your upload actions will appear here</p>
            <button
              className="opr-start-btn"
              onClick={() => navigate('/analysis-one-page')}
            >
              Start Uploading
            </button>
          </div>
        ) : (
          <div className="opr-history-table-wrapper">
              <table className="opr-history-table">
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Action</th>
                    <th>Target URL</th>
                    <th>File Details</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((entry) => (
                    <tr key={entry.id} className="opr-history-row">
                      <td>
                        <div className="opr-timestamp">
                          <Clock size={16} />
                          <span>{entry.timestamp.split(',')[0]}</span>
                        </div>
                      </td>
                      <td>
                        <span className={`opr-action-badge ${entry.action}`}>
                          {entry.action === 'add' && '+ Add'}
                          {entry.action === 'remove' && '- Remove'}
                          {entry.action === 'override' && '⚠ Override'}
                          {entry.action === 'merge' && '⇄ Merge'}
                          {entry.action === 'update' && '✓ Updated'}
                        </span>
                      </td>
                      <td>
                        <div className="opr-target-url">
                          {entry.targetUrl || 'No URL'}
                        </div>
                      </td>
                      <td>
                        <div className="opr-file-details">
                          {entry.files.slice(0, 2).map((file, idx) => (
                            <div key={idx} className="opr-file-name-small">
                              {file.name}
                            </div>
                          ))}
                          {entry.files.length > 2 && (
                            <button 
                              className="opr-view-files-btn"
                              onClick={() => viewAllFiles(entry)}
                            >
                              <Eye size={12} />
                              +{entry.files.length - 2} more
                            </button>
                          )}
                        </div>
                      </td>
                      <td>
                        <div className="opr-action-buttons">
                          <button
                            className="opr-load-btn"
                            onClick={() => loadFromHistory(entry)}
                            title="Load this state"
                          >
                            <Copy size={16} />
                            Load
                          </button>
                          <button
                            className="opr-delete-btn"
                            onClick={() => deleteHistoryEntry(entry.id)}
                            title="Delete entry"
                          >
                            <X size={16} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
        )}

        {/* View Files Modal */}
        {viewFilesModal && (
          <div className="opr-modal-overlay" onClick={() => setViewFilesModal(null)}>
            <div className="opr-modal" onClick={(e) => e.stopPropagation()}>
              <div className="opr-modal-header">
                <div>
                  <h3>All Files in This Entry</h3>
                  <p className="opr-modal-subtitle">
                    {viewFilesModal.fileCount} {viewFilesModal.fileCount === 1 ? 'file' : 'files'} uploaded on {viewFilesModal.timestamp.split(',')[0]}
                  </p>
                </div>
                <button 
                  className="opr-modal-close"
                  onClick={() => setViewFilesModal(null)}
                >
                  <X size={24} />
                </button>
              </div>
              <div className="opr-modal-body">
                {viewFilesModal.files.map((file, idx) => (
                  <div key={idx} className="opr-modal-file-item">
                    <FileText size={24} color="#26326e" />
                    <div className="opr-modal-file-info">
                      <div className="opr-modal-file-name">{file.name}</div>
                      <div className="opr-modal-file-meta">
                        <span className="opr-modal-file-type">{file.type}</span>
                        <span className="opr-modal-file-size">{file.size}</span>
                        <span className="opr-modal-file-date">{file.uploadedAt}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="opr-modal-footer">
                <button 
                  className="opr-modal-close-btn"
                  onClick={() => setViewFilesModal(null)}
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default OPRHistory;
