"""Seed the database with LA road segments + synthetic IRI/pothole data.

Usage: python scripts/seed_data.py
Requires: PostgreSQL running with schema from 001_initial.sql
"""

import json
import os
import random
import numpy as np
import osmnx as ox
import psycopg2
from psycopg2.extras import execute_values

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)

# LA center, 10km radius
CENTER = (34.0522, -118.2437)
DIST = 10000
SEED = 42


def main():
    rng = random.Random(SEED)
    np_rng = np.random.default_rng(SEED)

    print("Downloading LA road network (this may take a few minutes)...")
    G = ox.graph_from_point(CENTER, dist=DIST, network_type="drive")
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)

    edges = ox.graph_to_gdfs(G, nodes=False)
    print(f"Downloaded {len(edges)} edges")

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Clear existing data
    cur.execute("TRUNCATE road_segments, segment_defects, segment_scores CASCADE")
    conn.commit()

    # Insert road segments
    print("Inserting road segments...")
    seg_values = []
    for idx, (u, v, key) in enumerate(edges.index):
        row = edges.loc[(u, v, key)]
        geom_wkt = row.geometry.wkt
        length_m = row.get("length", 0)
        travel_time_s = row.get("travel_time", length_m / 13.4)  # fallback ~30mph

        # Synthetic IRI: 1-12 m/km, biased by road type
        highway_type = row.get("highway", "residential")
        if isinstance(highway_type, list):
            highway_type = highway_type[0]
        if highway_type in ("motorway", "trunk", "primary"):
            iri = float(np_rng.uniform(1.0, 4.0))
        elif highway_type in ("secondary", "tertiary"):
            iri = float(np_rng.uniform(2.0, 7.0))
        else:
            iri = float(np_rng.uniform(3.0, 12.0))

        osm_id = row.get("osmid", 0)
        if isinstance(osm_id, list):
            osm_id = osm_id[0]

        seg_values.append((
            int(osm_id),
            geom_wkt,
            float(length_m),
            float(travel_time_s),
            int(u),
            int(v),
            round(iri, 2),
        ))

    insert_sql = """
        INSERT INTO road_segments (osm_way_id, geom, length_m, travel_time_s, source, target, iri_value)
        VALUES %s
    """
    template = "(%s, ST_GeomFromText(%s, 4326), %s, %s, %s, %s, %s)"
    execute_values(cur, insert_sql, seg_values, template=template, page_size=1000)
    conn.commit()
    print(f"Inserted {len(seg_values)} road segments")

    # Normalize IRI
    cur.execute("SELECT MIN(iri_value), MAX(iri_value) FROM road_segments")
    iri_min, iri_max = cur.fetchone()
    iri_range = iri_max - iri_min if iri_max != iri_min else 1.0
    cur.execute(
        "UPDATE road_segments SET iri_norm = (iri_value - %s) / %s",
        (iri_min, iri_range),
    )
    conn.commit()
    print("IRI normalized")

    # Insert synthetic pothole defects (~30% of segments)
    print("Generating synthetic pothole data...")
    cur.execute("SELECT id FROM road_segments")
    segment_ids = [row[0] for row in cur.fetchall()]

    defect_values = []
    for sid in segment_ids:
        if rng.random() > 0.3:
            continue
        num_defects = rng.randint(1, 3)
        for _ in range(num_defects):
            severity = rng.choice(["moderate", "severe"])
            count = rng.randint(1, 5)
            confidence_sum = round(rng.uniform(0.3, 1.0) * count, 3)
            defect_values.append((sid, severity, count, confidence_sum))

    if defect_values:
        execute_values(
            cur,
            "INSERT INTO segment_defects (segment_id, severity, count, confidence_sum) VALUES %s",
            defect_values,
            page_size=1000,
        )
        conn.commit()
    print(f"Inserted {len(defect_values)} defect records")

    # Compute segment_scores
    print("Computing segment scores...")
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
    conn.commit()

    # Build pgRouting topology
    print("Building pgRouting topology...")
    cur.execute("SELECT pgr_createTopology('road_segments', 0.0001, 'geom', 'id')")
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM road_segments")
    count = cur.fetchone()[0]
    print(f"Done! {count} segments seeded with IRI + pothole data.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
