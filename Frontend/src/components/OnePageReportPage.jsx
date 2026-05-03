import React, { useState, useRef, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  FileText, ArrowLeft, Upload, File, X,
  CheckCircle2, History, Eye, Play,
  AlertCircle, ChevronDown, ChevronUp
} from "lucide-react";
import Swal from "sweetalert2";
import { previewOPR, processOPR } from "../services/oprService";
import "../css/OnePageReportPage.css";

function PreviewModal({ preview, onApprove, onCancel }) {
  const [expandedRows, setExpandedRows] = useState({});
  const [editedMappings, setEditedMappings] = useState(
    () => ({ ...preview.mappings })
  );

  const toggleRow = (date) =>
    setExpandedRows(prev => ({ ...prev, [date]: !prev[date] }));

  const handleMappingChange = (source, newTarget) => {
    setEditedMappings(prev => ({ ...prev, [source]: newTarget || null }));
  };

  const highConf = Object.entries(editedMappings).filter(
    ([, t]) => t !== null
  ).length;

  return (
    <div className="opr-modal-overlay">
      <div className="opr-modal">
        <div className="opr-modal-header">
          <h2><Eye size={20} /> Preview Changes</h2>
          <button className="opr-modal-close" onClick={onCancel}>
            <X size={20} />
          </button>
        </div>

        <div className="opr-modal-body">
          <div className="opr-preview-summary">
            <div className="opr-summary-stat">
              <span className="stat-value">{preview.matched_count}</span>
              <span className="stat-label">Dates Matched</span>
            </div>
            <div className="opr-summary-stat">
              <span className="stat-value">{highConf}</span>
              <span className="stat-label">Columns Mapped</span>
            </div>
            <div className="opr-summary-stat">
              <span className="stat-value">{preview.total_changes}</span>
              <span className="stat-label">Cells to Update</span>
            </div>
          </div>

          <div className="opr-section">
            <h3>Column Mappings</h3>
            <p className="opr-section-hint">
              Review and adjust how your file columns map to the Google Sheet.
            </p>
            <div className="opr-mappings-table">
              <div className="opr-mappings-header">
                <span>Your File Column</span>
                <span>Maps To (Google Sheet)</span>
              </div>
              {Object.entries(editedMappings)
                .filter(([source]) => source.toLowerCase() !== 'date')
                .map(([source, target]) => (
                  <div key={source} className="opr-mapping-row">
                    <span className="opr-source-col">{String(source)}</span>
                    <input
                      className="opr-target-input"
                      value={target || ''}
                      onChange={e => handleMappingChange(source, e.target.value)}
                      placeholder="(not mapped)"
                    />
                  </div>
                ))}
            </div>
          </div>

          {preview.preview_rows.length > 0 && (
            <div className="opr-section">
              <h3>Rows to be Updated ({preview.preview_rows.length})</h3>
              {preview.preview_rows.map((row) => (
                <div key={row.date} className="opr-preview-row">
                  <div
                    className="opr-preview-row-header"
                    onClick={() => toggleRow(row.date)}
                  >
                    <span className="opr-row-date">{row.date}</span>
                    <span className="opr-row-changes">
                      {row.changes.length} changes
                    </span>
                    {expandedRows[row.date]
                      ? <ChevronUp size={16} />
                      : <ChevronDown size={16} />}
                  </div>
                  {expandedRows[row.date] && (
                    <div className="opr-preview-row-detail">
                      {row.changes.map((change) => (
                        <div key={change.column} className="opr-change-item">
                          <span className="change-col">{change.column}</span>
                          <span className="change-old">{change.current_value || '(empty)'}</span>
                          <span className="change-arrow">→</span>
                          <span className="change-new">{change.new_value}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {preview.unmatched_dates.length > 0 && (
            <div className="opr-warning-box">
              <AlertCircle size={16} />
              <span>
                {preview.unmatched_dates.length} date(s) in your file were not
                found in the Google Sheet and will be skipped.
              </span>
            </div>
          )}
        </div>

        <div className="opr-modal-footer">
          <button className="opr-btn-secondary" onClick={onCancel}>
            Cancel
          </button>
          <button
            className="opr-btn-primary"
            onClick={() => onApprove(editedMappings)}
          >
            <Play size={16} />
            Apply Changes ({preview.matched_count} rows)
          </button>
        </div>
      </div>
    </div>
  );
}

function OnePageReportPage() {
  const navigate = useNavigate();
  const location = useLocation();

  const [targetFileUrl, setTargetFileUrl] = useState("");
  const [isValidUrlSaved, setIsValidUrlSaved] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingProgress, setProcessingProgress] = useState(0);
  const [processingStep, setProcessingStep] = useState("");

  const [showPreview, setShowPreview] = useState(false);
  const [previewData, setPreviewData] = useState(null);
  const [previewFile, setPreviewFile] = useState(null);
  const [isPreviewing, setIsPreviewing] = useState(false);

  const sourceFileInputRef = useRef(null);

  useEffect(() => {
    const loadEntry = location.state?.loadEntry;
    if (loadEntry) {
      setTargetFileUrl(loadEntry.targetUrl);
      setUploadedFiles(loadEntry.files || []);
      navigate(location.pathname, { replace: true, state: {} });
    }
  }, [location.state]);

  const handleTargetUrlChange = (e) => {
    setTargetFileUrl(e.target.value);
    setIsValidUrlSaved(false);
  };

  const handleSaveTargetUrl = () => {
    if (!targetFileUrl.trim()) {
      return Swal.fire({ icon: 'warning', title: 'URL Required',
        text: 'Please enter a Google Sheets URL', confirmButtonColor: '#26326e',
        customClass: { popup: 'swal-inter-font' } });
    }
    if (!targetFileUrl.includes('docs.google.com/spreadsheets')) {
      return Swal.fire({ icon: 'error', title: 'Invalid URL',
        text: 'Please enter a valid Google Sheets URL', confirmButtonColor: '#26326e',
        customClass: { popup: 'swal-inter-font' } });
    }
    Swal.fire({ icon: 'success', title: 'Saved!', text: 'Target URL saved successfully.',
      confirmButtonColor: '#26326e', timer: 1500,
      customClass: { popup: 'swal-inter-font' } });
    setIsValidUrlSaved(true);
  };

  const handleSourceFileSelect = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const validTypes = [
      'text/csv',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'application/vnd.ms-excel'
    ];
    if (!validTypes.includes(file.type)) {
      return Swal.fire({ icon: 'error', title: 'Invalid File Type',
        text: 'Only CSV and XLSX files are accepted for OPR.',
        confirmButtonColor: '#26326e', customClass: { popup: 'swal-inter-font' } });
    }
    if (!isValidUrlSaved) {
      return Swal.fire({ icon: 'warning', title: 'Target URL Required',
        text: 'Please save a valid Google Sheets URL first.',
        confirmButtonColor: '#26326e', customClass: { popup: 'swal-inter-font' } });
    }
    const newFile = {
      id: Date.now(), name: file.name,
      size: (file.size / 1024).toFixed(2) + ' KB',
      type: file.type.includes('csv') ? 'CSV' : 'XLSX',
      uploadedAt: new Date().toLocaleString(), rawFile: file
    };
    setUploadedFiles(prev => [...prev, newFile]);
    if (sourceFileInputRef.current) sourceFileInputRef.current.value = '';
  };

  const handleRemoveFile = (id) => {
    setUploadedFiles(prev => prev.filter(f => f.id !== id));
  };

  const handlePreviewFile = async (fileEntry) => {
    setIsPreviewing(true);
    try {
      setProcessingStep(`Previewing ${fileEntry.name}...`);
      const result = await previewOPR(fileEntry.rawFile, targetFileUrl);

      const raw = result.preview ?? {};
      const safePreview = {
        matched_count: Number(raw.matched_count ?? 0),
        total_changes: Number(raw.total_changes ?? 0),
        columns_mapped: Number(raw.columns_mapped ?? 0),
        high_confidence_count: Number(raw.high_confidence_count ?? 0),
        unmatched_count: Number(raw.unmatched_count ?? 0),
        mappings: (raw.mappings && typeof raw.mappings === 'object') ? raw.mappings : {},
        confidence_scores: (raw.confidence_scores && typeof raw.confidence_scores === 'object') ? raw.confidence_scores : {},
        unmatched_dates: Array.isArray(raw.unmatched_dates) ? raw.unmatched_dates.map(d => String(d)) : [],
        matched_dates: Array.isArray(raw.matched_dates) ? raw.matched_dates.map(d => String(d)) : [],
        needs_review: Array.isArray(raw.needs_review) ? raw.needs_review : [],
        preview_rows: Array.isArray(raw.preview_rows)
          ? raw.preview_rows.map(row => ({
              date: String(row.date ?? ''),
              row_number: Number(row.row_number ?? 0),
              changes: Array.isArray(row.changes)
                ? row.changes.map(change => ({
                    column: String(change.column ?? ''),
                    current_value: String(change.current_value ?? ''),
                    new_value: String(change.new_value ?? ''),
                    column_letter: String(change.column_letter ?? ''),
                    will_change: Boolean(change.will_change),
                  }))
                : [],
            }))
          : [],
      };

      setPreviewData(safePreview);
      setPreviewFile(fileEntry);
      setShowPreview(true);
    } catch (err) {
      Swal.fire({ icon: 'error', title: 'Preview Failed', text: err.message,
        confirmButtonColor: '#26326e', customClass: { popup: 'swal-inter-font' } });
    } finally {
      setIsPreviewing(false);
      setProcessingStep('');
    }
  };

  const handleApproveAndProcess = async (approvedMappings) => {
    setShowPreview(false);
    setIsProcessing(true);
    setProcessingProgress(0);
    setProcessingStep(`Processing ${previewFile.name}...`);
    try {
      const progressInterval = setInterval(() => {
        setProcessingProgress(p => p >= 85 ? 85 : p + 10);
      }, 800);
      const result = await processOPR(previewFile.rawFile, targetFileUrl, approvedMappings);
      clearInterval(progressInterval);
      setProcessingProgress(100);
      setProcessingStep('Complete!');
      saveToHistory(targetFileUrl, uploadedFiles, 'process', result);
      await Swal.fire({
        icon: 'success', title: 'Processing Complete!',
        html: `
          <strong>${result.rows_updated}</strong> rows updated<br/>
          <strong>${result.results?.columns_mapped ?? 0}</strong> columns mapped<br/>
          <strong>${result.results?.cells_updated ?? 0}</strong> cells updated
        `,
        confirmButtonColor: '#26326e', customClass: { popup: 'swal-inter-font' }
      });
      setUploadedFiles(prev => prev.filter(f => f.id !== previewFile.id));
    } catch (err) {
      Swal.fire({ icon: 'error', title: 'Processing Failed', text: err.message,
        confirmButtonColor: '#26326e', customClass: { popup: 'swal-inter-font' } });
    } finally {
      setIsProcessing(false);
      setProcessingProgress(0);
      setProcessingStep('');
      setPreviewFile(null);
    }
  };

  const saveToHistory = (targetUrl, files, action, result = null) => {
    const saved = localStorage.getItem('opr_history');
    const history = saved ? JSON.parse(saved) : [];
    const entry = {
      id: Date.now(), targetUrl,
      files: files.map(f => ({ name: f.name, size: f.size, type: f.type })),
      action, timestamp: new Date().toLocaleString(), result
    };
    localStorage.setItem('opr_history', JSON.stringify([entry, ...history]));
  };

  return (
    <div className="analysis-report-page">
      {showPreview && previewData && (
        <PreviewModal
          preview={previewData}
          onApprove={handleApproveAndProcess}
          onCancel={() => setShowPreview(false)}
        />
      )}

      <div className="analysis-report-container">
        <div className="analysis-report-header-row">
          <div>
            <button className="analysis-back-button" onClick={() => navigate('/analysis-report')}>
              <ArrowLeft size={20} />
            </button>
            <h1 className="analysis-report-header-title">
              <FileText size={40} /> One Page Report
            </h1>
            <div className="analysis-report-header-subtitle">
              Upload your OPR file and sync it to Google Sheets
            </div>
          </div>
          <button className="opr-view-history-btn" onClick={() => navigate('/opr-history')}>
            <History size={20} /> History
          </button>
        </div>

        <div className="kb-cards-container">
          <div className="kb-card">
            <div className="kb-card-header">
              <h3><FileText size={20} /> Target File</h3>
              <span className="kb-card-badge target">Google Sheets</span>
            </div>
            <div className="kb-card-body">
              <div className="kb-card-content" style={{ width: '100%' }}>
                <label style={{ display: 'block', fontWeight: '600',
                  marginBottom: '8px', color: '#1f2937', fontSize: '0.9rem' }}>
                  Google Sheets URL
                </label>
                <input type="url" value={targetFileUrl} onChange={handleTargetUrlChange}
                  placeholder="https://docs.google.com/spreadsheets/d/..."
                  style={{ width: '100%', padding: '12px', border: '1px solid #d1d5db',
                    borderRadius: '8px', fontSize: '0.9rem', fontFamily: 'Inter, sans-serif',
                    marginBottom: '16px' }} />
                {isValidUrlSaved && (
                  <div className="kb-file-display" style={{ marginBottom: '16px' }}>
                    <CheckCircle2 size={32} color="#10b981" />
                    <div className="kb-file-details">
                      <div className="kb-file-name-large">Google Sheets Connected</div>
                      <div className="kb-file-status">Ready to receive data</div>
                    </div>
                  </div>
                )}
                <button className="kb-card-button primary" onClick={handleSaveTargetUrl}
                  disabled={!targetFileUrl.trim()}>
                  <CheckCircle2 size={18} /> Save Target URL
                </button>
              </div>
            </div>
          </div>

          <div className="kb-card">
            <div className="kb-card-header">
              <h3><Upload size={20} /> Source Files</h3>
              <span className="kb-card-badge source">CSV / XLSX</span>
            </div>
            <div className="kb-card-body">
              <div className="kb-card-content" style={{ width: '100%' }}>
                <input ref={sourceFileInputRef} type="file" accept=".csv,.xlsx,.xls"
                  onChange={handleSourceFileSelect} style={{ display: 'none' }} />
                <button className="kb-card-button primary"
                  onClick={() => sourceFileInputRef.current?.click()}
                  disabled={!isValidUrlSaved || isProcessing}
                  style={{ width: '100%', marginBottom: '16px' }}>
                  <Upload size={18} /> Add File
                </button>

                {!isValidUrlSaved && (
                  <p style={{ textAlign: 'center', color: '#f59e0b',
                    fontSize: '0.85rem', marginBottom: '12px' }}>
                    ⚠️ Save a valid Google Sheets URL first
                  </p>
                )}

                {(isProcessing || isPreviewing) && (
                  <>
                    <div className="kb-processing-step">{processingStep}</div>
                    {isProcessing && (
                      <div className="kb-progress-bar" style={{ marginBottom: '16px' }}>
                        <div className="kb-progress-fill" style={{ width: `${processingProgress}%` }} />
                      </div>
                    )}
                  </>
                )}

                {uploadedFiles.length > 0 ? (
                  <div>
                    <h4 style={{ fontSize: '0.9rem', fontWeight: '700',
                      marginBottom: '12px', color: '#1f2937' }}>
                      Files ({uploadedFiles.length})
                    </h4>
                    {uploadedFiles.map(file => (
                      <div key={file.id} style={{ display: 'flex', alignItems: 'center',
                        justifyContent: 'space-between', padding: '12px',
                        background: '#f9fafb', borderRadius: '8px',
                        marginBottom: '8px', border: '1px solid #e5e7eb' }}>
                        <div style={{ display: 'flex', alignItems: 'center',
                          gap: '12px', flex: 1, minWidth: 0 }}>
                          <FileText size={24} color="#26326e" />
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontWeight: '600', fontSize: '0.85rem',
                              color: '#1f2937', overflow: 'hidden',
                              textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {file.name}
                            </div>
                            <div style={{ fontSize: '0.75rem', color: '#6b7280' }}>
                              {file.type} • {file.size}
                            </div>
                          </div>
                        </div>
                        <div style={{ display: 'flex', gap: '8px', flexShrink: 0 }}>
                          <button onClick={() => handlePreviewFile(file)}
                            disabled={isProcessing || isPreviewing || !file.rawFile}
                            title="Preview & Process"
                            style={{ background: '#26326e', color: 'white', border: 'none',
                              borderRadius: '6px', padding: '6px 12px', cursor: 'pointer',
                              fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <Eye size={14} /> Preview
                          </button>
                          <button onClick={() => handleRemoveFile(file.id)}
                            disabled={isProcessing}
                            style={{ background: 'none', border: 'none',
                              color: '#ef4444', cursor: 'pointer', padding: '4px' }}>
                            <X size={18} />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="kb-card-empty">
                    <File size={48} className="kb-empty-icon" />
                    <p>No files added yet</p>
                    <span className="kb-file-formats">CSV or XLSX</span>
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