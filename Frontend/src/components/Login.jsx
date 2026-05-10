import api from "../api";
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useGoogleLogin } from "@react-oauth/google";  // ← Changed this import
import { ACCESS_TOKEN } from "../token";
import { getUserRole } from "../utils/tokenManager";
import "../css/Login.css";
import safexpressLogo from "../assets/sfxLogo.png";

const Login = ({ onLogin }) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  // ── Google Workspace scopes the AI Assistant + sub-agents need ─────
  // Without these the OAuth code exchange (auth-lambda/lambda_google_login.py)
  // returns a token with only `openid email profile` — every Gmail / Drive /
  // Sheets / Docs / Calendar API call then fails with HTTP 403 "Request had
  // insufficient authentication scopes" (root cause of the 2026-05-03 bug
  // where freshly-onboarded users hit a 403 on `search_emails` despite
  // legacy users continuing to work). Set matches what the legacy
  // admin@safexpressops.com token (minted via the old generate_gmail_tokens
  // dev script) already carries — verified live against
  // https://oauth2.googleapis.com/tokeninfo — so the GCP project's OAuth
  // consent screen is already approved for every entry below; we are not
  // adding any new permissions at the project level, just plumbing them
  // through the in-app login flow that previously requested none of them.
  //
  // Existing users will see Google's consent screen ONCE on next login
  // (incremental authorization) and click through. Affected (paul-type)
  // users whose stored refresh_token already lacks these scopes need to
  // either sign out + sign in (Google will prompt because the requested
  // set changed) or revoke at myaccount.google.com/permissions and sign
  // in again.
  const GOOGLE_OAUTH_SCOPES = [
    'openid',
    'email',
    'profile',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/drive.metadata.readonly',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/calendar.readonly',
  ].join(' ');

  // ← Replace handleGoogleSuccess with this useGoogleLogin hook
  const googleLogin = useGoogleLogin({
    onSuccess: async (codeResponse) => {
      setLoading(true);
      setError(null);
      
      try {
        // AWS Lambda endpoint (no trailing slash)
        const response = await api.post("/api/auth/google", {
          code: codeResponse.code  // ← This will now definitely be an authorization code
        });
        
        // Store JWT tokens FIRST (both access and refresh)
        localStorage.setItem(ACCESS_TOKEN, response.data.access);
        localStorage.setItem('refresh', response.data.refresh);
        
        // Store ONLY non-sensitive user display info (id/user_id excluded for security)
        // Sensitive data like user_id is extracted from JWT token when needed
        const { id, user_id, ...displayUserInfo } = response.data.user;
        localStorage.setItem("user", JSON.stringify(displayUserInfo));
        
        // Update parent component BEFORE navigation
        if (onLogin) {
          onLogin();
        }
        
        // Wait a bit to ensure state updates, then navigate
        setTimeout(() => {
          const role = getUserRole();
          const landingPage = role === "manager" ? "/logs" : role === "user" ? "/sfx-bot" : "/dashboard";
          navigate(landingPage, { replace: true });
        }, 100);
      } catch (error) {
        console.error("Google login error:", error);
        
        if (error.response?.data?.error) {
          setError(error.response.data.error);
        } else {
          setError("Authentication failed. Please contact your administrator.");
        }
      } finally {
        setLoading(false);
      }
    },
    onError: (error) => {
      console.error("Google login failed:", error);
      setError("Google login failed. Please try again.");
    },
    flow: 'auth-code',
    scope: GOOGLE_OAUTH_SCOPES,
    // Removed ux_mode popup - it causes redirect_uri_mismatch with Google OAuth
  });

  return (
    <div className="login-page-wrapper">
      <div className="form-content">
        <div className="logo-container">
          <img
            src={safexpressLogo}
            alt="Safexpress Logo"
            className="sidebar-logo"
          />
        </div>

        {error && <div className="error-message">{error}</div>}

        <div
          style={{
            display: "flex",
            justifyContent: "center",
            width: "100%",
            marginTop: "20px",
          }}
        >
          {/* ← Replace GoogleLogin component with this button */}
          <button 
            onClick={() => googleLogin()}
            disabled={loading}
            style={{
              backgroundColor: '#4285f4',
              color: 'white',
              border: '1px solid #4285f4',
              padding: '12px 24px',
              borderRadius: '4px',
              fontSize: '16px',
              cursor: loading ? 'not-allowed' : 'pointer',
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              opacity: loading ? 0.6 : 1
            }}
          >
            {loading ? 'Authenticating...' : 'Sign in with Google'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default Login;