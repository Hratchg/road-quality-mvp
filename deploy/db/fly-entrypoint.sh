#!/bin/bash
# Fly volumes mount as root (uid 0, mode 0755); the postgres image's
# docker-entrypoint.sh runs as user `postgres` (uid 999) and cannot
# `mkdir $PGDATA` under the root-owned mount root. Pre-chown the mount
# root to postgres BEFORE invoking the upstream entrypoint so it can
# create $PGDATA = /var/lib/postgresql/data/pgdata on first boot.
set -e
if [ -d /var/lib/postgresql/data ] && [ "$(id -u)" = "0" ]; then
  chown -R postgres:postgres /var/lib/postgresql/data
fi
exec /usr/local/bin/docker-entrypoint.sh "$@"
