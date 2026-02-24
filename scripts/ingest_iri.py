"""Ingest real or improved-synthetic IRI data into road_segments.

Usage:
    # From a CSV file:
    python scripts/ingest_iri.py --source csv --path scripts/sample_iri_data.csv

    # From a shapefile:
    python scripts/ingest_iri.py --source shapefile --path data/iri_data.shp

    # Generate improved synthetic IRI (no file needed):
    python scripts/ingest_iri.py --source synthetic

    # Specify a random seed for synthetic generation:
    python scripts/ingest_iri.py --source synthetic --seed 123

Requires: PostgreSQL running with road_segments table already populated.
Does NOT modify seed_data.py or drop/recreate existing data -- only updates
iri_value and iri_norm columns on existing road_segments rows.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import psycopg2

# Ensure the scripts directory is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from iri_sources import (
    load_iri_from_csv,
    load_iri_from_shapefile,
    generate_improved_synthetic_iri,
    normalize_iri,
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)

logger = logging.getLogger(__name__)


def _spatial_match_and_update(
    conn, records: list[dict], batch_size: int = 500
) -> int:
    """Match IRI measurements to nearest road segments and update iri_value.

    For each record (latitude, longitude, iri_value), finds the nearest
    road_segment using PostGIS KNN (<->) and updates its iri_value.

    Args:
        conn: psycopg2 connection.
        records: List of dicts with latitude, longitude, iri_value.
        batch_size: Number of records per transaction commit.

    Returns:
        Number of segments updated.
    """
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

        updated += cur.rowcount

        # Commit periodically
        if (i + 1) % batch_size == 0:
            conn.commit()
            logger.info("  Processed %d / %d records...", i + 1, len(records))

    conn.commit()
    return updated


def _print_summary(conn) -> None:
    """Print summary statistics for IRI values in road_segments."""
    cur = conn.cursor()
    cur.execute("""
        SELECT
            COUNT(*) AS total,
            COUNT(iri_value) AS with_iri,
            ROUND(MIN(iri_value)::numeric, 3) AS min_iri,
            ROUND(MAX(iri_value)::numeric, 3) AS max_iri,
            ROUND(AVG(iri_value)::numeric, 3) AS mean_iri,
            ROUND(STDDEV(iri_value)::numeric, 3) AS std_iri
        FROM road_segments
    """)
    row = cur.fetchone()
    total, with_iri, min_iri, max_iri, mean_iri, std_iri = row

    print("\n--- IRI Ingestion Summary ---")
    print(f"  Total segments:    {total}")
    print(f"  Segments with IRI: {with_iri}")
    print(f"  IRI min:           {min_iri} m/km")
    print(f"  IRI max:           {max_iri} m/km")
    print(f"  IRI mean:          {mean_iri} m/km")
    print(f"  IRI std:           {std_iri} m/km")
    print("-----------------------------\n")


def ingest_csv(conn, csv_path: str) -> None:
    """Ingest IRI data from a CSV file."""
    print(f"Loading IRI data from CSV: {csv_path}")
    records = load_iri_from_csv(csv_path)
    print(f"  Loaded {len(records)} records")

    if not records:
        print("  No records to ingest. Exiting.")
        return

    print("  Spatial-matching to nearest road segments...")
    t0 = time.time()
    updated = _spatial_match_and_update(conn, records)
    elapsed = time.time() - t0
    print(f"  Updated {updated} segments in {elapsed:.1f}s")

    print("  Re-normalizing IRI values...")
    iri_min, iri_max = normalize_iri(conn)
    print(f"  IRI range after normalization: [{iri_min:.3f}, {iri_max:.3f}]")

    _print_summary(conn)


def ingest_shapefile(conn, shp_path: str) -> None:
    """Ingest IRI data from a shapefile."""
    print(f"Loading IRI data from shapefile: {shp_path}")
    records = load_iri_from_shapefile(shp_path)
    print(f"  Loaded {len(records)} records")

    if not records:
        print("  No records to ingest. Exiting.")
        return

    print("  Spatial-matching to nearest road segments...")
    t0 = time.time()
    updated = _spatial_match_and_update(conn, records)
    elapsed = time.time() - t0
    print(f"  Updated {updated} segments in {elapsed:.1f}s")

    print("  Re-normalizing IRI values...")
    iri_min, iri_max = normalize_iri(conn)
    print(f"  IRI range after normalization: [{iri_min:.3f}, {iri_max:.3f}]")

    _print_summary(conn)


def ingest_synthetic(conn, seed: int = 42) -> None:
    """Generate and ingest improved synthetic IRI data."""
    print(f"Generating improved synthetic IRI (seed={seed})...")
    t0 = time.time()
    stats = generate_improved_synthetic_iri(conn, seed=seed)
    elapsed = time.time() - t0
    print(f"  Generated IRI for {stats['count']} segments in {elapsed:.1f}s")
    print(f"  Distribution: mean={stats['mean']}, std={stats['std']}, "
          f"min={stats['min']}, max={stats['max']}")

    print("  Re-normalizing IRI values...")
    iri_min, iri_max = normalize_iri(conn)
    print(f"  IRI range after normalization: [{iri_min:.3f}, {iri_max:.3f}]")

    _print_summary(conn)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest IRI data into road_segments table.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--source",
        choices=["csv", "shapefile", "synthetic"],
        required=True,
        help="Data source type: csv, shapefile, or synthetic",
    )
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="Path to CSV or shapefile (required for csv/shapefile sources)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for synthetic generation (default: 42)",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Database URL (overrides DATABASE_URL env var)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Validate arguments
    if args.source in ("csv", "shapefile") and not args.path:
        parser.error(f"--path is required when --source is '{args.source}'")

    # Connect to database
    db_url = args.db_url or DATABASE_URL
    print(f"Connecting to database...")
    try:
        conn = psycopg2.connect(db_url)
    except psycopg2.OperationalError as exc:
        print(f"ERROR: Cannot connect to database: {exc}")
        sys.exit(1)

    try:
        if args.source == "csv":
            ingest_csv(conn, args.path)
        elif args.source == "shapefile":
            ingest_shapefile(conn, args.path)
        elif args.source == "synthetic":
            ingest_synthetic(conn, seed=args.seed)
    except Exception as exc:
        conn.rollback()
        print(f"ERROR: Ingestion failed: {exc}")
        raise
    finally:
        conn.close()
        print("Database connection closed.")


if __name__ == "__main__":
    main()
