import React from "react";
import { Check, X } from "lucide-react"; // ✅ Changed from Approve, Reject
import "../css/TaskApproval.css";

// ✅ Added ActionButton component
const ActionButton = ({ icon: Icon, children, className = "", ...props }) => (
  <button className={`action-button ${className}`} {...props}>
    {Icon && <Icon size={16} />}
    <span>{children}</span>
  </button>
);

function TaskApproval() {
  const pendingTasks = [
    {
      id: 1,
      title: "Deploy New Homepage to Production",
      submittedBy: "Maria Clara Ibarra",
      date: "2025-08-04",
    },
    {
      id: 2,
      title: "Update User Authentication Logic",
      submittedBy: "Juan Dela Cruz",
      date: "2025-08-03",
    },
    {
      id: 3,
      title: "Refresh Staging Database from Backup",
      submittedBy: "Ana Santos",
      date: "2025-08-02",
    },
  ];

  const handleApprove = (taskId) => {
    console.log("Approved task:", taskId);
    // Add your approve logic here
  };

  const handleReject = (taskId) => {
    console.log("Rejected task:", taskId);
    // Add your reject logic here
  };

  return (
    <div className="taskapproval-page">
      <div className="taskapproval-container">
        <header className="taskapproval-page-header">
          <div>
            <h1 className="taskapproval-header-title">Task Approval</h1>
            <p className="taskapproval-header-subtitle">
              Review and act on pending tasks submitted by your team.
            </p>
          </div>
        </header>

        <main className="taskapproval-content-card">
          <div className="taskapproval-task-list">
            {pendingTasks.map((task) => (
              <div className="taskapproval-task-card" key={task.id}>
                <div className="taskapproval-card-header">
                  <h3 className="taskapproval-card-title">{task.title}</h3>
                  <span className="taskapproval-status pending">Pending</span>
                </div>
                <div className="taskapproval-card-body">
                  <p>
                    <strong>Submitted by:</strong> {task.submittedBy}
                  </p>
                  <p>
                    <strong>Date Submitted:</strong> {task.date}
                  </p>
                </div>
                <div className="taskapproval-card-footer">
                  <ActionButton
                    icon={X}
                    className="taskapproval-btn-reject"
                    onClick={() => handleReject(task.id)}
                  >
                    Reject
                  </ActionButton>
                  <ActionButton
                    icon={Check}
                    className="taskapproval-btn-approve"
                    onClick={() => handleApprove(task.id)}
                  >
                    Approve
                  </ActionButton>
                </div>
              </div>
            ))}
            {pendingTasks.length === 0 && (
              <div className="taskapproval-no-tasks-message">
                There are no pending tasks at the moment.
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}

export default TaskApproval;
