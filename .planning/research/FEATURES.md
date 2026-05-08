# Feature Research

**Domain:** Crash-aware urban routing (subsequent milestone — adding crash data as a third routing-cost factor on top of v0.3.0 IRI + pothole routing)
**Researched:** 2026-05-07
**Confidence:** HIGH for table-stakes/anti-features (multiple corroborating sources: FHWA HSM, LADOT Vision Zero, Waze, HERE, Mapbox); MEDIUM for specific numeric thresholds (EPDO weights vary by jurisdiction); MEDIUM for time-of-day decay (research-grade, not standard product practice yet).

---

## Scope Note for Roadmap Authors

The user has **locked** several decisions for v0.4.0 that pre-resolve research questions:

- **Severity tiering**: three-tier fatal/injury/PDO (no KABCO five-tier expansion)
- **Time scope**: 5-year historical aggregate, quarterly refresh (no real-time, no per-hour)
- **Locked weights**: `0.40·iri + 0.35·pothole + 0.25·crash` (sliders REMOVED except `max_extra_minutes`)
- **No separate crash visualization layer** (segment color encodes the locked composite cost)
- **Data sources**: SWITRS/TIMS + LA City open-data

Features below are categorized **with these locks already applied**. Anything that would re-open a locked decision is flagged Anti-Feature regardless of how well it scores elsewhere. Categories are tagged `[Ingest] / [Scoring] / [UI] / [Operator]` for downstream phase-mapping.

---

## Feature Landscape

### Table Stakes (Users Expect These for a Credible Crash-Aware Demo)

Missing any of these makes the v0.4.0 demo feel either incomplete or scientifically suspect to a Vision Zero / transportation-engineering audience.

| # | Feature | Category | Why Expected | Complexity | Notes |
|---|---------|----------|--------------|------------|-------|
| T1 | **Three-tier severity weighting (fatal / injury / PDO) using EPDO-style multipliers** | [Scoring] | EPDO is the FHWA HSM-blessed approach for combining frequency + severity into one number. Every Vision Zero HIN methodology in use today (LA, SF, Boston, Philly) does this. Without it, a single fender-bender counts the same as a fatality. | LOW | HSM defaults: fatal α=10–12, injury β=3–5, PDO=1. Massachusetts variant collapses fatal+injury into 21 vs PDO=1 to avoid "chasing fatals." Recommend HSM defaults (fatal=10, injury=5, PDO=1) — well-documented, defensible, no parameter tuning required. |
| T2 | **5-year historical aggregation window** | [Ingest] | Vision Zero Network and FHWA both recommend ≥5 years to smooth random year-to-year variation. LA's HIN itself uses 5-year windows (2009–2013, then 2012–2016). Anything shorter triggers regression-to-the-mean bias. | LOW | User decision already locks this. Implementation: `WHERE crash_date >= NOW() - INTERVAL '5 years'` in ingest. Document in operator runbook why <5y windows are rejected. |
| T3 | **Spatial snap-match of crash points to road segments** | [Ingest] | SWITRS/TIMS publishes crashes as lat/lon points. To produce a per-segment cost component, you must associate each point with exactly one `road_segments.id`. This is the load-bearing data join. | MEDIUM | Standard PostGIS pattern: `ST_ClosestPoint` + `ST_Distance` with a tolerance (typically 15–25 m for urban). Order of operations: filter by bbox → ST_DWithin candidate set → pick min-distance segment → record offset for QA. |
| T4 | **Per-mile (length) normalization for segments** | [Scoring] | HSM section 3 — segment crash rates are crashes per **MVMT** (million vehicle-miles traveled); intersection rates are per **MEV** (million entering vehicles). Without length normalization, a 2-mile segment with 4 crashes looks worse than a 0.05-mile segment with 3 crashes, but the short segment is the real hotspot. | LOW | We don't have AADT (traffic volume), so true rate-per-MVMT is out. **Compromise:** `crash_norm = EPDO_weighted_count / segment_length_km`, normalized 0–1 against the LA-wide percentile distribution. Document the limitation honestly: "exposure-adjusted via length only; AADT integration deferred." |
| T5 | **0–1 normalization compatible with existing `iri_norm` / `pothole_norm`** | [Scoring] | The locked formula `0.40·iri + 0.35·pothole + 0.25·crash` only makes sense if all three terms live on the same scale. v0.3.0's iri_norm and pothole_norm both clamp to [0,1] via min-max or percentile. | LOW | Use the **95th-percentile cap** approach (matches v0.3.0 `iri_norm` semantics): `crash_norm = min(1.0, raw_score / p95(raw_score))`. Capping at p95 (not max) prevents one outlier corridor from compressing the whole distribution. |
| T6 | **Segments with zero crashes get `crash_norm = 0`, NOT NULL** | [Scoring] | Most LA segments will have zero historical crashes — that's the long tail of residential streets. NULL would either crash pgRouting math or, worse, propagate as a "missing" warning. Zero is the honest value: "no observed crashes in the window." | LOW | DB default in migration: `crash_norm REAL NOT NULL DEFAULT 0`. Still write a row for every segment in the LA bbox so percentile math has a complete denominator. |
| T7 | **Quarterly refresh runbook with idempotent re-ingest** | [Operator] | SWITRS publishes monthly; TIMS geocodes with a few-month lag. A demo that's frozen at one date in 2026 loses credibility within a year. Quarterly is the cadence LADOT, NYCDOT, and SFMTA all publish on. | LOW | Pattern from v0.3.0 Mapillary ingest: `ON CONFLICT DO NOTHING` on `(switrs_case_id, source)` UNIQUE. Document: download → stage → spatial-snap → recompute `crash_norm` → recompute `compute_scores.py` → tag commit. |
| T8 | **Legend disclosure showing data source, vintage, and "based on N crashes"** | [UI] | Every Vision Zero dashboard (LA GeoHub, SF, Philly) prominently labels the data window and source. Users — especially journalists or city staff — will not trust a segment color until they know what fed it. | LOW | Add a small "About the data" caption on the map: "Crashes 2021–2025 (SWITRS via TIMS, n=X); refreshed YYYY-MM-DD." Two lines of footer text + one config constant. |
| T9 | **Backwards-compatible `/route` API silently ignoring removed slider params** | [Scoring] | Users (and bookmarks) may still POST `w_IRI=0.5, w_pothole=0.5`. Returning a 422 validation error breaks the existing demo URL contract. | LOW | User decision already locks this. Pydantic model: keep fields with `default=None`, log a single-line "deprecated weight ignored" debug message, do not raise. |
| T10 | **Liability disclaimer in UI footer** | [UI] | This is the single highest-litigation-risk milestone of the project. A 2013 California ruling (*Rosenberg v. Google*) confirmed mapping providers carry residual liability when a recommended route causes harm. Every navigation product (Waze, Google, HERE, Mapbox) has explicit terms-of-use language. | LOW | One sentence: "Routing is informational only; safety depends on driver behavior, weather, and current conditions. Crash data reflects historical incidents and does not predict future risk." Display once on map page, link to fuller terms. |

### Differentiators (Set This Demo Apart from Generic Routing)

Features not strictly required, but each meaningfully advances "credible crash-aware demo." Choose 1–2 that fit the milestone budget.

| # | Feature | Category | Value Proposition | Complexity | Notes |
|---|---------|----------|-------------------|------------|-------|
| D1 | **Route-level summary: "this route passes N crash-prone segments (top decile)"** | [UI] | Concretizes the abstract `crash_norm` for the user. Comparable to Waze's "crash history alerts" and HERE's incident-count summaries. The user already gets a fastest-vs-best route comparison; adding "best route avoids 4 high-crash segments fastest passes through" makes the value visible. | LOW–MEDIUM | Compute on backend during route response: `count(segments WHERE crash_norm > p90 AND segment_id IN route)`. Avoid naming intersections (see Anti-A1). Phrasing: "passes N crash-prone segments" not "passes 3 fatal-crash sites." Treat as a **secondary** metric — the primary is still time + smoothness. |
| D2 | **Empirical Bayes (EB) shrinkage for low-count segments** | [Scoring] | FHWA HSM §4 names EB the gold-standard hotspot method specifically because it shrinks short-history estimates toward a population mean, defeating regression-to-the-mean bias. A segment with 0 crashes in 5 years on a 30-mph residential street should score similarly to its peers, not as a "perfect-safety" outlier. | MEDIUM–HIGH | Requires a Safety Performance Function (SPF) — typically a negative binomial regression of crashes vs. AADT and segment length. Without AADT, a simplified variant: shrink toward the mean of segments in the same OSM `highway=` class (`residential`, `secondary`, etc.). Honest middle ground: implement the simplified shrinkage, label it "SPF-lite," document the gap. |
| D3 | **Length-aware crash density visualization (segment color encodes density per km, not raw count)** | [UI] | This is already the user's locked decision (`crash_norm` is per-km), but worth calling out: the visual story "long arterials look dangerous" is a known KDE-on-network artifact. Per-km normalization is what makes the colors honest. | LOW | Already covered by T4. Listed here so the roadmap author doesn't accidentally swap to raw counts later. |
| D4 | **Operator-only crash-data freshness badge in admin/health endpoint** | [Operator] | Lets the operator know at a glance if the quarterly refresh slipped. Pattern: extend `/health` JSON with `{"crash_data_vintage": "2026-Q1", "days_since_refresh": 47}`. | LOW | Single SQL: `SELECT max(crash_date) FROM crashes`. Public users don't need this; gate it behind the same future `AUTH_ENABLED` toggle that's already latent in the codebase. |
| D5 | **Pre-computed `crash_norm` materialized at ingest time, not per-route** | [Scoring] | v0.3.0 Phase 8 demonstrated that pgr_ksp's inner SPI didn't use the GiST index. A per-route crash join would re-introduce that class of bug. Bake `crash_norm` into `road_segments` (or a 1:1 join table) so the cost calc is column-only. | LOW | Migration: `ALTER TABLE road_segments ADD COLUMN crash_norm REAL NOT NULL DEFAULT 0` (or extend `segment_scores`). Recompute via `scripts/compute_scores.py` after each refresh — same pattern as IRI/pothole today. |
| D6 | **Severity breakdown tooltip on segment hover (when zoomed in)** | [UI] | When a power-user hovers a red segment, showing "5y: 2 fatal, 8 injury, 14 PDO" justifies the color without needing them to trust a black-box score. Vision Zero practitioners will expect this; casual users will ignore it. | LOW–MEDIUM | Backend: extend `/segments` GeoJSON properties with `crash_breakdown: {fatal:2, injury:8, pdo:14}`. Frontend: react-leaflet popup. Avoid showing this as default labels — only on click/hover. |
| D7 | **Honest "data sparsity" indicator for segments with <N crashes in window** | [UI/Scoring] | Differentiates this demo from a glossy-but-misleading product. Industrial-strength version of the disclaimer: shade segments with insufficient data (e.g., <5y of inclusion in dataset, or new construction) differently — say, gray-with-stripe — instead of green. | MEDIUM | Add `data_quality_flag` column. Frontend: third color category beyond green/yellow/red. Be careful: easy to over-flag and end up with a sea of gray. |

### Anti-Features (Tempting but Should NOT Be Built)

These are commonly requested when stakeholders see the milestone described, but each carries a specific risk. Each entry includes the alternative.

| # | Anti-Feature | Why Tempting | Why Problematic | Alternative |
|---|--------------|--------------|-----------------|-------------|
| A1 | **Naming and shaming intersections ("Worst intersection in LA: 6th & Main")** | Makes great press and looks "data-driven." | (1) Property-value / neighborhood-defamation lawsuits — at least one similar case exists for crime-mapping apps. (2) Counterproductive: high-crash intersections often correlate with high-traffic intersections, so the "worst" is often "busiest" — bad signal. (3) v0.4.0 explicitly does NOT do per-intersection analysis (segment-level only). | Show segment color only. Tooltip language: "above-typical historical incidents in this area," NEVER "X-th most dangerous intersection." |
| A2 | **Real-time crash incident overlay (Waze-style "crash ahead")** | The phrase "crash-aware" makes users assume real-time. Waze does this and it's the feature people remember. | (1) Out of scope — user locked "historical aggregate, quarterly refresh." (2) Requires either a crowd-source feed (privacy + abuse vectors) or a paid HERE/TomTom feed. (3) Brings live-incident liability — if you display "crash ahead" and it's wrong, you steered the user. | A **prominent label** clarifying "historical risk, not live conditions." Defer real-time to a v0.5.0+ with proper data partner. |
| A3 | **Per-hour or per-day-of-week crash weighting ("nighttime mode")** | Research is clear that crash risk is higher at night and on weekends, especially for younger drivers. Sounds like a smart feature. | (1) SWITRS/TIMS aggregate quality is poor at the hour level — many crashes have only date + approximate time. (2) Adds a dimension to the cost function that competes with the locked scalar weights. (3) **Litigation risk**: if a "safe at 2am" route turns out unsafe, you've made a falsifiable claim. (4) Industry: no production navigation product publishes this; it's research-grade only. | Document as future work. Emit a single overall `crash_norm` and let the user infer that any historical hotspot is "more risky at night" via general knowledge. |
| A4 | **Predictive crash-probability ML model** | "We have crash data + road features — let's train a model to predict where the next crash will happen." | (1) Far out of scope. (2) Inevitable false-positive flagging that enters the "redlining" zone — predicting more crashes in lower-income neighborhoods because that's where historical reporting is denser. (3) The honest version is the EPDO + EB approach (D2), which has decades of FHWA validation. ML claims of "novel prediction" are usually just dressed-up Empirical Bayes. | EPDO with optional EB shrinkage (D2). Statistical, defensible, no neural net. |
| A5 | **User-visible weight sliders for crash term** | Symmetric with v0.3.0's IRI/pothole sliders. "Why remove sliders for two factors and keep one?" | User decision: ALL sliders except `max_extra_minutes` are being removed. Keeping a crash slider re-opens that decision and forces the team to explain "why is crash special?" Users tend to crank it to 1.0 to feel virtuous, generating impossible routes. Sliders also imply scientific tunability the system doesn't have (the 25% allocation reflects data-quality, not user preference). | Locked 0.25 weight. Period. |
| A6 | **A separate "crash heatmap" toggle layer** | Vision Zero dashboards have one. Looks impressive. | User decision explicitly excludes this — segment color ALREADY encodes the locked composite cost, so a separate layer would visualize the same data twice with different normalization. Two encodings of the same field is a known UI anti-pattern (users assume they mean different things). | One source of truth: the segment color from the locked composite. |
| A7 | **Comparative ranking ("This route is 23% safer than the fastest")** | Concrete and quotable. | (1) Implies a precision the data doesn't support — "safer" is not measurable from historical aggregate alone (you'd need exposure data). (2) Falsifiable: the user takes the "safer" route and crashes; you've made an actionable claim. (3) Crosses from "informational" to "advisory" in liability terms. | "This route avoids N high-crash-rate segments" — counts a fact, doesn't claim a probability. |
| A8 | **Crowd-sourced crash reporting from users** | Closes the "real-time" gap, fills LA-City-data lag. | Massive moderation, abuse, and privacy lift; would dwarf the rest of v0.4.0. Out of scope per locked decisions. | Defer indefinitely. If real-time matters, license a feed (HERE Traffic Vector Tile API has a `warning_level` field with low/minor/major/critical). |
| A9 | **Per-mode routing (pedestrian / bike / car) — using same crash data** | Mapbox and HERE both have separate pedestrian routing. SWITRS includes pedestrian + bike crashes. | Not in v0.4.0 scope. The cost function and IRI data only make sense for vehicles; reusing them for pedestrian routing would be misleading. | Defer to a separate milestone if it ever happens. SWITRS pedestrian crashes still count toward vehicle-route `crash_norm` because pedestrians-on-vehicles are a vehicle-route hazard — that's correct semantics. |
| A10 | **Naming the data with absolute claims ("100% of LA crashes")** | Sounds authoritative on a marketing page. | SWITRS misses ~10–20% of crashes (unreported, non-CHP-jurisdiction). LA City open-data has its own gaps. Claiming completeness is factually wrong. | Honest framing: "Reported crashes from SWITRS (CA Highway Patrol) and LA City open-data." |

---

## Feature Dependencies

```
[Existing v0.3.0 capabilities]
  ├── road_segments table (geom, length_m)             ← T3, T4 require
  ├── segment_scores table + compute_scores.py         ← D5 extends
  ├── /route + /segments APIs                          ← T9, D1 extend
  ├── PostGIS ST_DWithin / ST_ClosestPoint             ← T3 requires
  └── pgRouting cost-column pattern                    ← T5, D5 require

[New v0.4.0 features and their dependencies]

T1 (severity weighting) ──requires──> T2 (5y window data ingest)
T1 ──requires──> T3 (snap-match)

T4 (per-km normalization) ──requires──> T1 (weighted counts) + road_segments.length_m

T5 (0-1 normalization) ──requires──> T4

T6 (zero-not-null) ──ingest constraint──> T3, T5

D1 (route summary) ──requires──> T5 + p90 threshold computation

D2 (EB shrinkage) ──enhances──> T1 ──requires──> AADT or OSM-class proxy
                                                  └── PROXY ONLY (no AADT in v0.3.0)

D5 (materialized crash_norm) ──requires──> T5, T7 (refresh cadence)
   └──pre-empts──> in-route join (Phase 8 anti-pattern)

D6 (severity tooltip) ──requires──> T1 + extending /segments response
D7 (sparsity flag) ──requires──> T2 + per-segment crash count

T7 (quarterly refresh) ──requires──> T2, T3, D5

T8 (data legend) ──requires──> T7 (vintage tracking)

T9 (backwards-compat API) ──independent──>

T10 (disclaimer) ──independent──>

[Anti-features blocked]
A1, A6, A7, A10 ──conflict──> T8, T10 (disclaimer/honesty stance)
A2, A3, A4 ──conflict──> user-locked decisions
A5 ──conflict──> user decision to remove sliders
```

### Dependency Notes

- **T3 (snap-match) is the critical path.** Every scoring feature downstream needs this join to be correct. Budget operator-UAT time for spot-checking 20–50 random crashes against street-view to validate the snap tolerance. Phase 3's Mapillary ingest had a similar checkpoint and it caught a real bug.
- **D2 (EB shrinkage) requires data we don't have (AADT).** The simplified "shrink to OSM class mean" version is implementable without AADT and gives ~70% of the benefit. Roadmap should mark D2 as MEDIUM complexity *only if* that simplification is accepted; full SPF-based EB is HIGH and out of scope.
- **D1 (route summary) and T8 (legend) together establish trust.** Build them as a pair — a route-level claim ("avoids N crash-prone segments") is hollow without the legend explaining what "crash-prone" means.
- **T9 (backwards-compat) and A5 (no sliders) jointly resolve the API change.** Both must land together; only the second is user-facing.
- **T10 (disclaimer) is the cheapest litigation insurance in the milestone.** A single sentence rendered with the map page. Do not skip even if everything else is on fire.

---

## MVP Definition (for v0.4.0 milestone)

### Launch With (must ship to call v0.4.0 done)

These map 1:1 to the user's locked Active requirements plus the table-stakes items above.

- [ ] **T1** — Three-tier severity weighting (HSM defaults: fatal=10, injury=5, PDO=1)
- [ ] **T2** — 5-year aggregation window
- [ ] **T3** — Crash → segment snap-match pipeline (PostGIS, 20m default tolerance)
- [ ] **T4** — Per-km length normalization
- [ ] **T5** — 0–1 normalization with p95 cap, matching `iri_norm` semantics
- [ ] **T6** — Zero-default for no-crash segments
- [ ] **T7** — Quarterly refresh runbook + idempotent re-ingest
- [ ] **T8** — Data-vintage legend in UI
- [ ] **T9** — Backwards-compatible `/route` API (silently ignores removed weight params)
- [ ] **T10** — Liability disclaimer in UI footer
- [ ] **D5** — Pre-computed `crash_norm` materialized at ingest, not at route time *(critical to avoid Phase 8 perf regression)*
- [ ] Frontend: remove IRI + pothole sliders from Control Panel (keep `max_extra_minutes`)
- [ ] Operator runbook for quarterly refresh (extends Phase 3 Mapillary doc pattern)

### Add After Validation (v0.4.x patches)

Trigger: demo gets external feedback or user-testing surfaces gaps.

- [ ] **D1** — Route-level summary ("this route passes N crash-prone segments") *(trigger: user feedback that fastest-vs-best comparison feels abstract)*
- [ ] **D6** — Severity breakdown tooltip on segment hover *(trigger: technical/journalist viewers ask for justification of red segments)*
- [ ] **D4** — Operator data-freshness badge in `/health` *(trigger: first quarterly refresh slips and operator notices late)*

### Future Consideration (v0.5.0+)

Defer until v0.4.0 has been demoed and feedback gathered.

- [ ] **D2 (full SPF/EB)** — Empirical Bayes with proper SPF *(defer: requires AADT integration, separate milestone)*
- [ ] **D7** — Data sparsity / "insufficient data" segment shading *(defer: visual polish, not a credibility blocker)*
- [ ] AADT (traffic volume) integration for true MVMT-normalized rates *(defer: separate data source)*
- [ ] Real-time crash overlay via licensed feed *(defer: out of scope; requires partnership)*
- [ ] Multi-modal (pedestrian/bike) routing using same crash dataset *(defer: project is car-only)*

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| T1 EPDO severity weighting | HIGH | LOW | **P1** |
| T2 5-year window | HIGH | LOW | **P1** |
| T3 Spatial snap-match | HIGH | MEDIUM | **P1** |
| T4 Per-km normalization | HIGH | LOW | **P1** |
| T5 0–1 normalization | HIGH | LOW | **P1** |
| T6 Zero-default | MEDIUM | LOW | **P1** |
| T7 Quarterly refresh runbook | MEDIUM | LOW | **P1** |
| T8 Data legend | HIGH | LOW | **P1** |
| T9 Backwards-compat API | LOW (but blocking) | LOW | **P1** |
| T10 Liability disclaimer | LOW (but blocking) | LOW | **P1** |
| D5 Pre-computed crash_norm | HIGH | LOW | **P1** *(perf-critical)* |
| D1 Route-level summary | MEDIUM | LOW | P2 |
| D6 Severity tooltip | MEDIUM | LOW | P2 |
| D4 Operator freshness badge | LOW | LOW | P2 |
| D2 EB shrinkage (simplified) | MEDIUM | MEDIUM | P3 |
| D3 Length-aware viz | (covered by T4) | — | (already P1) |
| D7 Sparsity indicator | LOW | MEDIUM | P3 |
| D2 EB shrinkage (full SPF) | HIGH | HIGH | P3+ (next milestone) |

**Priority key**:
- **P1** — Required for v0.4.0 to be credible and shippable
- **P2** — Add if budget allows; otherwise patch in v0.4.x
- **P3** — Defer to v0.5.0 or later

---

## Competitor / Reference Feature Analysis

| Feature | Waze (Google) | HERE Traffic API | LA Vision Zero (LADOT/GeoHub) | Our Approach (v0.4.0) |
|---------|---------------|------------------|-------------------------------|------------------------|
| Severity tiering | Real-time only — confidence score 0–10 from user feedback | 4-level: low/minor/major/critical (`warning_level` field) | KSI binary (fatal-or-severe-injury vs other) for HIN | Three-tier EPDO (fatal/injury/PDO) — HSM-aligned |
| Time window | Real-time, decays with user "Not there" votes | Real-time with auto-expiry | Rolling 5-year (e.g., 2012–2016, 2018–2022) | Rolling 5-year aggregate, quarterly refresh |
| Spatial unit | Point incident on road | Vector tile per road segment | Corridor (multi-segment "high-injury network") | Per-segment (single road_segments row) |
| Recency decay | Yes — incident TTL adjusted by user reactions | Yes — auto-expire by incident type | None — flat 5y aggregate | Flat 5y aggregate (per user lock) |
| Visualization | Icon overlay + voice alert | Color-coded vector tile | Highlighted corridor on Vision Zero map | Color-encoded segment (composite cost) |
| Per-route warning | "Crash ahead" voice alert | API: route includes `notifications` array | N/A (planning tool, not routing) | "passes N crash-prone segments" (D1, P2) |
| Naming intersections | No | No | Aggregate corridors only (avoids individual intersections) | No (anti-feature A1) |
| Disclaimer | "Reports vary in accuracy" + ToS | API ToS only | "Data shown for planning purposes" | One-line disclaimer in UI footer (T10) |
| Data sources | Crowdsourced + partner feeds | Proprietary feeds + partner integrations | SWITRS + LADOT + LAPD records | SWITRS/TIMS + LA City open-data |
| Refresh cadence | Real-time | Real-time | Annual or biennial | Quarterly |
| Slider for crash weighting | N/A | N/A | N/A | None — locked at 0.25 |

**Takeaway:** Real-time products (Waze, HERE) emphasize recency and visual icons; planning products (Vision Zero) emphasize aggregation and corridor-level analysis. v0.4.0 is closer to the planning side, which means: (1) the "live incident" expectations don't apply; (2) the "honest aggregation" expectations from Vision Zero strongly apply; (3) we should adopt Vision Zero's corridor-level discretion (no per-intersection naming) but display per-segment colors because the routing engine is per-segment.

---

## Key Heuristics with Rationale

### Recency Decay: Why Flat 5-Year Aggregate Is the Right Choice for v0.4.0

The user has locked "historical aggregate, quarterly refresh" — meaning **all crashes within the 5-year window count equally**, no exponential decay by date.

**Why this is defensible** (not just a constraint to apologize for):

1. **HSM and Vision Zero precedent.** FHWA HSM's Empirical Bayes method explicitly uses a flat-window count (typically 3–5 years), then *shrinks toward expectation* — but the input is unweighted within the window. LA's HIN (`ladotlivablestreets.org/news/HIN-update`) uses 5-year flat windows. SF's HIN uses 5-year flat windows. None use exponential time decay.
2. **Sample-size starvation.** A typical urban segment has 1–10 crashes in 5 years. Decaying a 5-year-old fatal to 0.3× makes statistical noise dominant. The signal-to-noise ratio improves with more equal-weighted data, not less.
3. **Regression to the mean.** Recency-weighted counts amplify random year-to-year variation precisely the bias EB methods correct for. Flat windows are the right denominator.
4. **Operator simplicity.** A 5-year-old crash counting "the same" as a recent one is easier to explain in a runbook and easier to audit than `weight = exp(-age_years / τ)` for unspecified τ.

**When recency would matter** (and why it's deferred):

- A road has been physically rebuilt (new lanes, a road diet) in the last 2 years. The pre-rebuild crashes are obsolete signal.
- This is a real concern, but solving it requires road-construction event data that is not in scope. Roadmap should note this as a known limitation in PITFALLS.md.

**Anti-pattern to avoid:** "Recency decay because it sounds smart." A τ=2yr exponential decay would weight a 5-year-old fatal at e^(-2.5) ≈ 0.08 — effectively erasing it. That is rarely the right choice and is not what any production crash-routing or HIN methodology does.

### Per-Mile vs Per-Intersection Normalization: Why Per-km Length

Two equally defensible HSM normalizers exist:
- **Per MVMT (segments)** = crashes / (AADT × length × time × 365 / 10⁶)
- **Per MEV (intersections)** = crashes / (entering volume × time × 365 / 10⁶)

We don't have AADT (traffic volume), so true MVMT is unavailable. **Best honest substitute: crashes-per-km-per-year**, then percentile-normalized. Document that this is exposure-by-length-only, not exposure-by-volume.

**Why not per-intersection at all:** v0.4.0 is segment-level routing. Every cost has to be per-segment. Per-intersection logic would require introducing a new graph concept (vertices with cost) that pgRouting supports but our current schema does not — and the user has explicitly de-scoped intersection-level analysis.

### Cluster Identification: Implicit, Not Algorithmic

KDE-based hotspot identification (Getis-Ord Gi*, Moran's I) is the academic standard for *finding* hotspots in unstructured crash data. **For v0.4.0, hotspot identification is implicit** in the per-segment scoring: segments above the 90th percentile of `crash_norm` are de facto hotspots, and the routing engine naturally avoids them when they cost more.

**Don't run KDE.** It's a separate analysis pipeline that:
- Produces a continuous heatmap (which we explicitly de-scoped per user lock A6)
- Doesn't snap to road network (network-KDE is a research-grade variant)
- Adds a Python dependency (`scikit-learn` or similar) for marginal benefit

The percentile threshold of `crash_norm` is a faithful, simpler hotspot definition.

---

## Sources

### Production crash-routing and traffic products
- [Waze: Crash history alerts arrive to the map (Google blog)](https://blog.google/waze/crash-history-alerts-arrive-to-the-waze-map/)
- [Waze Help: Get alerts on roads with a history of crashes](https://support.google.com/waze/answer/13014546?hl=en)
- [HERE Traffic Vector Tile API — Layers (warning_level field)](https://developer.here.com/documentation/traffic-vector-tiles/dev_guide/topics/layers.html)
- [HERE: Location forecast 2026 — top trends advancing road safety](https://www.here.com/learn/blog/road-safety-trends-2026)
- [Mapbox: Improve Driver Safety with Route Notifications](https://www.mapbox.com/blog/route-notifications-improve-driver-safety)
- [Mapbox + Michelin Mobility Intelligence integration](https://www.mapbox.com/forms/michelin-mobility-intelligence-and-mapbox)

### Vision Zero / High Injury Network methodologies
- [LADOT Vision Zero High Injury Network update — 6% of streets, 70% of severe injuries](https://ladotlivablestreets.org/news/HIN-update)
- [Los Angeles GeoHub Vision Zero Initiative](https://visionzero.geohub.lacity.org/)
- [LADOT Vision Zero Safety Study, January 2024 (PDF)](https://ladot.lacity.gov/sites/default/files/documents/la-vision-zero-safety-study-2024.pdf)
- [SF Vision Zero High Injury Network 2022 update methodology (PDF)](https://www.visionzerosf.org/wp-content/uploads/2023/03/2022_Vision_Zero_Network_Update_Methodology.pdf)
- [Vision Zero Network — HIN methodology overview](https://visionzeronetwork.org/hin-for-the-win/)

### FHWA Highway Safety Manual / safety-engineering canon
- [FHWA: Network Screening with Crash Data — Frequency methods](https://safety.fhwa.dot.gov/local_rural/training/fhwasa14072/sec4.cfm)
- [FHWA: Crash Rates (per MVMT, per MEV)](https://safety.fhwa.dot.gov/local_rural/training/fhwasa1210/s3.cfm)
- [FHWA: Solving Safety Problems (EB method, RTM bias)](https://highways.dot.gov/safety/learn-safety/road-safety-fundamentals-html-version/unit-4-solving-safety-problems)
- [Crash Modification Factors Clearinghouse — what is a CMF](https://cmfclearinghouse.fhwa.dot.gov/userguide_CMF.php)

### EPDO weighting research
- [Frequency Analysis of EPDO Crashes at Intersections (MDPI 2023)](https://www.mdpi.com/2673-4117/4/2/64)
- [Evaluation of EPDO weight sets for hotspot identification (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S2213624X25001683)
- [Optimizing EPDO Prediction Models with Genetic Algorithms (MDPI Infrastructures)](https://www.mdpi.com/2412-3811/10/3/61)

### SWITRS / TIMS data sources
- [TIMS — Transportation Injury Mapping System (UC Berkeley SafeTREC)](https://tims.berkeley.edu/help/Query_and_Map.php)
- [SWITRS Codebook (PDF)](https://peteraldhous.com/Data/ca_traffic/SWITRS_codebook.pdf)
- [LA GeoHub: SWITRS Collisions 2014–2019 dataset](https://geohub.lacity.org/datasets?q=switrs)

### Spatial methodology references
- [PostGIS: ST_Snap documentation](https://postgis.net/docs/ST_Snap.html)
- [ESRI: Analyzing traffic accidents in space and time](https://desktop.arcgis.com/en/analytics/case-studies/analyzing-crashes-2-pro-workflow.htm)
- [Snapping Points to Street Segments (Medium, Michelle Ho)](https://medium.com/@michellemho/snapping-points-to-street-segments-22be59d0449)
- [Identification of crash hotspots using KDE and kriging (Springer)](https://link.springer.com/article/10.1007/s40534-015-0068-0)

### Liability and legal context
- [How GPS Liability Is Handled in Accidents](https://www.foryourrights.com/blog/how-is-liability-handled-in-accidents-caused-by-gps/)
- [Cartwright Law: Drivers using mobile map apps and California liability](https://www.cartwrightlaw.com/blog/2013/june/ruling-says-drivers-who-use-mobile-map-apps-run-/)

### Data-sparsity and graceful-degradation context
- [Identifying high crash risk segments in rural roads (Nature Sci Reports)](https://www.nature.com/articles/s41598-022-24476-z)
- [Comparative Evaluation of Hotspot Identification Methods — EB vs PSI (MDPI)](https://www.mdpi.com/2071-1050/16/4/1537)

---

*Feature research for: crash-aware routing milestone (v0.4.0)*
*Researched: 2026-05-07*
*Confidence: HIGH on table-stakes/anti-features (multi-source); MEDIUM on specific weight numbers (jurisdiction-dependent).*
