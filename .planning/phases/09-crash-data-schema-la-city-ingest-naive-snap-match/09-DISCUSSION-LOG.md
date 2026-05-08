# Phase 9: Crash-Data Schema + LA City Ingest + Naive Snap-Match - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-08
**Phase:** 09-Crash-Data Schema + LA City Ingest + Naive Snap-Match
**Areas discussed:** Time-window anchor, LACITY_SNAP_M default, Test strategy, Run-summary verbosity

---

## Time-Window Anchor for LA City Fetch

| Option | Description | Selected |
|--------|-------------|----------|
| Anchored 2019-03-01 → 2024-03-01 (5 full pre-freeze years) | Gets the densest LA crash dataset available: 5 full years before the LAPD NIBRS migration froze the portal. Demo looks substantive; quarterly refresh is genuinely a no-op (data won't change). | ✓ |
| Rolling last-5-years from today | Conventional choice. Today's pull would be 2021-05-08 → 2026-05-08, but only ~3 years of that has data (rest is post-freeze gaps). Demo dataset feels thin; quarterly refresh still no-op past 2024-03. | |
| All available data (no time filter) | Pull everything LA City has (back to 2010 for d5tf-ez2w). More data but mixes pre-NIBRS classification eras — may not fit the locked three-tier severity cleanly. | |

**User's choice:** Anchored 2019-03-01 → 2024-03-01
**Notes:** Captured as D-09-01 / D-09-02. Implication: quarterly refresh runbook will document why row counts are stable across runs.

---

## LACITY_SNAP_M Starting Default

| Option | Description | Selected |
|--------|-------------|----------|
| 50 m | Research-recommended. Tighter; mocodes-derived geocoding has decent precision. ~5% of crashes likely drop (caught by dropped_outside_snap counter); operator can widen via env var if drops exceed threshold. | ✓ |
| 75 m | Looser; fewer drops but higher chance of attributing a crash to the parallel street one block over. Matches what SWITRS would need (when added in v0.4.1). | |
| 100 m | Very loose; almost no drops but high mis-attribution rate. Generally not recommended unless the LA City data turns out to be poorly geocoded. | |

**User's choice:** 50 m
**Notes:** Captured as D-09-03 / D-09-04. Env-tunable; runbook documents the >5% drop trigger to revisit.

---

## Test Strategy — Live API vs Committed Fixture

| Option | Description | Selected |
|--------|-------------|----------|
| Committed CSV fixture (~200 real LA City rows) | Snapshot 200 representative rows into a committed file (data/crashes_la/lacity_fixture.csv). Stable, no network in CI, no LACITY_APP_TOKEN secret needed. Fixture refreshed manually at quarterly cadence. | ✓ |
| Live LA City API (CI hits Socrata) | Tests pull from data.lacity.org each run. Real data always; but CI flakes on Socrata downtime + needs LACITY_APP_TOKEN as a secret + slow. | |
| Both: live if available, fixture as fallback | Best of both but more code paths to maintain (a network-conditional skip). | |

**User's choice:** Committed CSV fixture
**Notes:** Captured as D-09-05 / D-09-06 / D-09-07. Fixture coverage criteria (multi-mocodes, intersection vs mid-block, drop-outside-snap, all severity tiers) explicitly enumerated for planner.

---

## Run-Summary JSON Verbosity

| Option | Description | Selected |
|--------|-------------|----------|
| Mid — counts + distance histogram + severity breakdown | {"inserted": N, "dropped_outside_snap": M, "errors": K, "snap_distance_p50_p95_max": [...], "by_severity": {"fatal": ..., "injury": ..., "pdo": ...}}. Enough to debug snap-tolerance tuning + spot data anomalies. Mirrors run-summary verbosity from v0.3.0 Phase 3. | ✓ |
| Minimal — counts only | {"inserted": N, "dropped_outside_snap": M, "errors": K}. Quick to read; no instrumentation for snap-tuning. | |
| Full — per-record audit log | Every record's snap distance + which segment + severity tier. Massive output; useful for one-time validation runs but noisy for routine refreshes. | |

**User's choice:** Mid (counts + distance histogram + severity breakdown)
**Notes:** Captured as D-09-08 / D-09-09. Exact JSON shape pinned in CONTEXT.md. `--summary-out` flag pattern from Phase 3 Plan 03-04.

---

## Claude's Discretion

User explicitly said no need for input on (these are planner-decided):
- Pagination size for Socrata fetch (default `$limit=1000` mirrors `data_pipeline/mapillary.py`)
- Internal class structure for `lacity_socrata.py` (one module-level function vs class — match Mapillary client style)
- Specific 200-row fixture composition (Claude picks during plan execution to satisfy D-09-07 coverage criteria)
- argparse subcommand structure (match `ingest_mapillary.py`)
- Run-summary `started_at` / `duration_s` precision

## Deferred Ideas

No new scope-creep candidates surfaced during Phase 9 discussion. All deferral decisions were already locked at milestone scoping (REQUIREMENTS.md):

- SWITRS/TIMS source → v0.4.1 (`crash_records.source` CHECK widening is non-breaking)
- Fractional intersection snap-match → v0.4.1 (additive `snap_point_to_intersection()` helper)
- Exponential recency decay → v0.4.1 (formula extension in Phase 10's `crash_norm`)
- `record_status` provisional/final tracking → v0.4.1 (additive column)
