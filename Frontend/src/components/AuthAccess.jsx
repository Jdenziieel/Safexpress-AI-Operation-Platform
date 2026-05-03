import React from "react";
import { Navigate } from "react-router-dom";
import { ACCESS_TOKEN } from "../token";

function ProtectedRoute({ children }) {
  const isLoggedIn = !!localStorage.getItem(ACCESS_TOKEN);

  if (!isLoggedIn) {
    return <Navigate to="/login" />;
  }

  if (
    isLoggedIn &&
    (window.location.pathname === "/login" ||
      window.location.pathname === "/register")
  ) {
    return <Navigate to="/" />;
  }

  return children;
}

export default ProtectedRoute;
