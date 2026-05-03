import React from 'react';
import { FiX, FiUploadCloud, FiInbox } from 'react-icons/fi';
import '../css/UploadModal.css';

function UploadModal({ onClose, onShowFiles }) {
    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="modal-content upload-modal" onClick={e => e.stopPropagation()}>
                <div className="modal-header">
                    <h3 className="modal-title">Upload Files</h3>
                    <div>
                        <button onClick={onShowFiles} className="modal-icon-btn" title="Show Uploaded Files">
                            <FiInbox size={20} />
                        </button>
                        <button onClick={onClose} className="modal-close-btn modal-icon-btn" title="Close">
                            <FiX size={24} />
                        </button>
                    </div>
                </div>
                <div className="upload-dropzone">
                    <FiUploadCloud size={48} className="upload-icon" />
                    <p className="upload-text">
                        <strong>Drag & drop files here</strong> or click to browse.
                    </p>
                    <p className="upload-subtext">Max file size: 50MB</p>
                    <input type="file" className="upload-input" />
                </div>
                <div className="upload-footer">
                    <button className="secondary-button" onClick={onClose}>Cancel</button>
                    <button className="primary-button" disabled>Upload</button>
                </div>
            </div>
        </div>
    );
}

export default UploadModal;