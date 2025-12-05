import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { 
  Upload,
  File,
  X,
  FileText,
  CheckCircle2
} from "lucide-react";
import Swal from "sweetalert2";
import { ACCESS_TOKEN } from "../token";
import "../css/KnowledgeBase.css";

const API_BASE_URL = "http://localhost:8000";

function KnowledgeBase() {
  const navigate = useNavigate();
  
  // Target and Source file states
  const [targetFileUrl, setTargetFileUrl] = useState(""); // Google Sheets URL
  const [isValidUrlSaved, setIsValidUrlSaved] = useState(false); // Track if valid URL is saved
  const [uploadedFiles, setUploadedFiles] = useState([]); // Array of uploaded files with metadata
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingProgress, setProcessingProgress] = useState(0);
  
  // Duplicate file handling
  const [showDuplicateModal, setShowDuplicateModal] = useState(false);
  const [duplicateFileInfo, setDuplicateFileInfo] = useState(null);
  const [pendingFile, setPendingFile] = useState(null);
  
  // Compare files modal
  const [showCompareModal, setShowCompareModal] = useState(false);
  const [existingFileContent, setExistingFileContent] = useState(null);
  const [newFileContent, setNewFileContent] = useState(null);
  
  const sourceFileInputRef = useRef(null);

  // Handle target file URL (Google Sheets link)
  const handleTargetUrlChange = (e) => {
    setTargetFileUrl(e.target.value);
    setIsValidUrlSaved(false); // Reset validation when URL changes
  };

  const handleSaveTargetUrl = () => {
    if (!targetFileUrl.trim()) {
      Swal.fire({
        icon: 'warning',
        title: 'URL Required',
        text: 'Please enter a Google Sheets URL',
        confirmButtonColor: '#26326e',
        customClass: {
          popup: 'swal-inter-font'
        }
      });
      return;
    }
    
    // Validate that the URL is a Google Sheets link
    const isGoogleSheetsUrl = targetFileUrl.includes('docs.google.com/spreadsheets');
    if (!isGoogleSheetsUrl) {
      Swal.fire({
        icon: 'error',
        title: 'Invalid URL',
        text: 'Please enter a valid Google Sheets URL (must contain docs.google.com/spreadsheets)',
        confirmButtonColor: '#26326e',
        customClass: {
          popup: 'swal-inter-font'
        }
      });
      return;
    }
    
    Swal.fire({
      icon: 'success',
      title: 'Success!',
      text: 'Target file URL saved successfully!',
      confirmButtonColor: '#26326e',
      customClass: {
        popup: 'swal-inter-font'
      }
    });
    
    setIsValidUrlSaved(true); // Enable upload button
  };

  // Check for duplicate files
  const checkForDuplicate = (file) => {
    // Check by filename
    const duplicateByName = uploadedFiles.find(f => f.name === file.name);
    
    // Check by file size (simple content check)
    const fileSizeKB = (file.size / 1024).toFixed(2);
    const fileType = file.type.includes('pdf') ? 'PDF' : 
                     file.type.includes('csv') ? 'CSV' : 
                     file.type.includes('spreadsheet') ? 'XLSX' : 'Unknown';
    const duplicateBySize = uploadedFiles.find(f => f.size === fileSizeKB + ' KB' && f.type === fileType);
    
    if (duplicateByName) {
      return { type: 'name', file: duplicateByName };
    } else if (duplicateBySize) {
      return { type: 'content', file: duplicateBySize };
    }
    return null;
  };

  // Handle source file selection and upload
  const handleSourceFileSelect = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const validTypes = [
      'application/pdf',
      'text/csv',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    ];
    
    if (!validTypes.includes(file.type)) {
      Swal.fire({
        icon: 'error',
        title: 'Invalid File Type',
        text: 'Only PDF, CSV, and XLSX files are accepted.',
        confirmButtonColor: '#26326e',
        customClass: {
          popup: 'swal-inter-font'
        }
      });
      return;
    }

    // Check if target file URL exists
    if (!targetFileUrl.trim()) {
      Swal.fire({
        icon: 'warning',
        title: 'Target URL Required',
        text: 'Please add a Target File URL (Google Sheets link) first',
        confirmButtonColor: '#26326e',
        customClass: {
          popup: 'swal-inter-font'
        }
      });
      return;
    }

    // Check for duplicates
    const duplicate = checkForDuplicate(file);
    if (duplicate) {
      setPendingFile(file);
      setDuplicateFileInfo(duplicate);
      setShowDuplicateModal(true);
      // Reset file input
      if (sourceFileInputRef.current) {
        sourceFileInputRef.current.value = '';
      }
      return;
    }

    // Proceed with upload
    await uploadFile(file);
  };

  // Upload file function
  const uploadFile = async (file, action = 'new') => {
    setIsProcessing(true);
    setProcessingProgress(0);

    try {
      // Simulate upload progress
      const progressInterval = setInterval(() => {
        setProcessingProgress(prev => {
          if (prev >= 90) {
            clearInterval(progressInterval);
            return 90;
          }
          return prev + 15;
        });
      }, 200);

      // Simulate API call delay
      await new Promise(resolve => setTimeout(resolve, 1500));
      
      clearInterval(progressInterval);
      setProcessingProgress(100);

      // Get file type
      const fileType = file.type.includes('pdf') ? 'PDF' : 
                      file.type.includes('csv') ? 'CSV' : 
                      file.type.includes('spreadsheet') ? 'XLSX' : 'Unknown';
      
      if (action === 'override') {
        // Find and replace existing file
        setUploadedFiles(prev => prev.map(f => {
          if (f.name === file.name) {
            return {
              ...f,
              size: (file.size / 1024).toFixed(2) + ' KB',
              uploadedAt: new Date().toLocaleString(),
            };
          }
          return f;
        }));
        Swal.fire({
          icon: 'success',
          title: 'Success!',
          text: 'File overridden successfully!',
          confirmButtonColor: '#26326e',
          timer: 2000,
          customClass: {
            popup: 'swal-inter-font'
          }
        });
      } else if (action === 'keepboth') {
        // Add with modified name
        const newUpload = {
          id: Date.now(),
          name: file.name.replace(/(\.[^.]+)$/, ` (${uploadedFiles.length + 1})$1`),
          type: fileType,
          size: (file.size / 1024).toFixed(2) + ' KB',
          uploadedAt: new Date().toLocaleString(),
        };
        setUploadedFiles(prev => [...prev, newUpload]);
        Swal.fire({
          icon: 'success',
          title: 'Success!',
          text: 'File uploaded successfully with new name!',
          confirmButtonColor: '#26326e',
          timer: 2000,
          customClass: {
            popup: 'swal-inter-font'
          }
        });
      } else {
        // Add new file
        const newUpload = {
          id: Date.now(),
          name: file.name,
          type: fileType,
          size: (file.size / 1024).toFixed(2) + ' KB',
          uploadedAt: new Date().toLocaleString(),
        };
        setUploadedFiles(prev => [...prev, newUpload]);
        Swal.fire({
          icon: 'success',
          title: 'Success!',
          text: 'File uploaded successfully!',
          confirmButtonColor: '#26326e',
          timer: 2000,
          customClass: {
            popup: 'swal-inter-font'
          }
        });
      }
      
      // Reset file input
      if (sourceFileInputRef.current) {
        sourceFileInputRef.current.value = '';
      }

      // TODO: When backend is ready, uncomment this:
      /*
      const formData = new FormData();
      formData.append('file', file);
      formData.append('target_url', targetFileUrl);

      const response = await fetch(`${API_BASE_URL}/knowledge-base/upload`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${localStorage.getItem(ACCESS_TOKEN)}`,
        },
        body: formData,
      });

      if (!response.ok) {
        throw new Error('Upload failed');
      }
      
      const data = await response.json();
      */
      
    } catch (error) {
      console.error('Error uploading file:', error);
      Swal.fire({
        icon: 'error',
        title: 'Upload Failed',
        text: 'Failed to upload file. Please try again.',
        confirmButtonColor: '#26326e',
        customClass: {
          popup: 'swal-inter-font'
        }
      });
    } finally {
      setIsProcessing(false);
      setProcessingProgress(0);
    }
  };

  // Remove uploaded file
  const handleRemoveUploadedFile = (fileId) => {
    setUploadedFiles(prev => prev.filter(f => f.id !== fileId));
  };

  // Read file content for comparison
  const readFileContent = (file) => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        const content = e.target.result;
        // For text files, return as text
        if (file.type === 'text/plain') {
          resolve({ type: 'text', content });
        } else if (file.type.includes('pdf')) {
          // For PDF, show basic info
          resolve({ 
            type: 'pdf', 
            content: 'PDF Preview',
            info: `PDF Document - ${(file.size / 1024).toFixed(2)} KB`
          });
        } else if (file.type.includes('word')) {
          // For DOCX, show basic info
          resolve({ 
            type: 'docx', 
            content: 'DOCX Preview',
            info: `Word Document - ${(file.size / 1024).toFixed(2)} KB`
          });
        } else {
          resolve({ type: 'unknown', content: 'Preview not available' });
        }
      };
      reader.onerror = reject;
      
      if (file.type === 'text/plain') {
        reader.readAsText(file);
      } else {
        reader.readAsArrayBuffer(file);
      }
    });
  };

  // Handle duplicate file actions
  const handleDuplicateAction = async (action) => {
    if (action === 'cancel') {
      setShowDuplicateModal(false);
      setPendingFile(null);
      setDuplicateFileInfo(null);
      return;
    }

    if (action === 'compare') {
      // Load file contents for comparison
      try {
        setShowDuplicateModal(false);
        
        // For existing file, create a mock File object from metadata
        const existingFileData = {
          name: duplicateFileInfo.file.name,
          type: duplicateFileInfo.file.type === 'PDF' ? 'application/pdf' : 
                duplicateFileInfo.file.type === 'DOCX' ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' : 
                'text/plain',
          size: duplicateFileInfo.file.size,
          uploadedAt: duplicateFileInfo.file.uploadedAt,
          content: `Existing file content preview\nFile: ${duplicateFileInfo.file.name}\nSize: ${duplicateFileInfo.file.size}\nUploaded: ${duplicateFileInfo.file.uploadedAt}\n\nNote: Full content comparison available when backend is connected.`
        };
        
        // Read new file content
        const newContent = await readFileContent(pendingFile);
        
        setExistingFileContent({
          ...existingFileData,
          preview: existingFileData.content
        });
        setNewFileContent({
          name: pendingFile.name,
          type: pendingFile.type,
          size: (pendingFile.size / 1024).toFixed(2) + ' KB',
          preview: newContent.content || newContent.info || 'Content preview'
        });
        
        setShowCompareModal(true);
      } catch (error) {
        console.error('Error reading file:', error);
        alert('Failed to load file contents for comparison');
      }
      return;
    }

    setShowDuplicateModal(false);
    if (pendingFile) {
      await uploadFile(pendingFile, action);
      setPendingFile(null);
      setDuplicateFileInfo(null);
    }
  };

  // Handle compare modal actions
  const handleCompareAction = async (action) => {
    setShowCompareModal(false);
    
    if (action === 'back') {
      setShowDuplicateModal(true);
      return;
    }
    
    if (action === 'cancel') {
      setPendingFile(null);
      setDuplicateFileInfo(null);
      setExistingFileContent(null);
      setNewFileContent(null);
      return;
    }

    // For override or keepboth from compare modal
    if (pendingFile) {
      await uploadFile(pendingFile, action);
      setPendingFile(null);
      setDuplicateFileInfo(null);
      setExistingFileContent(null);
      setNewFileContent(null);
    }
  };

  return (
    <div className="knowledge-base-page">
      <div className="knowledge-base-container">
        <div className="knowledge-base-header-row">
          <div>
            <h1 className="knowledge-base-header-title">
              Dynamic Mapping
            </h1>
            <div className="knowledge-base-header-subtitle">
              Upload source files to the target Google Sheets
            </div>
          </div>
        </div>

        {/* Target and Source Cards - Swapped positions */}
        <div className="kb-cards-container">
          {/* Target File Card - Now on LEFT */}
          <div className="kb-card">
            <div className="kb-card-header">
              <h3>
                <FileText size={20} />
                Target File
              </h3>
              <span className="kb-card-badge target">Google Sheets</span>
            </div>
            <div className="kb-card-body">
              <div className="kb-card-content" style={{ width: '100%' }}>
                <div style={{ marginBottom: '20px' }}>
                  <label style={{ 
                    display: 'block', 
                    fontWeight: '600', 
                    marginBottom: '8px', 
                    color: '#1f2937',
                    fontSize: '0.9rem'
                  }}>
                    Google Sheets URL
                  </label>
                  <input
                    type="url"
                    value={targetFileUrl}
                    onChange={handleTargetUrlChange}
                    placeholder="https://docs.google.com/spreadsheets/d/..."
                    style={{
                      width: '100%',
                      padding: '12px',
                      border: '1px solid #d1d5db',
                      borderRadius: '8px',
                      fontSize: '0.9rem',
                      fontFamily: 'Inter, sans-serif'
                    }}
                  />
                </div>
                {targetFileUrl && (
                  <div className="kb-file-display">
                    <CheckCircle2 size={40} className="kb-file-icon-large success" />
                    <div className="kb-file-details">
                      <div className="kb-file-name-large">Google Sheets Connected</div>
                      <div className="kb-file-status">
                        <CheckCircle2 size={14} />
                        Ready to receive uploads
                      </div>
                    </div>
                  </div>
                )}
                <div className="kb-card-actions">
                  <button
                    className="kb-card-button primary"
                    onClick={handleSaveTargetUrl}
                    disabled={!targetFileUrl.trim()}
                  >
                    <CheckCircle2 size={18} />
                    Save Target URL
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Source File Card - Now on RIGHT */}
          <div className="kb-card">
            <div className="kb-card-header">
              <h3>
                <Upload size={20} />
                Source Files
              </h3>
              <span className="kb-card-badge source">Upload History</span>
            </div>
            <div className="kb-card-body">
              <div className="kb-card-content" style={{ width: '100%' }}>
                <input
                  ref={sourceFileInputRef}
                  type="file"
                  accept=".pdf,.csv,.xlsx"
                  onChange={handleSourceFileSelect}
                  style={{ display: 'none' }}
                />
                <button
                  className="kb-card-button primary"
                  onClick={() => sourceFileInputRef.current?.click()}
                  disabled={!isValidUrlSaved || isProcessing}
                  style={{ width: '100%', marginBottom: '20px' }}
                >
                  <Upload size={18} />
                  {isProcessing ? `Uploading... ${processingProgress}%` : 'Upload Source File'}
                </button>
                
                {!isValidUrlSaved && (
                  <div className="kb-empty-hint" style={{ textAlign: 'center', marginBottom: '20px' }}>
                    ⚠️ Save a valid Google Sheets URL first to enable uploads
                  </div>
                )}

                {isProcessing && (
                  <div className="kb-progress-bar" style={{ marginBottom: '20px' }}>
                    <div className="kb-progress-fill" style={{ width: `${processingProgress}%` }}></div>
                  </div>
                )}

                {/* Uploaded Files List */}
                {uploadedFiles.length > 0 ? (
                  <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                    <h4 style={{ fontSize: '0.9rem', fontWeight: '700', marginBottom: '12px', color: '#1f2937' }}>
                      Uploaded Files ({uploadedFiles.length})
                    </h4>
                    {uploadedFiles.map((file) => (
                      <div key={file.id} style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '12px',
                        background: '#f9fafb',
                        borderRadius: '8px',
                        marginBottom: '8px',
                        border: '1px solid #e5e7eb'
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1 }}>
                          <FileText size={24} color="#26326e" />
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontWeight: '600', fontSize: '0.9rem', color: '#1f2937', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {file.name}
                            </div>
                            <div style={{ fontSize: '0.8rem', color: '#6b7280', marginTop: '4px' }}>
                              <span style={{ 
                                background: '#dbeafe', 
                                color: '#1e40af', 
                                padding: '2px 8px', 
                                borderRadius: '4px',
                                fontWeight: '600',
                                marginRight: '8px'
                              }}>
                                {file.type}
                              </span>
                              {file.size} • {file.uploadedAt}
                            </div>
                          </div>
                        </div>
                        <button
                          onClick={() => handleRemoveUploadedFile(file.id)}
                          style={{
                            background: 'none',
                            border: 'none',
                            color: '#ef4444',
                            cursor: 'pointer',
                            padding: '4px'
                          }}
                        >
                          <X size={18} />
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="kb-card-empty">
                    <File size={48} className="kb-empty-icon" />
                    <p>No files uploaded yet</p>
                    <span className="kb-file-formats">PDF, XLSX, and CSV</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Compare Files Modal */}
        {showCompareModal && existingFileContent && newFileContent && (
          <div className="duplicate-modal-overlay" onClick={() => handleCompareAction('cancel')}>
            <div className="compare-modal" onClick={(e) => e.stopPropagation()}>
              <div className="duplicate-modal-header">
                <Search size={32} color="#3b82f6" />
                <h2>Compare Files</h2>
                <button 
                  className="duplicate-modal-close" 
                  onClick={() => handleCompareAction('cancel')}
                >
                  <X size={20} />
                </button>
              </div>
              
              <div className="compare-modal-body">
                <div className="compare-columns">
                  {/* Existing File Column */}
                  <div className="compare-column">
                    <div className="compare-column-header existing">
                      <FileText size={20} />
                      <div>
                        <div className="compare-column-title">Existing File</div>
                        <div className="compare-column-subtitle">{existingFileContent.name}</div>
                      </div>
                    </div>
                    <div className="compare-column-meta">
                      <div className="compare-meta-item">
                        <strong>Size:</strong> {existingFileContent.size}
                      </div>
                      <div className="compare-meta-item">
                        <strong>Uploaded:</strong> {existingFileContent.uploadedAt}
                      </div>
                      <div className="compare-meta-item">
                        <strong>Type:</strong> {existingFileContent.type}
                      </div>
                    </div>
                    <div className="compare-column-content">
                      <div className="compare-preview-label">Content Preview:</div>
                      <pre className="compare-preview">{existingFileContent.preview}</pre>
                    </div>
                  </div>

                  {/* New File Column */}
                  <div className="compare-column">
                    <div className="compare-column-header new">
                      <Upload size={20} />
                      <div>
                        <div className="compare-column-title">New File</div>
                        <div className="compare-column-subtitle">{newFileContent.name}</div>
                      </div>
                    </div>
                    <div className="compare-column-meta">
                      <div className="compare-meta-item">
                        <strong>Size:</strong> {newFileContent.size}
                      </div>
                      <div className="compare-meta-item">
                        <strong>Type:</strong> {newFileContent.type}
                      </div>
                    </div>
                    <div className="compare-column-content">
                      <div className="compare-preview-label">Content Preview:</div>
                      <pre className="compare-preview">{newFileContent.preview}</pre>
                    </div>
                  </div>
                </div>

                <div className="compare-difference-summary">
                  <strong>Summary:</strong> {
                    existingFileContent.size === newFileContent.size 
                      ? "Files have the same size" 
                      : "Files have different sizes"
                  }
                </div>
              </div>

              <div className="compare-modal-actions">
                <button 
                  className="duplicate-action-btn back"
                  onClick={() => handleCompareAction('back')}
                >
                  <FileText size={18} />
                  Back to Options
                </button>
                <button 
                  className="duplicate-action-btn override"
                  onClick={() => handleCompareAction('override')}
                >
                  <Upload size={18} />
                  Use New File
                </button>
                <button 
                  className="duplicate-action-btn keepboth"
                  onClick={() => handleCompareAction('keepboth')}
                >
                  <CheckCircle2 size={18} />
                  Keep Both
                </button>
                <button 
                  className="duplicate-action-btn cancel"
                  onClick={() => handleCompareAction('cancel')}
                >
                  <X size={18} />
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Duplicate File Modal */}
        {showDuplicateModal && duplicateFileInfo && (
          <div className="duplicate-modal-overlay" onClick={() => handleDuplicateAction('cancel')}>
            <div className="duplicate-modal" onClick={(e) => e.stopPropagation()}>
              <div className="duplicate-modal-header">
                <FileText size={32} color="#fcb117" />
                <h2>Duplicate File Detected</h2>
                <button 
                  className="duplicate-modal-close" 
                  onClick={() => handleDuplicateAction('cancel')}
                >
                  <X size={20} />
                </button>
              </div>
              
              <div className="duplicate-modal-body">
                <p className="duplicate-modal-message">
                  {duplicateFileInfo.type === 'name' 
                    ? `A file named "${duplicateFileInfo.file.name}" already exists.`
                    : `A file with similar content already exists: "${duplicateFileInfo.file.name}"`
                  }
                </p>
                
                <div className="duplicate-file-info">
                  <div className="duplicate-file-item">
                    <div className="duplicate-file-label">Existing File:</div>
                    <div className="duplicate-file-details">
                      <FileText size={18} />
                      <span>{duplicateFileInfo.file.name}</span>
                      <span className="duplicate-file-meta">
                        {duplicateFileInfo.file.size} • {duplicateFileInfo.file.uploadedAt}
                      </span>
                    </div>
                  </div>
                  <div className="duplicate-file-item">
                    <div className="duplicate-file-label">New File:</div>
                    <div className="duplicate-file-details">
                      <FileText size={18} />
                      <span>{pendingFile?.name}</span>
                      <span className="duplicate-file-meta">
                        {(pendingFile?.size / 1024).toFixed(2)} KB
                      </span>
                    </div>
                  </div>
                </div>

                <div className="duplicate-modal-question">
                  What would you like to do?
                </div>
              </div>

              <div className="duplicate-modal-actions">
                <button 
                  className="duplicate-action-btn override"
                  onClick={() => handleDuplicateAction('override')}
                >
                  <Upload size={18} />
                  Override Existing
                </button>
                <button 
                  className="duplicate-action-btn keepboth"
                  onClick={() => handleDuplicateAction('keepboth')}
                >
                  <CheckCircle2 size={18} />
                  Keep Both Files
                </button>
                <button 
                  className="duplicate-action-btn compare"
                  onClick={() => handleDuplicateAction('compare')}
                >
                  <Search size={18} />
                  Compare Files
                </button>
                <button 
                  className="duplicate-action-btn cancel"
                  onClick={() => handleDuplicateAction('cancel')}
                >
                  <X size={18} />
                  Cancel Upload
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default KnowledgeBase;
