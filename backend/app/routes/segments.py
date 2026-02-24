import json
from fastapi import APIRouter, Query, HTTPException
from app.db import get_connection

router = APIRouter()


@router.get("/segments")
def get_segments(bbox: str = Query(..., description="min_lon,min_lat,max_lon,max_lat")):
    parts = bbox.split(",")
    if len(parts) != 4:
        raise HTTPException(status_code=400, detail="bbox must be min_lon,min_lat,max_lon,max_lat")

    try:
        min_lon, min_lat, max_lon, max_lat = (float(p) for p in parts)
    except ValueError:
        raise HTTPException(status_code=400, detail="bbox values must be numbers")

    sql = """
        SELECT
            rs.id,
            ST_AsGeoJSON(rs.geom) AS geojson,
            rs.iri_norm,
            COALESCE(ss.moderate_score, 0) AS moderate_score,
            COALESCE(ss.severe_score, 0) AS severe_score,
            COALESCE(ss.pothole_score_total, 0) AS pothole_score_total
        FROM road_segments rs
        LEFT JOIN segment_scores ss ON rs.id = ss.segment_id
        WHERE rs.geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (min_lon, min_lat, max_lon, max_lat))
            rows = cur.fetchall()

    features = []
    for row in rows:
        features.append({
            "type": "Feature",
            "geometry": json.loads(row["geojson"]),
            "properties": {
                "id": row["id"],
                "iri_norm": row["iri_norm"],
                "moderate_score": row["moderate_score"],
                "severe_score": row["severe_score"],
                "pothole_score_total": row["pothole_score_total"],
            },
        })

    return {"type": "FeatureCollection", "features": features}
