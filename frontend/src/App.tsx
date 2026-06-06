import React, { useEffect, useState } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { AlertCountProvider } from "./context/AlertCountContext";
import { TimezoneProvider } from "./context/TimezoneContext";
import Layout from "./components/Layout";
import DashboardPage from "./pages/DashboardPage";
import MetricsPage from "./pages/MetricsPage";
import EventsPage from "./pages/EventsPage";
import AlertsPage from "./pages/AlertsPage";
import ConfigPage from "./pages/ConfigPage";
import UsersPage from "./pages/UsersPage";
import LoginPage from "./pages/LoginPage";
import ForceChangePasswordPage from "./pages/ForceChangePasswordPage";
import ProtectedRoute from "./auth/ProtectedRoute";
import { getAuthConfig } from "./api/client";

// The authenticated application shell: providers + chrome + the page routes.
const AppShell: React.FC<{ authEnabled: boolean }> = ({ authEnabled }) => (
  <TimezoneProvider>
    <AlertCountProvider>
      <Layout>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/metrics" element={<MetricsPage />} />
          <Route path="/events" element={<EventsPage />} />
          <Route path="/alerts" element={<AlertsPage />} />
          <Route path="/config" element={<ConfigPage />} />
          {authEnabled && <Route path="/users" element={<UsersPage />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </AlertCountProvider>
  </TimezoneProvider>
);

const App: React.FC = () => {
  const [authEnabled, setAuthEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    getAuthConfig()
      .then((cfg) => setAuthEnabled(cfg.auth_enabled))
      .catch(() => setAuthEnabled(true)); // fail safe: assume auth is required
  }, []);

  if (authEnabled === null) {
    return (
      <div className="min-h-screen bg-canvas flex items-center justify-center text-text-muted text-[10px] font-black uppercase tracking-[0.3em]">
        Loading…
      </div>
    );
  }

  // Auth disabled: no login gate — protection is the backend's network allow-list
  // (tailnet + allowed_cidrs). The whole UI is reachable directly.
  if (!authEnabled) {
    return <AppShell authEnabled={false} />;
  }

  // Auth enabled: public login, a gated forced-password-change page, and the
  // gated app shell. ProtectedRoute redirects to /login when unauthenticated and
  // to /change-password when the user must rotate a provisioned password.
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/change-password"
        element={
          <ProtectedRoute>
            <ForceChangePasswordPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <AppShell authEnabled={true} />
          </ProtectedRoute>
        }
      />
    </Routes>
  );
};

export default App;
