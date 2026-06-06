import React, { createContext, useContext, useEffect, useState } from "react";
import { login as apiLogin, registerLogout, setAuthToken } from "../api/client";

interface UserInfo {
  username: string;
  role: "admin" | "operator" | "viewer";
  requires_password_change: boolean;
}

interface AuthContextValue {
  token: string | null;
  user: UserInfo | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

function decodeToken(token: string): UserInfo | null {
  try {
    // JWT segments are base64url; convert to base64 (+ padding) before atob,
    // otherwise real tokens containing '-' or '_' fail to decode.
    const part = token.split(".")[1];
    const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
    const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
    const payload = JSON.parse(atob(padded));
    return {
      username: payload.username,
      role: payload.role,
      requires_password_change: !!payload.rpc,
    } as UserInfo;
  } catch {
    return null;
  }
}

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem("wancontrol_token"));
  const [user, setUser] = useState<UserInfo | null>(() => (token ? decodeToken(token) : null));

  useEffect(() => {
    // Keep the API client's bearer token + persisted token in sync with state.
    // SSE is connected by DashboardPage (sseManager.connect()), not here.
    if (token) {
      setAuthToken(token);
      localStorage.setItem("wancontrol_token", token);
      setUser(decodeToken(token));
    } else {
      setAuthToken(null);
      localStorage.removeItem("wancontrol_token");
      setUser(null);
    }
  }, [token]);

  useEffect(() => {
    // apiFetch calls this on a 401 so an expired session forces re-login.
    registerLogout(() => {
      setAuthToken(null);
      setToken(null);
    });
  }, []);

  const doLogin = async (username: string, password: string) => {
    const pair = await apiLogin(username, password);
    // Set the client token synchronously so requests fired immediately after
    // navigation (e.g. DashboardPage's SSE ticket POST) are authenticated.
    setAuthToken(pair.access_token);
    setToken(pair.access_token);
  };

  const doLogout = () => {
    setAuthToken(null);
    setToken(null);
  };

  return (
    <AuthContext.Provider value={{ token, user, login: doLogin, logout: doLogout, isAuthenticated: !!token }}>
      {children}
    </AuthContext.Provider>
  );
};

export default AuthContext;
