"""Recompute segment_scores from segment_defects.

Phase 3 D-16 extension: --source {synthetic | mapillary | crash | all} (default 'all')
filters which detections contribute to the recompute. The SC #4 demo workflow
runs this twice (--source synthetic then --source mapillary) and diffs the
resulting /route responses.

Phase 10 (D-10-10..D-10-12) extension: adds --source crash, which runs a
correlated-subquery UPDATE against crash_records to populate
segment_scores.crash_norm. --source all now sequences synthetic+mapillary
(unchanged single-pass INSERT...ON CONFLICT) followed by the new crash
UPDATE. The synthetic and mapillary paths are unchanged (D-10-12 backwards
compat gate).

Run this after new detections are added (synthetic via seed_data.py, mapillary
via scripts/ingest_mapillary.py, crash via scripts/ingest_crashes.py).
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from pathlib import Path

# Phase 10 (D-10-04, D-10-05): severity weight + fatal-cap constants imported
# from the single source of truth (Plan 10-01). The backend/ directory is not
# normally on sys.path when this script is invoked as `python scripts/...`,
# so we prepend it before importing app.scoring. This keeps the constants
# DRY between offline compute_scores.py and online routing.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.scoring import (  # noqa: E402  (sys.path manipulation must come first)
    FATAL_WEIGHT,
    INJURY_WEIGHT,
    PDO_WEIGHT,
    FATAL_CAP,
)

import psycopg2  # noqa: E402

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)

# Phase 10 (D-10-10): VALID_SOURCES extended with 'crash'.
VALID_SOURCES = ("synthetic", "mapillary", "crash", "all")


# ---------------------------------------------------------------------------
# Phase 10 (D-10-07, D-10-08, D-10-09, D-10-11): canonical correlated-subquery
# UPDATE for crash_norm.
#
# Anti-pattern guard (PROJECT.md "Phase 10 must NOT inline crash-aggregation
# SQL into routing.py"): all crash math lives HERE, pre-baked into
# segment_scores.crash_norm. routing.py only ever READS the column.
#
# Critical detail tally:
#   1. JOIN is `road_segments LEFT JOIN crash_records` — NEVER segment_defects
#      (no cross-product blowup; RESEARCH §Pattern 1).
#   2. Length is `rs.length_m / 1000.0` to convert metres→km (Pitfall 5;
#      CONTEXT D-10-07 corrected to length_m, the actual schema column).
#   3. p95 is computed over `WHERE raw_per_km > 0` ONLY — Pitfall 6 prevents
#      zero-segment dominance from collapsing the percentile to ~0.
#   4. UPDATE WHERE clause also has `psc.raw_per_km > 0` — D-10-09 safety net
#      so zero-crash segments stay at the migration-default 0.0.
#   5. NULLIF((SELECT p95 FROM p95v), 0) defends against the all-zero case
#      (no crashes anywhere). When NULLIF returns NULL, LEAST(...) is NULL,
#      and the outer WHERE filter (raw_per_km > 0) means we never touch
#      those rows anyway — but defensive coding mandates the NULLIF.
#   6. LEAST(1.0, ...) clips to [0, 1] (D-10-08). Combined with
#      DEFAULT 0.0 NOT NULL on the column (Migration 004) we get a clean
#      [0, 1] domain — no negatives, no nulls.
#   7. Severity weights are passed as %(name)s parameters (NOT inlined)
#      so they stay in sync with backend/app/scoring.py (Plan 10-01).
# ---------------------------------------------------------------------------
CRASH_UPDATE_SQL = """
WITH per_seg AS (
    SELECT
        rs.id AS segment_id,
        rs.length_m,
        SUM(
            CASE c.severity
                WHEN 'fatal' THEN %(fatal_w)s
                WHEN 'injury' THEN %(injury_w)s
                WHEN 'pdo' THEN %(pdo_w)s
                ELSE 0
            END
        ) AS raw_sum
    FROM road_segments rs
    LEFT JOIN crash_records c ON c.snapped_segment_id = rs.id
    GROUP BY rs.id, rs.length_m
),
per_seg_capped AS (
    SELECT
        segment_id,
        length_m,
        LEAST(raw_sum, %(fatal_cap)s) AS capped_sum,
        LEAST(raw_sum, %(fatal_cap)s) /
            GREATEST(length_m / 1000.0, 0.05) AS raw_per_km
    FROM per_seg
),
p95v AS (
    -- Pitfall 6: p95 over crash-bearing segments only (raw_per_km > 0)
    SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY raw_per_km) AS p95
    FROM per_seg_capped
    WHERE raw_per_km > 0
)
UPDATE segment_scores ss
SET crash_norm = LEAST(
        1.0,
        psc.raw_per_km / NULLIF((SELECT p95 FROM p95v), 0)
    ),
    updated_at = NOW()
FROM per_seg_capped psc
WHERE ss.segment_id = psc.segment_id
  AND psc.raw_per_km > 0   -- D-10-09: zero-crash segments stay at DEFAULT 0.0
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute segment_scores from segment_defects + crash_records. "
            "Use --source to compute from a single provenance bucket."
        ),
    )
    parser.add_argument(
        "--source",
        choices=VALID_SOURCES,
        default="all",
        help=(
            "Which detection source to include "
            "(synthetic: seed_data.py rows; "
            "mapillary: ingest_mapillary.py rows; "
            "crash: ingest_crashes.py rows (per-segment severity-weighted, "
            "p95-capped, length-normalized; D-10-10..D-10-12); "
            "all: every source — default; preserves pre-Phase-3 behavior "
            "and Phase 10 sequences synthetic+mapillary then crash)"
        ),
    )
    args = parser.parse_args()

    # WR-04 fix: use context managers so the connection and cursor are
    # released even when cur.execute() raises (constraint violation,
    # transient error, etc.). psycopg2.connect() as a context manager
    # commits on clean exit and rolls back on exception, but does NOT
    # close the connection -- pair it with contextlib.closing() so the
    # socket is freed regardless of outcome.
    with contextlib.closing(psycopg2.connect(DATABASE_URL)) as conn:
        with conn.cursor() as cur:
            # ---------------------------------------------------------------
            # Path 1 (existing, D-10-12 unchanged): synthetic / mapillary / all
            # branch runs the segment_defects INSERT...ON CONFLICT.
            # The crash branch is independent and handled in Path 2 below.
            # ---------------------------------------------------------------
            if args.source in ("synthetic", "mapillary", "all"):
                # Pitfall 7: warn if --source mapillary is selected against an
                # empty mapillary set. Operators sometimes run the SC #4 demo
                # workflow before any ingest has happened; without this
                # warning, "all zeros" looks like a bug.
                if args.source == "mapillary":
                    cur.execute(
                        "SELECT COUNT(*) FROM segment_defects "
                        "WHERE source = 'mapillary'"
                    )
                    n_mapillary = cur.fetchone()[0]
                    if n_mapillary == 0:
                        print(
                            "WARNING: --source mapillary selected but 0 mapillary "
                            "detections in segment_defects; all scores will be "
                            "zero. Run scripts/ingest_mapillary.py first.",
                            file=sys.stderr,
                        )

                # Pattern 7: apply the source filter at JOIN time (not WHERE),
                # so segments without matching detections still appear in
                # segment_scores with zeros. Putting the filter in WHERE would
                # exclude them entirely — a behavior change.
                if args.source == "all":
                    join_filter = ""
                    params: tuple = ()
                else:
                    join_filter = "AND sd.source = %s"
                    params = (args.source,)

                sql = f"""
                    INSERT INTO segment_scores (segment_id, moderate_score, severe_score, pothole_score_total)
                    SELECT
                        rs.id,
                        COALESCE(SUM(CASE WHEN sd.severity = 'moderate' THEN 0.5 * sd.count * sd.confidence_sum ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN sd.severity = 'severe' THEN 1.0 * sd.count * sd.confidence_sum ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN sd.severity = 'moderate' THEN 0.5 * sd.count * sd.confidence_sum ELSE 0 END), 0)
                        + COALESCE(SUM(CASE WHEN sd.severity = 'severe' THEN 1.0 * sd.count * sd.confidence_sum ELSE 0 END), 0)
                    FROM road_segments rs
                    LEFT JOIN segment_defects sd ON rs.id = sd.segment_id {join_filter}
                    GROUP BY rs.id
                    ON CONFLICT (segment_id) DO UPDATE SET
                        moderate_score = EXCLUDED.moderate_score,
                        severe_score = EXCLUDED.severe_score,
                        pothole_score_total = EXCLUDED.pothole_score_total,
                        updated_at = NOW()
                """
                cur.execute(sql, params)
                conn.commit()

                cur.execute(
                    "SELECT COUNT(*) FROM segment_scores "
                    "WHERE pothole_score_total > 0"
                )
                count = cur.fetchone()[0]
                print(
                    f"Scores recomputed (--source {args.source}). "
                    f"{count} segments have pothole data."
                )

            # ---------------------------------------------------------------
            # Path 2 (Phase 10 NEW, D-10-10..D-10-12): crash / all branch
            # runs the correlated-subquery UPDATE against crash_records.
            # Sequenced AFTER the synthetic+mapillary path so a crash-UPDATE
            # failure doesn't roll back the synthetic+mapillary INSERT
            # (each path commits independently).
            # ---------------------------------------------------------------
            if args.source in ("crash", "all"):
                # Pitfall 7-crash mirror: warn if --source crash is selected
                # against an empty crash_records table (mirrors the existing
                # mapillary warning above for D-10-12 parity). Without this,
                # operators running the Phase-12 runbook against a fresh DB
                # would see "all zeros" and suspect a bug.
                cur.execute("SELECT COUNT(*) FROM crash_records")
                row = cur.fetchone()
                n_crashes = row[0]
                if n_crashes == 0:
                    print(
                        "WARNING: --source crash selected but 0 rows in "
                        "crash_records; crash_norm will stay at 0 for all "
                        "segments. Run scripts/ingest_crashes.py --source "
                        "lacity --csv data/crashes_la/lacity_fixture.csv "
                        "first.",
                        file=sys.stderr,
                    )
                else:
                    cur.execute(CRASH_UPDATE_SQL, {
                        "fatal_w": FATAL_WEIGHT,
                        "injury_w": INJURY_WEIGHT,
                        "pdo_w": PDO_WEIGHT,
                        "fatal_cap": FATAL_CAP,
                    })
                    conn.commit()
                    cur.execute(
                        "SELECT COUNT(*) FROM segment_scores "
                        "WHERE crash_norm > 0"
                    )
                    n_segments = cur.fetchone()[0]
                    print(
                        f"crash_norm recomputed (--source {args.source}). "
                        f"{n_segments} segments have non-zero crash_norm."
                    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
