# Roadmap: road-quality-mvp

## Overview

The MVP (M0, v0.2.0) shipped a full local-dev Docker stack routing drivers in LA on synthetic IRI + synthetic pothole scores. M1 (v0.3.0) took it to a publicly-demoable cloud deployment running on real LA Mapillary detections — including a documented-negative LA-trained detector experiment and a 2.5s cross-LA routing perf fix. The next milestone scope is open.

## Milestones

- ✅ **v0.2.0 M0 MVP** — Phases 0.1-0.7 (shipped 2026-02-23, per PRD)
- ✅ **v0.3.0 M1 Post-MVP + Public Demo** — Phases 1-8 (shipped 2026-05-08) — see `milestones/v0.3.0-ROADMAP.md`
- 📋 **next milestone** — TBD (run `/gsd-new-milestone`)

## Phases

<details>
<summary>✅ v0.2.0 M0 MVP (Phases 0.1-0.7) — SHIPPED 2026-02-23</summary>

- [x] Phase 0.1: Docker Stack + DB Init
- [x] Phase 0.2: Backend Skeleton + /health
- [x] Phase 0.3: Scoring + Pydantic Models
- [x] Phase 0.4: Seed + /segments + /route
- [x] Phase 0.5: Frontend
- [x] Phase 0.6: Caching + Admin
- [x] Phase 0.7: ML Pluggability + IRI Ingestion

Full details in PRD; not separately archived (pre-`.planning/`).

</details>

<details>
<summary>✅ v0.3.0 M1 Post-MVP + Public Demo (Phases 1-8) — SHIPPED 2026-05-08</summary>

- [x] Phase 1: MVP Integrity Cleanup (4/4 plans) — completed 2026-04-23
- [x] Phase 2: Real-Data Detector Accuracy (5/5 plans) — completed 2026-04-25
- [x] Phase 3: Mapillary Ingestion Pipeline (5/5 plans) — completed 2026-04-26
- [x] Phase 4: Authentication (5/5 plans) — completed 2026-04-27 (subsequently superseded by d0ef452 for public demo)
- [x] Phase 5: Cloud Deployment (5/5 plans) — completed 2026-04-28
- [x] Phase 6: Public Demo Launch (4/4 plans) — completed 2026-04-28
- [x] Phase 7: LA-Trained Detector (7/8 plans, 07-07 skipped per D-13 negative) — completed 2026-05-07 (DOCUMENTED NEGATIVE)
- [x] Phase 8: Routing Performance (5/5 plans) — completed 2026-05-07

Full details in `milestones/v0.3.0-ROADMAP.md`. Audit: `milestones/v0.3.0-MILESTONE-AUDIT.md` (passed).

</details>

### 📋 Next Milestone (Planned)

No phases planned yet. Run `/gsd-new-milestone` to scope the next milestone (questioning → research → requirements → roadmap).

## Progress

| Phase | Milestone | Plans Complete | Status   | Completed  |
| ----- | --------- | -------------- | -------- | ---------- |
| 0.1-0.7 | v0.2.0 | — | Complete | 2026-02-23 |
| 1. MVP Integrity Cleanup | v0.3.0 | 4/4 | Complete | 2026-04-23 |
| 2. Real-Data Detector Accuracy | v0.3.0 | 5/5 | Complete | 2026-04-25 |
| 3. Mapillary Ingestion Pipeline | v0.3.0 | 5/5 | Complete | 2026-04-26 |
| 4. Authentication | v0.3.0 | 5/5 | Complete (superseded) | 2026-04-27 |
| 5. Cloud Deployment | v0.3.0 | 5/5 | Complete | 2026-04-28 |
| 6. Public Demo Launch | v0.3.0 | 4/4 | Complete | 2026-04-28 |
| 7. LA-Trained Detector | v0.3.0 | 7/8 | Complete (negative) | 2026-05-07 |
| 8. Routing Performance | v0.3.0 | 5/5 | Complete | 2026-05-07 |

---
*Roadmap initialized: 2026-04-23 after ingest synthesis + codebase map*
*v0.3.0 archived: 2026-05-08 — 8 phases / 41 plans / 73 tasks shipped*
