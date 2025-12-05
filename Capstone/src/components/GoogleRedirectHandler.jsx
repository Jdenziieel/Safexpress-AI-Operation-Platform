import { useEffect } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import axios from "axios";
import { GOOGLE_ACCESS_TOKEN } from "../token";

function RedirectGoogleAuth() {
  const navigate = useNavigate();

  useEffect(() => {
    console.log("RedirectHanlder mounted successfully");

    const queryParams = new URLSearchParams(window.location.search);
    const accessToken = queryParams.get('access_token');

    console.log("QueryParams: ", window.location.search);

    if (accessToken) {
      console.log(accessToken);
      console.log("AccessToken found: ", accessToken);
      localStorage.setItem(GOOGLE_ACCESS_TOKEN, accessToken);

      //verify the token from the backend
      axios.defaults.headers.common["Authorization"] = `Bearer ${accessToken}`;
      axios
        .get('/api/auth/user/')    
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
      console.log("No token found in the URL");
      navigate("/login");
    }
  }, [navigate])
  return <div>Logging In........</div>;
}

export default RedirectGoogleAuth;