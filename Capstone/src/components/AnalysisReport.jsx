import React from "react";
import { useNavigate } from "react-router-dom";
import { BarChart3, FileText, Users } from "lucide-react";
import "../css/AnalysisReport.css";

function AnalysisReport() {
  const navigate = useNavigate();

  return (
    <div className="analysis-report-page">
      <div className="analysis-report-container">
        {/* Header */}
        <div className="analysis-report-header-row">
          <div>
            <h1 className="analysis-report-header-title">
              Analysis Report
            </h1>
            <div className="analysis-report-header-subtitle">
              Comprehensive analysis and reporting tools
            </div>
          </div>
        </div>

        {/* Analysis Cards */}
        <div className="analysis-nav-tabs">
          <div
            className="analysis-nav-tab"
            onClick={() => navigate('/analysis-abc')}
          >
            <div className="analysis-nav-icon">
              <BarChart3 size={28} />
            </div>
            <div className="analysis-nav-content">
              <div className="analysis-nav-title">ABC Analysis</div>
              <div className="analysis-nav-desc">Inventory classification and prioritization</div>
            </div>
          </div>

          <div
            className="analysis-nav-tab"
            onClick={() => navigate('/analysis-one-page')}
          >
            <div className="analysis-nav-icon">
              <FileText size={28} />
            </div>
            <div className="analysis-nav-content">
              <div className="analysis-nav-title">One Page Report</div>
              <div className="analysis-nav-desc">Summarized overview and insights</div>
            </div>
          </div>

          <div
            className="analysis-nav-tab"
            onClick={() => navigate('/analysis-workload')}
          >
            <div className="analysis-nav-icon">
              <Users size={28} />
            </div>
            <div className="analysis-nav-content">
              <div className="analysis-nav-title">Workload Analysis</div>
              <div className="analysis-nav-desc">Team capacity and distribution</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default AnalysisReport;
