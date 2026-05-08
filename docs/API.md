# road-quality-mvp Backend API

**Applies to:** v0.4.0 (Crash-Aware Routing milestone)
**Audience:** Frontend integrators, third-party API consumers, future-Claude.
**Last updated:** 2026-05-08 (Phase 10 / Plan 10-03)

---

## Endpoints

### POST /route

Compute the fastest + best routes between two LA-area points.

**Request body (Pydantic v2 model):**
```json
{
  "origin": {"lat": 34.05, "lon": -118.24},
  "destination": {"lat": 34.06, "lon": -118.25},
  "max_extra_minutes": 5
}
```

**Optional/legacy fields (silently accepted, semantically ignored):**
`include_iri`, `include_potholes`, `weight_iri`, `weight_potholes`. Any other
field is silently dropped (`model_config = ConfigDict(extra='ignore')`).

**Response:** `RouteResponse` JSON with `fastest_route`, `best_route`,
optional `warning`, and `per_segment_metrics`.

**Response headers:**
- `Deprecation: weight_iri,weight_potholes ignored as of v0.4.0` — present on
  EVERY response (success, cache hit, no-route fallback).

### GET /segments?bbox=min_lon,min_lat,max_lon,max_lat

Return GeoJSON FeatureCollection of road segments inside the bounding box.

**Each feature's `properties` dict includes:**
- `id` (int)
- `iri_norm` (float | null)
- `moderate_score` (float)
- `severe_score` (float)
- `pothole_score_total` (float)
- `crash_norm` (float, default 0.0 for segments with no crashes — D-10-17, D-10-18) **NEW in v0.4.0**

---

## Locked Outer Weights (v0.4.0)

The cost-segment formula uses three module constants from `backend/app/scoring.py`:

| Constant | Value | Meaning |
|----------|-------|---------|
| `W_IRI` | 0.40 | International Roughness Index normalized score |
| `W_POT` | 0.35 | Pothole detection severity-weighted score |
| `W_CRASH` | 0.25 | Per-segment crash density (severity-weighted, length-normalized, p95-capped) |

Sum = 1.0 by construction (no normalization step).

`compute_segment_cost(travel_time_s, iri_norm, pothole_total, crash_norm) = travel_time_s + 0.40*iri_norm + 0.35*pothole_total + 0.25*crash_norm`.

These constants REPLACE the user-tunable `weight_iri` / `weight_potholes`
sliders shipped in v0.2.0. Rationale: a single recommendation that respects
all three road-quality signals produces deterministic, defensible routes at
the demo level. The slider UX implied that user choice was meaningful; in
practice it was a UX-time tradeoff that should not depend on the
moment-of-decision.

---

## Severity Weights (v0.4.0)

Per-crash severity contributions to a segment's `crash_norm` aggregate:

| Constant | Value | Crash Tier (LA City KABCO) |
|----------|-------|----------------------------|
| `FATAL_WEIGHT` | 8 | KABCO=4 |
| `INJURY_WEIGHT` | 3 | KABCO=3 |
| `PDO_WEIGHT` | 1 | property-damage-only |

**NOT** the academic `100:10:1` ratio (which is correct for project
prioritization but produces bimodal saturation at 0/1 in routing — see
Pitfall 5 in `.planning/phases/10-crash-scoring-formula-locked-weight-routing-api/10-RESEARCH.md`).

Single-fatal cap: `min(per-segment raw severity sum, FATAL_CAP=24)` — caps
at 3 equivalent-fatal units so one freak crash doesn't dominate a long
arterial. `FATAL_CAP_K=3` is researcher-recommended (see RESEARCH.md
Open Question 1); recalibration is a one-line constant change + recompute
via `python scripts/compute_scores.py --source crash`.

Per-segment formula:
```
raw_per_km = LEAST(SUM(severity_weight), FATAL_CAP) / GREATEST(length_m / 1000.0, 0.05)
crash_norm = LEAST(1.0, raw_per_km / p95)
```
where `p95 = PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY raw_per_km)` over
crash-bearing segments only (Pitfall 6).

See `scripts/compute_scores.py` `CRASH_UPDATE_SQL` for the exact UPDATE
(landed in Plan 10-02).

---

## Silent-Ignore Behavior

The `RouteRequest` Pydantic model uses `ConfigDict(extra='ignore')` (D-10-13).
Concretely:

- `POST /route {... "weight_iri": 0.99, "weight_potholes": 0.01}` → 200 OK;
  the values are NOT used in the cost computation.
- `POST /route {... "evil_field": true}` → 200 OK; `evil_field` is silently
  dropped before the model is constructed.

**Why this is safer than `extra='forbid'`:** the locked CON-route-api contract
requires backwards-compat. `extra='forbid'` would 422-reject any caller still
sending the legacy fields — including any third-party integration we don't
know about. `extra='ignore'` is the additive non-breaking choice.

**Why this is safer than removing the fields outright:** v0.2.0 unit tests
introspect `RouteRequest().weight_iri == 50` (the Field default). Removing
the fields would break the v0.2.0 unit-test suite. They're kept as Field
defaults but unused at runtime.

---

## Deprecation Header

Every `/route` response carries:
```
Deprecation: weight_iri,weight_potholes ignored as of v0.4.0
```

The header is set BEFORE the audit-log INSERT and BEFORE the cache check, so
it persists across all three response paths: success, cache hit, no-route
fallback (Pitfall 4).

**Disclosure:** This header value is documentation-style, NOT RFC 9745
compliant (which mandates `@<unix-timestamp>` form). For the LA-only
single-frontend public demo, this is acceptable; revisit in v0.5.0+ if
external API consumers materialize.

---

## Identical-Route Guarantee

`POST /route {origin, destination, max_extra_minutes, weight_iri: 0.99, weight_potholes: 0.01}`
returns the SAME `geojson` and `total_cost` as
`POST /route {origin, destination, max_extra_minutes}` — semantic ignore,
not just accepted by the schema.

Pinned by integration test
`backend/tests/test_route.py::test_identical_route_with_legacy_weight_fields`
(Pitfall 7).

---

## Cache Key Composition

The route cache key (SHA-256 of a JSON dict, see
`backend/app/cache.py:make_route_cache_key`) is composed of EXACTLY 5 fields:

1. `origin_lat`
2. `origin_lon`
3. `dest_lat`
4. `dest_lon`
5. `max_extra_minutes`

`include_iri`, `include_potholes`, `weight_iri`, `weight_potholes` were
dropped from the cache-key signature in v0.4.0 because none of them affect
the computed response (the locked outer weights apply unconditionally).
Including them would fragment the cache without semantic benefit (Pitfall 2).

---

## REQ-ID Hygiene Pattern

Established in commit `d0ef452` (Phase-4 auth-removal for the public demo,
v0.3.0 milestone): any commit whose message contains "remove" / "supersede"
/ "drop" / "lock" must update BOTH `.planning/REQUIREMENTS.md` AND
`.planning/PROJECT.md` in the SAME diff. This is the v0.3.0 ce190d2 fix
pattern, audited at milestone close.

Carried forward to v0.4.0: the locked-weights swap in this milestone is a
supersede-commit pattern (replaces v0.2.0's user-tunable weights). The commit
landing this change updated REQUIREMENTS.md (`REQ-route-api-locked-weights`)
and PROJECT.md (key decisions table) atomically.

---

## Versioning

| Version | Milestone | Notable changes |
|---------|-----------|-----------------|
| v0.2.0 | M0 MVP | First public API; user-tunable IRI/pothole sliders |
| v0.3.0 | M1 Public Demo | Mapillary-driven detector data; routing performance overhaul (Phase 8); auth removed |
| **v0.4.0** | **M2 Crash-Aware Routing** | **Locked outer weights (40/35/25); crash data ingest + per-segment crash_norm; silent-ignore + Deprecation header for legacy slider fields; GET /segments exposes crash_norm** |

---

## Out of Scope (v0.4.0)

See `.planning/REQUIREMENTS.md` "Out of Scope" section. Notable items NOT in
v0.4.0:

- RFC 9745-compliant `Deprecation` header timestamp form
- SWITRS / TIMS crash data sources (LA City Socrata only)
- Fractional intersection snap-match (naive nearest-segment only)
- Exponential recency decay (flat 5-year window)
- GET /segments pagination
- `crash_records` real-time updates (quarterly batch ingest only)
- Per-route disclosure of which crashes contributed (privacy-by-design omission)

---

*This file is the canonical API contract for v0.4.0. Generated 2026-05-08
(Phase 10 / Plan 10-03).*
