import React, { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  BarChart3,
  Upload,
  ExternalLink,
  Loader2,
  CheckCircle2,
  AlertCircle,
  FileText,
  ArrowLeft,
  Clock,
  File as FileIcon,
  X,
} from "lucide-react";
import {
  runABCAnalysis,
  formatAnalysisResults,
} from "../services/abcAnalysisService";
import { useError } from "../utils/ErrorContext";
import "../css/ABCAnalysisPage.css";

const ActionButton = ({ icon: Icon, children, className = '', ...props }) => {
  const isDisabled = Boolean(props.disabled);

  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <button
        className={`main-card-btn ${className}`}
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '12px', fontSize: '1.15rem', fontWeight: 800 }}
        {...props}
      >
        <Icon size={20} />
      </button>
      {!isDisabled && (
        <span
          style={{
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
          }}
          className="button-tooltip"
        >
          {children}
        </span>
      )}
    </div>
  );
};

function ABCAnalysisPage() {
  const navigate = useNavigate();
  const { showError } = useError();
  const [abcFile, setAbcFile] = useState(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingProgress, setProcessingProgress] = useState(0);
  const [processingStep, setProcessingStep] = useState("");
  const [generatedSheetUrl, setGeneratedSheetUrl] = useState("");
  const [analysisResults, setAnalysisResults] = useState(null);
  const [error, setError] = useState(null);
  const [analysisHistory, setAnalysisHistory] = useState(() => {
    const saved = localStorage.getItem("abcAnalysisHistory");
    return saved ? JSON.parse(saved) : [];
  });
  const fileInputRef = useRef(null);

  // Check if there's a selected analysis to view from history
  useEffect(() => {
    const selectedAnalysis = localStorage.getItem("selectedAnalysis");
    if (selectedAnalysis) {
      const entry = JSON.parse(selectedAnalysis);
      setAnalysisResults(entry.results);
      setGeneratedSheetUrl(entry.sheetUrl);
      setAbcFile({ name: entry.fileName });
      localStorage.removeItem("selectedAnalysis");
    }
  }, []);

  const handleFileSelect = (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const validTypes = [
      "application/vnd.ms-excel",
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "text/csv",
    ];

    if (!validTypes.includes(file.type)) {
      setError("Please upload an Excel (.xlsx, .xls) or CSV file");
      return;
    }

    // Check file size (max 10MB)
    const maxSize = 10 * 1024 * 1024;
    if (file.size > maxSize) {
      setError("File size must be less than 10MB");
      return;
    }

    setAbcFile(file);
    setError(null);
  };

  const processAbcAnalysis = async () => {
    if (!abcFile) {
      setError("Please select a file first");
      return;
    }

    setIsProcessing(true);
    setProcessingProgress(0);
    setProcessingStep("Uploading file...");
    setError(null);

    try {
      // Progress simulation
      const progressSteps = [
        { progress: 10, step: "Uploading file..." },
        { progress: 30, step: "Parsing Excel data..." },
        { progress: 50, step: "Detecting months..." },
        { progress: 70, step: "Performing ABC analysis..." },
        { progress: 85, step: "Creating Google Sheet..." },
        { progress: 95, step: "Uploading results..." },
      ];

      let stepIndex = 0;
      const progressInterval = setInterval(() => {
        if (stepIndex < progressSteps.length) {
          setProcessingProgress(progressSteps[stepIndex].progress);
          setProcessingStep(progressSteps[stepIndex].step);
          stepIndex++;
        }
      }, 1000);

      // ✅ REAL API CALL
      const result = await runABCAnalysis(abcFile, {
        aThreshold: 70,
        bThreshold: 90,
      });

      clearInterval(progressInterval);
      setProcessingProgress(100);
      setProcessingStep("Complete!");

      // Format results
      const formattedResults = formatAnalysisResults(result);

      setGeneratedSheetUrl(result.sheet_url);
      setAnalysisResults(formattedResults);

      // Add to history
      const historyEntry = {
        id: Date.now(),
        fileName: abcFile.name,
        fileSize: (abcFile.size / 1024).toFixed(2) + " KB",
        analyzedAt: new Date().toLocaleString(),
        sheetUrl: result.sheet_url,
        results: formattedResults,
      };

      const updatedHistory = [historyEntry, ...analysisHistory];
      setAnalysisHistory(updatedHistory);
      localStorage.setItem(
        "abcAnalysisHistory",
        JSON.stringify(updatedHistory),
      );
    } catch (err) {
      console.error("Error processing ABC analysis:", err);

      let errorMessage = "Failed to process file. Please try again.";
      let errorTitle = "ABC Analysis Failed";
      let severity = "error";

      if (err.message.includes("Google")) {
        errorMessage =
          "Google authentication required. Please connect your Google account in Settings.";
        errorTitle = "Google Authentication Required";
        severity = "warning";
      } else if (
        err.message.includes("network") ||
        err.message.includes("fetch")
      ) {
        errorMessage =
          "Network error. Please check your connection and try again.";
        errorTitle = "Network Error";
      } else if (err.message) {
        errorMessage = err.message;
      }

      setError(errorMessage);

      // Show global error modal
      showError({
        title: errorTitle,
        message: errorMessage,
        severity: severity,
        details: err.stack,
        onRetry: () => processAbcAnalysis(),
      });
    } finally {
      setIsProcessing(false);
      setProcessingProgress(0);
      setProcessingStep("");
    }
  };

  const resetAbcAnalysis = () => {
    setAbcFile(null);
    setGeneratedSheetUrl("");
    setAnalysisResults(null);
    setError(null);
    setProcessingStep("");
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  return (
    <div className="analysis-report-page">
      <div className="analysis-report-container">
        <div className="analysis-report-header-row">
          <div>
            <ActionButton
              icon={ArrowLeft}
              className="abc-header-action-button-back"
              onClick={() => navigate("/analysis-report")}
            >
              Back
            </ActionButton>
            <h1 className="analysis-report-header-title">ABC Analysis</h1>
            <div className="analysis-report-header-subtitle">
              Inventory classification and prioritization
            </div>
          </div>
          <div className="analysis-header-actions">
            {analysisHistory.length > 0 && (
              <ActionButton
                icon={Clock}
                className="abc-header-action-button-history"
                onClick={() => navigate("/analysis-abc-history")}
              >
                History
              </ActionButton>
            )}
            {analysisResults && (
              <ActionButton
                icon={BarChart3}
                className="abc-header-action-button-history"
                onClick={resetAbcAnalysis}
              >
                Start New Analysis
              </ActionButton>
            )}
          </div>
        </div>

        <div className="analysis-content-area">
          {!analysisResults ? (
            <div className="de-card-container">
              <div className="kb-card">
                <div className="kb-card-header">
                  <h3>
                    Upload Inventory Data
                  </h3>
                  <span className="kb-card-badge source">Excel / CSV</span>
                </div>
                <div className="kb-card-body">
                  {!abcFile ? (
                    <div className="kb-card-empty">
                      <p>No document selected</p>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept=".xlsx,.xls,.csv"
                        onChange={handleFileSelect}
                        style={{ display: "none" }}
                        id="abc-file-input"
                      />
                      <button
                        className="kb-card-button primary"
                        onClick={() => fileInputRef.current?.click()}
                      >
                        Browse Files
                      </button>
                      <span className="kb-file-formats">
                        Excel (.xlsx, .xls) or CSV (max 10MB)
                      </span>
                      <div
                        className="abc-upload-note"
                        style={{ marginTop: "12px" }}
                      >
                        <strong>Required columns:</strong> Transdate, Itemcode,
                        Qtyordered, Description (optional)
                      </div>
                    </div>
                  ) : (
                    <div className="kb-card-content">
                      <div className="kb-file-display">
                        <FileText size={40} className="kb-file-icon-large" />
                        <div className="kb-file-details">
                          <div className="kb-file-name-large">
                            {abcFile.name}
                          </div>
                          <div className="kb-file-size">
                            {(abcFile.size / 1024).toFixed(2)} KB
                          </div>
                        </div>
                      </div>

                      {isProcessing && (
                        <>
                          <div className="kb-processing-step">
                            {processingStep}
                          </div>
                          <div
                            className="kb-progress-bar"
                            style={{ marginBottom: "20px" }}
                          >
                            <div
                              className="kb-progress-fill"
                              style={{ width: `${processingProgress}%` }}
                            ></div>
                          </div>
                        </>
                      )}

                      {error && (
                        <div
                          className="abc-error-message"
                          style={{ marginBottom: "20px" }}
                        >
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
                            if (fileInputRef.current)
                              fileInputRef.current.value = "";
                          }}
                          disabled={isProcessing}
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
                      <p>
                        Your ABC analysis has been processed and a Google Sheet
                        has been generated.
                      </p>
                      {analysisResults.monthsAnalyzed &&
                        analysisResults.monthsAnalyzed.length > 0 && (
                          <p className="months-analyzed">
                            <strong>Months analyzed:</strong>{" "}
                            {analysisResults.monthsAnalyzed.join(", ")}
                          </p>
                        )}
                    </div>
                  </div>

                  <div className="abc-sheet-link-box">
                    <div className="sheet-link-header">
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
                      </a>
                    </div>
                  </div>

                  <div className="abc-summary-grid">
                    <div className="abc-summary-card total">
                      <div className="summary-card-icon">.</div>
                      <div className="summary-card-value">
                        {analysisResults.totalItems}
                      </div>
                      <div className="summary-card-label">Total Items</div>
                      {analysisResults.totalTransactions && (
                        <div className="summary-card-details">
                          {analysisResults.totalTransactions} transactions
                        </div>
                      )}
                    </div>

                    <div className="abc-summary-card category-a">
                      <div className="summary-card-icon">.</div>
                      <div className="summary-card-value">
                        {analysisResults.categoryA.count}
                      </div>
                      <div className="summary-card-label">Category A</div>
                      <div className="summary-card-details">
                        {analysisResults.categoryA.percentage}% of items • ~
                        {analysisResults.categoryA.value}% of value
                      </div>
                    </div>

                    <div className="abc-summary-card category-b">
                      <div className="summary-card-icon">🟡</div>
                      <div className="summary-card-value">
                        {analysisResults.categoryB.count}
                      </div>
                      <div className="summary-card-label">Category B</div>
                      <div className="summary-card-details">
                        {analysisResults.categoryB.percentage}% of items • ~
                        {analysisResults.categoryB.value}% of value
                      </div>
                    </div>

                    <div className="abc-summary-card category-c">
                      <div className="summary-card-icon">🟢</div>
                      <div className="summary-card-value">
                        {analysisResults.categoryC.count}
                      </div>
                      <div className="summary-card-label">Category C</div>
                      <div className="summary-card-details">
                        {analysisResults.categoryC.percentage}% of items • ~
                        {analysisResults.categoryC.value}% of value
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
