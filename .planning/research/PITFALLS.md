# Pitfalls Research — v0.4.0 Crash-Aware Routing

**Domain:** Adding historical-crash-data ingest + crash-aware routing to a working production routing app (road-quality-mvp v0.3.0 → v0.4.0)
**Researched:** 2026-05-07
**Confidence:** HIGH for SWITRS / Fly-deploy / API-contract pitfalls (verified against authoritative SWITRS docs, official LA City GeoHub metadata, prior v0.3.0 lessons-learned, and codebase concerns); MEDIUM for severity-weighting math + recency-decay (literature is consistent but project-specific tuning is empirical).

This document is **specific to ADDING crash data to road-quality-mvp**. Generic Python / FastAPI / ML pitfalls are intentionally excluded — they were either solved in v0.2.0 / v0.3.0 or are not load-bearing for this milestone. Every pitfall below either:

1. Calls back to a v0.3.0 lesson-learned that could repeat verbatim if not pinned, or
2. Is unique to crash-data-as-a-routing-cost-factor (severity scale traps, intersection ownership, fatal-overweighting, ethical disclosure), or
3. Is unique to **changing a production scoring formula** in an app that has live users hitting `/route` today.

---

## Critical Pitfalls

### Pitfall 1: SWITRS data-recency cliff makes "current" data 12-18 months stale

**What goes wrong:**
You ingest "the latest SWITRS data" assuming it covers the last full year. SWITRS actually has a 12-18 month CHP data-entry lag. Worse, recent records are tagged **provisional** (not yet certified by CHP's annual report) and can be retroactively edited or deleted. If you mix provisional + final without flagging the boundary, your "5-year window" ends up being "5 years of certified data + 1 churning year of provisional records that change between quarterly refreshes."

**Why it happens:**
The SWITRS public-facing tooling (TIMS at UC Berkeley) does NOT visually distinguish provisional from final on a per-record basis — it surfaces both behind the same query interface. Developers reasonably assume "if it's in the dataset, it's stable." It isn't. Per CHP/SWITRS official docs: **3-month minimum delay for current-year inclusion; 12-18 month total lag for full input; provisional → final flip happens after CHP releases the annual report.**

**How to avoid:**
- Store the SWITRS `record_status` (or equivalent provisional/final flag) as a column on every ingested crash row. Do NOT collapse it.
- Quarterly refresh runbook (REQ-quarterly-refresh) MUST diff old-vs-new and write a delta report: "N records flipped provisional→final, M records were silently retracted by CHP." Surface retractions explicitly.
- For the public demo, **lag the routing window by 12 months** (e.g., use 2020-2024 for routing in 2026, even if 2025 partial data is available). Trade recency for stability.
- Document the lag in user-visible disclaimer (see Pitfall 11): "Crash data: California SWITRS, certified through [year]."

**Warning signs:**
- Quarterly refresh changes >2% of "final" records → CHP did a retroactive correction; trust the new data, surface the delta.
- A segment's `crash_norm` flips between green/yellow/red on routine refresh with no real-world cause → you're ingesting churning provisional records.

**Phase to address:**
Phase 1 (crash-data ingest schema design) — the `record_status` column is a one-line schema decision that's expensive to retrofit later. Phase 5 (refresh runbook) — codify the delta-report.

---

### Pitfall 2: Severity-scale code drift between SWITRS old codes (1-4) and MMUCC 5th-edition codes (5-7)

**What goes wrong:**
You write `if degree_of_injury == 2: severity = 'severe'` on a sample year, ship it, and quietly miscount severe injuries from years that use the new MMUCC codes. Per TIMS/CHP: SWITRS post-2016ish uses MMUCC 5th-edition codes 5/6/7 for new injury classifications, while older years use 2/3/4. They are **combined** in TIMS reporting (5+2 → "Suspected Serious Injury"), but raw SWITRS exports contain both code sets — and developers who only test on one year never notice.

This maps directly to the v0.3.0 Phase 7 lesson-learned: **operator labeling-style drift across CVAT splits silently broke fine-tuning** (val P=0.184 R=0.071 but 0 predictions on test). This is the same failure mode at the schema level: a categorical-encoding drift across slices that train metrics don't expose.

**Why it happens:**
- Codebook-reading is incomplete; codebooks are PDFs. The PDF mentions the code-set transition once, mid-document.
- Sample data for development (a single year, often Kaggle-mirrored) shows only one code regime.
- Test split uses the same year as train split → drift is invisible at test time.

**How to avoid:**
- **Schema-level constraint:** `CHECK (severity_tier IN ('fatal','injury','pdo'))` AFTER mapping; the raw SWITRS code goes into a separate `raw_severity_code SMALLINT` column.
- Mapping function lives in one file (`data_pipeline/switrs_severity.py`) with a single explicit mapping table covering BOTH code regimes (1-4 AND 5-7) and an explicit `else: raise ValueError`. Never silently default to PDO.
- Wave-0 RED test (per v0.3.0 lesson): unit test loads two synthetic rows — one with old-code `2`, one with new-code `5` — and asserts both map to `'injury'`. RED until mapping function is written. This test fails loudly if anyone adds new codes without updating the mapping.
- During ingest, log a histogram of `raw_severity_code → severity_tier` mapping counts; refuse to commit if the "unknown code" count > 0.

**Warning signs:**
- Histogram of `severity_tier` for year N looks dramatically different from year N+1 with no real-world cause → mapping bug.
- `crash_norm` on a segment trends downward year-over-year for no operational reason → likely missing the new code regime.

**Phase to address:**
Phase 1 (ingest pipeline). Wave-0 RED test belongs there.

---

### Pitfall 3: Jurisdictional double-counting between SWITRS (state) and LA City open-data (city)

**What goes wrong:**
LA City's open-data collision feed is **derived from SWITRS** plus LAPD's own records. Some crashes appear in both. If you ingest both feeds without dedup, segments near LA-City/state-highway boundaries (where SR-110, SR-2, SR-170, SR-1, SR-27, SR-47 transition between state and city jurisdiction — explicitly called out in LA GeoHub metadata) get **double-counted**, and `crash_norm` on those segments inflates 2x. Routing then steers users away from major arterials for entirely fictional reasons.

**Why it happens:**
- Both feeds use different primary keys (SWITRS `case_id` from CHP, LA City `dr_no` from LAPD) → naive `UNION ALL` doesn't dedup.
- Spatial dedup (same lat/lon) fails because geocoding precision differs between feeds (SWITRS uses postmile + intersection; LA City often uses LAPD-supplied address geocodes).
- The overlap is most concentrated on **the highest-traffic surface streets** that are most relevant to routing.

**How to avoid:**
- **Designate ONE feed as canonical** for each jurisdictional zone. LA City has historically published "Collisions YYYY-YYYY (SWITRS)" datasets that are **already deduplicated** against SWITRS for the LA-City portion — prefer those for inside-city geography. Use raw SWITRS only for outside-LA-City supplemental rows (e.g., crashes on city-of-LA enclaves like West Hollywood, Beverly Hills, Culver City that are within the routing bbox but outside LA City).
- If using both feeds, dedup with: same date (±1 day), same hour-of-day, same lat/lon (±100 m), same severity tier → mark as duplicate, retain the SWITRS record (state-of-record).
- Schema: `crashes (id, source TEXT, source_record_id TEXT, ...)` UNIQUE on `(source, source_record_id)` — this mirrors the v0.3.0 Phase 3 pattern (`(source_mapillary_id, source)` UNIQUE for ON CONFLICT idempotency). Reuse the proven pattern.
- Operator runbook for quarterly refresh MUST include a "boundary segment audit" — pick 5 segments along SR-110 / SR-2 / SR-170 and manually compare crash counts against SWITRS web tools.

**Warning signs:**
- Segments along SR-110 / SR-2 / SR-170 / SR-1 / SR-27 / SR-47 have ~2x the `crash_norm` of comparable arterials with no real-world cause.
- Routing produces visibly weird detours that prefer side-streets over major surface arterials → likely double-counting on the arterial.

**Phase to address:**
Phase 1 (canonical feed decision; schema UNIQUE constraint).

---

### Pitfall 4: Snap-match intersection ambiguity — "which of 4 segments owns a crash at an intersection?"

**What goes wrong:**
A crash geocoded to "Wilshire Blvd & Western Ave" sits at a 4-way intersection where 4 road_segments meet at one pgRouting vertex. A naive nearest-segment join (`ORDER BY ST_Distance LIMIT 1`) assigns the crash to whichever segment has its centroid happens to be closest to the intersection point — usually the shortest segment. Result: short stub segments at intersections accumulate crashes that should be distributed to the through-segments (which is where drivers were actually traveling when the crash occurred). Routing then confidently avoids 30 m of asphalt while sending users along the equally-dangerous through-roads it just chose.

This is the same mechanical failure as v0.3.0 Phase 8: **pgr_ksp's inner SQL evaluated via SPI doesn't use GiST** (the bbox WHERE was a full seq scan). Different mechanism, same shape — naive spatial query produces a "correct-looking" answer that's quietly wrong.

Per published research (Korde 2024, Quebec geocoding study, California police-collision report study): the nearest-segment-by-distance approach systematically misassigns intersection crashes; correct approaches require **conditional logic beyond a simple spatial join** — typically a buffer around intersection vertices, with crashes inside the buffer attributed to all incident segments (proportionally or weighted by approach direction if available).

**Why it happens:**
- PostGIS `<->` distance operator returns the literal nearest segment without semantic awareness of the road network.
- Intersection vertices in pgRouting are zero-dimensional; multi-segment ownership at one point isn't representable in a one-row-per-crash schema.
- Tests use mid-block crashes (where the answer is unambiguous) and never exercise the intersection case.

**How to avoid:**
- **Two-mode snap-match:**
  1. If crash is within `INTERSECTION_BUFFER_M` (recommend 15-25 m) of a pgRouting vertex with degree ≥ 3, attribute the crash **fractionally** to all incident segments (weight = 1/degree, or equal weight at first cut).
  2. Otherwise, attribute to the single nearest segment within `MAX_SNAP_DIST_M` (recommend 25 m). Drop crashes that are > 25 m from any segment (likely off-network: parking lots, private roads, geocoder failures). Log the drop count.
- Schema: `segment_crashes(segment_id BIGINT, crash_id BIGINT, weight NUMERIC)` — fractional weights make `SUM(weight * severity_value)` the per-segment crash score instead of `COUNT(*)`.
- Wave-0 RED tests (per v0.3.0 lesson): build a synthetic 4-way intersection fixture, place a crash AT the vertex, assert all 4 segments get weight 0.25. RED until snap-match handles intersection mode.
- **Inline anti-pattern pin** in `data_pipeline/snap_match.py` header citing Pitfalls A and G v0.3.0-style — the next maintainer will edit this file; the post-mortem belongs there.

**Warning signs:**
- Histogram of crashes-per-segment is bimodal: short stub-segments at intersections have crash counts 5-10x higher than mid-block segments → naive nearest-segment is assigning all intersection crashes to stubs.
- After snap-match, `SUM(crashes_per_segment) ≠ total_crashes_ingested` (or doesn't match modulo the off-network drop count) → silent loss in the spatial join.
- Routing visibly avoids tiny segments at intersections while routing through equally-dangerous through-segments → stub-segment over-attribution.

**Phase to address:**
Phase 2 (snap-match) — the highest-risk single piece of code in the milestone.

---

### Pitfall 5: Fatal-crash overweighting flips routing to absurd detours

**What goes wrong:**
You set severity weights `fatal=100, injury=10, pdo=1` (a common first-cut). Fatal crashes are ~1% of all crashes by base rate. A single fatal crash on a segment now contributes the same score-weight as 100 PDOs. Result: any segment that has had ONE fatal crash in the lookback window — even on a high-traffic arterial that is statistically as safe as its neighbors — gets routed-around. Users see detours that add 10 minutes to avoid one segment. The `crash_norm` distribution is dominated by ~50-100 segments out of ~205,000.

This is locked-weight-design's blind spot: the locked outer weights `0.40·iri_norm + 0.35·pothole_norm + 0.25·crash_norm` assume `crash_norm` is well-calibrated to [0,1]. If the **inner** severity weighting blows up the dynamic range, the outer 0.25 multiplier doesn't save you — `crash_norm` saturates to 1.0 on a few segments and stays near 0 everywhere else. The locked-weight UX is fragile to inner-weight calibration mistakes.

**Why it happens:**
- Severity-of-outcome is conflated with severity-of-causation. A fatal crash often reflects vehicle speed and seatbelt use, not road design.
- Equivalent-fatality units (used in highway-safety academic literature, e.g., 1F = 10 SI = 50 PI) are calibrated for **comparing intersections**, not for setting per-segment routing costs.
- Low base rate + high weight = a few segments dominate the distribution.

**How to avoid:**
- **Normalize severity weights to a bounded crash-score-per-segment that doesn't blow up at low N**, e.g., use a logarithm or smoothed rate: `crash_score = log(1 + Σ severity_weight_i) / max_log` rather than raw weighted count.
- **Cap any single fatal's contribution** to the segment's score (e.g., `min(severity_value, segment_length_km × 5)`) — prevents a single crash on a 30 m stub from saturating.
- **Test against the routing output**, not just the score distribution: pick 5 known-safe arterials, verify they don't get routed-around because of one historical fatal.
- Recommend starting weights from published research (literature converges roughly on `fatal:injury:pdo ≈ 8:3:1` for routing-cost purposes, not the 100:10:1 of academic equivalent-fatality reporting). Document the choice in `RESEARCH.md` with a decision log entry (D-XX).
- **Wave-0 RED test:** load a fixture with 1 fatal on segment A, 100 PDOs on segment B (A and B parallel). Assert that the routing engine picks A or B based on travel-time tie-break, not because A's score saturates to 1.0.

**Warning signs:**
- `crash_norm` histogram: > 50% of segments have `crash_norm = 0`, < 1% have `crash_norm > 0.5`. This means the score is binary, not a gradient.
- A test route comparison shows the "best" route deviates by 5+ minutes for a ride-quality cost difference of < 5 IRI points → fatal-overweighting is dominating.
- One operator-driven manual tour: open the live demo, route between 5 known city-pairs, and ask "does the best route make sense to a local?" — if the answer is "no, it's avoiding [arterial] for no obvious reason," check the fatal-weight calibration first.

**Phase to address:**
Phase 3 (scoring formula update). The Wave-0 RED test belongs there.

---

### Pitfall 6: Recency-decay 5-year cliff produces visible step-changes on the demo

**What goes wrong:**
You implement the lookback as `WHERE crash_date >= NOW() - INTERVAL '5 years'`. On 2027-05-08 at midnight, every crash from 2022-05-07 ages out simultaneously. Segment scores shift overnight; a public demo that worked yesterday now routes differently for users who saw the "old" version. Quarterly refreshes amplify this — the cliff isn't smooth, it's a stair-step.

Worse: a single fatal crash on a low-traffic segment from May 2022 dominates `crash_norm` until exactly 2027-05-07, then disappears. There's no signal-degradation; a single record's contribution goes from 100% to 0% at midnight. Same problem as Pitfall 5 in the time domain.

**Why it happens:**
- A `WHERE date >= cutoff` filter is the simplest implementation and "looks correct" in code review.
- Tests verify the filter excludes old data; they don't verify the score evolution is continuous.
- The only way to see the cliff is to compare snapshots taken on either side of an aging-out event.

**How to avoid:**
- **Exponential decay weight:** for each crash, `weight = exp(-age_in_years / TAU)` with `TAU = 3` years (so a 3-year-old crash weighs 1/e ≈ 37%, a 5-year-old crash weighs ~19%, a 10-year-old crash weighs ~4%). No cliff. Per Hardball Times / EWMA references: this is the standard approach when you want recent-but-not-cliff weighting.
- Choose `TAU` empirically by computing per-segment `crash_norm` at two points in time and verifying the median absolute change quarter-over-quarter is < 10%. If it's > 10%, your decay is too aggressive.
- Soft cutoff: also exclude crashes older than some safety horizon (e.g., 10 years), not for routing reasons but because road geometry changes (new traffic signals, repaving, signage) make old crashes uninformative. The exclusion happens at ingest, not at score-compute, and it's logged.
- **Test:** snapshot `crash_norm` for all segments at T and T+1 day; assert max absolute change < 0.05 for ANY segment. This catches both the cliff and ingest bugs that flip a segment's score overnight.

**Warning signs:**
- A scheduled job (quarterly refresh) causes a segment's `crash_norm` to change by > 0.2 with no new ingested data → either decay isn't being applied or the date column is being interpreted differently after refresh.
- Hard step in score histograms when comparing snapshots from before and after a calendar boundary.

**Phase to address:**
Phase 3 (scoring formula). Decay is part of the score-compute query, not the ingest pipeline.

---

### Pitfall 7: Removing `w_IRI` / `w_pothole` sliders without a backwards-compatible `/route` API silently breaks third-party callers

**What goes wrong:**
You remove the sliders from the frontend AND simultaneously change the `/route` Pydantic model to reject `w_IRI` / `w_pothole` as `extra='forbid'`. Anyone who's bookmarked a `/route` URL, written a script against the API, or screenshotted curl examples in a blog post now gets HTTP 422. Worse, since this app has **no auth and a public API** (per d0ef452), you have no way to identify who's using these fields. The locked-weights decision is correct (CON-route-api § Migration path: "backend ignores them"); the *implementation* of "ignores them" is the trap.

This is the v0.3.0 Phase 4 mistake re-played in API-contract space: **build it / supersede it without updating docs and stale tests**. The audit verdict for v0.3.0 surfaced REQ-user-auth doc-vs-code drift weeks late. If `/route` integration tests still POST `w_IRI=0.7` and they pass because the field is still accepted, the next milestone audit will surface "we silently changed semantics" — which is worse than having broken them loudly.

**Why it happens:**
- Pydantic v2 default behavior for unknown fields is `extra='ignore'`, but ad-hoc model edits can flip to `extra='forbid'` without anyone noticing.
- Tests that POST `w_IRI` keep passing if Pydantic accepts the field; they don't verify the value is actually being honored.
- The "silently ignore" path doesn't generate a log line, so operators never see "user X is still using w_IRI."

**How to avoid:**
- **Explicit Pydantic config:** `model_config = ConfigDict(extra='ignore')` on the request model. Document this choice with an inline comment citing CON-route-api.
- **Add a deprecation warning header** in the response if `w_IRI` or `w_pothole` was present in the request body: `X-Deprecated-Fields: w_IRI,w_pothole` or a `warnings` array in the response JSON. Operators can then `grep` access logs to find lingering callers.
- **Update the existing `/route` integration tests** (in v0.3.0 these accept and pass `w_IRI`/`w_pothole`):
  - One test asserts the request **with** `w_IRI=0.7` returns the **same** route as the request **without** `w_IRI` (semantic confirmation: ignored, not just accepted).
  - One test asserts the deprecation warning header is present when `w_IRI` is sent.
  - One test asserts `extra` fields beyond `w_IRI`/`w_pothole`/the documented set are still rejected (don't open the gate too wide).
- **Update `docs/API.md` (or the OpenAPI schema description) explicitly:** `w_IRI` and `w_pothole` documented as DEPRECATED, accepted-but-ignored, removed in v0.5.0+. This is the doc-update step v0.3.0 missed at the REQ-user-auth supersede commit.
- **REQ-ID hygiene per v0.3.0 lesson 2:** the supersede commit message should reference the locked CON-route-api line ("CON-route-api § Migration path: backend silently ignores w_IRI/w_pothole"). Audits scanning for "remove" / "supersede" then find the doc reference automatically.

**Warning signs:**
- Frontend slider removal lands without a corresponding `docs/API.md` diff in the same PR → doc drift starting.
- `/route` integration test count goes DOWN after the slider-removal PR (vs. staying the same with assertions changed) → coverage regressed silently.
- Production access logs show 0 requests with `w_IRI` field after the cutover → either nobody used the API in the wild OR you broke the silent-ignore (HTTP 422 might be filtered out of the log query).

**Phase to address:**
Phase 4 (API contract + frontend slider removal). The REQ-ID-in-supersede-commit discipline is process, not phase-specific, but Phase 4 is where it matters most.

---

### Pitfall 8: Production deploy: 100k crash rows + GiST index bust the 5 GB Fly volume budget

**What goes wrong:**
You add migration 003 with `CREATE TABLE crashes (...)` and a GiST index on `geom`. On the local dev DB this is ~50 MB. On the live Fly DB with the existing `road_segments` (~205k rows + GiST) and `segment_defects` (~125k rows + GiST), adding ~100k crash rows + a GiST index pushes total volume usage over the 5 GB volume Phase 5 provisioned. Postgres goes read-only on disk-full; the live demo returns 500s. Recovery requires `flyctl volumes extend` (paid, propagation delay) and possibly a forced restart that risks the v0.3.0 Phase 5 **Postgres-recovery-crash-loop** failure mode (which was already hit once during initial migration ordering).

Compounding: the v0.3.0 LESSON-LEARNED states **long DDL on Fly DB must use `flyctl ssh console -C`, NOT `flyctl proxy`** — wireguard timeouts trigger postgres recovery crash loops. CREATE INDEX CONCURRENTLY on 100k rows is a multi-minute operation. Run it via `flyctl proxy` on a flaky link and you're guaranteed to repeat the v0.3.0 Phase 5 disaster.

**Why it happens:**
- Local dev volume is unbounded (host disk); Fly volume is fixed-size and was sized for v0.3.0's data only.
- GiST indexes are larger than B-tree (PostGIS docs: "GiST indexes are typically larger than B-tree indexes"). Index size approaches table size for spatial data.
- Migration ordering: existing migrations 001 (BIGINT) + 002 (Mapillary UNIQUE) are already in production. Migration 003 must apply on top, not from scratch.

**How to avoid:**
- **Phase 5 sizing rehearsal (per v0.3.0 lesson):** before running migration 003 on prod, measure the dev DB size delta from "schema only" to "100k crashes + GiST". Multiply by 1.5 (safety factor for autovacuum bloat + WAL) and verify Fly volume free space ≥ delta. If not, run `flyctl volumes extend` FIRST, then deploy.
- **Migration 003 must be idempotent and safe-to-rerun:** `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, idempotent `ALTER TABLE ADD COLUMN IF NOT EXISTS` for `segment_scores.crash_norm`. If a flaky run leaves partial state, the rerun completes cleanly.
- **Migration ordering test (per v0.3.0 Phase 5 lesson-learned):** start from a fresh DB, apply 001 → 002 → 003 in sequence on a local Docker postgres, verify all migrations apply cleanly. CI runs this on every PR that touches `db/migrations/`. Mirrors the v0.3.0 Phase 1 BIGINT verification pattern.
- **DDL via `flyctl ssh console -C`** — locked anti-pattern. CREATE INDEX explicit, not implicit-via-CREATE-TABLE-WITH-CONSTRAINT. CREATE INDEX CONCURRENTLY where possible (avoids table lock; Postgres docs).
- **Store crashes as one row per crash with one geometry, not one row per (crash, party, victim).** SWITRS hierarchical structure (CRASH/PARTY/VICTIM) is tempting to ingest verbatim, but inflates row count 3-5x. For routing purposes, only the worst-injury severity per crash is needed. Pre-aggregate at ingest.

**Warning signs:**
- `df -h` on the Fly DB volume shows < 1 GB free before deploy → already at risk of disk-full mid-DDL.
- Migration 003 dry-run on local takes > 60s → wireguard tunnel will timeout in production. Pre-stage the table on the DB and add the GiST index in a second SSH session.
- Postgres logs after deploy contain `recovery from WAL` → you triggered the v0.3.0 Phase 5 crash-loop. STOP and follow the locked anti-pattern recovery procedure.

**Phase to address:**
Phase 5 (deploy). Volume sizing decision must precede the migration-write step in Phase 1, but the *enforcement* (the integration test, the CI check) lives in deploy.

---

### Pitfall 9: Public-demo "safer route" claim without legal-grade disclaimer

**What goes wrong:**
The public demo at `https://road-quality-frontend.fly.dev/` currently shows fastest vs. best route side-by-side with no medical/legal disclaimer (because the only "best" claim is "smoother"). Adding crash data shifts the implicit claim to "safer." Per the legal literature surveyed (visionarylawgroup.com, peter-thompson-associates.com, Setareh Law): GPS/routing apps face liability when their product **directly causes harm** by providing "grossly inaccurate or outdated data," "ignoring reports of dangerous routing errors," or **"failing to warn drivers of known hazards."** Disclaimers buried in user agreements provide some protection — but a public demo with no user agreement and no disclaimer offers none.

Additionally: implicit equity concern. Per the Waze-effect literature (StreetLightData, autoevolution): routing apps that direct drivers away from arterials onto residential streets have triggered municipal pushback (Takoma Park, Southern Shores NC). A "safer route" that systematically routes away from historically-crash-heavy roads can disproportionately route through historically-lower-crash neighborhoods — which often correlates with neighborhood demographics. This is the same shape as the v0.3.0 Phase 7 negative: a model that quietly behaves badly along a slice you didn't think to test.

**Why it happens:**
- "Safer route" sounds factually defensible if grounded in real crash data; the claim shifts implicitly without anyone explicitly endorsing it.
- The portfolio narrative ("crash-aware routing") encourages stronger language than the underlying statistical model supports.
- Demo URLs get linked from social media, blog posts, etc., where disclaimers don't propagate.

**How to avoid:**
- **Specific disclaimer copy on the route-finder page** (not in a hamburger menu — visible at the moment of route selection):
  > "Routes labeled 'best' minimize a combined ride-quality score (rough roads + potholes + historical crash density). Historical crash data is from California SWITRS and LA City open data, certified through [year]. This is a research demo, NOT a safety-critical system. Drive according to current conditions, not this map. Crash density does not predict your individual risk."
- **Avoid the word "safer"** in UI copy. Use "lower historical crash density" or "smoother + lower-crash" — descriptive, not predictive.
- Match the v0.3.0 Phase 7 honest-disclosure pattern: just as `DETECTOR_EVAL.md` documents the 0-test-predictions failure mode honestly, the demo should document its limitations on the page itself.
- **Equity audit:** pick 10 routes between high-income / low-income LA neighborhoods (use LAHD income data) in both directions, log fastest vs. best route geometries, manually inspect for systematic detour patterns. Publish findings in `docs/EQUITY_NOTE.md`. Negative is fine; silence is not.
- README + portfolio prose use "crash-aware" not "safer" — protects against the demo being mis-cited on social media.

**Warning signs:**
- Equity audit reveals: best routes from low-income origins systematically detour through higher-income neighborhoods more than the reverse → publish + add to disclaimer, don't ship without acknowledgment.
- Any user-reported "this app told me to drive [unsafe action]" → invokes the "ignored reports of dangerous routing errors" liability prong. Have a contact email + an issue-template ready.

**Phase to address:**
Phase 4 (frontend slider removal — same surface area where disclaimer copy lands) + Phase 6 (public-demo verification, mirrors v0.3.0 Phase 6 pattern). Equity audit is a Phase 6 deliverable.

---

### Pitfall 10: Re-running the v0.3.0 Phase 4 build-then-supersede cycle in v0.4.0

**What goes wrong:**
Phase 4 of v0.3.0 shipped JWT + sign-in modal + demo account, validated end-to-end via 8-scenario UAT, and was unwound by commit `d0ef452` two days later for a public-demo-friction reason that could have been decided in 30 seconds before scoping. ~5 plans of work landed and unlanded.

In v0.4.0, the analogous trap is shipping a feature whose *product framing* hasn't been settled. Most likely candidates:

- **Crash heatmap / markers map layer** (already explicitly out-of-scope per PROJECT.md, BUT product-pull tends to add it back; the v0.3.0 lesson says this happens late and unwinds work).
- **Severity-tier user toggle** ("show me routes that avoid only fatal crashes") — adds slider complexity right after Phase 3 explicitly removed sliders. Discuss BEFORE scoping, not after.
- **"Crash density" data layer disclosed numerically to the user** (e.g., "this route has 12% lower crash density"). Product-decision: do users understand "12% lower" or does it look like false precision and need a confidence interval the model can't actually compute?
- **Re-enabling auth** (the dormant Phase 4 modules are still in tree, env-var-toggleable). If the operator decides the public demo should require sign-up "for analytics," the entire d0ef452 reversal happens twice.

**Why it happens:**
- Phase scoping starts from "what would be cool" instead of "what's the smallest thing that proves the value prop."
- v0.3.0 ran 8 phases / 41 plans / 16 days; the velocity makes "let's just add it" seductive at phase boundaries.
- Operator product-pull happens mid-milestone; if there's no explicit decision-log entry rejecting the addition, it leaks in.

**How to avoid:**
- Per v0.3.0 KEY LESSON 1: **product-decision-before-phase-scoping**. Before Phase 4 starts, write a one-line decision log entry for each ambiguous product question (heatmap? severity toggle? auth?). If the answer is "no for v0.4.0," lock it in PROJECT.md "Out of scope this milestone."
- **D-XX-NEGATIVE contingency clauses** (per v0.3.0 lesson, Phase 7 D-13 pattern): for any phase that ends with an operator UAT, write the "if operator says no, what do we do?" path into the plan BEFORE execution. No improvisation.
- **REQ-ID hygiene at supersede commits** (per v0.3.0 lesson 2): if commit message contains "remove" / "supersede" / "drop", the same diff updates REQUIREMENTS.md and PROJECT.md. Audit gate scans for this. Mirror the ce190d2 fix pattern from v0.3.0.
- **Audit checklist gains a row:** "for any commit message containing 'remove' or 'supersede', does the diff include a corresponding REQ-ID update?" — enforced in milestone-close audit.

**Warning signs:**
- Mid-milestone discussion: "should we also add [thing not in scope]?" → STOP, write a decision-log entry, accept or reject explicitly. Don't say "let's just see."
- Commit message says "remove" / "supersede" / "no longer needed" without a corresponding REQUIREMENTS.md or PROJECT.md update in the same diff.
- Phase X ships and Phase X+1 starts with a discussion of "do we still want feature from Phase X?" → Phase X scoping skipped a product question. Audit the original scoping doc.

**Phase to address:**
Phase 0 (scoping / decision-log writeup) — before any code phase starts. Audit gate at `/gsd-complete-milestone`.

---

## Moderate Pitfalls

### Pitfall 11: Geocoding-precision claims unsupported by the data

**What goes wrong:**
Frontend or docs say "crash data placed accurately to within 5 m." SWITRS geocoding is intersection-coded for ~70% of urban crashes (per California police-collision report study) and postmile-coded for ~30%, with match rates of 86% intersection / 99.8% postmile (overall ~91%). LA City SWITRS-derived feeds inherit this precision. Real precision varies 5 m to 100+ m per crash; quoting "5 m" overstates it.

**Why it happens:** Reading geocoding match-rate (% located at all) as positional accuracy (% within X meters). Different metrics.

**How to avoid:**
- Don't claim a precision number. Describe the source: "Crash locations are geocoded by California SafeTREC TIMS from SWITRS reports; precision is typically intersection-level."
- Store an `geocoding_quality` column from the source feed if available (TIMS exposes a quality flag); use it to weight the snap-match (lower quality → wider buffer).

**Phase to address:** Phase 2 (snap-match) for the column; Phase 4 (frontend) for copy.

---

### Pitfall 12: Compute-scores re-run order leaves stale `crash_norm` if migration ordering is wrong

**What goes wrong:**
Existing `compute_scores.py --source {synthetic|mapillary|all}` (v0.3.0 Phase 3) writes to `segment_scores`. Adding `crash_norm` requires either a column in `segment_scores` or a separate `segment_crash_scores` table. If the new column is added to `segment_scores` but `compute_scores.py` is run with `--source mapillary` (only) without re-running the crash-score compute, `crash_norm` becomes stale relative to `iri_norm` / `pothole_norm`. The /route cost formula then uses stale crash data without anyone noticing.

**Why it happens:** Two pipelines, one shared table, no enforcement that both ran on the same dataset.

**How to avoid:**
- Either: separate `segment_crash_scores` table with its own freshness timestamp, joined at query time with COALESCE. Mirrors the v0.3.0 separation of concerns (segment_defects keeps mapillary/synthetic separate via `source` column).
- Or: extend `compute_scores.py` with `--source crash` and require the operator runbook to run all sources at every refresh.
- Add a `last_computed_at` timestamp column per source; `/route` logs a warning if any source's timestamp is older than 90 days.

**Phase to address:** Phase 3 (scoring formula update).

---

### Pitfall 13: Synthetic-vs-real mode in tests forgotten for crash data

**What goes wrong:**
v0.3.0 has `compute_scores.py --source {synthetic|mapillary|all}` for IRI / pothole. v0.4.0 introduces crashes; if there's no `--source synthetic-crash` mode, every test that needs crash data has to depend on real ingested SWITRS data, and CI breaks the moment the SWITRS feed format changes. v0.2.0's `seed_data.py` with `seed=42` synthetic data was the right pattern; not extending it costs deterministic-test capability.

**Why it happens:** Real-data feels "more realistic"; synthetic feels like a shortcut. Then real data churns.

**How to avoid:**
- Extend `seed_data.py` (or add `seed_crashes.py`) with a `seed=42` synthetic crash generator placing N crashes uniformly over the bbox, with a known severity distribution. Wave-0 RED tests assert known scores given known seed.
- Real-data tests are integration-tier (live DB); synthetic-data tests are unit-tier (in-memory or local Postgres). Don't blur the line.

**Phase to address:** Phase 1 (ingest pipeline) — the synthetic mode is ingest-shaped.

---

### Pitfall 14: Quarterly refresh runbook drifts because it's never executed

**What goes wrong:**
The quarterly refresh runbook is documented but never run end-to-end. Six months later, SWITRS schema changed slightly (new column, renamed field), and the runbook fails. v0.3.0 has 4 deferred operator-runbook walkthroughs (02-HUMAN-UAT, 02/03/05-VERIFICATION) — known carry-forward drag. v0.4.0 adds another runbook to the pile.

**Why it happens:** Operator-runbook walkthroughs are time-boxed to "after the next refresh," and the next refresh is "next quarter," and "next quarter" never arrives.

**How to avoid:**
- **First refresh is part of milestone close**, not deferred. Time-box: 30 minutes. Captures the runbook drift at a moment when the implementation context is fresh.
- Per v0.3.0 lesson 4 (carry-forward UATs become drag): treat the refresh runbook as a v0.4.0 acceptance criterion, not a v0.5.0 problem.
- Schedule a calendar reminder for one refresh + delta-report at +90 days post-milestone.

**Phase to address:** Phase 5 (deploy / operator runbook) — refresh is the deploy concern.

---

### Pitfall 15: pgRouting cost-update semantics — perturbation works for travel time, not for outer-weight changes

**What goes wrong:**
v0.3.0 Phase 8 wired pgr_dijkstra × K with edge-weight perturbation (Yen's-style). The perturbation modifies travel-time-derived weights. Adding `0.25·crash_norm` to the cost formula is straightforward at the SQL level (`cost = travel_time_s + 0.40*iri_norm + 0.35*pothole_norm + 0.25*crash_norm`), but the perturbation magnitude was tuned for travel-time scale. If `crash_norm` is comparable in magnitude to travel-time, the perturbation might produce visually-similar K paths instead of diverse K paths.

**Why it happens:** Perturbation magnitude in v0.3.0 routing.py is hard-coded relative to travel-time scale.

**How to avoid:**
- Profile K-path diversity post-cutover: pick 5 known city-pairs, count distinct edges across the K=5 alternatives, compare to v0.3.0 baseline. If diversity drops > 50%, retune the perturbation.
- Re-cite the v0.3.0 routing.py:272-298 inline anti-pattern pin to include the new pitfall (mirrors the v0.3.0 Phase 8 RESEARCH §8 Pitfalls A and G citation pattern).

**Phase to address:** Phase 3 (scoring) for the formula; Phase 6 (verification) for the diversity profiling.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Single `crashes` table without `record_status` | One less column in migration 003 | Provisional records churn silently quarter-over-quarter; refresh delta-report becomes meaningless | Never — the column is one line of SQL and the v0.3.0 source-tracking pattern (`segment_defects.source`) is precedent |
| Naive nearest-segment snap-match (Pitfall 4) | Single PostGIS query, easy to read | Stub segments at intersections accumulate fictional crashes; routing detours around them | Never for production; OK for a v0.4.0-alpha dev fixture if explicitly tagged WIP |
| Hard 5-year cliff (Pitfall 6) instead of exponential decay | One-line `WHERE` clause | Score discontinuities at calendar boundaries; quarterly refresh shows step changes | Never if the demo is public — exponential decay is also one line |
| Re-using `segment_scores` table for `crash_norm` instead of new table | No join to write | `compute_scores.py --source mapillary` leaves crash_norm stale; no per-source freshness tracking (Pitfall 12) | OK if `--source crash` is added at the same time AND a `last_computed_at` column gates use |
| Skipping "label all eval-style fixtures in one pass" for crash-snap-match test data | Faster fixture creation | Operator labeling-style drift across fixtures (Phase 7 v0.3.0 lesson redux) | Never — single operator, single session, per v0.3.0 KEY LESSON 3 |
| Skipping `flyctl ssh console -C` for migration 003 | Convenience of `flyctl proxy` | Wireguard timeout → Postgres recovery crash loop (locked v0.3.0 anti-pattern) | Never. Locked. |
| Removing `w_IRI` / `w_pothole` from Pydantic model (`extra='forbid'`) | Cleaner OpenAPI schema | Existing third-party callers get HTTP 422; breaks CON-route-api § Migration path | Never — silently-ignore is the locked contract per PROJECT.md |
| "Safer route" UI copy without disclaimer | More compelling marketing | Liability exposure per GPS-app caselaw; doesn't match what the model actually does | Never on a public demo without the legal-grade disclaimer (Pitfall 9) |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| SWITRS download (CHP web tool, not API) | Treating it as a stable feed; relying on column order | Quarterly export with column-by-name mapping; the codebook (PDF) is authoritative on field names |
| TIMS geocoding download | Assuming a single "lat/lon" column maps cleanly | TIMS exposes `point_x`/`point_y` (state-plane) AND `latitude`/`longitude`; never mix; verify SRID |
| LA City Open Data (Socrata-backed) | Querying without `$where` filters → multi-MB JSON | Socrata SODA API with `$where=year_acc>=2020`; respect rate-limits |
| LA City GeoHub SWITRS-derived collisions | Treating as raw SWITRS (it's pre-processed) | Read GeoHub metadata explicitly: it's deduped against SWITRS for LA-City portion only; supplement with raw SWITRS for outside-city LA-bbox geography |
| pgRouting + new cost column | Adding `crash_norm` to the SELECT inside `pgr_dijkstra` SQL string | Per v0.3.0 Phase 8 lesson: SPI doesn't use GiST. Pre-filter into temp table FIRST (with bbox WHERE on the outer query, btree on `source`/`target` of temp table), then `pgr_dijkstra` against the temp table |
| Mapillary ingest reuse for crash workflow | Trying to shoehorn `ingest_mapillary.py` to do crashes | Don't. Different shape (crashes are points, not images). Reuse the `(source_record_id, source)` UNIQUE pattern (Phase 3 D-decision); reuse the host-venv operator pattern (`/tmp/rq-venv` per MEMORY); do NOT reuse the YOLO-snap-match loop |
| Fly.io migration 003 deploy | `flyctl proxy` + `psql` for long DDL | Locked anti-pattern: `flyctl ssh console -C "psql ..."` only |
| GitHub Actions deploy.yml | Skipping migration step for crash table | New step: `flyctl ssh console -C "psql -f /app/db/migrations/003_crashes.sql"` after backend deploy, before frontend deploy (so the schema change lands before the frontend routes are exposed) |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| GiST scan on large bbox in scoring pipeline | `compute_scores.py` runtime > 10 min on full LA | Pre-filter to `road_segments` already-in-bbox via outer query; `crashes` GiST + `segment_id` btree (mirrors Phase 8 temp-table pattern) | At full-LA scale (~205k segments + ~100k crashes); not at DTLA bbox |
| Recompute crash score on every `/route` request | First-request latency creeps up post-cutover | `crash_norm` is precomputed in `segment_scores` (or `segment_crash_scores`); `/route` only reads | Always at scale; v0.3.0 cache layer covers single-instance burst |
| Cache key forgets to include "crash data version" | Routes served from cache after refresh point at stale geometry | Cache key includes `crash_data_refreshed_at` quarterly bucket; full cache flush on refresh runbook | After every quarterly refresh until cache TTL expires |
| `route_requests` audit-log table grows unbounded | Postgres VACUUM slows; eventual disk-full | Per v0.3.0 CONCERNS.md (already noted): retention policy, index on timestamp, scheduled VACUUM ANALYZE | At ~10M rows; current rate ~150 req/day, ~8 months to threshold post-public-demo if usage grows |
| pgr_dijkstra perturbation loses diversity post-crash-cost-add | K=5 alternatives look ~identical | Post-cutover diversity profile (5 city-pairs, distinct-edge count); retune perturbation magnitude if dropped (Pitfall 15) | After scoring-formula change; not catchable by unit tests |

---

## Security / Privacy Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Storing SWITRS `case_id` (CHP report number) in plaintext | Re-identification: `case_id` + date + LAPD page lookup → individual victim record | The numeric ID is technically not PII, but combined with date+geography it's identifying. Either use a hash, or document the threat in `docs/PRIVACY.md` and accept it (the data is already public via SWITRS, but our routing app aggregates it more accessibly) |
| Exposing per-crash geometry on a public `/crashes` endpoint | Inverse re-identification at low-density (rural LA bbox) per Sciencedirect re-identification studies (93% unique with 4 spatiotemporal points) | Don't expose per-crash. Aggregate to per-segment `crash_norm` (already the design). If a debug endpoint is needed, gate it behind auth (re-enable Phase 4 dormant auth via `AUTH_ENABLED=true`) |
| Surfacing crash detail in `/segments` GeoJSON properties | Same as above; bypasses the aggregation by leaking individual records | `/segments` returns `crash_norm` only, never per-crash records. Wave-0 RED test: assert `crashes` key is NOT in `/segments` response JSON |
| CORS open to any origin for `/crashes` | If a `/crashes` endpoint exists, hostile origin can scrape the whole dataset | Per v0.3.0 Phase 5: env-driven CORS, never `*` in prod. Keeps. |
| Re-identification via a single fatal in a low-density block | Single fatal in a residential block → news article + date → individual victim | The crash-score-saturation fix (Pitfall 5: log-transform / cap) also acts as a privacy fix — a single record contributes a bounded amount, not a saturating amount. Two-birds-one-stone. |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Removing sliders without explaining why | Returning users see "missing" UI; assume regression | One-time changelog modal on first visit post-cutover: "We replaced manual weighting with a fixed combination of road quality + crash history; max-extra-minutes still controls how much detour you'll accept." |
| Showing same route as "fastest" AND "best" with no explanation | Users think the app is broken | Render the "they're the same" case as a single highlighted route + a note: "On this trip, the fastest route is also the best by our combined score — no detour needed." |
| Coloring segments by crash density only without combining IRI / pothole signals | UI suggests crash data is the dominant factor | Segment color stays the locked combined cost (per PROJECT.md: "segment colors continue to encode the locked cost") — don't add a "crash heatmap" toggle (already out-of-scope per PROJECT.md, but UX pull will tempt it; see Pitfall 10) |
| Rendering crash data with red color (universally "danger") | Anchors users to a "this segment is dangerous" interpretation that's stronger than the model supports | Use color ramp matched to existing IRI / pothole palette; don't introduce a new red-for-crashes hue |
| Disclaimer hidden in footer | Doesn't propagate to the "I clicked best route, here's my path" moment | Disclaimer appears next to the route comparison, at the moment of decision (Pitfall 9 implementation) |

---

## "Looks Done But Isn't" Checklist

Verification gate items that look like they pass at first glance but commonly hide regressions.

- [ ] **SWITRS ingest:** Pipeline ingests N rows successfully — verify N matches the expected row count from a SWITRS web-tool query for the same year/bbox (off-by-one on date-range filters is endemic).
- [ ] **Severity mapping:** All `severity_tier` values present in dist — verify both old-codes (1-4) AND new-codes (5-7) appear in the input set; if input is one year only, mapping is undertested (Pitfall 2).
- [ ] **Snap-match:** All ingested crashes assigned to segments — verify `SUM(weight) ≈ crashes_ingested - off_network_drops`; if "≈" is "way less than," fractional weights are wrong (Pitfall 4).
- [ ] **Score distribution:** `crash_norm` looks "reasonable" — verify ≥ 50% of segments are in the 0.05-0.5 range; if 95% are at 0 and 5% are at 1, fatal-overweighting (Pitfall 5).
- [ ] **Decay:** Recent crashes weighted more — verify a snapshot diff at T vs. T+1d shows max change < 0.05 per segment; cliff (Pitfall 6) shows up here.
- [ ] **API:** `/route` accepts `w_IRI` / `w_pothole` without 422 — verify it returns the SAME route with and without those fields (semantic ignore, not just accepted; Pitfall 7).
- [ ] **API:** `/route` rejects truly-extra fields — verify a request with `evil_field: true` returns 422 (didn't open the gate too wide).
- [ ] **Migration 003:** Applies cleanly on top of 001+002 — verify on a fresh local Postgres, sequence 001→002→003; deploy gate (Pitfall 8).
- [ ] **Migration 003:** Idempotent — verify a second run on the same DB is a no-op (no duplicate-key errors).
- [ ] **Volume sizing:** `df -h` on Fly DB volume shows ≥ 1.5× the expected post-deploy size — pre-deploy gate (Pitfall 8).
- [ ] **Disclaimer:** Visible at the moment of route selection, not just in a footer — Pitfall 9.
- [ ] **Equity audit:** 10 cross-neighborhood routes inspected manually — `docs/EQUITY_NOTE.md` updated with findings (Pitfall 9).
- [ ] **Quarterly refresh runbook:** Executed once end-to-end before milestone close — not deferred (Pitfall 14, v0.3.0 lesson 4).
- [ ] **Doc-vs-code:** `docs/API.md` updated in the same diff as the slider-removal commit — REQ-ID hygiene (Pitfall 7 + Pitfall 10, v0.3.0 lesson 2).
- [ ] **Audit gate:** Milestone-close audit script scans for "remove" / "supersede" commits and verifies REQUIREMENTS.md update — Pitfall 10.

---

## Recovery Strategies

When pitfalls occur despite prevention.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Pitfall 2 (severity-code drift discovered post-deploy) | LOW | Update mapping table + rerun `compute_scores.py --source crash`; no schema change. ~30 min. |
| Pitfall 3 (jurisdictional double-count) | MEDIUM | Identify duplicates by (date, lat/lon, severity); deduplicate in place via DELETE. Rerun compute. ~1 hr. |
| Pitfall 4 (intersection ambiguity surfaced after deploy) | HIGH | Truncate `segment_crashes`, fix snap-match logic, rerun ingest. ~3 hr. Mostly compute time. |
| Pitfall 5 (fatal overweighting flips routing) | LOW | Tune severity weights in `compute_scores.py`, rerun. ~15 min. |
| Pitfall 6 (cliff observed in production score distribution) | LOW | Switch from `WHERE date >= cutoff` to exponential decay in score-compute SQL, rerun. ~15 min. |
| Pitfall 7 (API contract regression — third-party callers get 422) | HIGH | Rollback the affected commit + Pydantic config edit, redeploy, post-mortem. The "we silently ignore" semantic is the locked contract; restore it. ~1 hr if caught fast, much higher in operator-trust cost. |
| Pitfall 8 (Fly volume disk-full mid-migration) | HIGH | `flyctl volumes extend` (paid + propagation delay); restart Postgres carefully (avoid v0.3.0 Phase 5 crash loop); re-attempt migration 003 via `flyctl ssh console -C`. 30 min - 4 hr depending on Postgres-recovery state. |
| Pitfall 9 (liability claim from "safer route" without disclaimer) | UNKNOWN-but-bad | Take down the public demo; add disclaimer; relaunch. Reputational cost > engineering cost. |
| Pitfall 10 (Phase X build-then-supersede) | MEDIUM | Per v0.3.0 d0ef452 + ce190d2 pattern: write the supersede commit + REQUIREMENTS.md + PROJECT.md updates in the same diff. Audit at milestone close. |

---

## Pitfall-to-Phase Mapping

How v0.4.0 phases should address these pitfalls. (Phase numbers tentative; the roadmap LLM agent may reorder.)

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1: SWITRS recency cliff | Phase 1 (ingest schema) | `record_status` column exists; quarterly refresh delta-report runs |
| 2: Severity code drift | Phase 1 | Wave-0 RED unit test loads both code regimes; mapping table covers both |
| 3: Jurisdictional double-count | Phase 1 | UNIQUE on `(source, source_record_id)`; boundary-segment audit on 5 SR-* segments |
| 4: Intersection snap ambiguity | Phase 2 (snap-match) | Synthetic 4-way intersection fixture; assert all 4 segments get fractional weight |
| 5: Fatal overweighting | Phase 3 (scoring) | Score histogram smoke test; fixed-route inspection on 5 known-safe arterials |
| 6: Recency-decay cliff | Phase 3 | T vs. T+1d snapshot diff < 0.05 per segment |
| 7: API contract drift | Phase 4 (frontend + API) | Integration test asserts same-route-with-or-without `w_IRI`; deprecation warning header present; `docs/API.md` updated in same diff |
| 8: Fly volume / migration ordering | Phase 5 (deploy) | Pre-deploy `df -h` ≥ 1.5× delta; CI runs 001→002→003 fresh; `flyctl ssh console -C` for DDL |
| 9: Public-demo ethics | Phase 4 + Phase 6 (public-demo verification) | Disclaimer copy land; equity audit `docs/EQUITY_NOTE.md` |
| 10: Build-then-supersede cycle | Phase 0 (scoping) + audit gate | Decision-log entries; supersede-commit-includes-REQ-update audit |
| 11: Geocoding-precision claims | Phase 4 (frontend copy) | UI / docs avoid "5 m" precision claims |
| 12: Stale `crash_norm` from selective rerun | Phase 3 (scoring) | `last_computed_at` per source; `/route` warning on staleness > 90d |
| 13: Synthetic-vs-real mode for tests | Phase 1 (ingest synthetic mode) | `seed_crashes.py --seed 42` produces deterministic fixtures |
| 14: Refresh-runbook drift | Phase 5 + milestone close | Refresh executed once before close (not deferred) |
| 15: pgr perturbation post-formula-change | Phase 3 + Phase 6 | K-path diversity profile vs. v0.3.0 baseline; retune if drop > 50% |

---

## Sources

### Authoritative (HIGH confidence)

- [TIMS — Transportation Injury Mapping System (UC Berkeley SafeTREC)](https://tims.berkeley.edu/help/SWITRS.php) — SWITRS codebook, victim-degree-of-injury fields, MMUCC 5th-edition transition (codes 5/6/7 vs. legacy 2/3/4)
- [SWITRS Codebook PDF (Aldhous mirror of CHP)](https://peteraldhous.com/Data/ca_traffic/SWITRS_codebook.pdf) — full field-name and value enumeration
- [California Highway Patrol — SWITRS](https://www.chp.ca.gov/programs-services/services-information/switrs-statewide-integrated-traffic-records-system/) — provisional-vs-final certification cycle
- [LA City GeoHub — Collisions 2014-2019 (SWITRS)](https://geohub.lacity.org/datasets/66d96f15d4e14e039caa6134e6eab8e5) — jurisdictional metadata calling out SR-110/SR-2/SR-170/SR-1/SR-27/SR-47 boundary cases
- [LA City Open Data — Traffic Collision Data 2010-Present](https://data.lacity.org/Public-Safety/Traffic-Collision-Data-from-2010-to-Present/d5tf-ez2w/data) — Socrata-backed feed
- [PostGIS — Spatial Indexing (workshops)](http://postgis.net/workshops/postgis-intro/indexing.html) — GiST index size + memory characteristics
- [PostGIS — Spatial Joins (workshops)](https://postgis.net/workshops/postgis-intro/joins.html) — `ST_Intersects` / `ST_DWithin` / `ST_Distance` semantics for crash-to-segment matching
- [ScienceDirect — Privacy risk of transportation location-based data: Re-identification and de-anonymization](https://www.sciencedirect.com/science/article/abs/pii/S0968090X25004991) — re-identification rates from spatiotemporal points
- [PMC — The risk of re-identification remains high even in country-scale location datasets](https://pmc.ncbi.nlm.nih.gov/articles/PMC12459646/) — 93% unicity with 4 points

### Verified secondary (MEDIUM confidence)

- [Korde 2024 — When Simple Spatial Join Does Not Work? Assigning Speed Limits to Crash Points](https://medium.com/@milad.kordeh/when-simple-spatial-join-does-not-work-755f0353cf33) — intersection-buffer pattern for crash-to-segment attribution
- [ScienceDirect — Geocoding Police Collision Report Data From California (Comprehensive Approach)](https://researchgate.net/publication/40811935_Geocoding_Police_Collision_Report_Data_From_California_A_Comprehensive_Approach) — 99.8% postmile / 86% intersection match rate
- [ScienceDirect — Safe route-finding: A review of literature and future directions](https://www.sciencedirect.com/science/article/abs/pii/S0001457522002512) — 8% travel-time increase / 23% crash-likelihood reduction tradeoff
- [Hardball Times — The Math of Weighting Past Results](https://tht.fangraphs.com/the-math-of-weighting-past-results/) — exponential vs. linear decay tradeoffs
- [Wikipedia — Exponential smoothing](https://en.wikipedia.org/wiki/Exponential_smoothing) — EWMA formulation for recency weighting
- [Visionary Law Group — Car Accident Caused by GPS](https://visionarylawgroup.com/car-accident-caused-by-gps/) — liability prongs for routing apps (grossly inaccurate data, ignored hazard reports)
- [Peter Thompson Associates — When GPS Causes a Crash](https://www.peter-thompson-associates.com/news/gps-accidents/) — disclaimer-as-defense doctrine
- [StreetLightData — The Waze Traffic Effect](https://www.streetlightdata.com/waze-traffic-effect-4-steps-for-neighborhoods-cities-to-fight-back/) — neighborhood-routing externalities
- [autoevolution — Waze Asked to Stop Providing Drivers With Traffic Shortcuts](https://www.autoevolution.com/news/waze-asked-to-stop-providing-drivers-with-traffic-shortcuts-because-of-obvious-reasons-215490.html) — municipal pushback on routing decisions

### Internal (HIGH confidence — project archive)

- `/Users/hratchghanime/road-quality-mvp/.planning/PROJECT.md` — locked CON-route-api § Migration path; locked v0.3.0 anti-patterns
- `/Users/hratchghanime/road-quality-mvp/.planning/RETROSPECTIVE.md` — six v0.3.0 KEY LESSONS (Phase 4 supersede; doc-drift; labeling-style; pgr_ksp SPI; flyctl ssh; Phase 7 negative)
- `/Users/hratchghanime/road-quality-mvp/.planning/milestones/v0.3.0-MILESTONE-AUDIT.md` — REQ-user-auth doc-drift remediation pattern (the ce190d2 fix)
- `/Users/hratchghanime/road-quality-mvp/.planning/codebase/CONCERNS.md` — `route_requests` unbounded growth, in-memory cache no-persistence, hardcoded LA viewbox, no query timeout (existing-code traps that v0.4.0 mustn't worsen)

---

*Pitfalls research for: v0.4.0 Crash-Aware Routing — adding crash data + crash-aware routing to road-quality-mvp on top of the v0.3.0 production deploy.*
*Researched: 2026-05-07*
