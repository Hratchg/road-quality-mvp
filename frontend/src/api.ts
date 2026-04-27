import { getToken, clearToken } from "./api/auth";

const API_BASE = import.meta.env.VITE_API_URL || "/api";

// Thrown when a gated request hits 401, so the caller (RouteFinder) can open
// the SignInModal. Phase 4 SC #3 + 04-CONTEXT.md D-04.
export class UnauthorizedError extends Error {
  constructor() {
    super("Unauthorized");
    this.name = "UnauthorizedError";
  }
}

function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

// /segments stays public per SC #3 — no auth header attached.
export async function fetchSegments(bbox: string) {
  const res = await fetch(`${API_BASE}/segments?bbox=${bbox}`);
  if (!res.ok) throw new Error(`Segments fetch failed: ${res.status}`);
  return res.json();
}

export interface RouteRequestBody {
  origin: { lat: number; lon: number };
  destination: { lat: number; lon: number };
  include_iri: boolean;
  include_potholes: boolean;
  weight_iri: number;
  weight_potholes: number;
  max_extra_minutes: number;
}

// /route is gated per SC #3 — attach auth header + handle 401.
export async function fetchRoute(body: RouteRequestBody) {
  const res = await fetch(`${API_BASE}/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (res.status === 401) {
    // Stale / missing / invalid token — wipe localStorage so the modal opens
    // in 'no existing session' state, not in 'we have a token but the
    // server rejected it' confusion.
    clearToken();
    throw new UnauthorizedError();
  }
  if (!res.ok) throw new Error(`Route fetch failed: ${res.status}`);
  return res.json();
}
