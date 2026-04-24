import React from "react";
import { Routes, Route } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import ProtectedRoute from "./auth/ProtectedRoute";
import { AlertCountProvider } from "./context/AlertCountContext";
import Layout from "./components/Layout";

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
              path="*"
              element={
                <ProtectedRoute>
                  <Layout>
                    <Routes>
                      <Route path="/" element={<DashboardPage />} />
                      <Route path="/metrics" element={<MetricsPage />} />
                      <Route path="/events" element={<EventsPage />} />
                      <Route path="/alerts" element={<AlertsPage />} />
                      <Route path="/users" element={<UsersPage />} />
                      <Route path="/config" element={<ConfigPage />} />
                    </Routes>
                  </Layout>
                </ProtectedRoute>
              }
            />
          </Routes>
        </div>
      </AlertCountProvider>
    </AuthProvider>
  );
};

export default App;
