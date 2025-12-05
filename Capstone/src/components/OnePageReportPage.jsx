import React, { useState, useRef, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { 
  FileText, 
  ArrowLeft, 
  Upload, 
  File, 
  X, 
  CheckCircle2,
  History
} from "lucide-react";
import Swal from "sweetalert2";
import "../css/OnePageReportPage.css";

function OnePageReportPage() {
  const navigate = useNavigate();
  const location = useLocation();
  
  // Target and Source file states
  const [targetFileUrl, setTargetFileUrl] = useState("");
  const [isValidUrlSaved, setIsValidUrlSaved] = useState(false); // Track if valid URL is saved
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingProgress, setProcessingProgress] = useState(0);
  
  const sourceFileInputRef = useRef(null);

  // Load from history if navigated from history page
  useEffect(() => {
    const loadEntry = location.state?.loadEntry;
    if (loadEntry) {
      setTargetFileUrl(loadEntry.targetUrl);
      setUploadedFiles(loadEntry.files);
      // Clear the state so it doesn't reload on refresh
      navigate(location.pathname, { replace: true, state: {} });
    }
  }, [location.state]);

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

  // Handle source file selection
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

    await uploadFile(file);
  };

  // Upload file function
  const uploadFile = async (file) => {
    setIsProcessing(true);
    setProcessingProgress(0);

    try {
      const progressInterval = setInterval(() => {
        setProcessingProgress((prev) => {
          if (prev >= 90) {
            clearInterval(progressInterval);
            return 90;
          }
          return prev + 10;
        });
      }, 200);

      await new Promise(resolve => setTimeout(resolve, 1500));
      
      clearInterval(progressInterval);
      setProcessingProgress(100);

      const fileType = file.type.includes('pdf') ? 'PDF' : 
                      file.type.includes('csv') ? 'CSV' : 
                      file.type.includes('spreadsheet') ? 'XLSX' : 'Unknown';
      const fileSizeKB = (file.size / 1024).toFixed(2);
      
      const newFile = {
        id: Date.now(),
        name: file.name,
        type: fileType,
        size: fileSizeKB + ' KB',
        uploadedAt: new Date().toLocaleString()
      };

      const updatedFiles = [...uploadedFiles, newFile];
      setUploadedFiles(updatedFiles);
      
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
      
      if (sourceFileInputRef.current) {
        sourceFileInputRef.current.value = '';
      }
    } catch (error) {
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

  // Save to history function
  const saveToHistory = (targetUrl, files, action) => {
    const savedHistory = localStorage.getItem('opr_history');
    const history = savedHistory ? JSON.parse(savedHistory) : [];
    
    // Check if we're editing an existing entry
    const editingEntryId = localStorage.getItem('opr_editing_entry_id');
    
    if (editingEntryId && (action === 'add' || action === 'remove')) {
      // We're updating an existing entry (either adding or removing files)
      const entryIndex = history.findIndex(entry => entry.id === parseInt(editingEntryId));
      
      if (entryIndex !== -1) {
        // Remove the old entry from its position
        const updatedEntry = {
          ...history[entryIndex],
          files: files,
          action: 'update',
          timestamp: new Date().toLocaleString(),
          fileCount: files.length
        };
        
        // Remove from old position
        history.splice(entryIndex, 1);
        
        // Add to top of history
        const updatedHistory = [updatedEntry, ...history];
        localStorage.setItem('opr_history', JSON.stringify(updatedHistory));
        // Don't clear the editing flag yet, in case they add/remove more files
        
        // TODO: Send to backend API
        // await fetch('/api/opr-history', { method: 'PUT', body: JSON.stringify(updatedEntry) });
        return;
      }
    }
    
    // Create new entry if not updating
    const historyEntry = {
      id: Date.now(),
      targetUrl: targetUrl,
      files: files,
      action: action, // 'add', 'remove', 'override', 'update'
      timestamp: new Date().toLocaleString(),
      fileCount: files.length
    };

    const updatedHistory = [historyEntry, ...history];
    localStorage.setItem('opr_history', JSON.stringify(updatedHistory));
    
    // Clear the editing flag if this was a new entry
    if (action === 'add') {
      localStorage.removeItem('opr_editing_entry_id');
    }
    
    // TODO: Send to backend API
    // await fetch('/api/opr-history', { method: 'POST', body: JSON.stringify(historyEntry) });
  };

  // Remove uploaded file
  const handleRemoveUploadedFile = (fileId) => {
    const updatedFiles = uploadedFiles.filter(f => f.id !== fileId);
    setUploadedFiles(updatedFiles);
  };

  // Navigate to history page
  const handleViewHistory = () => {
    navigate('/opr-history');
  };

  // Handle process/confirm button
  const handleProcess = async () => {
    if (!isValidUrlSaved || uploadedFiles.length === 0) {
      Swal.fire({
        icon: 'warning',
        title: 'Incomplete Data',
        text: 'Please add a valid Target File URL and upload at least one source file.',
        confirmButtonColor: '#26326e',
        customClass: {
          popup: 'swal-inter-font'
        }
      });
      return;
    }

    // Show confirmation dialog
    const result = await Swal.fire({
      icon: 'question',
      title: 'Process Files',
      html: `<strong>Target:</strong> Google Sheets<br><strong>Source Files:</strong> ${uploadedFiles.length} file(s)<br><br>Ready to process?`,
      showCancelButton: true,
      confirmButtonText: 'Yes, Process',
      cancelButtonText: 'Cancel',
      confirmButtonColor: '#26326e',
      cancelButtonColor: '#6b7280',
      customClass: {
        popup: 'swal-inter-font'
      }
    });

    if (result.isConfirmed) {
      // Save to history
      saveToHistory(targetFileUrl, uploadedFiles, 'process');
      
      // Show success message
      Swal.fire({
        icon: 'success',
        title: 'Processing Complete!',
        text: 'Files have been saved to history.',
        confirmButtonColor: '#26326e',
        timer: 2000,
        customClass: {
          popup: 'swal-inter-font'
        }
      });

      // TODO: Add backend API call here
      // await fetch('/api/process-files', { 
      //   method: 'POST', 
      //   body: JSON.stringify({ targetUrl: targetFileUrl, files: uploadedFiles }) 
      // });
    }
  };

  return (
    <div className="analysis-report-page">
      <div className="analysis-report-container">
        <div className="analysis-report-header-row">
          <div>
            <button 
              className="analysis-back-button"
              onClick={() => navigate('/analysis-report')}
              title="Back to Analysis Report"
            >
              <ArrowLeft size={20} />
            </button>
            <h1 className="analysis-report-header-title">
              <FileText size={40} />
              One Page Report
            </h1>
            <div className="analysis-report-header-subtitle">
              Summarized overview and insights
            </div>
          </div>
          <div style={{ display: 'flex', gap: '12px' }}>
            <button
              className="opr-view-history-btn"
              onClick={handleViewHistory}
              title="View Upload History"
            >
              <History size={20} />
            </button>
            <button
              className="opr-process-btn"
              onClick={handleProcess}
              disabled={!isValidUrlSaved || uploadedFiles.length === 0}
              style={{
                padding: '12px 24px',
                background: (!isValidUrlSaved || uploadedFiles.length === 0) ? '#9ca3af' : '#26326e',
                color: 'white',
                border: 'none',
                borderRadius: '8px',
                fontSize: '1rem',
                fontWeight: '600',
                cursor: (!isValidUrlSaved || uploadedFiles.length === 0) ? 'not-allowed' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                transition: 'all 0.2s'
              }}
            >
              <CheckCircle2 size={20} />
              Process Files
            </button>
          </div>
        </div>

        {/* Target and Source Cards */}
        <div className="kb-cards-container">
          {/* Target File Card */}
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

          {/* Source File Card */}
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
                    <span className="kb-file-formats">PDF, CSV, or XLSX</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default OnePageReportPage;
