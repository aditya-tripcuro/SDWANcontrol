import type { InterfaceStatus } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string
  ) {
    super(message);
  }
}

// ── Auth token plumbing ────────────────────────────────────────────────────────
// apiFetch is a plain function (not a hook), so it holds the bearer token in a
// module-level variable that AuthContext keeps in sync via setAuthToken(). It is
// seeded from localStorage at module load so the very first request after a page
// reload (which can happen before AuthContext mounts) is already authenticated.
const TOKEN_KEY = "wancontrol_token";
let authToken: string | null = localStorage.getItem(TOKEN_KEY);
let onUnauthorized: (() => void) | null = null;

export function setAuthToken(token: string | null): void {
  authToken = token;
}

export function registerLogout(callback: () => void): void {
  onUnauthorized = callback;
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (authToken) headers.set("Authorization", `Bearer ${authToken}`);
  const res = await fetch(path, { ...options, headers });
  const text = await res.text();
  const contentType = res.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const body = text && isJson ? JSON.parse(text) : null;
  if (!res.ok) {
    // An expired/invalid session on a normal API call drops us back to login.
    // Skip this for the /api/auth/ endpoints themselves — a 401 there is a normal
    // bad-credentials response that LoginPage handles inline.
    if (res.status === 401 && onUnauthorized && !path.startsWith("/api/auth/")) {
      onUnauthorized();
    }
    const code = body?.error || "unknown_error";
    const message = body?.message || res.statusText;
    throw new ApiError(res.status, code, message);
  }
  return body as T;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  requires_password_change: boolean;
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

export async function getAuthConfig(): Promise<{ auth_enabled: boolean }> {
  return apiFetch<{ auth_enabled: boolean }>("/api/auth/config");
}

export async function changePassword(
  oldPassword: string,
  newPassword: string
): Promise<{ changed: boolean }> {
  return apiFetch<{ changed: boolean }>("/api/auth/change-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  });
}

export async function getStatus(): Promise<any> {
  return apiFetch<any>("/api/status");
}

export async function getMetrics(params?: { interface?: string; limit?: number; since?: number }): Promise<any[]> {
  const query = new URLSearchParams();
  if (params?.interface) query.append("interface", params.interface);
  if (params?.limit) query.append("limit", params.limit.toString());
  if (params?.since) query.append("since", params.since.toString());
  const queryString = query.toString();
  return apiFetch<any[]>(`/api/metrics${queryString ? `?${queryString}` : ""}`);
}

export async function getAlerts(limit: number = 20): Promise<any[]> {
  return apiFetch<any[]>(`/api/alerts?limit=${limit}`);
}

export async function getSwitchEvents(limit: number = 50): Promise<any[]> {
  return apiFetch<any[]>(`/api/events/switches?limit=${limit}`);
}

export async function getUsers(): Promise<any[]> {
  return apiFetch<any[]>("/api/users");
}

export async function getInterfacesStatus(): Promise<InterfaceStatus[]> {
  return apiFetch<InterfaceStatus[]>("/api/status/interfaces");
}

export async function discoverInterfaces(): Promise<any> {
  return apiFetch<any>("/api/interfaces/discover");
}

export async function putConfigInterfaces(interfaces: any[]): Promise<any> {
  return apiFetch<any>("/api/config/interfaces", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ interfaces }),
  });
}

export async function reloadConfig(): Promise<any> {
  return apiFetch<any>("/api/config/reload", { method: "POST" });
}

export async function putWanMode(wanMode: "failover" | "load_balance"): Promise<any> {
  return apiFetch<any>("/api/config/wan-mode", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ wan_mode: wanMode }),
  });
}

export async function getControllerEvents(limit = 100, level?: string): Promise<any[]> {
  const params = new URLSearchParams({ limit: limit.toString() });
  if (level) params.append("level", level);
  return apiFetch<any[]>(`/api/events/controller?${params}`);
}
