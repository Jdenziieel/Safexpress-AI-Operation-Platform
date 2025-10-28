import React, { useState, useEffect } from "react";
import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
} from "react-router-dom";
import { KeepAlive, AliveScope } from "react-activation";
import { GoogleOAuthProvider } from "@react-oauth/google";
import Sidebar from "./components/Sidebar";
import Login from "./components/Login";
import Dashboard from "./components/Dashboard";
import AuditLogs from "./components/AuditLogs";
import Accounts from "./components/Accounts.jsx";
import AIChat from "./components/AIChat.jsx";
import TaskApproval from "./components/TaskApproval";
import ReportAnalysis from "./components/ReportAnalysis.jsx";
import DocumentExtraction from "./components/DocumentExtraction.jsx";
import AdminOnboardingForm from "./components/AdminOnboardingForm.jsx";
import "./css/App.css";
import { ACCESS_TOKEN } from "./token";
import { isTokenExpired } from "./utils/tokenManager";

const GOOGLE_CLIENT_ID =
  "460375457443-s7g5sm51b3ouhiqtpjpka6np618ubrjb.apps.googleusercontent.com";

function App() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isLoggedIn, setIsLoggedIn] = useState(() => {
    return !!localStorage.getItem(ACCESS_TOKEN) && !isTokenExpired();
  });

  const handleLogin = () => {
    setIsLoggedIn(true);
  };

  const handleLogout = () => {
    localStorage.removeItem(ACCESS_TOKEN);
    localStorage.removeItem("user");
    setIsLoggedIn(false);
  };

  // Check token expiry periodically
  useEffect(() => {
    // Check immediately on mount
    if (isLoggedIn && isTokenExpired()) {
      console.log("Token expired, logging out...");
      handleLogout();
    }

    // Check every 5 minutes
    const interval = setInterval(() => {
      if (isLoggedIn && isTokenExpired()) {
        console.log("Token expired, logging out...");
        handleLogout();
      }
    }, 5 * 60 * 1000); // 5 minutes

    return () => clearInterval(interval);
  }, [isLoggedIn]);

  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <Router>
        {!isLoggedIn ? (
          <Routes>
            <Route path="/login" element={<Login onLogin={handleLogin} />} />
            <Route
              path="/login/callback"
              element={<Login onLogin={handleLogin} />}
            />
            <Route path="*" element={<Navigate to="/login" />} />
          </Routes>
        ) : (
          <div className="app-container">
            <Sidebar
              isOpen={isSidebarOpen}
              toggleSidebar={() => setIsSidebarOpen((prev) => !prev)}
              onLogout={handleLogout}
            />
            <div className="main-content">
              <AliveScope>
                <Routes>
                  <Route
                    path="/dashboard"
                    element={
                      <KeepAlive id="dashboard">
                        <Dashboard />
                      </KeepAlive>
                    }
                  />
                  <Route
                    path="/audit-logs"
                    element={
                      <KeepAlive id="audit-logs">
                        <AuditLogs />
                      </KeepAlive>
                    }
                  />
                  <Route
                    path="/accounts"
                    element={
                      <KeepAlive id="accounts">
                        <Accounts />
                      </KeepAlive>
                    }
                  />
                  <Route
                    path="/ai-chat"
                    element={
                      <KeepAlive id="ai-chat">
                        <AIChat />
                      </KeepAlive>
                    }
                  />
                  <Route
                    path="/task-approval"
                    element={
                      <KeepAlive id="task-approval">
                        <TaskApproval />
                      </KeepAlive>
                    }
                  />
                  <Route
                    path="/report-analysis"
                    element={
                      <KeepAlive id="report-analysis">
                        <ReportAnalysis />
                      </KeepAlive>
                    }
                  />
                  <Route
                    path="/document-extraction"
                    element={
                      <KeepAlive id="document-extraction">
                        <DocumentExtraction />
                      </KeepAlive>
                    }
                  />
                  <Route
                    path="/admin-onboarding"
                    element={
                      <KeepAlive id="admin-onboarding">
                        <AdminOnboardingForm />
                      </KeepAlive>
                    }
                  />
                  <Route path="*" element={<Navigate to="/dashboard" />} />
                </Routes>
              </AliveScope>
            </div>
          </div>
        )}
      </Router>
    </GoogleOAuthProvider>
  );
}

export default App;
