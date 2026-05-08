# Milestones

## v0.3.0 Post-MVP + Public Demo (Shipped: 2026-05-08)

**Delivered:** Took road-quality-mvp from synthetic local Docker stack to a public Fly.io demo serving real LA pothole data, with a routing engine that handles cross-LA trips in < 5s. Phase 4 auth was built and validated, then intentionally superseded for the public-demo target. Phase 7 closed as a documented negative result.

**Stats:** 8 phases · 41 plans · 73 tasks · 296 commits · 2,877 files changed (+72,985 / -82) · 11,583 LOC (Py+TS+SQL) · 16 days (2026-04-22 → 2026-05-07)

**Key accomplishments:**

- **Phase 1 — Integrity Cleanup:** Verified BIGINT migration, reconciled 20 km seed-radius drift across 4 docs, retired `REACT_APP_MAPBOX_TOKEN` for `VITE_MAPBOX_TOKEN`, shipped repo-root `.env.example`.
- **Phase 2 — Real-Data Detector:** Env-var `YOLO_MODEL_PATH` config + HF resolution, deterministic eval harness with seed=42 bootstrap CIs, Mapillary v4 client with SHA256 verify + bbox DoS guard, fine-tune CLI with three operator recipes (Laptop/Colab/EC2), `docs/DETECTOR_EVAL.md` writeup.
- **Phase 3 — Mapillary Pipeline:** Migration 002 (`segment_defects.source_mapillary_id` + UNIQUE for ON CONFLICT dedup), `compute_scores.py --source {synthetic|mapillary|all}` filter, `scripts/ingest_mapillary.py` with three target-resolution modes + ST_Buffer→YOLO→snap-match loop + `--wipe-synthetic` cutover, `docs/MAPILLARY_INGEST.md` operator runbook.
- **Phase 4 — Authentication:** Shipped JWT (HS256, AUTH_SIGNING_KEY) + pwdlib argon2id + `/auth/{register,login,logout}` + sign-in modal + demo account, validated via 8-scenario curl UAT. **Subsequently superseded by commit `d0ef452` (2026-04-28)** for fully-public demo target; auth backend modules retained in tree as dormant code.
- **Phase 5 — Cloud Deployment:** Fly.io tri-app live (db with custom PostGIS+pgRouting 3.8 image on internal-only network, backend with /health LB probe, frontend with build-time-baked `VITE_API_URL`), GH Actions deploy.yml, ThreadedConnectionPool wrapper, env-driven CORS, /health 503-on-DB-down.
- **Phase 6 — Public Demo:** Live URL `https://road-quality-frontend.fly.dev/` serves real LA Mapillary-ingested data via the public-baseline `keremberke/yolov8s-pothole-segmentation` detector (per Phase 6 D-09); ~205k segments + ~74k vertices + ~125k defects across 12 LA zones.
- **Phase 7 — LA-Trained Detector (DOCUMENTED NEGATIVE):** D-11 win-check FAILED for both training iterations (iter-1 collapse, iter-2 train/test labeling-style drift) on a 171-bbox eval set. Per D-13 contingency: production retains keremberke baseline; both trained models preserved on HF for traceability; `DETECTOR_EVAL.md` v0.3.0 documents both failure modes honestly.
- **Phase 8 — Routing Performance:** pgr_ksp K=5 (super-linear, 20-90s on cross-LA) replaced with pre-filter temp table + pgr_dijkstra×K with edge-weight perturbation (Yen's-style, linear in K) wired into a 3-attempt fallback chain (filter → wide → full). Cross-LA route now 2.47s uncached; DTLA 0.385s.

**Audit verdict:** `passed` (flipped from `tech_debt` 2026-05-08 by ce190d2 after REQ-user-auth doc-vs-code drift was resolved). See `milestones/v0.3.0-MILESTONE-AUDIT.md`.

**Known deferred items at close:** 4 (see `STATE.md` § Deferred Items › Acknowledged at v0.3.0 milestone close — operator-runbook walkthroughs for Phase 02/03/05 verification + Phase 02 HUMAN-UAT).

**Requirements:** 6/7 SATISFIED + 1 SUPERSEDED (REQ-user-auth, public-demo decision). See `milestones/v0.3.0-REQUIREMENTS.md`.

**Archives:**
- `milestones/v0.3.0-ROADMAP.md`
- `milestones/v0.3.0-REQUIREMENTS.md`
- `milestones/v0.3.0-MILESTONE-AUDIT.md`

**Tag:** `v0.3.0`

---
