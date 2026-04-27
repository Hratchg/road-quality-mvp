#!/usr/bin/env bash
# deploy/frontend/test-build.sh — Local smoke test for deploy/frontend/Dockerfile.
#
# Builds the image with VITE_API_URL=https://road-quality-backend.fly.dev
# (the production target), then runs the image transiently and asserts:
#   1. The built JS bundle contains the literal string "road-quality-backend.fly.dev"
#   2. The built JS bundle does NOT contain "localhost" or "127.0.0.1"
#
# This is the SC #4 regression gate at the Docker layer. Plan 05-05's GH
# Actions workflow may invoke this same script as a pre-deploy CI check.
#
# Usage: from repo root, run: bash deploy/frontend/test-build.sh
# Exit codes: 0 = build successful + URL baked in; non-zero = failure.

set -euo pipefail

if [ ! -f "deploy/frontend/Dockerfile" ]; then
    echo "ERROR: run this from the repo root (deploy/frontend/Dockerfile not found)" >&2
    exit 1
fi

IMAGE_TAG="road-quality-frontend:test"
TARGET_URL="https://road-quality-backend.fly.dev"

echo "Building $IMAGE_TAG with VITE_API_URL=$TARGET_URL ..."
docker build \
    -f deploy/frontend/Dockerfile \
    --build-arg "VITE_API_URL=$TARGET_URL" \
    -t "$IMAGE_TAG" \
    .

echo "Asserting $TARGET_URL is baked into the JS bundle..."
if ! docker run --rm "$IMAGE_TAG" sh -c \
    "grep -rq 'road-quality-backend.fly.dev' /usr/share/nginx/html/assets/"; then
    echo "FAIL: SC #4 violation — VITE_API_URL was NOT baked into the bundle" >&2
    echo "  Vite consumes import.meta.env.VITE_API_URL at BUILD time, not runtime." >&2
    echo "  Re-check that ARG VITE_API_URL + ENV VITE_API_URL=\$VITE_API_URL appear" >&2
    echo "  BEFORE 'RUN npm run build' in deploy/frontend/Dockerfile." >&2
    exit 1
fi
echo "  PASS: $TARGET_URL found in /usr/share/nginx/html/assets/"

echo "Asserting no localhost API endpoint is baked into the JS bundle (SC #4 negative half)..."
# Match the actual API-misconfig signatures: localhost:<port> or 127.0.0.1.
# Bare "http://localhost" (no port) is a react-router internal (URL parse
# base, see react-router@7.1.1 dist/production/index.js); it's dead code in
# the browser path because window.location.origin overrides it. The real
# SC #4 failure mode is api.ts falling back to a localhost API URL like
# "http://localhost:8000" (uvicorn dev port) or "http://localhost:3000".
if docker run --rm "$IMAGE_TAG" sh -c \
    "grep -rqE 'localhost:[0-9]+|127\\.0\\.0\\.1' /usr/share/nginx/html/assets/" 2>/dev/null; then
    echo "FAIL: SC #4 violation — a localhost API URL was found in the production bundle" >&2
    echo "  Confirm VITE_API_URL was passed via --build-arg and did not fall through" >&2
    echo "  to api.ts's '|| \"/api\"' default." >&2
    docker run --rm "$IMAGE_TAG" sh -c \
        "grep -roE '(localhost:[0-9]+|127\\.0\\.0\\.1)[a-zA-Z0-9:/.-]*' /usr/share/nginx/html/assets/ | sort -u" >&2
    exit 1
fi
echo "  PASS: no localhost API endpoint in production bundle"

echo "Asserting nginx config is in place..."
if ! docker run --rm "$IMAGE_TAG" test -f /etc/nginx/conf.d/default.conf; then
    echo "FAIL: /etc/nginx/conf.d/default.conf not present in image" >&2
    exit 1
fi
echo "  PASS: nginx config baked in"

echo "Asserting index.html is in place..."
if ! docker run --rm "$IMAGE_TAG" test -f /usr/share/nginx/html/index.html; then
    echo "FAIL: /usr/share/nginx/html/index.html not present" >&2
    exit 1
fi
echo "  PASS: index.html baked in"

echo
echo "PASS: deploy/frontend/Dockerfile builds successfully; SC #4 regression gate green."
