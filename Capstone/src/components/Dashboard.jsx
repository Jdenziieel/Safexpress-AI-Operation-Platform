import React, { useState } from "react";
import {
  FiUsers,
  FiCheckSquare,
  FiFileText,
  FiTag,
  FiArrowUpRight,
  FiArrowDownRight,
  FiX,
} from "react-icons/fi";
import UploadModal from "../components/UploadModal";
import "../css/Dashboard.css";

function Dashboard() {
  const [isUploadModalOpen, setUploadModalOpen] = useState(false);
  const [isFilesModalOpen, setFilesModalOpen] = useState(false);

  // Example data
  const userInfo = {
    name: "Maria Clara",
    lastLogin: "July 17, 5:09 PM",
  };

  const uploadedFiles = [
    { name: "Project_Plan_v2.pdf", type: "pdf" },
    { name: "UI_Mockups_Final.png", type: "image" },
    { name: "Sprint-Retrospective-Notes.docx", type: "doc" },
  ];

  const fileTasks = [
    { text: "Review project brief", completed: true },
    { text: "Finalize UI/UX mockups", completed: false },
    { text: "Submit weekly progress report", completed: false },
  ];

  const metadataTasks = [
    { text: "Tag all new assets from Q2", completed: true },
    { text: "Update legacy metadata schema", completed: true },
    { text: "Organize files by project phase", completed: false },
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

          {/* Add this inside .dashboard-header-row, after .dashboard-actions */}
          <select className="dashboard-date-range">
            <option>This Week</option>
            <option>Last Week</option>
            <option>This Month</option>
            <option>Last Month</option>
          </select>
        </div>

        {/* Stats Row */}
        <div className="dashboard-stats-row">
          <div className="stat-card stat-blue">
            <div className="stat-icon">{<FiUsers size={28} />}</div>
            <div>
              <div className="stat-title">Total Accounts</div>
              <div className="stat-value">200 <FiArrowUpRight className="stat-trend-up" /></div>
              <div className="stat-desc">+12 this week</div>
            </div>
          </div>
          <div className="stat-card stat-green">
            <div className="stat-icon">{<FiCheckSquare size={28} />}</div>
            <div>
              <div className="stat-title">Tasks Approved</div>
              <div className="stat-value">60 <FiArrowDownRight className="stat-trend-down" /></div>
              <div className="stat-desc">-3 this week</div>
            </div>
          </div>
          <div className="stat-card stat-purple">
            <div className="stat-icon">{<FiFileText size={28} />}</div>
            <div>
              <div className="stat-title">Files Uploaded</div>
              <div className="stat-value">3</div>
              <div className="stat-desc">Latest: {uploadedFiles[0].name}</div>
            </div>
          </div>
        </div>

        {/* Progress Bar */}
        <div className="dashboard-progress-row">
          <div className="progress-label">Weekly Progress</div>
          <div className="progress-bar">
            <div className="progress-bar-fill" style={{ width: "75%" }}></div>
          </div>
          <div className="progress-percent">75%</div>
        </div>

        {/* Main Grid */}
        <div className="dashboard-main-row">
          {/* Left: File Tasks */}
          <div className="main-card">
            <div className="main-card-title">File Management</div>
            <div className="main-card-subtitle">Central Repository</div>
            <ul className="main-card-tasks">
              {fileTasks.map((task, idx) => (
                <li key={idx} className={task.completed ? "task-completed" : "task-pending"}>
                  <FiCheckSquare className={task.completed ? "task-icon-completed" : "task-icon-pending"} />
                  {task.text}
                </li>
              ))}
            </ul>
            <button className="main-card-btn" onClick={() => setUploadModalOpen(true)}>
              Upload File
            </button>
          </div>
          {/* Right: Metadata Tasks */}
          <div className="main-card">
            <div className="main-card-title">Metadata Tagging</div>
            <div className="main-card-subtitle">Content Organization</div>
            <ul className="main-card-tasks">
              {metadataTasks.map((task, idx) => (
                <li key={idx} className={task.completed ? "task-completed" : "task-pending"}>
                  <FiCheckSquare className={task.completed ? "task-icon-completed" : "task-icon-pending"} />
                  {task.text}
                </li>
              ))}
            </ul>
            <button className="main-card-btn" onClick={() => alert("Navigate to tagging page")}>
              Add New Tags
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