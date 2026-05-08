"""LA City Socrata → crash_records ingestion pipeline (Phase 9, REQ-crash-ingest-lacity).

Operator-facing CLI:
    # Live ingest (Phase 12 operator runbook):
    python scripts/ingest_crashes.py --source lacity

    # Override window:
    python scripts/ingest_crashes.py --source lacity \\
        --start-date 2020-01-01 --end-date 2024-03-01

    # Integration-test path (no live network — D-09-06):
    python scripts/ingest_crashes.py --source lacity \\
        --csv data/crashes_la/lacity_fixture.csv

    # Tighter snap radius:
    python scripts/ingest_crashes.py --source lacity --snap-meters 25

    # Capture run-summary to file:
    python scripts/ingest_crashes.py --source lacity \\
        --summary-out /tmp/run-summary.json

Workflow per row:
    1. Read mocodes → map_mocodes_to_severity (fail row on ValueError)
    2. Parse location_1 (or lat/lon CSV columns) → (lon, lat)
    3. Parse date_occ → date
    4. snap_point_to_segment(lon, lat, snap_meters) → (seg_id, dist_m)
    5. If seg_id is None: counters["dropped_outside_snap"] += 1; continue
    6. Queue (source='lacity', dr_no, severity, date, seg_id, dist_m, lon, lat)
    7. After loop: execute_values INSERT ON CONFLICT DO NOTHING RETURNING 1
    8. Emit run-summary JSON (D-09-08 shape) to stdout + optional --summary-out

Operator environment (D-09-19):
    Run from host /tmp/rq-venv (Python 3.12) — backend container does NOT
    mount scripts/. DATABASE_URL connects to local stack OR Fly DB.
    LACITY_APP_TOKEN is OPTIONAL (anonymous Socrata works at lower rate
    limit per D-09-20). Token loaded via project's Python .env parser
    (memory pin: never `source .env`; tokens contain pipes).

Exit codes (matching scripts/ingest_mapillary.py convention):
    0 OK
    1 generic error (DB connection failed)
    2 validation error (--start-date / --end-date malformed; --source not 'lacity')
    3 missing resource (--csv path doesn't exist)
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import logging
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

import psycopg2
from psycopg2.extras import execute_values

# Pattern S-3 from ingest_mapillary.py: project-root importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_pipeline.lacity_socrata import iter_crashes  # noqa: E402
from data_pipeline.lacity_mocodes import map_mocodes_to_severity  # noqa: E402
from data_pipeline.snap import snap_point_to_segment  # noqa: E402

logger = logging.getLogger(__name__)

# Pattern S-1: module-top env-var read (matches backend/app/db.py:5-7).
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)

# D-09-03: env-tunable snap radius default 50m.
DEFAULT_SNAP_METERS = float(os.environ.get("LACITY_SNAP_M", "50.0"))

# D-09-01: anchored 5-year pre-freeze window.
DEFAULT_START_DATE = "2019-03-01"
DEFAULT_END_DATE = "2024-03-01"

# Default LA City viewbox (ymin, xmin, ymax, xmax).
DEFAULT_BBOX = "33.7,-118.7,34.4,-118.0"

# Exit codes (Pattern S-2; mirror ingest_mapillary.py).
EXIT_OK = 0
EXIT_OTHER = 1
EXIT_VALIDATION = 2
EXIT_MISSING_RESOURCE = 3


def parse_location_1(loc: dict | None) -> tuple[float, float]:
    """Parse Socrata location_1 nested object → (lon, lat).

    Raises ValueError on missing or malformed input. Pitfall B (09-RESEARCH.md):
    a small fraction of LA City rows have null location_1 (location-suppressed).
    The driver's per-row try/except catches ValueError and increments
    counters['errors'] so the run continues.
    """
    if not loc or "latitude" not in loc or "longitude" not in loc:
        raise ValueError(f"missing lat/lon in location_1: {loc!r}")
    return (float(loc["longitude"]), float(loc["latitude"]))


def parse_date_occ(s: str) -> _dt.date:
    """Parse Socrata date_occ string → date.

    Pitfall F (09-RESEARCH.md): Socrata returns "2021-09-02T00:00:00.000" with
    a `.000` ms suffix and no Z timezone. Python 3.11+ fromisoformat accepts
    both forms; project pin is 3.12.
    """
    # Defensive: strip trailing Z if present (Socrata sometimes adds it).
    cleaned = s.replace("Z", "")
    return datetime.fromisoformat(cleaned).date()


def iter_csv_rows(csv_path: Path) -> Iterator[dict]:
    """Read a committed CSV fixture and yield dicts in the same shape iter_crashes
    yields (so the per-row loop is source-agnostic). The CSV has flat columns
    (latitude, longitude); we wrap them into a location_1 dict to match Socrata.

    Used for integration tests per D-09-06 (no live API in CI).
    """
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield {
                "dr_no": row["dr_no"],
                "date_occ": row["date_occ"],
                "mocodes": row["mocodes"],
                "location_1": {
                    "latitude": row["latitude"],
                    "longitude": row["longitude"],
                },
            }


def quantile(values: list[float], q: int) -> float:
    """stdlib statistics.quantiles wrapper. Returns 0.0 on empty input.

    `q` is the percentile [1..100]. statistics.quantiles(xs, n=100) returns
    99 cut points; index q-1 picks the qth percentile. Returns max(values)
    when q == 100 (which statistics.quantiles doesn't include).
    """
    if not values:
        return 0.0
    if q == 100:
        return max(values)
    if len(values) < 2:
        # statistics.quantiles requires at least 2 data points.
        return values[0]
    return statistics.quantiles(values, n=100)[q - 1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "LA City Socrata → crash_records ingestion pipeline. "
            "Reads either the live Socrata API or a committed CSV fixture, "
            "snaps each crash to the nearest road segment, and writes "
            "idempotent rows into crash_records."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source", required=True, choices=["lacity"],
        help="Crash data source (only 'lacity' in v0.4.0; 'switrs' deferred)",
    )
    parser.add_argument(
        "--start-date", default=DEFAULT_START_DATE,
        help=f"ISO start date (default: {DEFAULT_START_DATE} per D-09-01)",
    )
    parser.add_argument(
        "--end-date", default=DEFAULT_END_DATE,
        help=f"ISO end date, exclusive (default: {DEFAULT_END_DATE} per D-09-01)",
    )
    parser.add_argument(
        "--snap-meters", type=float, default=DEFAULT_SNAP_METERS,
        help=f"Snap-match radius in meters (default {DEFAULT_SNAP_METERS}; "
             "env: LACITY_SNAP_M)",
    )
    parser.add_argument(
        "--bbox", default=DEFAULT_BBOX,
        help="LA viewbox 'ymin,xmin,ymax,xmax' (default LA full)",
    )
    parser.add_argument(
        "--csv", type=Path, default=None,
        help="Read from a CSV fixture instead of live Socrata (D-09-06; "
             "integration-test path)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Cap rows fetched (testing only)",
    )
    parser.add_argument(
        "--summary-out", type=Path, default=None,
        help="Write run-summary JSON to this path (D-09-09)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # --csv path validation.
    if args.csv is not None and not args.csv.exists():
        print(f"ERROR: --csv path does not exist: {args.csv}", file=sys.stderr)
        return EXIT_MISSING_RESOURCE

    # bbox parse + validate.
    try:
        bbox_parts = [float(c) for c in args.bbox.split(",")]
        if len(bbox_parts) != 4:
            raise ValueError(f"bbox must have 4 components; got {len(bbox_parts)}")
        bbox = (bbox_parts[0], bbox_parts[1], bbox_parts[2], bbox_parts[3])
    except ValueError as e:
        print(f"ERROR: invalid --bbox: {e}", file=sys.stderr)
        return EXIT_VALIDATION

    # Validate date strings.
    try:
        datetime.fromisoformat(args.start_date)
        datetime.fromisoformat(args.end_date)
    except ValueError as e:
        print(f"ERROR: invalid date format: {e}", file=sys.stderr)
        return EXIT_VALIDATION

    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    t0 = time.monotonic()

    counters: dict = {
        "fetched": 0,
        "inserted": 0,
        "skipped_duplicate": 0,
        "dropped_outside_snap": 0,
        "errors": 0,
        "by_severity": {"fatal": 0, "injury": 0, "pdo": 0},
    }
    snap_distances: list[float] = []
    rows_to_insert: list[tuple] = []

    # Pick row-source: --csv (test path) OR live Socrata.
    if args.csv is not None:
        row_iter: Iterable[dict] = iter_csv_rows(args.csv)
        logger.info("Reading from CSV fixture: %s", args.csv)
    else:
        row_iter = iter_crashes(
            args.start_date, args.end_date,
            bbox=bbox, page_size=1000,
        )
        logger.info(
            "Live Socrata fetch: %s → %s, bbox=%s",
            args.start_date, args.end_date, bbox,
        )

    try:
        conn = psycopg2.connect(DATABASE_URL)
    except psycopg2.OperationalError as e:
        print(f"ERROR: cannot connect to database: {e}", file=sys.stderr)
        return EXIT_OTHER

    try:
        with conn.cursor() as cur:
            for crash in row_iter:
                counters["fetched"] += 1
                if args.limit is not None and counters["fetched"] > args.limit:
                    counters["fetched"] -= 1  # don't count the row we didn't process
                    break
                try:
                    severity = map_mocodes_to_severity(crash["mocodes"])
                    lon, lat = parse_location_1(crash["location_1"])
                    occurred = parse_date_occ(crash["date_occ"])
                except (ValueError, KeyError, TypeError) as e:
                    logger.warning(
                        "row %s skipped: %s", crash.get("dr_no"), e,
                    )
                    counters["errors"] += 1
                    continue
                seg_id, dist_m = snap_point_to_segment(
                    cur, lon, lat, args.snap_meters,
                )
                if seg_id is None:
                    counters["dropped_outside_snap"] += 1
                    continue
                snap_distances.append(dist_m)
                counters["by_severity"][severity] += 1
                rows_to_insert.append((
                    "lacity",            # source
                    crash["dr_no"],      # source_record_id
                    severity,            # severity
                    occurred,            # occurred_at
                    seg_id,              # snapped_segment_id
                    dist_m,              # snap_distance_m
                    lon, lat,            # ST_MakePoint(lon, lat) in template
                ))

            # Idempotent batch INSERT (Pattern from ingest_mapillary.py:698-714).
            if rows_to_insert:
                returned = execute_values(
                    cur,
                    """
                    INSERT INTO crash_records
                        (source, source_record_id, severity, occurred_at,
                         snapped_segment_id, snap_distance_m, geom)
                    VALUES %s
                    ON CONFLICT (source, source_record_id) DO NOTHING
                    RETURNING 1
                    """,
                    rows_to_insert,
                    template=(
                        "(%s, %s, %s, %s, %s, %s, "
                        "ST_SetSRID(ST_MakePoint(%s, %s), 4326))"
                    ),
                    page_size=500,
                    fetch=True,
                )
                conn.commit()
                inserted = len(returned) if returned is not None else 0
            else:
                inserted = 0
            counters["inserted"] = inserted
            counters["skipped_duplicate"] = len(rows_to_insert) - inserted

        # Run-summary JSON (D-09-08 shape — EXACTLY 10 top-level keys).
        summary = {
            "source": "lacity",
            "fetched": counters["fetched"],
            "inserted": counters["inserted"],
            "skipped_duplicate": counters["skipped_duplicate"],
            "dropped_outside_snap": counters["dropped_outside_snap"],
            "errors": counters["errors"],
            "snap_distance_m": {
                "p50": round(quantile(snap_distances, 50), 2),
                "p95": round(quantile(snap_distances, 95), 2),
                "max": round(max(snap_distances) if snap_distances else 0.0, 2),
            },
            "by_severity": counters["by_severity"],
            "started_at": started_at,
            "duration_s": round(time.monotonic() - t0, 2),
        }
        out_json = json.dumps(summary, indent=2)
        print(out_json)
        if args.summary_out:
            args.summary_out.write_text(out_json)
    except Exception:
        conn.rollback()
        logger.exception("ingest aborted")
        return EXIT_OTHER
    finally:
        conn.close()

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
