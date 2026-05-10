import React, { useState, useEffect } from "react";
import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
} from "react-router-dom";
import { KeepAlive, AliveScope } from "react-activation";
import { GoogleOAuthProvider } from "@react-oauth/google";
import Sidebar from "./components/Sidebar.jsx";
import Login from "./components/Login.jsx";
import Accounts from "./components/Accounts.jsx";
import AdminActivityLogs from "./components/AdminActivityLogs.jsx";
import AIChatNew from "./components/AIChatNew.jsx";
import TaskApproval from "./components/TaskApproval.jsx";
import DocumentExtraction from "./components/DocumentExtraction.jsx";
import DynamicMapping from "./components/DynamicMapping.jsx";
import SFXBot from "./components/SFXBot.jsx";
import AnalysisReport from "./components/AnalysisReport.jsx";
import ABCAnalysisPage from "./components/ABCAnalysisPage.jsx";
import ABCAnalysisHistory from "./components/ABCAnalysisHistory.jsx";
import OnePageReportPage from "./components/OnePageReportPage.jsx";
import OPRHistory from "./components/OPRHistory.jsx";
import WorkloadAnalysisPage from "./components/WorkloadAnalysisPage.jsx";
import ProfilePage from "./components/ProfilePage.jsx";
import EditAccount from "./components/EditAccount.jsx";
import ErrorModal from "./components/ErrorModal.jsx";
import LogsPage from "./components/LogsPage.jsx";
import KBAnalyticsPage from "./components/KBAnalyticsPage.jsx";
import QuotaPage from "./components/QuotaPage.jsx";
import ProtectedRoute from "./components/ProtectedRoute.jsx";
import TermsAndConditionsModal from "./components/TermsAndConditionsModal.jsx";
import { ErrorProvider, useError } from "./utils/ErrorContext.jsx";
import api from "./api.js";
import "./css/App.css";
import { ACCESS_TOKEN, clearDocumentStorage } from "./token.js";
import { isTokenExpired, getUserRole } from "./utils/tokenManager.js";

// Google OAuth Client ID from environment variables
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

/**
 * Component to redirect users to their appropriate default page based on role
 * - Admin/Manager: Logs dashboard
 * - User: SFX Bot
 */
const RoleBasedRedirect = () => {
  const role = getUserRole();

  switch (role) {
    case "user":
      return <Navigate to="/sfx-bot" replace />;
    case "manager":
    case "admin":
    default:
      return <Navigate to="/logs" replace />;
  }
};

const readStoredUser = () => {
  try {
    return JSON.parse(localStorage.getItem("user") || "null");
  } catch {
    return null;
  }
};

function App() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isLoggedIn, setIsLoggedIn] = useState(() => {
    const token = localStorage.getItem(ACCESS_TOKEN);
    return !!token;
  });
  const [storedUser, setStoredUser] = useState(() => readStoredUser());
  const [error, setError] = useState(null);
  const [showErrorModal, setShowErrorModal] = useState(false);

  // Global error handler function
  const handleError = React.useCallback((errorData) => {
    setError(errorData);
    setShowErrorModal(true);
  }, []);

  const handleLogin = React.useCallback(() => {
    const token = localStorage.getItem(ACCESS_TOKEN);
    if (token) {
      setIsLoggedIn(true);
      setStoredUser(readStoredUser());
    }
  }, []);

  const handleLogout = React.useCallback(() => {
    localStorage.removeItem(ACCESS_TOKEN);
    localStorage.removeItem("user");
    localStorage.removeItem("refresh");
    sessionStorage.removeItem("sfxbot_active_session"); // Clear SFX Bot active thread
    clearDocumentStorage(); // Clear any parsed document data
    setIsLoggedIn(false);
    setStoredUser(null);
  }, []);

  const handleTermsAccepted = React.useCallback((updatedUser) => {
    setStoredUser(updatedUser);
  }, []);

  const toggleSidebar = React.useCallback(() => {
    setIsSidebarOpen((prev) => !prev);
  }, []);

  // Set up periodic token check only once on mount
  // We check every 55 minutes (5 min before 60 min expiry) to proactively refresh
  // This prevents the token from expiring while the user is active
  useEffect(() => {
    const checkAndRefreshToken = async () => {
      const token = localStorage.getItem(ACCESS_TOKEN);
      const refreshToken = localStorage.getItem("refresh");

      if (!token) {
        setIsLoggedIn(false);
        return;
      }

      try {
        // Check if token will expire in the next 5 minutes
        if (isTokenExpired()) {
          // Don't logout immediately - try to refresh first
          if (refreshToken) {
            try {
              // AWS Lambda endpoint - no trailing slash
              const response = await api.post("/api/token/refresh", {
                refresh: refreshToken,
              });

              localStorage.setItem(ACCESS_TOKEN, response.data.access);
              // If we get a new refresh token (rotation), save it
              if (response.data.refresh) {
                localStorage.setItem("refresh", response.data.refresh);
              }
            } catch (refreshError) {
              handleLogout();
            }
          } else {
            handleLogout();
          }
        }
      } catch (error) {
        console.error("Error checking token expiry:", error);
      }
    };

    // Check every 55 minutes (proactive refresh before 60 min expiry)
    const interval = setInterval(checkAndRefreshToken, 55 * 60 * 1000);

    // Also check on mount in case token is already expired
    checkAndRefreshToken();

    return () => clearInterval(interval);
  }, []); // Empty dependency array - run only once on mount

  // Global error handler for uncaught errors
  useEffect(() => {
    const handleGlobalError = (event) => {
      console.error("Global error caught:", event.error);
      handleError({
        title: "Application Error",
        message: event.error?.message || "An unexpected error occurred",
        severity: "critical",
        details: event.error?.stack,
        timestamp: new Date().toISOString(),
      });
    };

    const handleUnhandledRejection = (event) => {
      console.error("Unhandled promise rejection:", event.reason);
      handleError({
        title: "Promise Rejection",
        message: event.reason?.message || "An async operation failed",
        severity: "warning",
        details: event.reason?.stack || String(event.reason),
        timestamp: new Date().toISOString(),
      });
    };

    window.addEventListener("error", handleGlobalError);
    window.addEventListener("unhandledrejection", handleUnhandledRejection);

    return () => {
      window.removeEventListener("error", handleGlobalError);
      window.removeEventListener(
        "unhandledrejection",
        handleUnhandledRejection,
      );
    };
  }, [handleError]);

  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <ErrorProvider>
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
          ) : storedUser && storedUser.gmail && storedUser.terms_accepted === false ? (
            <TermsAndConditionsModal
              user={storedUser}
              onAccept={handleTermsAccepted}
              onDecline={handleLogout}
            />
          ) : (
            <div className="app-container">
              <Sidebar
                isOpen={isSidebarOpen}
                toggleSidebar={toggleSidebar}
                onLogout={handleLogout}
              />
              <div className="main-content">
                <AliveScope>
                  <Routes>
                    {/* Accounts - Admin only */}
                    <Route
                      path="/accounts"
                      element={
                        <ProtectedRoute allowedRoles={["admin"]}>
                          <KeepAlive id="accounts">
                            <Accounts />
                          </KeepAlive>
                        </ProtectedRoute>
                      }
                    />
                    {/* Admin Activity Logs - Admin only */}
                    <Route
                      path="/admin-activity-logs"
                      element={
                        <ProtectedRoute allowedRoles={["admin"]}>
                          <KeepAlive id="admin-activity-logs">
                            <AdminActivityLogs />
                          </KeepAlive>
                        </ProtectedRoute>
                      }
                    />
                    {/* AI Chat - Admin and Manager only */}
                    <Route
                      path="/ai-chat-new"
                      element={
                        <ProtectedRoute allowedRoles={["admin", "manager"]}>
                          <KeepAlive id="ai-chat-new">
                            <AIChatNew />
                          </KeepAlive>
                        </ProtectedRoute>
                      }
                    />
                    <Route
                      path="/task-approval"
                      element={
                        <ProtectedRoute allowedRoles={["admin", "manager"]}>
                          <KeepAlive id="task-approval">
                            <TaskApproval />
                          </KeepAlive>
                        </ProtectedRoute>
                      }
                    />
                    {/* Manage Knowledge Base - Admin and Manager only */}
                    <Route
                      path="/document-extraction"
                      element={
                        <ProtectedRoute allowedRoles={["admin", "manager"]}>
                          <KeepAlive id="document-extraction">
                            <DocumentExtraction />
                          </KeepAlive>
                        </ProtectedRoute>
                      }
                    />
                    {/* Dynamic Mapping - All roles */}
                    <Route
                      path="/dynamic-mapping"
                      element={
                        <ProtectedRoute
                          allowedRoles={["admin", "manager", "user"]}
                        >
                          <KeepAlive id="dynamic-mapping">
                            <DynamicMapping />
                          </KeepAlive>
                        </ProtectedRoute>
                      }
                    />
                    {/* SFX Bot - All roles */}
                    <Route
                      path="/sfx-bot"
                      element={
                        <ProtectedRoute
                          allowedRoles={["admin", "manager", "user"]}
                        >
                          <KeepAlive id="sfx-bot">
                            <SFXBot />
                          </KeepAlive>
                        </ProtectedRoute>
                      }
                    />
                    {/* Analysis Report - All roles */}
                    <Route
                      path="/analysis-report"
                      element={
                        <ProtectedRoute
                          allowedRoles={["admin", "manager", "user"]}
                        >
                          <KeepAlive id="analysis-report">
                            <AnalysisReport />
                          </KeepAlive>
                        </ProtectedRoute>
                      }
                    />
                    {/* Analysis sub-pages - All roles */}
                    <Route
                      path="/analysis-abc"
                      element={
                        <ProtectedRoute
                          allowedRoles={["admin", "manager", "user"]}
                        >
                          <KeepAlive id="analysis-abc">
                            <ABCAnalysisPage />
                          </KeepAlive>
                        </ProtectedRoute>
                      }
                    />
                    <Route
                      path="/analysis-abc-history"
                      element={
                        <ProtectedRoute
                          allowedRoles={["admin", "manager", "user"]}
                        >
                          <KeepAlive id="analysis-abc-history">
                            <ABCAnalysisHistory />
                          </KeepAlive>
                        </ProtectedRoute>
                      }
                    />
                    <Route
                      path="/analysis-one-page"
                      element={
                        <ProtectedRoute
                          allowedRoles={["admin", "manager", "user"]}
                        >
                          <KeepAlive id="analysis-one-page">
                            <OnePageReportPage />
                          </KeepAlive>
                        </ProtectedRoute>
                      }
                    />
                    <Route
                      path="/opr-history"
                      element={
                        <ProtectedRoute
                          allowedRoles={["admin", "manager", "user"]}
                        >
                          <KeepAlive id="opr-history">
                            <OPRHistory />
                          </KeepAlive>
                        </ProtectedRoute>
                      }
                    />
                    <Route
                      path="/analysis-workload"
                      element={
                        <ProtectedRoute
                          allowedRoles={["admin", "manager", "user"]}
                        >
                          <KeepAlive id="analysis-workload">
                            <WorkloadAnalysisPage />
                          </KeepAlive>
                        </ProtectedRoute>
                      }
                    />
                    {/* Profile - All roles */}
                    <Route
                      path="/profile"
                      element={
                        <KeepAlive id="profile">
                          <ProfilePage />
                        </KeepAlive>
                      }
                    />
                    {/* Edit Account - Admin only */}
                    <Route
                      path="/edit-account"
                      element={
                        <ProtectedRoute allowedRoles={["admin"]}>
                          <KeepAlive id="edit-account">
                            <EditAccount />
                          </KeepAlive>
                        </ProtectedRoute>
                      }
                    />
                    {/* Logs & Analytics - Admin only */}
                    <Route
                      path="/logs"
                      element={
                        <ProtectedRoute allowedRoles={["admin"]}>
                          <KeepAlive id="logs">
                            <LogsPage />
                          </KeepAlive>
                        </ProtectedRoute>
                      }
                    />
                    {/* KB Analytics - Admin only */}
                    <Route
                      path="/kb-analytics"
                      element={
                        <ProtectedRoute allowedRoles={["admin"]}>
                          <KeepAlive id="kb-analytics">
                            <KBAnalyticsPage />
                          </KeepAlive>
                        </ProtectedRoute>
                      }
                    />
                    {/* Token Quota - Admin only */}
                    <Route
                      path="/quota"
                      element={
                        <ProtectedRoute allowedRoles={["admin"]}>
                          <KeepAlive id="quota">
                            <QuotaPage />
                          </KeepAlive>
                        </ProtectedRoute>
                      }
                    />
                    {/* Default redirect based on role */}
                    <Route path="*" element={<RoleBasedRedirect />} />
                  </Routes>
                </AliveScope>
              </div>
            </div>
          )}

          {/* Global Error Modal */}
          <ErrorModal
            isOpen={showErrorModal}
            onClose={() => {
              setShowErrorModal(false);
              setError(null);
            }}
            error={error}
          />
        </Router>
      </ErrorProvider>
    </GoogleOAuthProvider>
  );
}

export default App;
