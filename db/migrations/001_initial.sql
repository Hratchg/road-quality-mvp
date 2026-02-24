CREATE TABLE IF NOT EXISTS road_segments (
    id            SERIAL PRIMARY KEY,
    osm_way_id    BIGINT,
    geom          GEOMETRY(LineString, 4326) NOT NULL,
    length_m      DOUBLE PRECISION NOT NULL,
    travel_time_s DOUBLE PRECISION NOT NULL,
    source        BIGINT,
    target        BIGINT,
    iri_value     DOUBLE PRECISION,
    iri_norm      DOUBLE PRECISION,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_segments_geom ON road_segments USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_segments_source ON road_segments(source);
CREATE INDEX IF NOT EXISTS idx_segments_target ON road_segments(target);

CREATE TABLE IF NOT EXISTS segment_defects (
    id              SERIAL PRIMARY KEY,
    segment_id      INTEGER REFERENCES road_segments(id) ON DELETE CASCADE,
    severity        VARCHAR(10) NOT NULL CHECK (severity IN ('moderate', 'severe')),
    count           INTEGER NOT NULL DEFAULT 1,
    confidence_sum  DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_defects_segment ON segment_defects(segment_id);

CREATE TABLE IF NOT EXISTS segment_scores (
    segment_id          INTEGER PRIMARY KEY REFERENCES road_segments(id) ON DELETE CASCADE,
    moderate_score      DOUBLE PRECISION DEFAULT 0.0,
    severe_score        DOUBLE PRECISION DEFAULT 0.0,
    pothole_score_total DOUBLE PRECISION DEFAULT 0.0,
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS route_requests (
    id          SERIAL PRIMARY KEY,
    params_json JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
