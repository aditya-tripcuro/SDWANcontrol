import { TokenPair } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string
  ) {
    super(message);
  }
}

type LogoutHandler = () => void;
let _logoutHandler: LogoutHandler | null = null;
export function registerLogout(fn: LogoutHandler) {
  _logoutHandler = fn;
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem("wancontrol_token");
  const headers = new Headers(options?.headers as HeadersInit || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(path, { ...options, headers });
  const text = await res.text();
  const contentType = res.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const body = text && isJson ? JSON.parse(text) : null;
  if (!res.ok) {
    if (res.status === 401 && _logoutHandler) {
      _logoutHandler();
    }
    const code = body?.error || "unknown_error";
    const message = body?.message || res.statusText;
    throw new ApiError(res.status, code, message);
  }
  return body as T;
}

export async function login(username: string, password: string): Promise<TokenPair> {
  const res = await apiFetch<TokenPair>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  return res;
}
