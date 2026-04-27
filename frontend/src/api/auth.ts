// Auth API client — register, login, logout + token storage.
// Locked decisions: 04-CONTEXT.md D-04 (localStorage), D-05 (demo creds), D-06 (endpoint shapes).
// Token storage seam: getToken / clearToken are the ONLY exported surface that
// touches localStorage. setToken is private — callers MUST go through register
// or login. If we ever migrate to httpOnly cookies (post-MVP), this is the
// single file that changes.

const API_BASE = import.meta.env.VITE_API_URL || "/api";
const TOKEN_KEY = "rq_auth_token";

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user_id?: number; // present on /register, absent on /login
  email?: string;   // present on /register, absent on /login
}

async function _postJson(path: string, body: unknown): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function register(email: string, password: string): Promise<AuthResponse> {
  const res = await _postJson("/auth/register", { email, password });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Register failed: ${res.status}`);
  }
  const data = (await res.json()) as AuthResponse;
  setToken(data.access_token);
  return data;
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const res = await _postJson("/auth/login", { email, password });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Login failed: ${res.status}`);
  }
  const data = (await res.json()) as AuthResponse;
  setToken(data.access_token);
  return data;
}

export async function logout(): Promise<void> {
  // Server-side is a no-op for stateless JWT; we just clear localStorage.
  // Calling /auth/logout for symmetry — server returns 204, no body.
  // Swallow network errors (logout should always succeed client-side).
  try {
    await _postJson("/auth/logout", {});
  } catch {
    // intentionally ignored
  }
  clearToken();
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

function setToken(t: string): void {
  localStorage.setItem(TOKEN_KEY, t);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return getToken() !== null;
}
