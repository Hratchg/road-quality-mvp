# deploy/frontend/Dockerfile — multi-stage Vite build → nginx:alpine static
# serve for the road-quality-frontend Fly app (Phase 5, REQ-prod-deploy
# SC #1 + SC #4, CONTEXT D-03).
#
# Stage 1 (build): node:20-alpine runs `npm ci && npm run build`. The
# VITE_API_URL build ARG is propagated as an ENV var BEFORE `npm run build`
# so Vite's import.meta.env.VITE_API_URL resolves at compile time and the
# literal "https://road-quality-backend.fly.dev" is baked into the JS bundle.
# Runtime env vars (docker run -e VITE_API_URL=...) DO NOT reach the bundle —
# this is a Vite design choice, NOT a Docker quirk (RESEARCH Pitfall 4).
#
# Stage 2 (runtime): nginx:alpine serves the built dist/ output. ~50 MB
# image; nginx handles SPA fallback, gzip, and cache headers via the
# baked-in deploy/frontend/nginx.conf.
#
# Build context is the repo root (matches deploy/db/Dockerfile's convention):
# `flyctl deploy --config deploy/frontend/fly.toml .` from repo root resolves
# all COPY paths.

# Stage 1: build the Vite bundle
FROM node:20-alpine AS build
WORKDIR /app

# Copy package manifests first for Docker layer caching: as long as
# package.json + package-lock.json don't change, the npm ci layer is reused
# across rebuilds (saves ~30-60s per local rebuild iteration).
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy the rest of the frontend source.
COPY frontend/ ./

# VITE_API_URL is consumed by import.meta.env.VITE_API_URL at BUILD TIME.
# Runtime env vars (docker run -e VITE_API_URL=...) DO NOT propagate into
# the bundle. SC #4 regression gate (Plan 05-04 Task 4 + Plan 05-05 CI):
# `grep -r road-quality-backend.fly.dev /usr/share/nginx/html/assets/`
# must return matches in the deployed image; `grep -r localhost
# /usr/share/nginx/html/assets/` must return ZERO matches.
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build  # produces /app/dist with index.html + hashed assets

# Stage 2: serve the static bundle via nginx
FROM nginx:alpine

# Replace nginx's default config with our SPA-aware one.
COPY deploy/frontend/nginx.conf /etc/nginx/conf.d/default.conf

# Copy the built bundle from Stage 1.
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
