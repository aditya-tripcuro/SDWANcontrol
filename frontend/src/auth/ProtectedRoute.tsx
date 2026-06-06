import React from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "./AuthContext";

const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const auth = useAuth();
  if (!auth.isAuthenticated) return <Navigate to="/login" replace />;
  
  if (auth.user?.requires_password_change && window.location.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace />;
  }
  
  return <>{children}</>;
};

export default ProtectedRoute;
