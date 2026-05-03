import { useEffect } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import api from "../api";
import { GOOGLE_ACCESS_TOKEN } from "../token";

function RedirectGoogleAuth() {
  const navigate = useNavigate();

  useEffect(() => {
    const queryParams = new URLSearchParams(window.location.search);
    const accessToken = queryParams.get('access_token');

    if (accessToken) {
      localStorage.setItem(GOOGLE_ACCESS_TOKEN, accessToken);

      //verify the token from the backend (AWS Lambda endpoint - no trailing slash)
      api.defaults.headers.common["Authorization"] = `Bearer ${accessToken}`;
      api
        .get('/api/auth/user')    
        .then(response => {
          navigate('/dashboard')
        })
        .catch(error => {
          console.error(
            "Error Verifying Token",
            error.response ? error.response.data : error.message
          );    
          navigate("/login");
        });
    } else {
      navigate("/login");
    }
  }, [navigate])
  return <div>Logging In........</div>;
}

export default RedirectGoogleAuth;