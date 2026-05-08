const API_BASE = import.meta.env.VITE_API_URL || "/api";

export async function fetchSegments(bbox: string) {
  const res = await fetch(`${API_BASE}/segments?bbox=${bbox}`);
  if (!res.ok) throw new Error(`Segments fetch failed: ${res.status}`);
  return res.json();
}

export interface RouteRequestBody {
  origin: { lat: number; lon: number };
  destination: { lat: number; lon: number };
  max_extra_minutes: number;
}

// /segments returns FeatureCollection where every Feature.properties has at least:
// (D-11-09) crash_norm typed-through from Phase 10 backend; default 0.0, non-null.
// Type-only consumption — NOT visualized (D-11-07; anti-features D-11-10..D-11-12).
export interface SegmentProperties {
  iri_norm?: number;
  pothole_score_total?: number;
  crash_norm: number;
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
