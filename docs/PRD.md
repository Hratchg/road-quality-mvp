# Road Quality / Pothole Tracker — PRD

**Version:** 0.1.0 (MVP)
**Last Updated:** 2026-02-23

---

## Implemented

- [x] Docker Compose (db with PostGIS + pgRouting, backend, frontend services)
- [x] Database schema: road_segments, segment_defects, segment_scores, route_requests
- [x] .gitattributes for LF line endings on shell scripts
- [x] FastAPI backend skeleton + /health endpoint
- [x] Scoring logic (weight normalization + segment cost)
- [x] Pydantic request/response models
- [x] GET /segments endpoint (GeoJSON bbox query)
- [x] POST /route endpoint (pgRouting k-shortest paths + scoring)
- [x] ML interface stub (PotholeDetector protocol + StubDetector)
- [x] Seed data script (osmnx LA 10km + synthetic IRI/potholes)
- [x] React frontend skeleton (Vite + TypeScript + Tailwind)
- [x] Map View page (segment overlay + controls + legend)
- [x] Route Finder page (click-to-select + route comparison)
- [x] README with quick start, scoring docs, and API overview
- [x] DEMO LAUNCH (Docker Desktop + seed data + backend + frontend)
- [x] Integration tests against real DB (6 tests, auto-skip when DB down)
- [x] Caching layer (in-memory TTL caches for segments + routes, admin endpoints)
- [x] YOLOv8 detector implementation (protocol + factory + fallback to stub)
- [x] Real IRI data ingestion (CSV/shapefile + improved synthetic with spatial smoothing)

## Planned (Post-MVP)

- [ ] Mapillary image pipeline
- [ ] User authentication
- [ ] Production deployment (Docker to cloud)

## Scoring Formula

```
cost_segment = travel_time_s + w_IRI * iri_norm + w_pothole * (moderate_score + severe_score)
total_route_cost = sum(cost_segment)
```

### Weight Normalization
- One parameter enabled: that weight = 100%
- Both enabled: sliders normalized to sum to 100%

### Max Time Rule
- Reject routes where total_time > fastest_time + max_extra_minutes * 60
- If all rejected: return fastest route + warning

## Design Doc

See [docs/plans/2026-02-23-pothole-tracker-design.md](plans/2026-02-23-pothole-tracker-design.md)
