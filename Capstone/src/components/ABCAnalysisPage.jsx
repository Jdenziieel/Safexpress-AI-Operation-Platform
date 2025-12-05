import React, { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { BarChart3, Upload, ExternalLink, Loader2, CheckCircle2, AlertCircle, FileText, ArrowLeft, Clock, File as FileIcon, X } from "lucide-react";
import "../css/ABCAnalysisPage.css";

function ABCAnalysisPage() {
  const navigate = useNavigate();
  const [abcFile, setAbcFile] = useState(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingProgress, setProcessingProgress] = useState(0);
  const [generatedSheetUrl, setGeneratedSheetUrl] = useState("");
  const [analysisResults, setAnalysisResults] = useState(null);
  const [error, setError] = useState(null);
  const [analysisHistory, setAnalysisHistory] = useState(() => {
    const saved = localStorage.getItem('abcAnalysisHistory');
    return saved ? JSON.parse(saved) : [];
  });
  const fileInputRef = useRef(null);

  // Check if there's a selected analysis to view from history
  useEffect(() => {
    const selectedAnalysis = localStorage.getItem('selectedAnalysis');
    if (selectedAnalysis) {
      const entry = JSON.parse(selectedAnalysis);
      setAnalysisResults(entry.results);
      setGeneratedSheetUrl(entry.sheetUrl);
      setAbcFile({ name: entry.fileName });
      localStorage.removeItem('selectedAnalysis');
    }
  }, []);

  const handleFileSelect = (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const validTypes = [
      'application/vnd.ms-excel',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'text/csv'
    ];

    if (!validTypes.includes(file.type)) {
      setError('Please upload an Excel (.xlsx, .xls) or CSV file');
      return;
    }

    setAbcFile(file);
    setError(null);
  };

  const processAbcAnalysis = async () => {
    if (!abcFile) {
      setError('Please select a file first');
      return;
    }

    setIsProcessing(true);
    setProcessingProgress(0);
    setError(null);

    try {
      const progressInterval = setInterval(() => {
        setProcessingProgress(prev => {
          if (prev >= 90) {
            clearInterval(progressInterval);
            return 90;
          }
          return prev + 10;
        });
      }, 300);

      await new Promise(resolve => setTimeout(resolve, 3000));
      
      clearInterval(progressInterval);
      setProcessingProgress(100);

      const mockSheetUrl = `https://docs.google.com/spreadsheets/d/${Math.random().toString(36).substring(7)}/edit`;
      
      const mockResults = {
        totalItems: 150,
        categoryA: { count: 15, percentage: 10, value: 70 },
        categoryB: { count: 45, percentage: 30, value: 25 },
        categoryC: { count: 90, percentage: 60, value: 5 },
        processedAt: new Date().toLocaleString()
      };

      setGeneratedSheetUrl(mockSheetUrl);
      setAnalysisResults(mockResults);

      // Add to history
      const historyEntry = {
        id: Date.now(),
        fileName: abcFile.name,
        fileSize: (abcFile.size / 1024).toFixed(2) + ' KB',
        analyzedAt: new Date().toLocaleString(),
        sheetUrl: mockSheetUrl,
        results: mockResults
      };
      
      const updatedHistory = [historyEntry, ...analysisHistory];
      setAnalysisHistory(updatedHistory);
      localStorage.setItem('abcAnalysisHistory', JSON.stringify(updatedHistory));

    } catch (err) {
      console.error('Error processing ABC analysis:', err);
      setError('Failed to process file. Please try again.');
    } finally {
      setIsProcessing(false);
      setProcessingProgress(0);
    }
  };

  const resetAbcAnalysis = () => {
    setAbcFile(null);
    setGeneratedSheetUrl("");
    setAnalysisResults(null);
    setError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
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
            >
              <ArrowLeft size={20} />
              Back to Analysis Report
            </button>
            <h1 className="analysis-report-header-title">
              ABC Analysis
            </h1>
            <div className="analysis-report-header-subtitle">
              Inventory classification and prioritization
            </div>
          </div>
          <div className="analysis-header-actions">
            {analysisHistory.length > 0 && (
              <button 
                className="history-toggle-btn" 
                onClick={() => navigate('/analysis-abc-history')}
              >
                <Clock size={20} />
                History ({analysisHistory.length})
              </button>
            )}
            {analysisResults && (
              <button className="reset-analysis-btn" onClick={resetAbcAnalysis}>
                Start New Analysis
              </button>
            )}
          </div>
        </div>

        <div className="analysis-content-area">
          {!analysisResults ? (
            <div className="de-card-container">
              <div className="kb-card">
                <div className="kb-card-header">
                  <h3>
                    <Upload size={20} />
                    Upload Inventory Data
                  </h3>
                  <span className="kb-card-badge source">Excel / CSV</span>
                </div>
                <div className="kb-card-body">
                  {!abcFile ? (
                    <div className="kb-card-empty">
                      <FileIcon size={48} className="kb-empty-icon" />
                      <p>No document selected</p>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept=".xlsx,.xls,.csv"
                        onChange={handleFileSelect}
                        style={{ display: 'none' }}
                        id="abc-file-input"
                      />
                      <button
                        className="kb-card-button primary"
                        onClick={() => fileInputRef.current?.click()}
                      >
                        <Upload size={18} />
                        Browse Files
                      </button>
                      <span className="kb-file-formats">Excel (.xlsx, .xls) or CSV</span>
                      <div className="abc-upload-note" style={{ marginTop: '12px' }}>
                        <strong>Required columns:</strong> Item Name, Quantity, Unit Price
                      </div>
                    </div>
                  ) : (
                    <div className="kb-card-content">
                      <div className="kb-file-display">
                        <FileText size={40} className="kb-file-icon-large" />
                        <div className="kb-file-details">
                          <div className="kb-file-name-large">{abcFile.name}</div>
                          <div className="kb-file-size">{(abcFile.size / 1024).toFixed(2)} KB</div>
                        </div>
                      </div>

                      {isProcessing && (
                        <div className="kb-progress-bar" style={{ marginBottom: '20px' }}>
                          <div className="kb-progress-fill" style={{ width: `${processingProgress}%` }}></div>
                        </div>
                      )}

                      {error && (
                        <div className="abc-error-message" style={{ marginBottom: '20px' }}>
                          <AlertCircle size={18} />
                          {error}
                        </div>
                      )}

                      <div className="kb-card-actions">
                        <button
                          className="kb-card-button secondary"
                          onClick={() => {
                            setAbcFile(null);
                            setError(null);
                            if (fileInputRef.current) fileInputRef.current.value = '';
                          }}
                        >
                          <X size={18} />
                          Clear Selection
                        </button>
                        <button
                          className="kb-card-button primary"
                          onClick={processAbcAnalysis}
                          disabled={isProcessing}
                        >
                          {isProcessing ? (
                            <>
                              <Loader2 size={18} className="spinner" />
                              Processing {processingProgress}%
                            </>
                          ) : (
                            <>
                              <BarChart3 size={18} />
                              Analyze
                            </>
                          )}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="kb-card">
              <div className="kb-card-header">
                  <h3>
                    <BarChart3 size={20} />
                    Analysis Results
                  </h3>
                  <span className="kb-card-badge target">Completed</span>
                </div>
                <div className="kb-card-body">
                  <div className="abc-results-section">
                  <div className="abc-success-box">
                    <CheckCircle2 size={32} color="#10b981" />
                    <div>
                      <h3>Analysis Complete!</h3>
                      <p>Your ABC analysis has been processed and a Google Sheet has been generated.</p>
                    </div>
                  </div>

                  <div className="abc-sheet-link-box">
                    <div className="sheet-link-header">
                      <FileText size={24} color="#26326e" />
                      <h4>Generated Analysis Report</h4>
                    </div>
                    <div className="sheet-link-content">
                      <div className="sheet-link-url">{generatedSheetUrl}</div>
                      <a 
                        href={generatedSheetUrl} 
                        target="_blank" 
                        rel="noopener noreferrer"
                        className="open-sheet-btn"
                      >
                        <ExternalLink size={18} />
                        Open in Google Sheets
                      </a>
                    </div>
                  </div>

                  <div className="abc-summary-grid">
                    <div className="abc-summary-card total">
                      <div className="summary-card-icon">📦</div>
                      <div className="summary-card-value">{analysisResults.totalItems}</div>
                      <div className="summary-card-label">Total Items</div>
                    </div>

                    <div className="abc-summary-card category-a">
                      <div className="summary-card-icon">🔴</div>
                      <div className="summary-card-value">{analysisResults.categoryA.count}</div>
                      <div className="summary-card-label">Category A</div>
                      <div className="summary-card-details">
                        {analysisResults.categoryA.percentage}% of items • {analysisResults.categoryA.value}% of value
                      </div>
                    </div>

                    <div className="abc-summary-card category-b">
                      <div className="summary-card-icon">🟡</div>
                      <div className="summary-card-value">{analysisResults.categoryB.count}</div>
                      <div className="summary-card-label">Category B</div>
                      <div className="summary-card-details">
                        {analysisResults.categoryB.percentage}% of items • {analysisResults.categoryB.value}% of value
                      </div>
                    </div>

                    <div className="abc-summary-card category-c">
                      <div className="summary-card-icon">🟢</div>
                      <div className="summary-card-value">{analysisResults.categoryC.count}</div>
                      <div className="summary-card-label">Category C</div>
                      <div className="summary-card-details">
                        {analysisResults.categoryC.percentage}% of items • {analysisResults.categoryC.value}% of value
                      </div>
                    </div>
                  </div>

                  <div className="abc-process-info">
                    <strong>Processed:</strong> {analysisResults.processedAt}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default ABCAnalysisPage;
