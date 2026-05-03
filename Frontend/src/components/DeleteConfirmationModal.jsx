import React from 'react';
import { X, AlertTriangle } from 'lucide-react';

const DeleteConfirmationModal = ({ 
  isOpen, 
  onClose, 
  onConfirm, 
  documentName, 
  isDeleting = false 
}) => {
  if (!isOpen) return null;

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget && !isDeleting) {
      onClose();
    }
  };

  const handleConfirm = () => {
    if (!isDeleting) {
      onConfirm();
    }
  };

  return (
    <div className="modal-backdrop" onClick={handleBackdropClick}>
      <div 
        className="history-modal" 
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: '500px' }}
      >
        <div className="history-modal-header" style={{ background: '#fee2e2', borderBottom: '2px solid #ef4444' }}>
          <h2 style={{ color: '#991b1b', display: 'flex', alignItems: 'center', gap: '8px' }}>
            Delete Document?
          </h2>
        </div>

        <div className="history-modal-body">
          <div style={{ marginBottom: '20px' }}>
            <p style={{ fontSize: '1rem', color: '#991b1b', marginBottom: '12px', fontWeight: '600' }}>
              Are you sure you want to delete <strong>{documentName}</strong>?
            </p>
            <p style={{ fontSize: '0.9rem', color: '#6b7280', lineHeight: '1.6' }}>
              This action cannot be undone. All associated chunks and data will be permanently removed.
            </p>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', paddingTop: '16px', borderTop: '1px solid #e5e7eb' }}>
            <button 
              onClick={onClose}
              disabled={isDeleting}
              className="pagination-btn"
              style={{ background: '#e5e7eb', color: '#374151', border: '1px solid #d1d5db' }}
            >
              Cancel
            </button>
            <button 
              onClick={handleConfirm}
              disabled={isDeleting}
              className="pagination-btn"
              style={{ 
                background: isDeleting ? '#9ca3af' : '#ef4444',
                color: 'white',
                border: isDeleting ? '1px solid #9ca3af' : '1px solid #ef4444',
                cursor: isDeleting ? 'not-allowed' : 'pointer',
                opacity: isDeleting ? 0.6 : 1,
                display: 'flex',
                alignItems: 'center',
                gap: '8px'
              }}
            >
              {isDeleting && (
                <span style={{
                  width: '14px',
                  height: '14px',
                  border: '2px solid white',
                  borderTopColor: 'transparent',
                  borderRadius: '50%',
                  display: 'inline-block',
                  animation: 'spin 0.6s linear infinite'
                }}></span>
              )}
              {isDeleting ? 'Deleting...' : 'Delete'}
            </button>
          </div>
        </div>
      </div>
      <style jsx>{`
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
};

export default DeleteConfirmationModal;
