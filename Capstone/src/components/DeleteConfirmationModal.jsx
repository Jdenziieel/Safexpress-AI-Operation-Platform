import React from 'react';
import { X, AlertTriangle } from 'lucide-react';
import '../css/DeleteConfirmationModal.css';

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
    <div className="delete-modal-overlay" onClick={handleBackdropClick}>
      <div className="delete-modal">
        <button 
          className="delete-modal-close" 
          onClick={onClose}
          disabled={isDeleting}
          aria-label="Close modal"
        >
          <X size={20} />
        </button>

        <div className="delete-modal-header">
          <div className="delete-modal-icon">
            <AlertTriangle size={32} />
          </div>
          <h2 className="delete-modal-title">Delete Document</h2>
        </div>

        <div className="delete-modal-body">
          <p className="delete-modal-text">
            Are you sure you want to delete <strong>{documentName}</strong>?
          </p>
          <p className="delete-modal-warning">
            This action cannot be undone. All associated chunks and data will be permanently removed.
          </p>
        </div>

        <div className="delete-modal-footer">
          <button 
            className="delete-modal-btn delete-modal-btn-cancel"
            onClick={onClose}
            disabled={isDeleting}
          >
            Cancel
          </button>
          <button 
            className="delete-modal-btn delete-modal-btn-delete"
            onClick={handleConfirm}
            disabled={isDeleting}
          >
            {isDeleting ? (
              <>
                <span className="delete-modal-spinner"></span>
                Deleting...
              </>
            ) : (
              'Delete Document'
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

export default DeleteConfirmationModal;
