import api from "../api";
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useGoogleLogin } from "@react-oauth/google";  // ← Changed this import
import { ACCESS_TOKEN } from "../token";
import "../css/Login.css";
import safexpressLogo from "../assets/sfxLogo.png";

const Login = ({ onLogin }) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  // ← Replace handleGoogleSuccess with this useGoogleLogin hook
  const googleLogin = useGoogleLogin({
    onSuccess: async (codeResponse) => {
      setLoading(true);
      setError(null);
      
      try {
        console.log("Google code response:", codeResponse);
        console.log("Sending auth code to backend...");
        
        const response = await api.post("/api/auth/google/", {
          code: codeResponse.code  // ← This will now definitely be an authorization code
        });
        
        console.log("Login response:", response.data);
        
        // Store JWT tokens FIRST (both access and refresh)
        localStorage.setItem(ACCESS_TOKEN, response.data.access);
        localStorage.setItem('refresh', response.data.refresh);
        console.log("Tokens stored - Access and Refresh");
        
        // Store user info
        localStorage.setItem("user", JSON.stringify(response.data.user));
        console.log("User stored:", response.data.user);
        
        // Update parent component BEFORE navigation
        if (onLogin) {
          console.log("Calling onLogin()...");
          onLogin();
        }
        
        // Wait a bit to ensure state updates, then navigate
        setTimeout(() => {
          console.log("Navigating to dashboard...");
          navigate("/dashboard", { replace: true });
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
    ux_mode: 'popup',  // Use popup mode for better compatibility
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