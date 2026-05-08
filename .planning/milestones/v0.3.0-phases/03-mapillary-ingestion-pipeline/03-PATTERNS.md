# Phase 3: Mapillary Ingestion Pipeline - Pattern Map

**Mapped:** 2026-04-25
**Files analyzed:** 11 (8 new, 3 modified)
**Analogs found:** 11 / 11

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `db/migrations/002_mapillary_provenance.sql` (NEW) | migration | DDL / batch | `db/migrations/001_initial.sql` | exact (only existing migration; same style) |
| `scripts/ingest_mapillary.py` (NEW) | script / CLI orchestrator | request-response + batch + spatial-match | `scripts/fetch_eval_data.py` (Mapillary CLI) + `scripts/ingest_iri.py` (DB-writing CLI w/ argparse + spatial match) | exact (composite — Mapillary client invocation + DB-writing CLI) |
| `scripts/compute_scores.py` (MODIFIED) | script / SQL CLI | batch / aggregation | `scripts/compute_scores.py` (self — extend; minimal change) | exact (in-place enhancement) |
| `data_pipeline/ingest.py` (OPTIONAL NEW helpers) | utility module | pure functions | `scripts/iri_sources.py` (helper module imported by CLI) | exact (same script-helper split convention) |
| `backend/tests/test_ingest_mapillary.py` (NEW) | test (unit) | mocked I/O | `backend/tests/test_mapillary.py` (mocked Mapillary unit tests) + `backend/tests/test_finetune_detector.py` (subprocess CLI smoke) | exact (composite) |
| `backend/tests/test_integration.py` (EXTEND) | test (integration) | live DB + HTTP | `backend/tests/test_integration.py` (self — add tests; auto-skip-when-DB-down pattern preserved) | exact (in-place extension) |
| `data/ingest_la/.gitkeep` (NEW) | config / placeholder | filesystem | `data/eval_la/.gitkeep` | exact |
| `.gitignore` (MODIFIED) | config | text | `.gitignore` lines 36-39 (`data/eval_la/*` block) | exact (adjacent block, same shape) |
| `docker-compose.yml` (MODIFIED) | config | YAML mount | `docker-compose.yml:11` (`001_initial.sql` mount) | exact (mirror new mount line) |
| `docs/MAPILLARY_INGEST.md` (NEW) | documentation | markdown | (no exact analog; closest reference is `scripts/fetch_eval_data.py:1-46` runbook docstring) | partial (documentation tier; freeform but cite Phase 2 patterns) |
| `README.md` (MODIFIED) | documentation | markdown | `README.md` (self — add section pointing to docs/MAPILLARY_INGEST.md) | exact (in-place link addition) |

## Pattern Assignments

### `db/migrations/002_mapillary_provenance.sql` (migration, DDL)

**Analog:** `db/migrations/001_initial.sql`

**Imports / preamble pattern** — none; plain SQL, no header comment in 001. Phase 3 SHOULD add a leading comment block per RESEARCH.md Pattern 1 (no analog enforces this; the analog itself has no preamble).

**Idempotent DDL pattern** (001_initial.sql:1-25):
```sql
CREATE TABLE IF NOT EXISTS road_segments (
    id            SERIAL PRIMARY KEY,
    osm_way_id    BIGINT,
    geom          GEOMETRY(LineString, 4326) NOT NULL,
    ...
);

CREATE INDEX IF NOT EXISTS idx_segments_geom ON road_segments USING GIST(geom);
```

Key conventions to copy:
- `IF NOT EXISTS` everywhere
- Trailing comma style, lowercase types in CHECK clauses
- Index naming: `idx_<table>_<column>` (lowercase, underscore-separated)
- `CHECK (severity IN ('moderate', 'severe'))` style is the canon for enum-like text columns (line 21)

**Phase 3 additions** (not in analog — see RESEARCH.md Pattern 1 verbatim):
- `ALTER TABLE ... ADD COLUMN IF NOT EXISTS source_mapillary_id TEXT;`
- `ALTER TABLE ... ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'synthetic';`
- DROP-then-ADD CHECK constraint (Postgres 16 has no `ADD CONSTRAINT IF NOT EXISTS`)
- `CREATE UNIQUE INDEX IF NOT EXISTS uniq_defects_segment_source_severity ...`
- Plain `UNIQUE` (NULL-distinct default) — NOT `NULLS NOT DISTINCT` (RESEARCH.md correction)

---

### `scripts/ingest_mapillary.py` (script / CLI orchestrator)

**Primary analog:** `scripts/fetch_eval_data.py` — Mapillary client invocation pattern + multi-mode argparse with mutex group.
**Secondary analog:** `scripts/ingest_iri.py` — DB-writing CLI with PostGIS spatial-match in a per-record loop.

**Imports pattern** (fetch_eval_data.py:47-69):
```python
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import shutil
import sys
from pathlib import Path

# Ensure project root is importable (so data_pipeline.* resolves when this
# script is run directly from the repo root)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_pipeline.mapillary import (  # noqa: E402
    MAPILLARY_TOKEN,
    download_image,
    search_images,
    validate_bbox,
    verify_manifest,
    write_manifest,
)

logger = logging.getLogger(__name__)
```

Phase 3 adds: `from data_pipeline.detector_factory import get_detector`, `import psycopg2`, `from psycopg2 import sql as psql`, `from psycopg2.extras import execute_values`. Module-top env vars: `MAPILLARY_TOKEN` (re-exported from data_pipeline.mapillary), `DATABASE_URL` (mirrored from `backend/app/db.py:5-7`).

**Exit-code constants pattern** (fetch_eval_data.py:73-76):
```python
# D-18 exit codes
EXIT_OK = 0
EXIT_OTHER = 1
EXIT_MISSING_DATA = 3
```
Phase 3 adds: `EXIT_VALIDATION = 2` (used when `--where` matches 0 segments — Pitfall 9).

**argparse mutex-group pattern** (fetch_eval_data.py:318-329):
```python
group = parser.add_mutually_exclusive_group()
group.add_argument(
    "--verify-only",
    action="store_true",
    default=False,
    help="Hash-check existing dataset (default mode when neither flag set)",
)
group.add_argument(
    "--build",
    action="store_true",
    help="Fresh pull from Mapillary (requires MAPILLARY_ACCESS_TOKEN)",
)
```
Phase 3 wraps `--segment-ids`, `--segment-ids-file`, `--where` in `parser.add_mutually_exclusive_group(required=True)` — same shape, but with `required=True` because there is no implicit default mode.

**Token-precondition pattern** (fetch_eval_data.py:104-110):
```python
if not MAPILLARY_TOKEN:
    print(
        "ERROR: --build requires MAPILLARY_ACCESS_TOKEN. "
        "Get a token at https://www.mapillary.com/dashboard/developers",
        file=sys.stderr,
    )
    return EXIT_OTHER
```
Phase 3 copies verbatim with the message tweaked to `"ingest_mapillary requires MAPILLARY_ACCESS_TOKEN"`.

**Per-bbox / per-image loop pattern** (fetch_eval_data.py:135-189):
```python
all_fetched: list[dict] = []
for zone, bbox in _DEFAULT_LA_BBOXES.items():
    logger.info("Searching Mapillary in zone=%s bbox=%s", zone, bbox)
    results = search_images(bbox, limit=count_per_bbox)
    logger.info("  got %d results", len(results))
    all_fetched.extend([{**r, "_zone": zone} for r in results])

# Download in the same pass as metadata (Pitfall 5: URL TTL).
for img in all_fetched:
    ...
    try:
        written = download_image(img, out_dir)
    except Exception as exc:  # noqa: BLE001
        logger.warning("  download failed for %s: %s", img.get("id"), exc)
        continue
```
Phase 3 mirrors this — `validate_bbox` BEFORE network I/O, search-then-download in single pass, `try/except + continue` on per-image failure.

**Manifest write pattern** (fetch_eval_data.py:170-189, 230-240):
```python
manifest_entries.append(
    {
        "path": rel,
        "source_mapillary_id": str(img["id"]),
        "sequence_id": seq,
        "split": split,
    }
)
...
write_manifest(
    manifest_path,
    manifest_entries,
    source_bucket=f"mapillary:bboxes={list(_DEFAULT_LA_BBOXES.keys())}",
    license_str=(
        "CC-BY-SA 4.0 (Mapillary open imagery -- "
        "attribution via source_mapillary_id)"
    ),
)
```
Phase 3 adds `matched_segment_id` and `snap_meters` to each entry; uses `source_bucket="mapillary:per-segment-targeted-ingest"`. **Caveat from RESEARCH.md Pattern 5: write manifest BEFORE `--no-keep` unlinks** because `write_manifest` reads files for SHA256.

**Spatial-match in per-record loop pattern** (ingest_iri.py:64-91):
```python
def _spatial_match_and_update(
    conn, records: list[dict], batch_size: int = 500
) -> int:
    cur = conn.cursor()
    updated = 0

    for i, rec in enumerate(records):
        lat = rec["latitude"]
        lon = rec["longitude"]
        iri = rec["iri_value"]

        # Find the nearest segment and update it
        cur.execute("""
            UPDATE road_segments
            SET iri_value = %s
            WHERE id = (
                SELECT id FROM road_segments
                ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
                LIMIT 1
            )
        """, (iri, lon, lat))
        ...
```
Phase 3 mirrors the per-record loop shape but for SELECT-not-UPDATE (snap-match returns segment_id), and uses `ST_DWithin + ORDER BY <-> + LIMIT 1` from RESEARCH.md Pattern 3 (longitude-first `ST_MakePoint(lon, lat)` — note ingest_iri passes `(lon, lat)` correctly at line 81).

**Idempotent batch INSERT pattern** (seed_data.py:78-83, 115-121):
```python
insert_sql = """
    INSERT INTO road_segments (osm_way_id, geom, length_m, travel_time_s, source, target, iri_value)
    VALUES %s
"""
template = "(%s, ST_GeomFromText(%s, 4326), %s, %s, %s, %s, %s)"
execute_values(cur, insert_sql, seg_values, template=template, page_size=1000)
conn.commit()
```
Plus seed_data.py:115-121 (the segment_defects insert):
```python
execute_values(
    cur,
    "INSERT INTO segment_defects (segment_id, severity, count, confidence_sum) VALUES %s",
    defect_values,
    page_size=1000,
)
conn.commit()
```
Phase 3 extends to 6 columns (adds `source_mapillary_id`, `source`) and appends `ON CONFLICT (segment_id, source_mapillary_id, severity) DO NOTHING` per RESEARCH.md Pattern 4. Use `cur.rowcount` after `execute_values` for inserted-count (skips conflict-skipped).

**Subprocess-chain pattern for triggering compute_scores.py** — no exact analog in the codebase; closest reference is the documented behavior in CONTEXT.md D-14 ("triggers `compute_scores.py` after"). Use `subprocess.run([sys.executable, str(REPO_ROOT / "scripts/compute_scores.py")], check=True)`. Add `--no-recompute` flag (RESEARCH.md Open Question #3 recommendation).

**Logging-config pattern** (ingest_iri.py:218-225):
```python
log_level = logging.DEBUG if args.verbose else logging.INFO
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
```
Phase 3 copies verbatim.

**Connection + try/except/finally pattern** (ingest_iri.py:231-253):
```python
print(f"Connecting to database...")
try:
    conn = psycopg2.connect(db_url)
except psycopg2.OperationalError as exc:
    print(f"ERROR: Cannot connect to database: {exc}")
    sys.exit(1)

try:
    if args.source == "csv":
        ingest_csv(conn, args.path)
    ...
except Exception as exc:
    conn.rollback()
    print(f"ERROR: Ingestion failed: {exc}")
    raise
finally:
    conn.close()
    print("Database connection closed.")
```
Phase 3 mirrors this exactly.

---

### `scripts/compute_scores.py` (MODIFIED — add `--source` flag, D-16)

**Analog:** itself (existing 43-line script).

**Existing core SQL pattern** (compute_scores.py:15-31):
```python
cur.execute("""
    INSERT INTO segment_scores (segment_id, moderate_score, severe_score, pothole_score_total)
    SELECT
        rs.id,
        COALESCE(SUM(CASE WHEN sd.severity = 'moderate' THEN 0.5 * sd.count * sd.confidence_sum ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN sd.severity = 'severe' THEN 1.0 * sd.count * sd.confidence_sum ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN sd.severity = 'moderate' THEN 0.5 * sd.count * sd.confidence_sum ELSE 0 END), 0)
        + COALESCE(SUM(CASE WHEN sd.severity = 'severe' THEN 1.0 * sd.count * sd.confidence_sum ELSE 0 END), 0)
    FROM road_segments rs
    LEFT JOIN segment_defects sd ON rs.id = sd.segment_id
    GROUP BY rs.id
    ON CONFLICT (segment_id) DO UPDATE SET
        moderate_score = EXCLUDED.moderate_score,
        severe_score = EXCLUDED.severe_score,
        pothole_score_total = EXCLUDED.pothole_score_total,
        updated_at = NOW()
""")
```

**Modification per RESEARCH.md Pattern 7** — apply source filter at JOIN time (not WHERE), to preserve LEFT JOIN's "every segment present" property:
```python
where_clause = "" if args.source == "all" else "AND sd.source = %s"
params = () if args.source == "all" else (args.source,)
sql = f"""
    INSERT INTO segment_scores ...
    LEFT JOIN segment_defects sd ON rs.id = sd.segment_id {where_clause}
    GROUP BY rs.id
    ON CONFLICT ...
"""
cur.execute(sql, params)
```
Add argparse with `choices=("synthetic", "mapillary", "all")`, `default="all"`. Wire main() to `return 0`/`int` and `sys.exit(main())` if not already.

---

### `data_pipeline/ingest.py` (OPTIONAL NEW — pure helper module)

**Analog:** `scripts/iri_sources.py`

**Module structure pattern** (iri_sources.py:1-38):
```python
"""IRI data source module: load real IRI data or generate improved synthetic IRI.

Supports two tiers of IRI data ingestion:
...
"""

from __future__ import annotations

import csv
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)
```

Then pure functions imported by the CLI (`scripts/ingest_iri.py:34-39` shows the import contract):
```python
from iri_sources import (
    load_iri_from_csv,
    load_iri_from_shapefile,
    generate_improved_synthetic_iri,
    normalize_iri,
)
```

Phase 3 only creates this if `scripts/ingest_mapillary.py` exceeds ~250 lines (RESEARCH.md Architectural Responsibility Map). Default = inline. Candidate helpers if extracted: `compute_padded_bbox`, `subdivide_bbox`, `snap_match_image`, `aggregate_detections`, `with_retry`, `validate_where_predicate`, `resolve_targets`.

---

### `backend/tests/test_ingest_mapillary.py` (NEW — unit tests)

**Primary analog:** `backend/tests/test_mapillary.py` — Phase 2 pure-unit pattern with `unittest.mock.MagicMock + patch`, no network, no token.
**Secondary analog:** `backend/tests/test_finetune_detector.py` — subprocess-smoke pattern for CLI scripts.
**Tertiary analog:** `backend/tests/test_eval_detector.py` — combined unit + subprocess CLI smoke at line 175-214.

**sys.path bootstrap pattern** (test_mapillary.py:19-20 + test_eval_detector.py:18-21):
```python
# Project root importable so data_pipeline.* resolves from any CWD
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from data_pipeline.mapillary import (  # noqa: E402
    ...
)
```

**Subprocess smoke pattern** (test_finetune_detector.py:22-50, test_eval_detector.py:182-214):
```python
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
SCRIPT = os.path.join(REPO_ROOT, "scripts", "finetune_detector.py")


class TestFinetuneDetectorCLI:
    def test_help_lists_all_flags(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "--help"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stderr
        for flag in [
            "--data", "--base", "--epochs", "--batch", ...
        ]:
            assert flag in result.stdout, f"Missing flag {flag}"
```

**Token-fast-fail pattern** (test_finetune_detector.py:62-97):
```python
def test_push_without_token_exits_1(self):
    env = os.environ.copy()
    env.pop("HUGGINGFACE_TOKEN", None)
    fixture = os.path.join(
        REPO_ROOT, "backend/tests/fixtures/eval_fixtures/data.yaml"
    )
    result = subprocess.run(
        [sys.executable, SCRIPT, "--data", fixture, "--push-to-hub", "user/test"],
        capture_output=True, text=True, cwd=REPO_ROOT, env=env,
    )
    assert result.returncode == 1
    assert "HUGGINGFACE_TOKEN" in result.stderr
```
Phase 3 mirrors for `MAPILLARY_ACCESS_TOKEN` exit-1 with helpful error (D-19; SC #5 grep test).

**Mocked-requests unit pattern** (test_mapillary.py:118-135):
```python
def test_search_uses_token_arg(self):
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "data": [{"id": "123", "thumb_2048_url": "http://x"}]
    }
    fake_response.raise_for_status = MagicMock()
    with patch(
        "data_pipeline.mapillary.requests.get", return_value=fake_response
    ) as mock_get:
        results = search_images(
            (-118.25, 34.04, -118.24, 34.05), token="fake_token", limit=10
        )
        assert len(results) == 1
        ...
```
Phase 3 unit tests for `--where` injection / target-resolution / aggregate_detections use mocked `psycopg2.connect` cursor (mock `cur.execute` + `cur.fetchall`/`fetchone`).

**Test classes for Phase 3 (per RESEARCH.md Validation Architecture):**
- `TestTargetResolution` — `--segment-ids`, `--segment-ids-file`, `--where` resolve correctly
- `TestWhereInjection` — forbidden tokens raise; `--` and `;` rejected; empty match exits 2
- `TestSnapMatch` — snap-match returns nearest within radius; returns None outside
- `TestAggregateDetections` — group by severity, count + confidence_sum shape
- `TestRetry` — 429 retries, 4xx raises immediately
- `TestCLIExitCodes` — `--help` exits 0, missing token exits 1, no-targets exits 2

---

### `backend/tests/test_integration.py` (EXTEND — add Phase 3 SC tests)

**Analog:** itself.

**Integration-marker pattern** (test_integration.py:11):
```python
import pytest
pytestmark = pytest.mark.integration
```
Auto-skip-when-DB-unreachable comes from `conftest.py:13-21`'s `db_available` fixture; Phase 3 tests must accept `db_conn` or `client` fixtures (which depend on `db_available`) so they auto-skip.

**Existing endpoint-test pattern** (test_integration.py:21-32):
```python
def test_segments_returns_geojson(client):
    resp = client.get(f"/segments?bbox={LA_BBOX}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) > 0

    feat = data["features"][0]
    assert feat["geometry"]["type"] == "LineString"
    for key in ("id", "iri_norm", "moderate_score", "severe_score", "pothole_score_total"):
        assert key in feat["properties"]
```

**Tests Phase 3 must add (per RESEARCH.md Validation Architecture line 1089-1104):**
- `test_ingest_mapillary_end_to_end` (SC #1) — invoke CLI via subprocess with mocked Mapillary (env-stub or `monkeypatch.setattr` on the module), assert rows in `segment_defects WHERE source='mapillary'`
- `test_ingest_mapillary_idempotent_rerun` (SC #2) — run twice, assert row count unchanged
- `test_segments_reflects_mapillary_after_compute_scores` (SC #3) — ingest → recompute → `client.get('/segments?bbox=...')` shows the matched segment with `pothole_score_total > 0`
- `test_route_ranks_differ_by_source` (SC #4) — `compute_scores --source synthetic` then capture `/route` cost, then `--source mapillary`, assert costs differ
- `test_unique_constraint_dedups_mapillary` (D-05) — manual INSERT same `(seg, src_mly, sev)` twice, assert second is skipped
- `test_existing_rows_backfill_synthetic_source` (D-07) — post-migration assert `SELECT COUNT(*) FROM segment_defects WHERE source='synthetic'` matches pre-migration count
- `test_wipe_synthetic_preserves_mapillary` (D-14) — seed both, run `--wipe-synthetic`, assert mapillary rows survive
- `test_compute_scores_source_filter` (D-16) — verify only matching-source detections contribute

---

### `data/ingest_la/.gitkeep` (NEW)

**Analog:** `data/eval_la/.gitkeep` (referenced by `.gitignore:39`).

Empty file. Pattern: `touch data/ingest_la/.gitkeep`.

---

### `.gitignore` (MODIFIED)

**Analog:** `.gitignore` lines 36-39:
```
data/eval_la/*
!data/eval_la/manifest.json
!data/eval_la/data.yaml
!data/eval_la/.gitkeep
```

Phase 3 adds an adjacent block (Pitfall 10):
```
data/ingest_la/*
!data/ingest_la/.gitkeep
```
(No `manifest.json` whitelist since per-run manifests are run-timestamped under per-segment dirs, ephemeral by design — but the planner may opt to whitelist a top-level latest-manifest.json if useful for SC #4 archival.)

---

### `docker-compose.yml` (MODIFIED)

**Analog:** `docker-compose.yml:11`:
```yaml
- ./db/migrations/001_initial.sql:/docker-entrypoint-initdb.d/02-schema.sql
```

Phase 3 adds an adjacent line:
```yaml
- ./db/migrations/002_mapillary_provenance.sql:/docker-entrypoint-initdb.d/03-mapillary.sql
```
RESEARCH.md Runtime State Inventory: Postgres only runs `docker-entrypoint-initdb.d/` scripts on FRESH init. For existing volumes, document the manual `docker compose exec -T db psql -U rq -d roadquality < db/migrations/002_*.sql` apply in `docs/MAPILLARY_INGEST.md`.

---

### `docs/MAPILLARY_INGEST.md` (NEW)

**Closest analog:** the docstring runbook at the top of `scripts/fetch_eval_data.py:1-46`:
```python
"""Fetch or verify the LA pothole eval dataset.

Modes:
    --verify-only (default): hash-check every file in data/eval_la/
                             ...

Usage:
    # Verify (default, safe):
    python scripts/fetch_eval_data.py
    ...

Exit codes (D-18):
    0 = OK
    ...

Licensing:
    Mapillary imagery is CC-BY-SA 4.0. ...
"""
```

No first-class markdown runbook exists in `docs/` for any other phase script. Phase 3 invents the format. Sections to mirror from the docstring style:
- Overview / what it does
- Modes & flags table
- Quickstart commands (segment-ids, --where, --wipe-synthetic)
- Trust model for `--where` (RESEARCH.md Pattern 6)
- Migration apply for existing dev DBs (RESEARCH.md Runtime State Inventory)
- SC #4 ranking-comparison workflow (RESEARCH.md Validation Architecture line 1119-1129)
- CC-BY-SA attribution requirement
- Pitfalls 4 (cache), 5 (drift to neighbors), 7 (`--source mapillary` empty)
- Phase 6 cutover sequence (`--wipe-synthetic` + recompute + smoke `/route`)

---

### `README.md` (MODIFIED)

**Analog:** itself.

Add a "Real-Data Ingest" section with a one-line link to `docs/MAPILLARY_INGEST.md`. Pattern: any existing doc link in README (no specific line range required; planner places contextually).

---

## Shared Patterns

### Pattern S-1: Module-top env-var read

**Source:** `backend/app/db.py:5-7` (canonical), mirrored in `data_pipeline/mapillary.py:49`, `scripts/seed_data.py:15-17`, `scripts/compute_scores.py:6-8`, `scripts/ingest_iri.py:41-43`, `scripts/eval_detector.py:51`, `scripts/finetune_detector.py:57`.

**Apply to:** `scripts/ingest_mapillary.py`, modified `scripts/compute_scores.py`.

```python
import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)
```
For `MAPILLARY_ACCESS_TOKEN`: re-export from `data_pipeline.mapillary` rather than re-reading; the import side-effect happens at module load.

---

### Pattern S-2: D-18 exit codes

**Source:** Phase 2 D-18 (constant block at the top of every script).
- `scripts/fetch_eval_data.py:73-76`
- `scripts/eval_detector.py:55-59`
- `scripts/finetune_detector.py:61-64`

```python
EXIT_OK = 0
EXIT_OTHER = 1
EXIT_VALIDATION = 2     # for --where matches 0 segments (Pitfall 9), --min-precision floor
EXIT_MISSING_RESOURCE = 3
```
Phase 3: ingest_mapillary.py uses 0/1/2/3; compute_scores.py keeps 0 (no failure modes).

---

### Pattern S-3: sys.path bootstrap for `data_pipeline.*` imports

**Source:** `scripts/fetch_eval_data.py:58-60`, `scripts/eval_detector.py:44-46`, `scripts/finetune_detector.py:53`, `scripts/ingest_iri.py:31-32`. Test variant: `backend/tests/test_mapillary.py:19-20`.

```python
# Ensure project root is importable (so data_pipeline.* resolves when this
# script is run directly from the repo root)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

**Apply to:** every new file in `scripts/` and `backend/tests/`.

---

### Pattern S-4: SEED = 42 project convention

**Source:** `scripts/seed_data.py:22`, `scripts/fetch_eval_data.py:151` (uses `random.Random(42)`), `scripts/finetune_detector.py:67`, `data_pipeline/eval.py::DEFAULT_SEED` (asserted in `test_eval_detector.py:99-100`).

**Apply to:** any new file that introduces randomness. Phase 3's expected randomness sources are `with_retry` jitter (if used) and any test-fixture seeding. Default: `SEED = 42`.

---

### Pattern S-5: Logging setup

**Source:** `scripts/ingest_iri.py:218-225`, `scripts/eval_detector.py`, `scripts/finetune_detector.py`.

```python
log_level = logging.DEBUG if args.verbose else logging.INFO
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
```
**Apply to:** `scripts/ingest_mapillary.py`. Module-top `logger = logging.getLogger(__name__)`.

---

### Pattern S-6: psycopg2 parameterized queries (anti-injection)

**Source:** `scripts/ingest_iri.py:73-81` (named-style here uses `%s` positional, not `%(name)s` — both project styles exist). `scripts/seed_data.py:91-94`, `scripts/iri_sources.py:357-367`.

```python
cur.execute("""
    UPDATE road_segments
    SET iri_value = %s
    WHERE id = (
        SELECT id FROM road_segments
        ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
        LIMIT 1
    )
""", (iri, lon, lat))
```

**Apply to:** every CLI SQL operation in Phase 3 (snap-match, padded-bbox query, segment-id resolution, INSERT, the `--source` filter, the `--wipe-synthetic` DELETE). For operator-supplied SQL (`--where`), use `psycopg2.sql.SQL` composition + the regex blocklist per RESEARCH.md Pattern 6.

---

### Pattern S-7: PostGIS geography-cast for meter ops

**Source:** `scripts/iri_sources.py:357-367` for `ST_DWithin(geom::geography, geom::geography, meters)`. `scripts/ingest_iri.py:78` for `geom <-> ST_SetSRID(ST_MakePoint(lon, lat), 4326)` KNN.

```python
cur.execute("""
    SELECT a.id AS seg_id, b.id AS neighbor_id
    FROM road_segments a
    JOIN road_segments b ON a.id != b.id
        AND ST_DWithin(
            a.geom::geography,
            b.geom::geography,
            %s
        )
    WHERE a.id = ANY(%s)
""", (NEIGHBOR_RADIUS_METERS, batch_ids))
```

**Apply to:** snap-match query (Pattern 3 in RESEARCH.md), bbox-padding query (Pattern 2 helper). Anti-pattern reminder: never `ST_Buffer(geom, 50)` without `::geography` — would mean 50 degrees.

---

### Pattern S-8: Auto-skip-when-DB-unreachable for integration tests

**Source:** `backend/tests/conftest.py:13-21` defines `db_available` fixture; `backend/tests/test_integration.py:11` declares `pytestmark = pytest.mark.integration`.

```python
@pytest.fixture(scope="session")
def db_available():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        return True
    except psycopg2.OperationalError:
        pytest.skip("Database not available — skipping integration tests")
```

**Apply to:** every Phase 3 test that touches a live DB. Use `client` or `db_conn` fixture (both depend on `db_available`) so the auto-skip is inherited.

---

### Pattern S-9: Mapillary client reuse (NEVER reimplement)

**Source:** D-20 lock + `data_pipeline/mapillary.py` (entire surface). `scripts/fetch_eval_data.py:62-69` is the canonical import.

```python
from data_pipeline.mapillary import (  # noqa: E402
    MAPILLARY_TOKEN,
    download_image,
    search_images,
    validate_bbox,
    verify_manifest,
    write_manifest,
)
```

**Apply to:** `scripts/ingest_mapillary.py`. RESEARCH.md "Don't Hand-Roll" table. Phase 3 wraps these — never modifies them. Pre-merge verification: `git diff main HEAD -- data_pipeline/mapillary.py` should be empty.

---

### Pattern S-10: Detector factory single-injection-point

**Source:** `data_pipeline/detector_factory.py::get_detector` (Phase 2 D-14).

```python
from data_pipeline.detector_factory import get_detector

detector = get_detector(use_yolo=True)  # one model load for the entire run
detections = detector.detect(str(local_path))  # returns list[Detection]
```

**Apply to:** `scripts/ingest_mapillary.py` once at startup (after token validation, before per-segment loop). Reads `YOLO_MODEL_PATH` env var via the factory; CLI does not handle model resolution itself.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `docs/MAPILLARY_INGEST.md` | documentation | markdown | No first-class markdown runbook in `docs/` for any other phase script. Closest is the docstring runbook at the top of `scripts/fetch_eval_data.py:1-46`. Planner invents the format using that docstring as a structural guide. |

(All other files have strong analogs.)

---

## Metadata

**Analog search scope:**
- `data_pipeline/` (all *.py)
- `scripts/` (all *.py)
- `db/migrations/` (all *.sql)
- `backend/app/` (db.py for env-var pattern; routes/ skipped — Phase 3 is read-only on the API)
- `backend/tests/` (test_mapillary.py, test_finetune_detector.py, test_eval_detector.py, test_iri_ingestion.py, test_integration.py, test_fetch_eval_data.py, conftest.py)
- `docker-compose.yml`, `.gitignore`, `data/eval_la/.gitkeep`

**Files scanned:** 17 (full reads where relevant; targeted reads on the 1252-line RESEARCH.md and the 408-line fetch_eval_data.py)

**Pattern extraction date:** 2026-04-25

**Key insight reaffirming RESEARCH.md:** Phase 3 is a 200–400 line orchestrator on top of three pre-existing libraries (`data_pipeline.mapillary`, `data_pipeline.detector_factory`, psycopg2). Every new file has at least one strong existing analog. The only freeform deliverable is `docs/MAPILLARY_INGEST.md`. If the planner finds themselves writing >600 LOC of new Python or inventing patterns not present in the analogs above, something is being reinvented.
