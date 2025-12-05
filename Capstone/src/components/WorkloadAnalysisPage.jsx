import React from "react";
import { useNavigate } from "react-router-dom";
import { Users, ArrowLeft } from "lucide-react";
import "../css/WorkloadAnalysisPage.css";

function WorkloadAnalysisPage() {
  const navigate = useNavigate();

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
              <Users size={40} />
              Workload Analysis
            </h1>
            <div className="analysis-report-header-subtitle">
              Team capacity and distribution
            </div>
          </div>
        </div>

        <div className="analysis-content-area">
          <div className="analysis-content-card">
            <div className="analysis-content-body">
              <p className="analysis-placeholder">
                Workload Analysis content will be displayed here. Monitor and optimize team resource allocation and capacity.
              </p>
              <div className="analysis-placeholder-features">
                <div className="feature-item">✓ Team capacity overview</div>
                <div className="feature-item">✓ Task distribution metrics</div>
                <div className="feature-item">✓ Bottleneck identification</div>
                <div className="feature-item">✓ Utilization rates</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default WorkloadAnalysisPage;
