# Project Research Summary

**Project:** road-quality-mvp v0.4.0 — Crash-Aware Routing
**Domain:** Subsequent-milestone integration: adding historical crash data as a third routing-cost factor on top of v0.3.0 IRI + pothole routing (PostGIS / pgRouting / FastAPI / React stack already shipped to Fly.io)
**Researched:** 2026-05-07
**Confidence:** HIGH overall — the four documents converge on a single, internally-consistent build plan with the few open questions concentrated in well-isolated places (severity-weight tuning, data-source operational details).

## Executive Summary

v0.4.0 is a **reuse-first, reskin-the-Mapillary-pipeline** milestone. All four research documents independently arrive at the same conclusion: it is the v0.3.0 Phase 3 ingest pipeline with crash data substituted for image detections, plus a locked routing-cost formula and a slider removal in the frontend. The user has already locked enough decisions (three-tier severity, 5-year aggregate, fixed weights `0.40·iri + 0.35·pothole + 0.25·crash`, no heatmap layer, no real-time, no sliders for crash) that the research scope shrinks dramatically — what remains is *how* to ingest, snap, score, and combine, not *whether*.

STACK introduces exactly **one new dependency line** (`geopandas>=1.0` bump for the pyogrio engine). ARCHITECTURE adds exactly **one new migration (004), one new table (`crash_records`), one new column (`segment_scores.crash_norm`)**. FEATURES locks 12 P1 items (10 table-stakes + slider removal + materialized `crash_norm`). PITFALLS catalogs 15 traps, of which 10 are critical-priority and 5 directly mirror v0.3.0 lessons-learned.

**Recommended approach:** strictly additive, non-breaking integration in five build-order-gated steps — schema migration → crash ingest script → score recompute → routing cost-formula constants → frontend slider removal — with each step independently deployable behind a `LEFT JOIN COALESCE(0)` safety net. The Mapillary `(source, source_record_id)` UNIQUE-on-conflict pattern is reused unchanged for idempotent re-ingest. The `ST_DWithin + <-> KNN` snap-match pattern is reused unchanged but with **wider tolerance (75 m for SWITRS vs. 25 m for Mapillary)** because crash data is geocoded at intersection centroids, not lane-precise. `crash_norm` is **pre-baked at ingest time** into `segment_scores`, never computed at request time.

**Risk concentration (three areas):**

1. **Intersection-attribution snap-match** (Pitfall 4) — naive nearest-segment over-attributes intersection crashes to short stub segments; requires fractional/buffer-based attribution. Highest-risk single piece of code in the milestone.
2. **Fatal-overweighting in severity calibration** (Pitfall 5) — naive `fatal=100` weights saturate `crash_norm` to 1.0 on a handful of segments, defeating the locked outer-weights design. Recommended starting point `fatal:injury:pdo ≈ 8:3:1`.
3. **Data-source operational pitfalls that affect milestone shape** — TIMS has no programmatic API and excludes PDO crashes; LA City `d5tf-ez2w` has been frozen since LAPD's March 2024 NIBRS migration; SWITRS provisional-vs-final certification has a 12-18 month lag. These are honest-disclosure problems, not blockers — they shape the operator runbook and disclaimer copy, not the architecture.

## Key Findings

### Recommended Stack

The crash-ingest pipeline reuses ~95% of the existing dependency tree. The only new line is a **version bump on `geopandas` from `>=0.14` to `>=1.0,<2.0`** (gets `pyogrio` as default I/O engine, 5-20× shapefile speedup vs. fiona). All other libraries — `requests`, `psycopg2-binary`, `numpy`, PostGIS 3.4 — are already in the tree.

STACK explicitly **rejects** `sodapy` (officially unmaintained since Aug 2022; `data_pipeline/mapillary.py` already proves the right pattern is a thin `requests` wrapper with module-top env-var token). Rejects introducing any ORM, async HTTP stack, job queue, or migration framework — all project-constraint violations.

**Core technologies (reused unchanged unless noted):**
- **PostGIS 3.4 + `ST_DWithin` + `<->` KNN** — snap-match crashes to nearest road segment via existing GIST index `idx_segments_geom`
- **psycopg2-binary 2.9.11 + `execute_values` + ON CONFLICT DO NOTHING** — idempotent bulk INSERT into `crash_records`, mirroring Phase 3 D-08
- **`requests`** — thin Socrata SoQL client for LA City `d5tf-ez2w.json`, mirroring `data_pipeline/mapillary.py` module pattern
- **`geopandas>=1.0` (BUMPED) + `pyogrio` (transitive)** — TIMS shapefile/CSV read with WGS84 reprojection
- **pgRouting 3.6 (existing) + Phase 8 perturbation pattern** — preserved; only the cost expression inside changes

### Expected Features

**P1 — Must-have (table stakes, all locked by user decisions):**
- T1: EPDO three-tier severity weighting (HSM-aligned)
- T2: 5-year flat aggregation window (no temporal decay)
- T3: PostGIS spatial snap-match (reuses Phase 3 SQL primitive)
- T4: Per-km length normalization (honest substitute for unavailable AADT)
- T5: 0–1 normalization with p95 cap (matches `iri_norm` semantics)
- T6: Zero-default for no-crash segments (DB DEFAULT 0 NOT NULL)
- T7: Quarterly refresh runbook (idempotent re-ingest)
- T8: Data-vintage legend (one-line "About the data" footer)
- T9: Backwards-compatible `/route` API (silently ignore `w_IRI` / `w_pothole`)
- T10: Liability disclaimer at route-selection moment
- D5: Pre-computed `crash_norm` at ingest (not request-time)

**P2 — Should-have (after validation):**
- D1: Route-level summary ("passes N crash-prone segments")
- D6: Severity-breakdown tooltip on hover
- D4: Operator data-freshness badge in `/health`

**Defer to v0.5.0+:** SPF-based EB shrinkage (D2 — needs AADT), data-sparsity shading (D7), real-time crash overlay, multi-modal routing.

**Anti-features locked OUT:** A1 (naming intersections — litigation risk), A2 (real-time overlay), A3 (per-hour weighting), A5 (crash sliders), A6 (separate heatmap toggle layer), A7 (comparative ranking like "23% safer").

### Architecture Approach

Strictly additive layer on the v0.3.0 PostGIS+pgRouting+FastAPI+React tree. ARCHITECTURE resolves seven sub-questions decisively in favor of new-not-extend, ingest-time-not-request-time, locked-constants-not-config-files, additive-not-breaking. Zero deletions and zero breaking changes; rollout staged behind `LEFT JOIN COALESCE(0)` graceful-degradation safety net.

**Major components:**

1. **`crash_records` (NEW table, migration 004)** — source-tagged points with severity tier and snap-distance audit; `(source, source_record_id)` UNIQUE for idempotent re-ingest; FK to `road_segments(id) ON DELETE SET NULL`.
2. **`segment_scores.crash_norm` (NEW additive column, DEFAULT 0)** — pre-baked per-segment normalized score; same row that already holds `iri_norm` / `moderate_score` / `severe_score` / `pothole_score_total`.
3. **`scripts/ingest_crashes.py` (NEW, ~250 LOC)** — driver mirroring `ingest_mapillary.py` minus YOLO/image-download loop.
4. **`scripts/compute_scores.py` (MODIFIED — extended UPSERT)** — adds `'crash'` to `VALID_SOURCES`; adds correlated subquery against `crash_records` to avoid cross-product explosion.
5. **`backend/app/scoring.py` + `backend/app/routes/routing.py` (MODIFIED — locked constants)** — `compute_segment_cost()` gains `crash_norm` arg + `w_crash` kwarg; routing.py replaces `normalize_weights()` call with module constants `W_IRI=0.40, W_POT=0.35, W_CRASH=0.25`; Pydantic `RouteRequest` preserved with `model_config = ConfigDict(extra='ignore')`.
6. **`backend/app/routes/segments.py` (MODIFIED — additive field)** — properties dict gains `crash_norm`.
7. **Frontend `ControlPanel.tsx` + `RouteFinder.tsx` (MODIFIED — slider removal)** — only two files touched; `MapView.tsx` unchanged because color comes from cost which now silently includes crash term.

### Critical Pitfalls

**Top 5 (highest blast radius):**

1. **Intersection-attribution snap-match (Pitfall 4)** — Same shape as v0.3.0 Phase 8 `pgr_ksp` SPI/GiST trap. Mitigation: two-mode snap-match — buffer-based fractional attribution (weight = 1/degree) when within 15-25 m of a degree-≥3 vertex, single nearest-segment otherwise. Wave-0 RED test with synthetic 4-way intersection fixture.
2. **Fatal-overweighting flips routing to absurd detours (Pitfall 5)** — `fatal=100, injury=10, pdo=1` saturates `crash_norm` to 1.0 on ~50-100 segments. Mitigation: start with `fatal:injury:pdo ≈ 8:3:1`; cap any single fatal's per-segment contribution; log-transform the per-segment sum.
3. **SWITRS provisional-vs-final 12-18 month certification lag (Pitfall 1)** — Recent records can be retroactively edited. Mitigation: `record_status` column; quarterly delta-report surfaces retractions; lag routing window by 12 months for public demo.
4. **Severity-code drift between SWITRS old codes (1-4) and MMUCC 5th-edition codes (5-7) (Pitfall 2)** — Same shape as v0.3.0 Phase 7 operator-labeling-style drift. Mitigation: mapping function in one file with explicit table covering both regimes and `else: raise ValueError`.
5. **Public-demo "safer route" claim without legal-grade disclaimer (Pitfall 9)** — Mitigation: specific disclaimer copy at route-selection moment; avoid "safer" — use "lower historical crash density"; equity audit (10 cross-neighborhood routes) in `docs/EQUITY_NOTE.md`.

**Honorable mentions:** jurisdictional double-counting on SR-110/SR-2/SR-170/SR-1/SR-27/SR-47 (Pitfall 3); recency-decay 5-year cliff (Pitfall 6); API contract drift on `/route` (Pitfall 7); Fly volume disk-full mid-migration (Pitfall 8); build-then-supersede cycle repeat (Pitfall 10).

## Implications for Roadmap

**Recommended phase shape (consensus across all 4 docs):**

### Phase 9: Scoping & Decision Log
v0.3.0 KEY LESSON 1 redux. Lock ambiguous product questions before code starts.
**Delivers:** Decision-log entries for severity weights starting point, intersection-buffer radius, SWITRS snap tolerance, recency-decay TAU, `record_status` column, synthetic-crash seed scope, equity-audit scope, TIMS license verification.

### Phase 10: Schema Migration + Ingest Pipeline
**Delivers:** `db/migrations/004_crash_records.sql` (idempotent, mirrors 002 pattern); `scripts/ingest_crashes.py`; `data_pipeline/tims.py` (~80 LOC) + `data_pipeline/lacity_socrata.py` (~120 LOC); `data_pipeline/switrs_severity.py` (mapping with both code regimes); synthetic seed mode; geopandas version bump.
**Avoids:** Pitfalls 1, 2, 3, 13.

### Phase 11: Snap-Match (highest-risk phase)
**Delivers:** `snap_match_crash()` with two-mode logic; fractional-weight schema; Wave-0 RED test with synthetic 4-way intersection fixture; histogram-of-snap-distance audit; `dropped_outside_snap` counter.
**Avoids:** Pitfall 4 (intersection ambiguity), Pitfall 11 (geocoding-precision claims).

### Phase 12: Score Recompute & Cost Formula
**Delivers:** Extended `compute_scores.py` UPSERT with correlated subquery; `crash_norm` formula; `compute_segment_cost(travel_time, iri_norm, pothole_total, crash_norm, W_IRI=0.40, W_POT=0.35, W_CRASH=0.25)`; module constants replacing `normalize_weights()`; extended `SEGMENTS_BY_IDS_SQL`; `last_computed_at` per-source timestamp; exponential decay (TAU=3y).
**Avoids:** Pitfalls 5, 6, 12, 15.

### Phase 13: API Contract + Frontend Slider Removal + Disclaimer
**Delivers:** `RouteRequest` Pydantic config explicit `extra='ignore'`; deprecation warning header; integration tests asserting same-route-with-or-without-w_IRI; `/segments` extended with `crash_norm`; ControlPanel slider removal (keep `max_extra_minutes`); changelog modal; legal-grade disclaimer at route-selection moment; data-vintage legend; "lower historical crash density" copy (NOT "safer").
**Avoids:** Pitfalls 7, 9, 11, 14.

### Phase 14: Deploy + First Quarterly Refresh + Equity Audit
**Delivers:** Pre-deploy `df -h` volume sizing rehearsal; `flyctl ssh console -C` migration apply; CI gate running 001→002→003→004 fresh on every PR touching migrations; one full quarterly refresh end-to-end; cache flush on refresh; `docs/EQUITY_NOTE.md` from 10 cross-neighborhood routes.
**Avoids:** Pitfall 8 (locked anti-pattern), Pitfall 14 (refresh runbook drift).

### Phase 15: Verification + Milestone Close Audit
**Delivers:** All "Looks Done But Isn't" 16-item checklist items; K-path diversity profile vs. v0.3.0 baseline; 5-known-safe-arterials manual route inspection; T-vs-T+1d snapshot diff; audit-gate scan for "remove"/"supersede" commits; milestone-close audit doc.
**Avoids:** Pitfalls 14, 15, 10.

### Build-Order Dependencies (strict, load-bearing)

- Schema before ingest (can't INSERT into a non-existent table)
- Ingest before recompute (recompute reads from `crash_records`)
- Recompute before routing constants (`COALESCE(crash_norm, 0)` silently zeros third term otherwise)
- Backend before frontend (frontend slider-removal requests will break if backend still requires `w_IRI`)
- Disclaimer before public-demo verification (equity-audit findings need a place to land)

This ordering was independently arrived at by ARCHITECTURE g, STACK § Integration Points, FEATURES dependency tree, and PITFALLS pitfall-to-phase mapping. **No tension between docs.**

### Cross-Doc Consensus

| Topic | STACK | FEATURES | ARCHITECTURE | PITFALLS |
|-------|-------|----------|--------------|----------|
| One new dependency line (geopandas bump) | ✓ | — | — | — |
| New migration 004 + new `crash_records` table | ✓ | ✓ T7 | ✓ a, e | ✓ Pitfall 8 |
| `segment_scores.crash_norm` additive column | ✓ | ✓ D5 | ✓ b | ✓ Pitfall 12 |
| Pre-bake at ingest, NOT request-time | ✓ | ✓ D5 | ✓ b | ✓ perf-trap row 2 |
| Reuse `(source, source_record_id)` UNIQUE | ✓ | ✓ T7 | ✓ a | ✓ Pitfall 3 |
| Reuse `ST_DWithin + <->` snap pattern | ✓ | ✓ T3 | ✓ d | ✓ Pitfall 4 with mod |
| Wider snap tolerance for crashes (~75m vs 25m) | ✓ | — | ✓ d | ✓ Pitfall 4 |
| EPDO three-tier severity, HSM-aligned | ✓ | ✓ T1 | — | ✓ Pitfall 5 |
| Locked weights as module constants | ✓ | ✓ A5 | ✓ f | ✓ Pitfall 7 |
| Backwards-compat `/route` API silent-ignore | ✓ | ✓ T9 | ✓ f | ✓ Pitfall 7 |
| Slider removal, frontend last in build order | ✓ | ✓ T9, A5 | ✓ g step 6 | ✓ Pitfall 7 |
| Quarterly refresh as operator runbook | ✓ | ✓ T7 | ✓ | ✓ Pitfall 14 |
| No new ML libraries / no detector | ✓ | ✓ A4 | ✓ | — |
| Disclaimer required, "crash-aware" not "safer" | — | ✓ T10 | — | ✓ Pitfall 9 |
| No heatmap toggle / no real-time / no sliders | — | ✓ A2, A5, A6 | — | ✓ Pitfall 10 |

**Disagreements / tensions:** None substantive. Two minor points where docs differ in emphasis but not direction:

1. **EPDO severity weight numbers** — FEATURES T1 cites HSM defaults `fatal=10, injury=5, PDO=1`; PITFALLS Pitfall 5 cites literature `fatal:injury:pdo ≈ 8:3:1` for routing-cost; ARCHITECTURE sketch uses `3.0:1.0:0.3`. Resolution: Phase 9 decision-log + Phase 12 empirical iteration.
2. **PDO data availability** — STACK + PITFALLS note TIMS excludes PDO; LA City `mocodes` mapping is lossy. Resolution (already in STACK): treat formula as `0.25·(fatal_weighted + injury_weighted)` with `pdo_norm = 0` documented honestly. Do NOT renegotiate the locked formula.

### Data-Source Surprises That Affect Milestone Shape

These reshape the **operator runbook and disclaimer copy**, NOT the architecture:

1. **TIMS has no PDO crashes.** Locked three-tier severity will have permanently-zero PDO. Phase 10 documents `pdo_norm = 0` explicitly; Phase 13 disclaimer notes "fatal + injury crashes only"; Phase 9 decision-log captures reserved-for-future status.
2. **LA City `d5tf-ez2w` is FROZEN since LAPD's March 2024 NIBRS migration.** Quarterly refreshes will not produce new LA-City rows past 2024-03. Phase 10 ingest_crashes.py accepts both sources independently; Phase 14 runbook documents this; operator should expect identical LA-City row counts each quarter.
3. **SWITRS provisional-vs-final 12-18 month certification lag.** Phase 10 schema includes `record_status` column; Phase 14 quarterly refresh delta-report surfaces retractions; for public demo, lag routing window by 12 months; Phase 13 disclaimer cites "certified through [year]."

### Research Flags (deeper research during planning)

**Phases needing deeper research (`/gsd-research-phase`):**
- **Phase 10 (Schema + Ingest):** SWITRS column-by-name vs. column-order schema; `record_status` field name in actual exports; severity-code mapping table; `mocodes`-to-severity precision.
- **Phase 11 (Snap-Match):** `INTERSECTION_BUFFER_M` empirical tuning (15 vs. 20 vs. 25 m); fractional-weight schema design; degree-2 vs. degree-≥3 vertex handling.
- **Phase 12 (Scoring):** Severity-weight starting numbers; single-fatal cap formula; log-transform vs. smooth-rate vs. p95 cap; recency-decay TAU benchmark.

**Phases with standard patterns (skip research-phase):**
- **Phase 9 (Scoping):** Process discipline; v0.3.0 KEY LESSON 1 + REQ-ID hygiene patterns documented.
- **Phase 13 (API + Frontend + Disclaimer):** Pydantic v2 `extra='ignore'`, React edits, disclaimer-copy patterns well-documented.
- **Phase 14 (Deploy):** v0.3.0 Phase 5 lessons explicit and locked.
- **Phase 15 (Verification):** Checklist-driven; v0.3.0 Phase 6 precedent.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Context7 + official docs verified for geopandas/pyogrio/Socrata; sodapy maintenance status verified via PyPI |
| Features | HIGH for table-stakes/anti-features (FHWA HSM + LADOT Vision Zero + Waze + HERE + Mapbox); MEDIUM for specific severity-weight numbers (jurisdiction-dependent) |
| Architecture | HIGH | Direct repo-source grounding; seven sub-questions resolved decisively |
| Pitfalls | HIGH for SWITRS / Fly-deploy / API-contract pitfalls; MEDIUM for severity-weighting math + recency-decay (literature consistent but empirical) |

**Overall confidence: HIGH.** Cross-doc agreement on build order, schema decisions, and risk concentration is unusually strong. Gaps are well-bounded and assigned to specific phases.

### Gaps to Address

- **Severity-weight starting numbers** — HSM `10:5:1` vs. literature `8:3:1` vs. ARCHITECTURE sketch `3.0:1.0:0.3`. Phase 9 decision-log; Phase 12 empirical iteration.
- **Intersection-buffer radius** — 15-25 m range. Phase 9 picks starting value (recommend 20 m); Phase 11 tunes empirically.
- **Recency-decay TAU value** — PITFALLS recommends 3 years; needs empirical validation. Phase 12.
- **CCRS public CSV geocoding completeness** — Defer to v0.5.0; v0.4.0 uses TIMS + LA City only.
- **`mocodes`-to-severity mapping precision** — Phase 10 needs operator validation; treat as best-effort with explicit "lossy mapping" note.
- **TIMS license terms for public-Fly.io demo** — Phase 9 decision-log; operator reads TIMS terms-of-use.
- **Synthetic-crash test data scope** — Phase 9 decision: extend `seed_data.py` (recommended per Pitfall 13) or skip.
- **Frontend legend update scope** — PROJECT.md says "no new map layer"; T8 + Pitfall 9 require data-vintage caption. Phase 13 carries "small caption, not new layer" interpretation.
- **Boundary-segment audit list** — Pitfall 3 calls out SR-110/SR-2/SR-170/SR-1/SR-27/SR-47. Phase 14 quarterly-refresh runbook lists 5 specific segments to spot-check.
- **First-quarterly-refresh equity-audit route pairs** — Pitfall 9 calls for 10 cross-neighborhood routes. Phase 9 or Phase 14 picks specific pairs.

## Sources

**Primary (HIGH confidence):**
- Repo source: `db/migrations/001-003`, `backend/app/routes/routing.py`, `segments.py`, `scoring.py`, `models.py`, `scripts/compute_scores.py`, `scripts/ingest_mapillary.py`, `.planning/PROJECT.md`, `.planning/RETROSPECTIVE.md`, `.planning/milestones/v0.3.0-MILESTONE-AUDIT.md`
- Library docs: GeoPandas migration guide, Pyogrio releases, Socrata SODA API, PostGIS workshops
- Authoritative data: LA City `d5tf-ez2w` listing, Berkeley TIMS docs, SWITRS Codebook, CHP SWITRS, LA GeoHub Vision Zero
- Vision Zero / safety canon: LADOT Vision Zero HIN, SF Vision Zero 2022 methodology, FHWA Network Screening, FHWA Solving Safety Problems

**Secondary (MEDIUM confidence):** Korde 2024 (intersection-buffer pattern), Geocoding Police Collision Report Data From California, MDPI EPDO papers, Hardball Times exponential decay, Wikipedia exponential smoothing, GPS-liability legal sources

**Tertiary (LOW confidence — needs validation):** CCRS CSV geocoding, `mocodes`-to-severity precision, TIMS commercial-demo license terms, exact SWITRS field name for provisional/final flag
