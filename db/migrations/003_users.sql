-- Migration 003: users table for Phase 4 authentication.
-- Phase 4, plans 04-01..04-05. Implements REQ-user-auth and 04-CONTEXT.md
-- decisions D-03 (argon2id password hashing — column shape only; the hashing
-- happens at the app layer in backend/app/auth/passwords.py) and the
-- "Locked column shape for users table" section (BIGSERIAL id, TEXT email
-- NOT NULL, TEXT password_hash NOT NULL, TIMESTAMPTZ NOT NULL DEFAULT NOW()).
--
-- Idempotency model (mirrors Phase 3 migration 002_mapillary_provenance.sql):
--   - CREATE TABLE IF NOT EXISTS users — re-applies are no-ops on the table.
--   - CREATE UNIQUE INDEX IF NOT EXISTS users_email_key ON users(email) —
--     idempotent index creation. Postgres 16 has no idempotent ADD CONSTRAINT
--     form, so we use a separate CREATE UNIQUE INDEX rather than an inline
--     UNIQUE column constraint, exactly as Phase 3 did for
--     uniq_defects_segment_source_severity. See 04-RESEARCH.md §5 for rationale.
--
-- Email case normalization: emails are lowercased + trimmed at the app layer
-- before INSERT/SELECT (see backend/app/routes/auth.py _normalize_email and
-- 04-RESEARCH.md Pitfall 3). The UNIQUE index on the raw column value is
-- correct because the app guarantees byte-exact lowercase form.
--
-- The migration MUST apply cleanly to a fresh DB via the existing init flow
-- (mounted in docker-compose.yml under /docker-entrypoint-initdb.d/04-users.sql).
-- The migration MUST NOT contain seed INSERTs (the demo user is seeded by
-- scripts/seed_demo_user.py in plan 04-05; researcher decision per
-- 04-RESEARCH.md §7 — keeps hashes out of git history and rotation is one
-- script invocation).

CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    email         TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- UNIQUE index on email (separate from column declaration for idempotent re-apply).
CREATE UNIQUE INDEX IF NOT EXISTS users_email_key ON users(email);
