"""Recompute segment_scores from segment_defects. Run after new detections are added."""

import os
import psycopg2

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

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

    cur.execute("SELECT COUNT(*) FROM segment_scores WHERE pothole_score_total > 0")
    count = cur.fetchone()[0]
    print(f"Scores recomputed. {count} segments have pothole data.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
