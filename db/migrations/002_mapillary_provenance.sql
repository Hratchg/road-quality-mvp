-- Migration 002: Mapillary provenance columns + UNIQUE index for idempotent ingest.
-- Phase 3, plans 03-01..03-05. Implements decisions D-05 (UNIQUE constraint),
-- D-06 (ON CONFLICT target), D-07 (source column with CHECK + DEFAULT 'synthetic').
--
-- Postgres 16 supports IF NOT EXISTS on column adds but does not support an
-- IF-NOT-EXISTS form for adding constraints. We use `CREATE UNIQUE INDEX IF NOT
-- EXISTS` for the dedup index and a DROP-then-ADD pattern for the CHECK
-- constraint so the migration is safe to re-run on existing DBs.
--
-- Default Postgres NULL-distinct UNIQUE behavior is REQUIRED (do NOT add the
-- option that would treat NULLs as equal): existing synthetic rows have
-- source_mapillary_id IS NULL and must remain distinct from each other.
-- Mapillary rows always have a non-NULL source_mapillary_id and so DO dedupe
-- on (segment_id, source_mapillary_id, severity).

-- D-05: source_mapillary_id is the per-image dedup key. NULL allowed (synthetic rows).
ALTER TABLE segment_defects
    ADD COLUMN IF NOT EXISTS source_mapillary_id TEXT;

-- D-07: source column tags origin. DEFAULT 'synthetic' so existing rows backfill
-- automatically without a separate UPDATE statement.
ALTER TABLE segment_defects
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'synthetic';

-- DROP-then-ADD CHECK constraint (Postgres 16 has no idempotent ADD-CONSTRAINT form).
ALTER TABLE segment_defects
    DROP CONSTRAINT IF EXISTS segment_defects_source_check;
ALTER TABLE segment_defects
    ADD CONSTRAINT segment_defects_source_check
    CHECK (source IN ('synthetic', 'mapillary'));

-- D-05 UNIQUE enforcement via UNIQUE INDEX (idempotent via IF NOT EXISTS).
-- NULL-distinct default: synthetic rows (source_mapillary_id IS NULL) do NOT collide
-- with each other. Mapillary rows always have a non-NULL source_mapillary_id and DO
-- dedupe on (segment_id, source_mapillary_id, severity) — the ON CONFLICT target.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_defects_segment_source_severity
    ON segment_defects (segment_id, source_mapillary_id, severity);

-- Index on source for fast --source filter in compute_scores.py (D-16).
CREATE INDEX IF NOT EXISTS idx_defects_source ON segment_defects(source);
