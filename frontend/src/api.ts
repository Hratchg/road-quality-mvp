const API_BASE = import.meta.env.VITE_API_URL || "";

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

export async function fetchRoute(body: RouteRequestBody) {
  const res = await fetch(`${API_BASE}/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Route fetch failed: ${res.status}`);
  return res.json();
}
