# Phase 12: Cloud Deploy + First LA City Ingest + Verification + Doc Carryforward - Context

**Gathered:** 2026-05-08
**Status:** Ready for planning
**Mode:** Auto-generated via `/gsd-discuss-phase 12 --auto` (decisions sourced from REQUIREMENTS.md REQ-crash-cloud-deploy + REQ-route-filter-env-vars-doc, PROJECT.md locked anti-patterns, the v0.3.0 Phase 5 LESSONS-LEARNED, the user's Fly.io deploy-state memory, and Phase 9-11 verification hand-offs)

<domain>
## Phase Boundary

Take Phases 9–11 (which all shipped to `main` 2026-05-08) live on Fly.io: Migration 004 lands on the prod Postgres via the locked `flyctl ssh console -C "psql ..."` anti-pattern (NEVER `flyctl proxy` — wireguard timeouts trigger Postgres recovery crash loops, recorded as load-bearing in v0.3.0 Phase 5 LESSONS-LEARNED). Run the first quarterly LA City Socrata ingest on the live DB. Recompute `segment_scores` with the new `--source all` (which now includes `--source crash` from Phase 10). Backend and frontend redeploy through the existing GH Actions `deploy.yml` pipeline. Live demo at `https://road-quality-frontend.fly.dev/` returns crash-aware routes within the Phase 8 cold-cross-LA <5s perf budget. Same milestone-close diff lands the v0.3.0 carryforward of `ROUTE_FILTER_BUFFER_DEG` / `ROUTE_FILTER_WIDEN_FACTOR` env-var documentation.

This phase explicitly does:
- Apply migration 004 to the live `road-quality-db` Fly app
- Pull LA City Socrata data with the live `LACITY_APP_TOKEN` secret
- Run `scripts/compute_scores.py --source all` on prod
- Trigger backend + frontend redeploy via push-to-main (deploy.yml auto-fires)
- Live-smoke 3 routes (DTLA-local, cross-LA, known-safe arterial like Wilshire)
- Document `ROUTE_FILTER_BUFFER_DEG` (default `0.03`) and `ROUTE_FILTER_WIDEN_FACTOR` (default `2.0`) in `.env.example` + `README.md`
- Commit a delta report under `.planning/phases/12-*/12-DELTA-REPORT.md`

This phase explicitly does NOT:
- Re-architect deploy.yml — it already passed v0.3.0 Phase 5 UAT (5/5 + 16 inline defects fixed)
- Touch `.flycast` vs `.internal` DNS — locked from Phase 5: inter-app uses `<app>.internal`, browser uses `https://*.fly.dev`
- Use `flyctl proxy` for any DDL — locked anti-pattern (recovery crash loops)
- Run blue/green or canary — single-flake `road-quality-backend` machine pattern preserved (v0.3.0 baseline)
- Add new infrastructure — no new Fly app, no new volume, no Redis, no Sentry (deferred per PROJECT.md)
- Resolve the 4 v0.3.0-archived operator-runbook walkthroughs (02/03/05-VERIFICATION human-needed items) — explicitly carry-forward, not v0.4.0 scope

</domain>

<decisions>
## Implementation Decisions

### Pre-Deploy Rehearsal (REQ-crash-cloud-deploy AC #1)
- **D-12-01:** Run `flyctl ssh console -a road-quality-db -C "df -h /var/lib/postgresql/data"` BEFORE applying migration 004. Confirm ≥1.5× expected `crash_records` + GiST footprint is free. Expected footprint is small (~10–20 MB for 5-year LA City + spatial index per REQUIREMENTS); current volume is 5 GB extended, so this should pass with massive headroom — but the rehearsal is mandatory anyway (Pitfall protocol from Phase 5 LESSONS-LEARNED).
- **D-12-02:** Capture pre-rehearsal output verbatim into `12-DELTA-REPORT.md` so milestone-close audit can verify.

### Migration 004 Cloud Apply (REQ-crash-cloud-deploy AC #2)
- **D-12-03:** Apply migration 004 via `flyctl ssh console -a road-quality-db -C "psql -U rq -d roadquality -f /tmp/004_crash_records.sql"`. Mechanism: copy the SQL file in via `flyctl ssh sftp shell` first, OR pipe via stdin with a shell-here-doc, OR scp-then-psql — researcher to recommend the most reliable variant.
- **D-12-04:** **NEVER** use `flyctl proxy` for this DDL. The wireguard tunnel times out on long DDL → Postgres goes into recovery crash loop. This is the load-bearing anti-pattern from v0.3.0 Phase 5 LESSONS-LEARNED (the seed-data run in Phase 5 had to be re-architected after this exact failure).
- **D-12-05:** Migration is idempotent (verified Phase 9: `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, `DROP-then-ADD CHECK`). A second apply is safe — captures both initial-apply log + re-apply-log into the delta report.
- **D-12-06:** Post-apply verification: `flyctl ssh console -a road-quality-db -C "psql -U rq -d roadquality -c '\d+ crash_records'"` and same for `\d+ segment_scores`. Capture into delta report.

### First LA City Ingest on Prod (REQ-crash-cloud-deploy AC #3)
- **D-12-07:** Set `LACITY_APP_TOKEN` Fly secret on `road-quality-backend` (or new `road-quality-ingest` if a separate ingest app is preferred — researcher recommends; default: reuse `road-quality-backend` machine since `scripts/` aren't in the backend image, the ingest will run via `flyctl ssh console -C` against a temporary host-venv-style invocation OR via a one-off ingest container).
- **D-12-08:** **CRITICAL constraint:** `scripts/ingest_crashes.py` is NOT in the backend Docker image (Phase 5 / Phase 9 confirmed: `backend/Dockerfile` only COPYs `backend/`). Two viable approaches — researcher picks:
  - **Option A (preferred per Phase 5 precedent):** Run the ingest from operator's host venv (`/tmp/rq-venv`) against the live DB through `flyctl proxy` — but ONLY for ingest (read+INSERT, no DDL). The `flyctl proxy` anti-pattern is specific to long DDL; INSERT batching does not trigger the recovery loop. v0.3.0 Phase 5 ran `seed_data.py` this way successfully.
  - **Option B:** Build a one-off `road-quality-ingest` Fly machine that includes `scripts/`. Adds infrastructure; out of scope per PROJECT.md "no new Fly app for v0.4.0".
  - **Default: Option A** unless researcher finds a blocker.
- **D-12-09:** Ingest emits a run-summary JSON (Phase 9 D-09-08 contract). Capture verbatim into `12-DELTA-REPORT.md`. Acceptance: run completes, ≥100 segments end up with non-zero `crash_norm` after step D-12-10.
- **D-12-10:** Post-ingest, run `flyctl ssh console -a road-quality-db -C "psql ..."` (NOT proxy) to invoke `compute_scores.py` from the host venv via `flyctl proxy` since the script also isn't in the image. Sequence: `--source all` runs synthetic + mapillary + crash. Validate with `SELECT COUNT(*) FROM segment_scores WHERE crash_norm > 0;` ≥ 100.

### Backend + Frontend Redeploy (REQ-crash-cloud-deploy AC #4–6)
- **D-12-11:** Redeploy is automatic — pushing to `main` triggers `.github/workflows/deploy.yml`, which already passed v0.3.0 Phase 5 UAT and contains the changes from Phases 10/11. No manual `flyctl deploy` invocation expected.
- **D-12-12:** GH Actions deploy.yml expectations:
  - `changes` job (paths-filter) detects backend (Phase 10 changed `backend/`) and frontend (Phase 11 changed `frontend/`) — both deploy
  - `test` job runs host-venv pytest against postgis+pgrouting service container
  - `deploy-backend` runs after `test` and after `deploy-db` (which is skipped — no `db/` path changes in this phase BEFORE manual migration; the manual `flyctl ssh` step happens out-of-band)
  - `deploy-frontend` runs after `deploy-backend`
  - Pitfall 7 defense (skip-cascade) and Pitfall 8 (concurrency) already in place from Phase 5
- **D-12-13:** Migration 004 is intentionally applied OUT-OF-BAND (D-12-03), NOT via `deploy-db`. Reason: deploy.yml's `deploy-db` job runs `flyctl deploy --config deploy/db/fly.toml`, which redeploys the DB image but does not run migrations. Migrations have been a manual step since v0.3.0 Phase 5; no change to that policy in v0.4.0.
- **D-12-14:** Live smoke acceptance: `curl https://road-quality-frontend.fly.dev/ -I` returns 200; `POST https://road-quality-backend.fly.dev/route` returns 200 with `Deprecation: weight_iri,weight_potholes ignored as of v0.4.0` header (Phase 10 contract); `GET /segments?bbox=...` returns features with `crash_norm` field present (Phase 10 contract).

### 3-Route Manual Spot Check (REQ-crash-cloud-deploy AC #6 + Pitfall 5 sanity gate)
- **D-12-15:** Spot check 3 routes in the live demo browser session (`https://road-quality-frontend.fly.dev/`):
  - **DTLA-local:** Pershing Square → Bunker Hill (~1 mi). Expected: `best_route` differs slightly from `fastest_route` if any LA City crashes are snapped to the involved segments; otherwise identical (acceptable).
  - **Cross-LA:** Westwood → Boyle Heights (~14 mi). Expected: routes complete in <5s cold (Phase 8 perf budget). `best_route` may swing onto Sunset/3rd if Wilshire/Olympic carry higher crash density.
  - **Known-safe arterial:** Wilshire Blvd Mid-Wilshire portion. Expected: NOT routed onto Wilshire if crash density is high there. Pitfall 5 sanity gate — fatal weights at 8:3:1 with the K=3 cap should NOT push a known-safe arterial above 0.5 `crash_norm`. If it does, Phase 12 has surfaced a calibration issue and Plan 12-05 logs it as a remediation hand-off (NOT a Phase 12 blocker).
- **D-12-16:** Capture screenshots OR copy the route URLs into `12-DELTA-REPORT.md`. Disclaimer copy must be visible adjacent to the find-route button (Phase 11 D-11-04 verification on live deploy).

### REQ-route-filter-env-vars-doc (Carryforward)
- **D-12-17:** `.env.example` gets a new section documenting:
  ```
  # ----- Routing perf tunables (Phase 8 carryforward; cite 08-PERF-NUMBERS.md) -----
  # Spatial buffer in degrees around route bbox for segment_scores filter (default 0.03 ≈ 3.3 km).
  # Wider buffer covers more candidate detours; narrower keeps the temp-table small (Phase 8 perf budget).
  ROUTE_FILTER_BUFFER_DEG=0.03
  # Multiplier for the wide-fallback buffer when the initial filter returns 0 candidates (default 2.0 → 6.6 km).
  # 3-attempt fallback chain: filter → wide → full. Tune up for sparse corners, down for tight perf.
  ROUTE_FILTER_WIDEN_FACTOR=2.0
  ```
- **D-12-18:** `README.md` Configuration section (or equivalent — researcher to verify section name) gets two new bullet entries cross-linking to `.planning/milestones/v0.3.0-phases/08-routing-performance/08-PERF-NUMBERS.md` for tuning rationale.
- **D-12-19:** Inline comment in `backend/app/routes/routing.py:22-23` (where the env vars are read) gets the same cross-link to the perf-numbers archive — anti-pattern pin reciprocity with Phase 8 line 272-298.

### Delta Report (REQ-crash-cloud-deploy AC #7)
- **D-12-20:** Commit `12-DELTA-REPORT.md` with:
  - Pre-deploy `df -h` capture
  - Migration 004 apply log (initial + re-apply)
  - `\d+ crash_records` and `\d+ segment_scores` post-apply
  - First LA City ingest run-summary JSON (D-09-08 shape)
  - `compute_scores.py --source all` exit + `SELECT COUNT(*) FROM segment_scores WHERE crash_norm > 0` result
  - 3 spot-check route URLs / screenshots
  - GH Actions deploy.yml run URL
  - Any deviations from this CONTEXT.md
- **D-12-21:** This report is the milestone-close audit's primary input. Phase 12 verification reads it.

### Operator-Action Plans vs Autonomous Plans
- **D-12-22:** Phases 12-01 (rehearsal + DDL apply) and 12-02 (live ingest + recompute) require operator credentials (`flyctl auth`, `LACITY_APP_TOKEN` secret) and are **`autonomous: false`** with `type: human-action`. They cannot run via `gsd-executor` — they need a human running `flyctl` from a credentialed shell.
- **D-12-23:** Plans 12-04 (env doc carryforward) and 12-05 (delta report scaffolding) are **`autonomous: true`** — pure repo edits. Can run via `gsd-executor` while the operator is working on 12-01/12-02 in parallel.
- **D-12-24:** Plan 12-03 (push-to-main → deploy.yml auto-fires) is a hybrid: the push itself is a human action, the deploy is auto-driven by GH Actions. Mark `autonomous: false` `type: human-action`.

### Failure / Rollback
- **D-12-25:** If migration 004 fails on prod, `flyctl ssh console -C "psql -c 'BEGIN; ROLLBACK;'"` is a no-op (the migration is idempotent and atomic). If `crash_records` table got created but indexes failed, re-run the same migration — IF NOT EXISTS guards make it safe.
- **D-12-26:** If the LA City ingest fails mid-run, the `(source, source_record_id)` UNIQUE constraint + `ON CONFLICT DO NOTHING` (Phase 9 D-09-08) makes a re-run a no-op for already-ingested rows. Free retry policy.
- **D-12-27:** If the live frontend smoke fails (e.g., missing disclaimer, no `crash_norm` in /segments), revert via Fly's machine-history feature (`flyctl deploy --image-label v0.3.0-final` or equivalent) — but only if the broken state would actively mislead users. A missing crash_norm field is non-breaking (frontend defaults to 0). A missing disclaimer is breaking (legal liability) — that triggers a rollback.
- **D-12-28:** Phase 12 has NO automated revert. Rollback is a human decision; document the trigger conditions in `12-DELTA-REPORT.md`.

### Claude's Discretion
- The exact `flyctl ssh sftp` vs `psql -f /dev/stdin` mechanism for migration 004 apply (researcher recommends — both are valid; preference is whichever is most resilient to wireguard interruption mid-DDL — though migration 004 is fast enough that interruption is unlikely)
- Whether plan 12-04 (env doc) and 12-05 (delta report) collapse into a single plan
- Whether to bump pytest-timeout in deploy.yml's test job (Phase 10 deferred-items.md flagged a parallel-agent timeout in `test_idempotent_reingest`) — default: yes, bump to 180s, since test workload grew with Phase 9-10
- Exact location of the README env-var docs (top-level "Configuration" section vs Phase 8 archive cross-link only) — researcher to recommend; bias toward minimum disruption to existing README structure

### Folded Todos (from STATE.md)
- "Phase 12: `df -h` Fly volume rehearsal BEFORE migration apply; `flyctl ssh console -C` for DDL (locked); document `ROUTE_FILTER_BUFFER_DEG` + `ROUTE_FILTER_WIDEN_FACTOR` in `.env.example` + README (carryforward from v0.3.0 Phase 8 tech debt)" — folded as D-12-01, D-12-03/04, D-12-17/18/19.
- Phase 10 deferred-items: "test_ingest_crashes.py::test_idempotent_reingest timed out under parallel-agent load" — folded as Claude's-discretion item (bump deploy.yml pytest-timeout).
- Phase 11 hand-offs: "Frontend redeploy + 3-route spot check" — folded as D-12-15, D-12-16.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Locked Anti-Patterns (load-bearing)
- `.planning/PROJECT.md` "Long DDL on Fly DB MUST run via `flyctl ssh console -C`, NEVER `flyctl proxy`" — load-bearing
- `.planning/milestones/v0.3.0-phases/05-cloud-deployment/05-LESSONS-LEARNED.md` (if exists) — wireguard-timeout/recovery-crash-loop incident report
- `.github/workflows/deploy.yml` — already-passing pipeline; do NOT re-architect

### Locked Acceptance Criteria
- `.planning/REQUIREMENTS.md` §REQ-crash-cloud-deploy — 9 acceptance criteria
- `.planning/REQUIREMENTS.md` §REQ-route-filter-env-vars-doc — 3 acceptance criteria
- `.planning/ROADMAP.md` §Phase 12 — 5 success criteria

### Phase 9–11 Hand-Offs (consumed by Phase 12)
- `.planning/phases/09-crash-data-schema-la-city-ingest-naive-snap-match/09-VERIFICATION.md` — schema invariants
- `.planning/phases/10-crash-scoring-formula-locked-weight-routing-api/10-VERIFICATION.md` — `--source all` correctness; Pitfall 5 sanity-check basis
- `.planning/phases/10-crash-scoring-formula-locked-weight-routing-api/deferred-items.md` — pytest-timeout flag for deploy.yml
- `.planning/phases/11-frontend-slider-removal-liability-disclaimer-data-vintage-caption/11-VERIFICATION.md` — frontend live-smoke checklist

### Existing Code (touched by Phase 12)
- `.env.example` — extends with two new env-var sections (D-12-17)
- `README.md` — Configuration section gains two bullets (D-12-18)
- `backend/app/routes/routing.py:22-23` — inline comment cross-link (D-12-19)
- `.github/workflows/deploy.yml` — pytest-timeout bump (Claude's discretion)

### Live Infrastructure (read-only references)
- `deploy/db/fly.toml` — `road-quality-db` Fly app config (5 GB volume, lax region)
- `deploy/backend/fly.toml` — `road-quality-backend` config (auto_stop_machines on)
- `deploy/frontend/fly.toml` — `road-quality-frontend` config
- User auto-memory `road-quality-mvp_fly_deploy.md` — secrets list, machine IDs, port mappings, `<app>.internal` DNS

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `.github/workflows/deploy.yml` — already shipped, passed v0.3.0 Phase 5 UAT; auto-fires on push to main. No re-architecture needed.
- Fly secret-management already wired (`AUTH_SIGNING_KEY`, `MAPILLARY_ACCESS_TOKEN`, `DATABASE_URL`); add `LACITY_APP_TOKEN` and `LACITY_SNAP_M` (Phase 9 D-09-08) the same way.
- v0.3.0 Phase 5 LESSONS-LEARNED documents 16 inline defects already fixed (PGDATA, volume permissions, dockerfile path, .internal vs .flycast). Phase 12 inherits the fixes.
- Migration 004 is idempotent — no Phase-12 "if-this-fails-rollback" engineering needed (D-12-25, D-12-26).

### Established Patterns
- Migration apply via `flyctl ssh console -C "psql ..."` (NOT proxy) — Phase 5 precedent
- Seed/ingest scripts run from operator host venv via `flyctl proxy` (TCP tunnel — safe for INSERT, NOT for DDL) — Phase 5 precedent
- Multi-app Fly deployment with `<app>.internal` for inter-app DNS, `<app>.fly.dev` for browser access
- Concurrency group `deploy-prod` cancel-in-progress=false prevents mid-deploy races (Pitfall 8 from Phase 5)

### Integration Points
- Phase 12 is the milestone-close phase — no Phase 13 in v0.4.0. The `12-DELTA-REPORT.md` is the audit input.
- `gsd-complete-milestone v0.4.0` runs after Phase 12 verification passes.

</code_context>

<specifics>
## Specific Ideas

- The `flyctl ssh console -a <app> -C` command must be quoted carefully — `psql` arguments live inside the `-C` string. Test with a no-op first (`-C "echo hello"`) to confirm shell quoting before applying migration 004.
- The `LACITY_APP_TOKEN` secret should be set via `flyctl secrets set LACITY_APP_TOKEN=<token> -a road-quality-backend` BEFORE the ingest run. Confirm with `flyctl secrets list -a road-quality-backend`.
- For the host-venv ingest (D-12-08 Option A), use `flyctl proxy 5432:5432 -a road-quality-db &` then `DATABASE_URL=postgresql://rq:<pw>@127.0.0.1:5432/roadquality /tmp/rq-venv/bin/python scripts/ingest_crashes.py --source lacity`. Kill the proxy with `kill %1` after the ingest completes.
- The 3-route spot check (D-12-15) is qualitative — "looks reasonable to a local". Document the screenshots + URLs even if all 3 look fine.
- Em dash in disclaimer (Phase 11) is U+2014; live-smoke that the deployed bundle still has `e2 80 94` bytes (against the served CSS-in-JS or Vite-bundled JS) — quick sanity grep on `curl https://road-quality-frontend.fly.dev/assets/index-*.js | grep -aoE "...always drive..."`.

</specifics>

<deferred>
## Deferred Ideas

- **Single-fatal cap K calibration via 5-arterial spot check (Phase 10 hand-off)** — folded into D-12-15's known-safe-arterial test (Wilshire). If Wilshire's `crash_norm` exceeds 0.5, log as remediation (Phase 13 / v0.4.1).
- **Histogram smoke test running end-to-end with live data** — opportunistic during Plan 12-02 ingest run; if ≥100 crash-bearing segments emerge, the Phase 10 `test_crash_norm_histogram_not_bimodal` smoke can finally run unskipped. Capture into delta report.
- **4 v0.3.0-archived operator-runbook walkthroughs** (02/03/05-VERIFICATION human_needed items) — explicitly carry-forward, NOT v0.4.0 scope. Re-audit at next milestone scoping.
- **Resolving Phase 10 deferred-items parallel-agent test_idempotent_reingest timeout** — folded as Claude's-discretion bump in deploy.yml; if the bump doesn't resolve cleanly, defer to v0.4.1.
- **Sentry / Prometheus / structured logging** — already deferred to post-v0.4.0 (PROJECT.md).
- **Blue/green deploy / canary / multi-region** — out of scope for v0.4.0 (PROJECT.md "no new infrastructure").

</deferred>

---

*Phase: 12-Cloud Deploy + First LA City Ingest + Verification + Doc Carryforward*
*Context gathered: 2026-05-08*
