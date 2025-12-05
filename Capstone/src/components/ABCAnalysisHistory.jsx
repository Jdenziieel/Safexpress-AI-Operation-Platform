import React from "react";
import { useNavigate } from "react-router-dom";
import { Clock, Trash2, Eye, FileText, ExternalLink, ArrowLeft } from "lucide-react";
import "../css/ABCAnalysisHistory.css";

function ABCAnalysisHistory() {
  const navigate = useNavigate();
  const [analysisHistory, setAnalysisHistory] = React.useState(() => {
    const saved = localStorage.getItem('abcAnalysisHistory');
    return saved ? JSON.parse(saved) : [];
  });

  const viewHistoryEntry = (entry) => {
    // Store the selected entry to view it in the main page
    localStorage.setItem('selectedAnalysis', JSON.stringify(entry));
    navigate('/analysis-abc');
  };

  const deleteHistoryEntry = (id) => {
    const updatedHistory = analysisHistory.filter(entry => entry.id !== id);
    setAnalysisHistory(updatedHistory);
    localStorage.setItem('abcAnalysisHistory', JSON.stringify(updatedHistory));
  };

  const clearAllHistory = () => {
    if (window.confirm('Are you sure you want to clear all history? This action cannot be undone.')) {
      setAnalysisHistory([]);
      localStorage.removeItem('abcAnalysisHistory');
    }
  };

  return (
    <div className="analysis-report-page">
      <div className="analysis-report-container">
        <div className="analysis-report-header-row">
          <div>
            <button 
              className="analysis-back-button"
              onClick={() => navigate('/analysis-abc')}
            >
              <ArrowLeft size={20} />
              Back to ABC Analysis
            </button>
            <h1 className="analysis-report-header-title">
              ABC Analysis History
            </h1>
            <div className="analysis-report-header-subtitle">
              View and manage your past ABC analyses
            </div>
          </div>
          {analysisHistory.length > 0 && (
            <button className="clear-history-btn" onClick={clearAllHistory}>
              <Trash2 size={18} />
              Clear All History
            </button>
          )}
        </div>

        <div className="analysis-content-area">
          <div className="analysis-content-card">
            {analysisHistory.length === 0 ? (
              <div className="history-empty">
                <Clock size={64} />
                <p>No analysis history yet</p>
                <span>Your completed analyses will appear here</span>
              </div>
            ) : (
              <div className="history-table-container">
                <table className="history-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>File Name</th>
                      <th>Date & Time</th>
                      <th>Total Items</th>
                      <th>Category A</th>
                      <th>Category B</th>
                      <th>Category C</th>
                      <th>Sheet Link</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analysisHistory.map((entry, index) => (
                      <tr key={entry.id}>
                        <td>{index + 1}</td>
                        <td>
                          <div className="file-cell">
                            <FileText size={16} />
                            <span>{entry.fileName}</span>
                          </div>
                        </td>
                        <td>{entry.analyzedAt}</td>
                        <td>{entry.results.totalItems}</td>
                        <td>
                          <span className="category-badge cat-a">
                            {entry.results.categoryA.count}
                          </span>
                        </td>
                        <td>
                          <span className="category-badge cat-b">
                            {entry.results.categoryB.count}
                          </span>
                        </td>
                        <td>
                          <span className="category-badge cat-c">
                            {entry.results.categoryC.count}
                          </span>
                        </td>
                        <td>
                          <a 
                            href={entry.sheetUrl} 
                            target="_blank" 
                            rel="noopener noreferrer"
                            className="sheet-link"
                          >
                            <ExternalLink size={16} />
                            Open
                          </a>
                        </td>
                        <td>
                          <div className="history-actions">
                            <button 
                              className="action-btn delete-btn"
                              onClick={() => deleteHistoryEntry(entry.id)}
                              title="Delete Entry"
                            >
                              <Trash2 size={18} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default ABCAnalysisHistory;
