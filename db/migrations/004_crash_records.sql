-- Migration 004: crash_records table + segment_scores.crash_norm column.
-- Phase 9, plans 09-01..09-04. Implements decisions D-09-10 (table shape),
-- D-09-11 (segment_scores.crash_norm column), D-09-12 (idempotent mirror of
-- migration 002), D-09-15 (UNIQUE on source+source_record_id for ON CONFLICT).
--
-- Mirrors db/migrations/002_mapillary_provenance.sql line-by-line: CREATE IF
-- NOT EXISTS, separate CREATE UNIQUE INDEX, DROP-then-ADD CHECK constraints.
-- Postgres 16 supports IF NOT EXISTS on column adds and indexes but does NOT
-- support an idempotent ADD CONSTRAINT form. Safe to re-run on fresh,
-- half-applied, or fully-applied DBs.
--
-- FK type note: snapped_segment_id is INTEGER (not BIGINT) to match the
-- parent column type road_segments.id which is SERIAL (= INTEGER) per
-- migration 001. Postgres rejects FKs whose parent/child types don't match.
-- (Pitfall D in 09-RESEARCH.md; matches segment_defects.segment_id INTEGER
-- precedent in 001_initial.sql line 20.)

-- D-09-10: crash_records table (NEW). ON DELETE SET NULL preserves the raw
-- crash row even if segment topology is rebuilt.
CREATE TABLE IF NOT EXISTS crash_records (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    occurred_at DATE NOT NULL,
    snapped_segment_id INTEGER REFERENCES road_segments(id) ON DELETE SET NULL,
    snap_distance_m DOUBLE PRECISION,
    geom GEOMETRY(POINT, 4326) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- DROP-then-ADD CHECK constraints (Postgres 16 has no idempotent ADD-CONSTRAINT form).
-- Mirrors 002_mapillary_provenance.sql lines 26-30.
ALTER TABLE crash_records DROP CONSTRAINT IF EXISTS crash_records_source_check;
ALTER TABLE crash_records ADD CONSTRAINT crash_records_source_check
    CHECK (source IN ('lacity'));   -- v0.4.1 will widen to ('lacity','switrs')

ALTER TABLE crash_records DROP CONSTRAINT IF EXISTS crash_records_severity_check;
ALTER TABLE crash_records ADD CONSTRAINT crash_records_severity_check
    CHECK (severity IN ('fatal', 'injury', 'pdo'));

-- D-09-15: ON CONFLICT target. UNIQUE on (source, source_record_id) so re-running
-- ingest produces zero new rows on the same Socrata `dr_no` set.
CREATE UNIQUE INDEX IF NOT EXISTS idx_crash_records_source_id
    ON crash_records (source, source_record_id);

-- Spatial + foreign-key access patterns.
CREATE INDEX IF NOT EXISTS idx_crash_records_geom
    ON crash_records USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_crash_records_segment
    ON crash_records (snapped_segment_id);

-- D-09-11: segment_scores.crash_norm column (NEW, additive, default 0).
-- Populated by Phase 10's compute_scores.py extension; Phase 9 leaves it at 0.
-- Adding it here keeps the schema migration atomic so the LEFT JOIN COALESCE(0)
-- safety net works during the Phase 9 → 10 gap.
ALTER TABLE segment_scores
    ADD COLUMN IF NOT EXISTS crash_norm DOUBLE PRECISION NOT NULL DEFAULT 0.0;
