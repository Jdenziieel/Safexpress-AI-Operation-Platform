import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import "../css/Dashboard.css";

function Dashboard() {
  const navigate = useNavigate();
  const [userInfo, setUserInfo] = useState({
    name: "User",
    lastLogin: new Date().toLocaleString('en-US', { 
      month: 'long', 
      day: 'numeric', 
      hour: 'numeric', 
      minute: '2-digit', 
      hour12: true 
    }),
  });

  // Load user info from localStorage
  useEffect(() => {
    try {
      const storedUser = localStorage.getItem("user");
      if (storedUser) {
        const userData = JSON.parse(storedUser);
        
        // Get display name for dashboard greeting
        let displayName = "User";
        
        // Priority: Use full name from Google to get first and middle names
        if (userData.name) {
          const nameParts = userData.name.trim().split(/\s+/);
          // Show first two parts if available (First + Middle name)
          if (nameParts.length >= 2) {
            displayName = `${nameParts[0]} ${nameParts[1]}`;
          } else {
            displayName = nameParts[0]; // Just first name if only one word
          }
        } else if (userData.first_name) {
          // Fallback to first_name field
          displayName = userData.first_name;
        } else if (userData.username) {
          displayName = userData.username;
        }
        
        setUserInfo({
          name: displayName,
          lastLogin: new Date().toLocaleString('en-US', { 
            month: 'long', 
            day: 'numeric', 
            hour: 'numeric', 
            minute: '2-digit', 
            hour12: true 
          }),
        });
      }
    } catch (error) {
      console.error("Error loading user info in Dashboard:", error);
    }
  }, []);

  const stats = [
    { label: "Total Accounts", value: "0" },
    { label: "Documents Processed", value: "0" },
    { label: "Active Users", value: "2" },
    { label: "Pending Tasks", value: "0" },
  ];

  const tokenUsage = {
    used: 0,
    limit: 100000,
    percentage: 0
  };

  return (
    <div className="dashboard-page">
      <div className="dashboard-container">
        {/* Header */}
        <div className="dashboard-header-row">
          <div className="dashboard-welcome">
            <div>
              <h1 className="welcome-title">Welcome, <span>{userInfo.name}</span></h1>
              <div className="welcome-last-login">
                Last Login: <strong>{userInfo.lastLogin}</strong>
              </div>
            </div>
          </div>
        </div>

        {/* Stats Grid */}
        <div className="stats-grid">
          {stats.map((stat, idx) => (
            <div key={idx} className="stat-card">
              <div className="stat-label">{stat.label}</div>
              <div className="stat-value">{stat.value}</div>
              <div className={`stat-change ${stat.positive ? 'positive' : 'negative'}`}>{stat.change}</div>
            </div>
          ))}
        </div>

        {/* Main Dashboard Grid */}
        <div className="dashboard-main-grid">
          {/* Token Usage Overview */}
          <div className="dashboard-card">
            <h2 className="d-card-title">Token Usage</h2>
            <div className="token-usage-content">
              <div className="token-stats">
                <div className="token-stat-item">
                  <span className="token-stat-label">Used</span>
                  <span className="token-stat-value">{tokenUsage.used.toLocaleString()}</span>
                </div>
                <div className="token-stat-item">
                  <span className="token-stat-label">Limit</span>
                  <span className="token-stat-value">{tokenUsage.limit.toLocaleString()}</span>
                </div>
                <div className="token-stat-item">
                  <span className="token-stat-label">Remaining</span>
                  <span className="token-stat-value">{(tokenUsage.limit - tokenUsage.used).toLocaleString()}</span>
                </div>
              </div>
              <div className="token-progress-bar">
                <div className="token-progress-fill" style={{ width: `${tokenUsage.percentage}%` }}></div>
              </div>
              <div className="token-progress-label">{tokenUsage.percentage}% used</div>
            </div>
          </div>

          {/* Task Approval */}
          <div className="dashboard-card dashboard-card-large" onClick={() => navigate('/tasks')}>
            <h2 className="d-card-title">Task Approval</h2>
            <div className="card-content">
              <p className="card-description">Review and approve pending tasks, manage workflow approvals and track task completion status.</p>
              <div className="card-stats">
                <span className="card-stat-value">8</span>
                <span className="card-stat-label">Pending Tasks</span>
              </div>
            </div>
          </div>

          {/* Document Extraction */}
          <div className="dashboard-card dashboard-card-large" onClick={() => navigate('/document-extraction')}>
            <h2 className="d-card-title">Document Extraction</h2>
            <div className="card-content">
              <p className="card-description">Upload and process PDF documents, extract content and manage document chunks with AI-powered analysis.</p>
              <div className="card-stats">
                <span className="card-stat-value">1,245</span>
                <span className="card-stat-label">Documents Processed</span>
              </div>
            </div>
          </div>

          {/* Token Management */}
          <div className="dashboard-card dashboard-card-large" onClick={() => navigate('/quota')}>
            <h2 className="d-card-title">Token Management</h2>
            <div className="card-content">
              <p className="card-description">Monitor and manage AI token usage across the platform, view user quotas and admin actions.</p>
              <div className="card-stats">
                <span className="card-stat-value">2</span>
                <span className="card-stat-label">Active Users</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;