"""IRI data source module: load real IRI data or generate improved synthetic IRI.

Supports two tiers of IRI data ingestion:

Tier 1 -- Real data ingestion:
  - CSV files with columns: latitude, longitude, iri_value (required);
    road_name, route_id, begin_mile, end_mile (optional)
  - Shapefiles with IRI attributes (requires geopandas)

Tier 2 -- Improved synthetic generation:
  - Spatially-correlated IRI values based on road classification, segment
    length, and neighbor smoothing via PostGIS ST_DWithin.
  - Uses FHWA-derived distribution parameters for realistic output.

Public IRI data sources for California / LA:
  - FHWA HPMS: https://www.fhwa.dot.gov/policyinformation/hpms.cfm
  - Caltrans PMS: https://dot.ca.gov/programs/maintenance/pavement
  - Caltrans TIMS: https://tims.berkeley.edu/
  - data.gov search "pavement IRI California"

Expected CSV format (header row required):
    latitude,longitude,iri_value,road_name
    34.0522,-118.2437,3.2,Main St
    34.0530,-118.2500,5.1,Broadway
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

# ---------------------------------------------------------------------------
# FHWA-derived IRI distribution parameters (m/km)
# Source: FHWA HPMS data summaries for US road network
# ---------------------------------------------------------------------------
IRI_DISTRIBUTIONS: dict[str, dict[str, float]] = {
    # Highway class -> mean, std (m/km)
    "motorway":    {"mean": 2.0, "std": 0.6},
    "trunk":       {"mean": 2.5, "std": 0.8},
    "primary":     {"mean": 2.8, "std": 0.9},
    "secondary":   {"mean": 3.5, "std": 1.5},
    "tertiary":    {"mean": 4.0, "std": 1.8},
    "residential": {"mean": 5.0, "std": 2.5},
    "unclassified":{"mean": 5.5, "std": 2.8},
    "service":     {"mean": 5.5, "std": 2.8},
    "living_street":{"mean": 5.0, "std": 2.5},
    "default":     {"mean": 5.0, "std": 2.5},
}

# Length factor: longer segments accumulate more variance
# We add std * length_factor * log(1 + length_m / 500) to the std
LENGTH_VARIANCE_FACTOR = 0.15

# Spatial smoothing: weight of neighbor average vs raw value
NEIGHBOR_SMOOTH_WEIGHT = 0.3
NEIGHBOR_RADIUS_METERS = 200


# ---------------------------------------------------------------------------
# Tier 1: CSV ingestion
# ---------------------------------------------------------------------------

def load_iri_from_csv(csv_path: str) -> list[dict[str, Any]]:
    """Load IRI measurements from a CSV file.

    Expected CSV columns (header row required):
        latitude    -- float, WGS84 latitude
        longitude   -- float, WGS84 longitude
        iri_value   -- float, IRI in m/km

    Optional columns:
        road_name   -- str
        route_id    -- str
        begin_mile  -- float
        end_mile    -- float

    Args:
        csv_path: Path to the CSV file.

    Returns:
        List of dicts with at least keys: latitude, longitude, iri_value.

    Raises:
        FileNotFoundError: If the CSV file does not exist.
        ValueError: If required columns are missing or data is invalid.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    records: list[dict[str, Any]] = []
    required_columns = {"latitude", "longitude", "iri_value"}

    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV file is empty or has no header row")

        header_set = set(reader.fieldnames)
        missing = required_columns - header_set
        if missing:
            raise ValueError(
                f"CSV missing required columns: {', '.join(sorted(missing))}. "
                f"Found: {', '.join(sorted(header_set))}"
            )

        for line_num, row in enumerate(reader, start=2):
            try:
                record: dict[str, Any] = {
                    "latitude": float(row["latitude"]),
                    "longitude": float(row["longitude"]),
                    "iri_value": float(row["iri_value"]),
                }
            except (ValueError, TypeError) as exc:
                logger.warning("Skipping row %d: %s", line_num, exc)
                continue

            # Validate ranges
            if not (-90 <= record["latitude"] <= 90):
                logger.warning("Skipping row %d: latitude out of range", line_num)
                continue
            if not (-180 <= record["longitude"] <= 180):
                logger.warning("Skipping row %d: longitude out of range", line_num)
                continue
            if record["iri_value"] < 0:
                logger.warning("Skipping row %d: negative IRI value", line_num)
                continue

            # Optional fields
            for col in ("road_name", "route_id"):
                if col in row and row[col]:
                    record[col] = row[col]
            for col in ("begin_mile", "end_mile"):
                if col in row and row[col]:
                    try:
                        record[col] = float(row[col])
                    except (ValueError, TypeError):
                        pass

            records.append(record)

    logger.info("Loaded %d IRI records from %s", len(records), csv_path)
    return records


# ---------------------------------------------------------------------------
# Tier 1: Shapefile ingestion
# ---------------------------------------------------------------------------

def load_iri_from_shapefile(shp_path: str) -> list[dict[str, Any]]:
    """Load IRI measurements from a shapefile with IRI attributes.

    The shapefile must have:
        - A geometry column (Point or LineString)
        - An 'iri_value' or 'IRI' attribute column

    For LineString geometries, the centroid is used as the reference point.

    Args:
        shp_path: Path to the .shp file.

    Returns:
        List of dicts with keys: latitude, longitude, iri_value.

    Raises:
        FileNotFoundError: If the shapefile does not exist.
        ImportError: If geopandas is not installed.
    """
    path = Path(shp_path)
    if not path.exists():
        raise FileNotFoundError(f"Shapefile not found: {shp_path}")

    try:
        import geopandas as gpd
    except ImportError:
        raise ImportError(
            "geopandas is required for shapefile ingestion. "
            "Install it with: python -m pip install geopandas>=0.14"
        )

    gdf = gpd.read_file(shp_path)

    # Find the IRI column (case-insensitive)
    iri_col = None
    for col in gdf.columns:
        if col.lower() in ("iri_value", "iri", "iri_mean", "iri_avg"):
            iri_col = col
            break
    if iri_col is None:
        raise ValueError(
            f"No IRI column found in shapefile. "
            f"Expected one of: iri_value, IRI, iri_mean, iri_avg. "
            f"Found columns: {list(gdf.columns)}"
        )

    # Ensure CRS is WGS84
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    records: list[dict[str, Any]] = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue

        # Use centroid for line/polygon geometries
        point = geom.centroid if geom.geom_type != "Point" else geom

        iri_val = row[iri_col]
        if iri_val is None or (isinstance(iri_val, float) and np.isnan(iri_val)):
            continue

        records.append({
            "latitude": point.y,
            "longitude": point.x,
            "iri_value": float(iri_val),
        })

    logger.info("Loaded %d IRI records from shapefile %s", len(records), shp_path)
    return records


# ---------------------------------------------------------------------------
# Tier 2: Improved synthetic IRI generation
# ---------------------------------------------------------------------------

def _classify_highway(highway_tag: str | None) -> str:
    """Normalize an OSM highway tag to a known classification key."""
    if highway_tag is None:
        return "default"
    tag = highway_tag.strip().lower()
    # Handle list-encoded tags (stored as JSON arrays sometimes)
    if tag.startswith("["):
        tag = tag.strip("[]\"' ").split(",")[0].strip("\"' ")
    if tag in IRI_DISTRIBUTIONS:
        return tag
    # Map link roads to their parent type
    for parent in ("motorway", "trunk", "primary", "secondary", "tertiary"):
        if tag.startswith(parent):
            return parent
    return "default"


def generate_improved_synthetic_iri(conn, seed: int = 42) -> dict[str, Any]:
    """Generate spatially-correlated, realistic IRI values for all road segments.

    This replaces iri_value in road_segments with values drawn from
    FHWA-derived distributions, adjusted for road classification and segment
    length, then smoothed using spatial neighbor averaging.

    Algorithm:
        1. Fetch all segments with their highway tag, length, and centroid.
        2. For each segment, draw IRI from N(mean, std) for its road class.
        3. Adjust std by segment length (longer = more variance).
        4. Clamp to [0.5, 15.0] m/km (physical bounds).
        5. Spatial smoothing pass: for each segment, blend its value with
           the average of neighbors within NEIGHBOR_RADIUS_METERS.

    Args:
        conn: psycopg2 connection to the roadquality database.
        seed: Random seed for reproducibility.

    Returns:
        Dict with summary statistics: count, mean, std, min, max.
    """
    rng = np.random.default_rng(seed)
    cur = conn.cursor()

    # Step 1: Fetch segment metadata
    # We need id, highway tag (from osm_way_id or stored tag), and length
    # The road_segments table has osm_way_id but not highway type directly.
    # We need to check what columns are available.
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'road_segments'
        ORDER BY ordinal_position
    """)
    columns = [row[0] for row in cur.fetchall()]

    has_highway = "highway" in columns
    has_tags = "tags" in columns

    if has_highway:
        cur.execute("""
            SELECT id, highway, length_m,
                   ST_X(ST_Centroid(geom)) AS cx,
                   ST_Y(ST_Centroid(geom)) AS cy
            FROM road_segments
            ORDER BY id
        """)
    elif has_tags:
        cur.execute("""
            SELECT id, tags->>'highway' AS highway, length_m,
                   ST_X(ST_Centroid(geom)) AS cx,
                   ST_Y(ST_Centroid(geom)) AS cy
            FROM road_segments
            ORDER BY id
        """)
    else:
        # No highway info: use default distribution for all
        cur.execute("""
            SELECT id, NULL AS highway, length_m,
                   ST_X(ST_Centroid(geom)) AS cx,
                   ST_Y(ST_Centroid(geom)) AS cy
            FROM road_segments
            ORDER BY id
        """)

    rows = cur.fetchall()
    if not rows:
        logger.warning("No road segments found in database")
        return {"count": 0, "mean": 0, "std": 0, "min": 0, "max": 0}

    n = len(rows)
    seg_ids = np.array([r[0] for r in rows], dtype=np.int64)
    highway_tags = [r[1] for r in rows]
    lengths = np.array([r[2] or 100.0 for r in rows], dtype=np.float64)

    # Step 2 & 3: Draw IRI values from distributions
    iri_values = np.empty(n, dtype=np.float64)
    for i in range(n):
        cls = _classify_highway(highway_tags[i])
        params = IRI_DISTRIBUTIONS[cls]
        mean = params["mean"]
        std = params["std"]
        # Adjust std by segment length
        length_adj = LENGTH_VARIANCE_FACTOR * np.log1p(lengths[i] / 500.0)
        adjusted_std = std * (1.0 + length_adj)
        iri_values[i] = rng.normal(mean, adjusted_std)

    # Step 4: Clamp to physical bounds
    np.clip(iri_values, 0.5, 15.0, out=iri_values)

    # Step 5: Spatial smoothing via PostGIS neighbor lookup
    logger.info("Performing spatial smoothing (radius=%dm)...", NEIGHBOR_RADIUS_METERS)
    # Build a mapping from id to index
    id_to_idx = {int(seg_ids[i]): i for i in range(n)}

    # Batch query: for each segment, find neighbor IDs within radius
    # We process in batches to avoid memory issues
    smoothed = iri_values.copy()
    batch_size = 5000
    for batch_start in range(0, n, batch_size):
        batch_end = min(batch_start + batch_size, n)
        batch_ids = seg_ids[batch_start:batch_end].tolist()

        # Use a single query to get all neighbor pairs for this batch
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

        # Group neighbors by segment
        neighbor_map: dict[int, list[int]] = {}
        for seg_id, neighbor_id in cur.fetchall():
            neighbor_map.setdefault(seg_id, []).append(neighbor_id)

        # Smooth: blend with neighbor average
        for seg_id, neighbors in neighbor_map.items():
            idx = id_to_idx.get(seg_id)
            if idx is None:
                continue
            neighbor_idxs = [
                id_to_idx[nid] for nid in neighbors if nid in id_to_idx
            ]
            if neighbor_idxs:
                neighbor_avg = np.mean(iri_values[neighbor_idxs])
                smoothed[idx] = (
                    (1 - NEIGHBOR_SMOOTH_WEIGHT) * iri_values[idx]
                    + NEIGHBOR_SMOOTH_WEIGHT * neighbor_avg
                )

    # Final clamp after smoothing
    np.clip(smoothed, 0.5, 15.0, out=smoothed)

    # Step 6: Update database
    logger.info("Updating %d segments with improved synthetic IRI...", n)

    update_data = [(round(float(smoothed[i]), 2), int(seg_ids[i])) for i in range(n)]

    # Use a temp table approach for efficient bulk update
    cur.execute("CREATE TEMP TABLE _iri_update (iri_val DOUBLE PRECISION, seg_id BIGINT)")
    execute_values(
        cur,
        "INSERT INTO _iri_update (iri_val, seg_id) VALUES %s",
        update_data,
        page_size=5000,
    )
    cur.execute("""
        UPDATE road_segments rs
        SET iri_value = t.iri_val
        FROM _iri_update t
        WHERE rs.id = t.seg_id
    """)
    cur.execute("DROP TABLE _iri_update")
    conn.commit()

    stats = {
        "count": n,
        "mean": round(float(np.mean(smoothed)), 3),
        "std": round(float(np.std(smoothed)), 3),
        "min": round(float(np.min(smoothed)), 3),
        "max": round(float(np.max(smoothed)), 3),
    }
    logger.info("Synthetic IRI stats: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# IRI normalization helper
# ---------------------------------------------------------------------------

def normalize_iri(conn) -> tuple[float, float]:
    """Recompute iri_norm as (iri_value - min) / (max - min) for all segments.

    Returns:
        Tuple of (iri_min, iri_max).
    """
    cur = conn.cursor()
    cur.execute("SELECT MIN(iri_value), MAX(iri_value) FROM road_segments")
    iri_min, iri_max = cur.fetchone()

    if iri_min is None or iri_max is None:
        logger.warning("No IRI values found in road_segments")
        return (0.0, 0.0)

    iri_range = iri_max - iri_min if iri_max != iri_min else 1.0
    cur.execute(
        "UPDATE road_segments SET iri_norm = (iri_value - %s) / %s",
        (iri_min, iri_range),
    )
    conn.commit()
    logger.info("IRI normalized: min=%.3f, max=%.3f", iri_min, iri_max)
    return (float(iri_min), float(iri_max))
