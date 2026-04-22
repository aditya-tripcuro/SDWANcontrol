import React, { createContext, useContext, useEffect, useState } from "react";
import { login as apiLogin } from "../api/client";
import { sseManager } from "../api/sse";
import { registerLogout } from "../api/client";

interface UserInfo {
  username: string;
  role: "admin" | "operator" | "viewer";
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
    const payload = JSON.parse(atob(token.split(".")[1]));
    return { username: payload.username, role: payload.role } as UserInfo;
  } catch {
    return null;
  }
}

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem("wancontrol_token"));
  const [user, setUser] = useState<UserInfo | null>(() => (token ? decodeToken(token) : null));

  useEffect(() => {
    if (token) {
      sseManager.connect(token);
      localStorage.setItem("wancontrol_token", token);
      setUser(decodeToken(token));
    } else {
      sseManager.disconnect();
      localStorage.removeItem("wancontrol_token");
      setUser(null);
    }
  }, [token]);

  useEffect(() => {
    registerLogout(() => setToken(null));
  }, []);

  const doLogin = async (username: string, password: string) => {
    const pair = await apiLogin(username, password);
    setToken(pair.access_token);
  };

  const doLogout = () => setToken(null);

  return (
    <AuthContext.Provider value={{ token, user, login: doLogin, logout: doLogout, isAuthenticated: !!token }}>
      {children}
    </AuthContext.Provider>
  );
};

export default AuthContext;
