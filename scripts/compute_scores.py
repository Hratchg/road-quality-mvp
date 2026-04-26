"""Recompute segment_scores from segment_defects.

Phase 3 D-16 extension: --source {synthetic | mapillary | all} (default 'all')
filters which detections contribute to the recompute. The SC #4 demo workflow
runs this twice (--source synthetic then --source mapillary) and diffs the
resulting /route responses.

Run this after new detections are added (synthetic via seed_data.py, mapillary
via scripts/ingest_mapillary.py).
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys

import psycopg2

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)

VALID_SOURCES = ("synthetic", "mapillary", "all")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute segment_scores from segment_defects. "
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
            "all: both — default; preserves pre-Phase-3 behavior)"
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
