# deploy/db/Dockerfile — Postgres 16 + PostGIS 3.4 + pgRouting 3.8 image for
# the road-quality-db Fly app (Phase 5, REQ-prod-deploy SC #1).
#
# Built from postgis/postgis:16-3.4 (verified Debian 11 bullseye base via
# `docker run --rm postgis/postgis:16-3.4 cat /etc/os-release`); apt-installs
# postgresql-16-pgrouting from the image's pre-configured bullseye-pgdg repo
# (verified to ship pgRouting 3.8.0 via curl + gunzip on the apt Packages
# manifest as of 2026-04-27 — RESEARCH §1 line 102).
#
# Migrations are baked INTO the image so a fresh Fly volume picks them up
# automatically on first boot via Postgres' /docker-entrypoint-initdb.d/
# auto-init flow. Idempotency: all migrations use CREATE TABLE IF NOT EXISTS
# / CREATE INDEX IF NOT EXISTS, so manual re-application via flyctl ssh is
# also safe (RESEARCH Migration Init Flow + Pitfall 6 covers volume-restore
# corner case).
#
# Baking strategy chosen over Fly file-mounts (RESEARCH alternatives table:
# "B) Mount db/migrations/ via Fly [mounts]" rejected) because the image IS
# the deploy artifact — no drift between volume snapshot and migration set.

FROM postgis/postgis:16-3.4

RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-16-pgrouting \
 && rm -rf /var/lib/apt/lists/*

# Init scripts run in lexicographic order on FIRST boot of an EMPTY $PGDATA
# volume. Numeric prefixes match docker-compose.yml's local-dev convention
# (one-prefix-lower than the compose mounts so future Phase 6+ migrations
# can slot in as 04-*.sql etc.).
COPY db/init-pgrouting.sh                      /docker-entrypoint-initdb.d/00-init-pgrouting.sh
COPY db/migrations/001_initial.sql             /docker-entrypoint-initdb.d/01-schema.sql
COPY db/migrations/002_mapillary_provenance.sql /docker-entrypoint-initdb.d/02-mapillary.sql
COPY db/migrations/003_users.sql               /docker-entrypoint-initdb.d/03-users.sql
