#!/usr/bin/env bash
# deploy/db/test-build.sh — Local smoke test for deploy/db/Dockerfile.
#
# Builds the image from repo root and asserts that pgRouting 3.8 (or newer)
# is installed in the resulting image. RESEARCH §1 line 138-146 verbatim.
#
# Usage: from repo root, run: bash deploy/db/test-build.sh
# Exit codes: 0 = build successful + pgRouting present; non-zero = failure.

set -euo pipefail

# Ensure we're at repo root (the build context).
if [ ! -f "deploy/db/Dockerfile" ]; then
    echo "ERROR: run this from the repo root (deploy/db/Dockerfile not found in cwd)" >&2
    exit 1
fi

IMAGE_TAG="road-quality-db:test"

echo "Building $IMAGE_TAG from repo root..."
docker build -f deploy/db/Dockerfile -t "$IMAGE_TAG" .

echo "Verifying pgRouting extension is installed..."
PGROUTING_FILE=$(docker run --rm "$IMAGE_TAG" sh -c \
    "ls /usr/share/postgresql/16/extension/pgrouting--*.sql 2>/dev/null | grep -v -- '--.*--' | head -1" \
    || true)

if [ -z "$PGROUTING_FILE" ]; then
    echo "FAIL: pgrouting--*.sql not found in image" >&2
    exit 1
fi

echo "  Found: $PGROUTING_FILE"

# Extract version: pgrouting--3.8.0.sql -> 3.8.0
VERSION=$(echo "$PGROUTING_FILE" | sed -E 's|.*pgrouting--([0-9.]+)\.sql|\1|')
echo "  pgRouting version: $VERSION"

# Assert version is >= 3.6 (project floor per CON-stack-database).
MAJOR=$(echo "$VERSION" | cut -d. -f1)
MINOR=$(echo "$VERSION" | cut -d. -f2)
if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 6 ]; }; then
    echo "FAIL: pgRouting $VERSION is below project floor 3.6" >&2
    exit 1
fi

echo "Verifying baked migrations are present..."
for migration in 00-init-pgrouting.sh 01-schema.sql 02-mapillary.sql 03-users.sql; do
    if ! docker run --rm "$IMAGE_TAG" test -f "/docker-entrypoint-initdb.d/$migration"; then
        echo "FAIL: /docker-entrypoint-initdb.d/$migration missing from image" >&2
        exit 1
    fi
    echo "  Present: /docker-entrypoint-initdb.d/$migration"
done

echo
echo "PASS: deploy/db/Dockerfile builds successfully; pgRouting $VERSION installed; all 4 init scripts baked in."
