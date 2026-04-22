import React, { useEffect } from "react";
import { Routes, Route, Link } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import ProtectedRoute from "./auth/ProtectedRoute";
import { AlertCountProvider } from "./context/AlertCountContext";

import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import MetricsPage from "./pages/MetricsPage";
import EventsPage from "./pages/EventsPage";
import AlertsPage from "./pages/AlertsPage";
import UsersPage from "./pages/UsersPage";
import ConfigPage from "./pages/ConfigPage";

const App: React.FC = () => {
  return (
    <AuthProvider>
      <AlertCountProvider>
        <div className="min-h-screen">
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <DashboardPage />
                </ProtectedRoute>
              }
            />
            <Route path="/metrics" element={<ProtectedRoute><MetricsPage /></ProtectedRoute>} />
            <Route path="/events" element={<ProtectedRoute><EventsPage /></ProtectedRoute>} />
            <Route path="/alerts" element={<ProtectedRoute><AlertsPage /></ProtectedRoute>} />
            <Route path="/users" element={<ProtectedRoute><UsersPage /></ProtectedRoute>} />
            <Route path="/config" element={<ProtectedRoute><ConfigPage /></ProtectedRoute>} />
          </Routes>
        </div>
      </AlertCountProvider>
    </AuthProvider>
  );
};

export default App;
