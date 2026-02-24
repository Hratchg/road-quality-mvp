# Road Quality / Pothole Tracker — PRD

**Version:** 0.1.0 (MVP)
**Last Updated:** 2026-02-23

---

## Implemented

- [x] Docker Compose (db with PostGIS + pgRouting, backend, frontend services)
- [x] Database schema: road_segments, segment_defects, segment_scores, route_requests
- [x] .gitattributes for LF line endings on shell scripts
- [x] FastAPI backend skeleton + /health endpoint

## In Progress

- [ ] Scoring logic (weight normalization + segment cost)
- [ ] Pydantic request/response models
- [ ] GET /segments endpoint (GeoJSON bbox query)
- [ ] POST /route endpoint (pgRouting k-shortest paths + scoring)
- [ ] ML interface stub (PotholeDetector protocol + StubDetector)
- [ ] Seed data script (osmnx LA 10km + synthetic IRI/potholes)
- [ ] React frontend skeleton (Vite + TypeScript + Tailwind)
- [ ] Map View page (segment overlay + controls + legend)
- [ ] Route Finder page (click-to-select + route comparison)
- [ ] README with quick start + scoring docs

## Planned (Post-MVP)

- [ ] Integration tests against real DB
- [ ] YOLOv8 detector implementation (replace StubDetector)
- [ ] Real IRI data ingestion (FHWA/state DOT sources)
- [ ] Mapillary image pipeline
- [ ] Caching layer for heavy queries
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
