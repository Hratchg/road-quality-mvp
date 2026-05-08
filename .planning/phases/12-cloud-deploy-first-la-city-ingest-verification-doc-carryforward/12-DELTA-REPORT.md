---
phase: 12-cloud-deploy-first-la-city-ingest-verification-doc-carryforward
report_type: delta
report_status: in_progress
started: 2026-05-08
operator: hratchghanime@gmail.com
fly_apps:
  - road-quality-db
  - road-quality-backend
  - road-quality-frontend
fly_org: personal
fly_region: lax
plans_covered:
  - 12-01 (Wave 2 — DDL apply)
  - 12-02 (Wave 3 — ingest + recompute)
  - 12-03 (Wave 4 — deploy + smoke)
plan_05_scaffolded: 2026-05-08
---

# Phase 12 Delta Report

> **Living document.** This is the milestone-close audit input per CONTEXT.md D-12-21.
> Each section below is filled in by the corresponding plan; sections start as TBD
> placeholders and become CAPTURED as Plans 12-01 / 12-02 / 12-03 execute.

## Section 1 — Pre-Deploy `df -h` Rehearsal (Plan 12-01 Task 1)

**Status:** PASS
**Decision ref:** D-12-01, D-12-02
**Acceptance:** Volume free space ≥1.5× expected `crash_records` + GiST footprint (~10–20 MB) — **massively exceeded**.
**Captured:** 2026-05-08

**Command:**
```bash
flyctl ssh console -a road-quality-db -C "df -h /var/lib/postgresql/data"
```

**Captured output:**
```
Filesystem      Size  Used Avail Use% Mounted on
/dev/vdc        4.9G  985M  3.8G  21% /var/lib/postgresql/data
```

**Decision:** PROCEED. 3.8 GB free vs ~20 MB expected — 190× headroom.

---

## Section 2 — Migration 004 Cloud Apply (Plan 12-01 Task 2)

**Status:** PASS
**Decision ref:** D-12-03, D-12-04, D-12-05
**Anti-pattern lock honored:** `flyctl ssh console -C "psql ..."` used. NO `flyctl proxy` involvement in any DDL step.
**Acceptance:** First-apply succeeded; re-apply was a no-op (idempotent verified on prod, mirroring Phase 9 local verification).
**Captured:** 2026-05-08

**Pre-state:** prod had neither `crash_records` table nor `segment_scores.crash_norm` column (verified `false / false` via information_schema query).

**Command (exact):**
```bash
# Step A: ship the SQL into the DB container
cat db/migrations/004_crash_records.sql | flyctl ssh console -a road-quality-db -C "tee /tmp/004_crash_records.sql > /dev/null"
# (verified 58 lines on prod = 58 lines local)

# Step B: apply (-v ON_ERROR_STOP=1 makes failure loud)
flyctl ssh console -a road-quality-db -C "psql -U rq -d roadquality -v ON_ERROR_STOP=1 -f /tmp/004_crash_records.sql"

# Step C: re-apply for idempotency proof
flyctl ssh console -a road-quality-db -C "psql -U rq -d roadquality -v ON_ERROR_STOP=1 -f /tmp/004_crash_records.sql"
```

**First-apply log:**
```
psql:/tmp/004_crash_records.sql:34: NOTICE:  constraint "crash_records_source_check" of relation "crash_records" does not exist, skipping
CREATE TABLE
ALTER TABLE
ALTER TABLE
psql:/tmp/004_crash_records.sql:38: NOTICE:  constraint "crash_records_severity_check" of relation "crash_records" does not exist, skipping
ALTER TABLE
ALTER TABLE
CREATE INDEX
CREATE INDEX
CREATE INDEX
ALTER TABLE
```

The two NOTICE lines are the DROP CONSTRAINT IF EXISTS no-op messages on first apply — expected, not errors.

**Re-apply log (idempotency proof):**
```
CREATE TABLE
psql:/tmp/004_crash_records.sql:30: NOTICE:  relation "crash_records" already exists, skipping
psql:/tmp/004_crash_records.sql:45: NOTICE:  relation "idx_crash_records_source_id" already exists, skipping
ALTER TABLE
ALTER TABLE
ALTER TABLE
ALTER TABLE
CREATE INDEX
CREATE INDEX
CREATE INDEX
psql:/tmp/004_crash_records.sql:49: NOTICE:  relation "idx_crash_records_geom" already exists, skipping
psql:/tmp/004_crash_records.sql:51: NOTICE:  relation "idx_crash_records_segment" already exists, skipping
psql:/tmp/004_crash_records.sql:58: NOTICE:  column "crash_norm" of relation "segment_scores" already exists, skipping
ALTER TABLE
```

All NOTICE lines are "already exists, skipping" — zero errors. **Migration is idempotent on prod.**

**Decision:** PROCEED to Section 3 verification.

---

## Section 3 — Schema Verification (Plan 12-01 Task 3)

**Status:** PASS
**Decision ref:** D-12-06
**Acceptance:** `crash_records` table exists with all D-09-10 fields; `segment_scores.crash_norm` is `DOUBLE PRECISION NOT NULL DEFAULT 0.0`. **All checks pass.**
**Captured:** 2026-05-08

**`\d+ crash_records` output:**
```
                       Table "public.crash_records"
       Column       |           Type           | Nullable | Default
--------------------+--------------------------+----------+---------
 id                 | bigint                   | not null | nextval('crash_records_id_seq')
 source             | text                     | not null |
 source_record_id   | text                     | not null |
 severity           | text                     | not null |
 occurred_at        | date                     | not null |
 snapped_segment_id | integer                  |          |
 snap_distance_m    | double precision         |          |
 geom               | geometry(Point,4326)     | not null |
 created_at         | timestamp with time zone | not null | now()
Indexes:
    "crash_records_pkey" PRIMARY KEY, btree (id)
    "idx_crash_records_geom" gist (geom)
    "idx_crash_records_segment" btree (snapped_segment_id)
    "idx_crash_records_source_id" UNIQUE, btree (source, source_record_id)
Check constraints:
    "crash_records_severity_check" CHECK (severity IN ('fatal','injury','pdo'))
    "crash_records_source_check" CHECK (source = 'lacity')
Foreign-key constraints:
    "crash_records_snapped_segment_id_fkey" FK snapped_segment_id REFERENCES road_segments(id) ON DELETE SET NULL
```

**`\d+ segment_scores` output:** crash_norm column present (`double precision NOT NULL DEFAULT 0.0`):
```
       Column        |           Type           | Nullable | Default
---------------------+--------------------------+----------+---------
 segment_id          | integer                  | not null |
 moderate_score      | double precision         |          | 0.0
 severe_score        | double precision         |          | 0.0
 pothole_score_total | double precision         |          | 0.0
 updated_at          | timestamp with time zone |          | now()
 crash_norm          | double precision         | not null | 0.0
```

**FK type check (Pitfall D — must be `integer`):**
```
integer
```

✓ All Phase 9 invariants verified on prod: POINT/4326 geom, INTEGER FK ON DELETE SET NULL, DROP-then-ADD CHECKs intact, all 3 indexes present (UNIQUE source+source_record_id, GIST geom, btree snapped_segment_id), `crash_norm` NOT NULL with 0.0 default.

---

## Section 4 — First LA City Ingest Run (Plan 12-02 Tasks 1+2)

**Status:** TBD
**Decision ref:** D-12-07, D-12-08, D-12-09
**Anti-pattern note:** `flyctl proxy` for the INSERT-side ingest is the v0.3.0 Phase 5 seed_data.py precedent — `proxy` is BANNED for DDL only. INSERT batching does not trigger the recovery loop.
**Acceptance:** Run completes with run-summary JSON per D-09-08 shape; `dropped_outside_snap` is logged.

**Pre-step — set Fly secret (if a token is available):**
```bash
# OPTIONAL — anonymous Socrata also works at lower rate limit (D-09-02).
flyctl secrets set LACITY_APP_TOKEN=<token> -a road-quality-backend
flyctl secrets list -a road-quality-backend | grep LACITY
```

**Ingest commands (operator host venv via flyctl proxy):**
```bash
# Terminal A — open the proxy
flyctl proxy 5432:5432 -a road-quality-db &
PROXY_PID=$!

# Terminal A — run the ingest from host venv
DATABASE_URL='postgresql://rq:<POSTGRES_PASSWORD>@127.0.0.1:5432/roadquality' \
LACITY_APP_TOKEN='<token-or-empty>' \
LACITY_SNAP_M=50.0 \
PYTHONPATH=backend:. \
/tmp/rq-venv/bin/python scripts/ingest_crashes.py --source lacity --summary-out /tmp/ingest-12-02.json

# Tear down
kill $PROXY_PID
```

**Run-summary JSON (D-09-08 10-key shape):**
```json
[paste /tmp/ingest-12-02.json verbatim]
```

**Key counters:**
- `fetched`: TBD
- `inserted`: TBD
- `skipped_duplicate`: TBD (≥0; idempotent re-run target)
- `dropped_outside_snap`: TBD (target <5% per D-09-03 runbook check)
- `errors`: TBD (must be 0 or documented)

**Deviations from CONTEXT:**
- [ ] LACITY_APP_TOKEN: TBD (set / token-less; document which)
- [ ] Other: none expected

---

## Section 5 — `compute_scores.py --source all` Recompute (Plan 12-02 Task 3)

**Status:** TBD
**Decision ref:** D-12-10
**Acceptance:** ≥100 segments with non-zero `crash_norm` post-recompute.

**Commands (operator host venv via flyctl proxy):**
```bash
flyctl proxy 5432:5432 -a road-quality-db &
PROXY_PID=$!

# Run all sources sequentially (synthetic + mapillary + crash)
DATABASE_URL='postgresql://rq:<POSTGRES_PASSWORD>@127.0.0.1:5432/roadquality' \
PYTHONPATH=backend:. \
/tmp/rq-venv/bin/python scripts/compute_scores.py --source all

# Verification SELECT
flyctl ssh console -a road-quality-db -C "psql -U rq -d roadquality -c 'SELECT COUNT(*) AS crash_bearing FROM segment_scores WHERE crash_norm > 0;'"

# Bonus — distribution check (Pitfall 5 sanity)
flyctl ssh console -a road-quality-db -C "psql -U rq -d roadquality -c 'SELECT MIN(crash_norm), AVG(crash_norm), MAX(crash_norm), COUNT(*) FROM segment_scores WHERE crash_norm > 0;'"

kill $PROXY_PID
```

**`compute_scores.py --source all` output:**
```
[paste]
```

**`COUNT(*) WHERE crash_norm > 0` result (≥100 acceptance):**
```
TBD
```

**Distribution (Pitfall 5 non-bimodal sanity):**
```
TBD — check crash_norm range; if AVG > 0.6 with high count, calibration may need revisit (Phase 13/v0.4.1)
```

---

## Section 6 — Push to Main → GH Actions Deploy (Plan 12-03 Task 1)

**Status:** TBD
**Decision ref:** D-12-11, D-12-12, D-12-13
**Acceptance:** GH Actions deploy.yml runs green on the Phase 9-12 commit set; backend + frontend redeploy.

**Commands:**
```bash
git push origin main   # 80+ commits ahead, including all of Phases 9-12
```

**GH Actions run URL:**
```
TBD — paste from https://github.com/Hratchg/road-quality-mvp/actions
```

**Job results:**
- `changes` (paths-filter): TBD
- `test` (host-venv pytest with --timeout=180): TBD (must pass; Phase 10 deferred-items rationale)
- `deploy-db` (Migration 004 already applied OUT-OF-BAND; this job redeploys the DB image only, NOT migrations): TBD
- `deploy-backend`: TBD
- `deploy-frontend`: TBD

**Note:** Migration 004 was applied via `flyctl ssh console -C` in Section 2. The `deploy-db` job in deploy.yml redeploys the DB Docker image, NOT migrations — that's the established v0.3.0 Phase 5 policy (D-12-13). No conflict.

---

## Section 7 — 3-Route Live Smoke (Plan 12-03 Task 2)

**Status:** TBD
**Decision ref:** D-12-14, D-12-15, D-12-16
**Acceptance:** All 3 routes return 200 in <5s (Phase 8 cold-cross-LA budget); response carries `Deprecation: weight_iri,weight_potholes ignored as of v0.4.0` header (Phase 10 D-10-15); `GET /segments?bbox=...` features include `crash_norm` field; Wilshire is NOT routed onto unsafe-arterial path (Pitfall 5 sanity).

**Routes to smoke (curl-equivalent — capture HTTP status, time, key headers):**

### Route A — DTLA-local (Pershing Square → Bunker Hill, ~1 mi)
```bash
time curl -sS -i -X POST https://road-quality-backend.fly.dev/route \
  -H 'Content-Type: application/json' \
  -d '{"origin":{"lat":34.0481,"lon":-118.2519},"destination":{"lat":34.0535,"lon":-118.2511},"max_extra_minutes":5}' | head -20
```
**Result:** TBD

### Route B — Cross-LA (Westwood → Boyle Heights, ~14 mi)
```bash
time curl -sS -i -X POST https://road-quality-backend.fly.dev/route \
  -H 'Content-Type: application/json' \
  -d '{"origin":{"lat":34.0635,"lon":-118.4455},"destination":{"lat":34.0335,"lon":-118.2156},"max_extra_minutes":10}' | head -20
```
**Result:** TBD (cold-LA budget <5s)

### Route C — Wilshire Pitfall-5 sanity (Mid-Wilshire arterial)
```bash
# Probe whether Mid-Wilshire segment crash_norm exceeds 0.5 (calibration warning if so)
curl -sS "https://road-quality-backend.fly.dev/segments?bbox=-118.36,-118.34,34.06,34.07" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
features = data.get('features', [])
high = [f for f in features if f.get('properties', {}).get('crash_norm', 0) > 0.5]
print(f'segments_in_bbox={len(features)}, crash_norm>0.5: {len(high)}')
if high:
    print('high-crash segments (potential Pitfall 5 saturation):')
    for f in high[:5]: print(' ', f.get('properties', {}))
"
```
**Result:** TBD (if Wilshire shows `crash_norm > 0.5`, calibration may need revisit; non-blocking for v0.4.0 close)

### Backwards-compat: legacy slider keys silently ignored (Phase 10 D-10-16)
```bash
curl -sS -i -X POST https://road-quality-backend.fly.dev/route \
  -H 'Content-Type: application/json' \
  -d '{"origin":{"lat":34.0481,"lon":-118.2519},"destination":{"lat":34.0535,"lon":-118.2511},"max_extra_minutes":5,"weight_iri":99,"weight_potholes":1,"include_iri":true,"include_potholes":true}' \
  | head -20
```
**Result:** TBD (must return identical geojson + total_cost as Route A; Deprecation header MUST be present)

---

## Section 8 — Frontend Live-Smoke (Plan 12-03 Task 3)

**Status:** TBD
**Decision ref:** D-12-14, D-12-16, Phase 11 hand-off
**Acceptance:** `road-quality-frontend.fly.dev` returns 200; bundled JS contains the locked disclaimer + caption strings (em dash U+2014).

**Commands:**
```bash
# 1. Frontend serves
curl -sS -I https://road-quality-frontend.fly.dev/ | head -5

# 2. Bundle contains locked disclaimer (Phase 11 D-11-04)
curl -sS https://road-quality-frontend.fly.dev/ | grep -oE 'src="/assets/index-[^"]+\.js"' | head -1
# Then fetch that JS file:
BUNDLE=$(curl -sS https://road-quality-frontend.fly.dev/ | grep -oE '/assets/index-[^"]+\.js' | head -1)
curl -sS "https://road-quality-frontend.fly.dev${BUNDLE}" | grep -oE 'Routes incorporate historical crash data[^"]{0,150}' | head -1
curl -sS "https://road-quality-frontend.fly.dev${BUNDLE}" | grep -oE 'Crash data: LA City open-data[^"]{0,150}' | head -1
```

**Frontend status:**
```
TBD
```

**Disclaimer string in bundle:**
```
TBD — must match `Routes incorporate historical crash data from LA City open-data (through March 2024). This is informational, not a safety guarantee — always drive defensively.` (em dash U+2014)
```

**Caption string in bundle:**
```
TBD — must match `Crash data: LA City open-data through March 2024. Single-segment attribution; intersection distribution to be added in a future release.`
```

---

## Section 9 — Sign-Off (Plan 12-03 Task 3)

**Status:** TBD
**Date:** TBD
**Operator:** hratchghanime@gmail.com

### REQ-crash-cloud-deploy acceptance verdict
- [ ] Pre-deploy `df -h` rehearsal: PASS / FAIL
- [ ] Migration 004 applied via `flyctl ssh console -C` (NOT `flyctl proxy`): PASS / FAIL
- [ ] First quarterly LA City ingest completed end-to-end: PASS / FAIL
- [ ] `compute_scores.py --source all` post-ingest with ≥100 segments crash_norm > 0: PASS / FAIL
- [ ] Backend + frontend redeployed via deploy.yml: PASS / FAIL
- [ ] Live `POST /route` returns 200 with Deprecation header in <5s cold cross-LA: PASS / FAIL
- [ ] Live `GET /segments?bbox=...` returns features with `crash_norm`: PASS / FAIL
- [ ] GH Actions deploy.yml passed for the v0.4.0 commit: PASS / FAIL
- [ ] First-deploy delta report committed under `.planning/phases/12-*/`: PASS (this file)

### REQ-route-filter-env-vars-doc acceptance verdict
- [x] `.env.example` lists `ROUTE_FILTER_BUFFER_DEG=0.03` and `ROUTE_FILTER_WIDEN_FACTOR=2.0` with descriptions: **PASS** (commit `d086c1b`)
- [x] `README.md` Configuration section documents both env vars + cross-links to `08-PERF-NUMBERS.md`: **PASS** (commit `f4c9bf1`)
- [x] `routing.py:22-23` inline cross-link header: **PASS** (commit `9acd3cc`)

### Deviations from CONTEXT.md
- [ ] Document any here

### Pitfall verdicts
- [ ] Pitfall 5 (academic-saturation): histogram non-bimodal — PASS / FAIL with crash_norm distribution data from Section 5
- [ ] Pitfall 7 (semantic ignore): legacy slider keys produce identical-route — PASS / FAIL with Section 7 backwards-compat curl
- [ ] Pitfall 9 (moment-of-decision disclaimer): bundle contains exact-locked string — PASS / FAIL with Section 8 grep

### Hand-offs to v0.4.1 / next milestone
- [ ] None expected unless Wilshire spot check (Section 7 Route C) flagged calibration drift

### v0.4.0 Milestone Close Verdict
**TBD** — fill in after all checkboxes resolved. Run `/gsd-verify-phase 12` and `/gsd-complete-milestone v0.4.0` once verdict is `passed`.

---

*Generated: 2026-05-08 by Plan 12-05 (D-12-20 scaffold).*
*Filled by: Plans 12-01 (Sections 1-3), 12-02 (Sections 4-5), 12-03 (Sections 6-9).*
