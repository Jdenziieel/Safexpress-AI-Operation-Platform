import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  FiUsers,
  FiCheckSquare,
  FiFileText,
  FiTag,
  FiArrowUpRight,
  FiArrowDownRight,
  FiX,
  FiMessageSquare,
} from "react-icons/fi";
import UploadModal from "./UploadModal";
import "../css/Dashboard.css";

function Dashboard() {
  const navigate = useNavigate();
  const [isUploadModalOpen, setUploadModalOpen] = useState(false);
  const [isFilesModalOpen, setFilesModalOpen] = useState(false);
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
        console.log("Dashboard - Full user data from localStorage:", userData);
        
        // Get display name for dashboard greeting
        let displayName = "User";
        
        // Priority: Use full name from Google to get first and middle names
        if (userData.name) {
          const nameParts = userData.name.trim().split(/\s+/);
          console.log("Dashboard - Name parts:", nameParts);
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
        
        console.log("Dashboard - Display name set to:", displayName);
        
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
        
        console.log("Dashboard loaded user:", displayName);
      }
    } catch (error) {
      console.error("Error loading user info in Dashboard:", error);
    }
  }, []);

  const uploadedFiles = [
    { name: "Project_Plan_v2.pdf", type: "pdf" },
    { name: "UI_Mockups_Final.png", type: "image" },
    { name: "Sprint-Retrospective-Notes.docx", type: "doc" },
  ];

  const systemCapabilities = [
    { 
      title: "AI-Powered Chat Assistant", 
      description: "Interact with intelligent AI for document analysis and workflow automation",
      icon: "chat"
    },
    { 
      title: "Document Extraction", 
      description: "Extract and process data from PDFs, images, and various document formats",
      icon: "document"
    },
    { 
      title: "Task Management", 
      description: "Review, approve, and track automated tasks with built-in safety checks",
      icon: "task"
    },
    { 
      title: "Report Analysis", 
      description: "Generate comprehensive insights and analytics from your documents",
      icon: "report"
    },
  ];

  const recentAIActions = [
    { text: "Email draft created successfully", completed: true, risk: "safe" },
    { text: "Document extraction completed", completed: true, risk: "safe" },
    { text: "Scheduled 5 emails for review", completed: true, risk: "moderate" },
  ];

  const recentActivity = [
    { label: "Approved 2 tasks", date: "Today", type: "success" },
    { label: "Uploaded Project_Plan_v2.pdf", date: "Yesterday", type: "info" },
    { label: "Added new tags", date: "2 days ago", type: "warning" },
  ];

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

        {/* Stats Row */}
        <div className="dashboard-stats-row">
          <div className="stat-card stat-blue">
            <div className="stat-icon">
              <FiUsers size={28} />
            </div>
            <div className="stat-content">
              <div className="stat-title">Total Accounts</div>
              <div className="stat-value">200</div>
            </div>
          </div>
        </div>

        {/* Navigation Links */}
        <div className="dashboard-nav-links">
          <div className="nav-link-card" onClick={() => navigate('/task-approval')}>
            <div className="nav-link-icon">
              <FiCheckSquare size={24} />
            </div>
            <div className="nav-link-content">
              <div className="nav-link-title">Task Approval</div>
              <div className="nav-link-desc">Review and approve pending tasks</div>
            </div>
            <FiArrowUpRight className="nav-link-arrow" />
          </div>
          <div className="nav-link-card" onClick={() => navigate('/document-extraction')}>
            <div className="nav-link-icon">
              <FiFileText size={24} />
            </div>
            <div className="nav-link-content">
              <div className="nav-link-title">Document Extraction</div>
              <div className="nav-link-desc">Extract and analyze document data</div>
            </div>
            <FiArrowUpRight className="nav-link-arrow" />
          </div>
          <div className="nav-link-card" onClick={() => navigate('/ai-chat')}>
            <div className="nav-link-icon">
              <FiMessageSquare size={24} />
            </div>
            <div className="nav-link-content">
              <div className="nav-link-title">AI Chat</div>
              <div className="nav-link-desc">Chat with AI assistant</div>
            </div>
            <FiArrowUpRight className="nav-link-arrow" />
          </div>
        </div>

        {/* Main Grid */}
        <div className="dashboard-main-row">
          {/* Left: System Capabilities */}
          <div className="main-card">
            <div className="main-card-title">System Capabilities</div>
            <div className="main-card-subtitle">Available Features</div>
            <div className="capabilities-grid">
              {systemCapabilities.map((capability, idx) => (
                <div key={idx} className="capability-item">
                  <div className="capability-icon">
                    {capability.icon === 'chat' && <FiMessageSquare size={20} />}
                    {capability.icon === 'document' && <FiFileText size={20} />}
                    {capability.icon === 'task' && <FiCheckSquare size={20} />}
                    {capability.icon === 'report' && <FiTag size={20} />}
                  </div>
                  <div className="capability-content">
                    <div className="capability-title">{capability.title}</div>
                    <div className="capability-desc">{capability.description}</div>
                  </div>
                </div>
              ))}
            </div>
            <button className="main-card-btn" onClick={() => navigate('/ai-chat')}>
              Get Started
            </button>
          </div>
          {/* Right: Recent AI Actions */}
          <div className="main-card">
            <div className="main-card-title">Recent AI Actions</div>
            <div className="main-card-subtitle">Automated Workflow</div>
            <ul className="main-card-tasks">
              {recentAIActions.map((task, idx) => (
                <li key={idx} className={task.completed ? "task-completed" : "task-pending"}>
                  <FiCheckSquare className={task.completed ? "task-icon-completed" : "task-icon-pending"} />
                  <span>{task.text}</span>
                  <span className={`risk-badge risk-${task.risk}`}>
                    {task.risk.toUpperCase()}
                  </span>
                </li>
              ))}
            </ul>
            <button className="main-card-btn" onClick={() => navigate('/ai-chat')}>
              Open AI Chat
            </button>
          </div>
          {/* Recent Activity Feed */}
          <div className="main-card activity-card">
            <div className="main-card-title">Recent Activity</div>
            <ul className="activity-list">
              {recentActivity.map((item, idx) => (
                <li key={idx} className={`activity-item activity-${item.type}`}>
                  {item.label}
                  <span className="activity-date">{item.date}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Upload Modal */}
        {isUploadModalOpen && (
          <UploadModal
            onClose={() => setUploadModalOpen(false)}
            onShowFiles={() => {
              setUploadModalOpen(false);
              setFilesModalOpen(true);
            }}
          />
        )}

        {/* Files Modal */}
        {isFilesModalOpen && (
          <div className="modal-overlay" onClick={() => setFilesModalOpen(false)}>
            <div className="modal-content" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3 className="modal-title">Uploaded Files</h3>
                <button onClick={() => setFilesModalOpen(false)} className="modal-close-btn">
                  <FiX size={24} />
                </button>
              </div>
              <ul className="files-list">
                {uploadedFiles.map((file, index) => (
                  <li key={index} className="file-item">
                    {file.name}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default Dashboard;