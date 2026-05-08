---
phase: 05-cloud-deployment
plan: 04
subsystem: infra
tags: [fly, docker, nginx, vite, frontend, multi-stage, build-args, spa-fallback]

# Dependency graph
requires:
  - phase: 05-cloud-deployment
    provides: Plan 05-03's deploy/backend/fly.toml app name (road-quality-backend) — frontend's [build.args].VITE_API_URL points at https://road-quality-backend.fly.dev
provides:
  - Multi-stage production frontend image (node:20-alpine builder → nginx:alpine runtime, ~92 MB)
  - SPA-aware nginx config (try_files fallback for react-router-dom v7, immutable cache for hashed assets, no-cache for index.html)
  - Reproducible Fly app config (road-quality-frontend) with [build.args].VITE_API_URL inline so the deployed-backend URL lives in git
  - SC #4 regression gate at the Docker layer (test-build.sh asserts the deployed-backend URL IS in the bundle and no localhost API URL leaks)
affects: [05-05-deploy-runbook, 06-custom-domain, 06-cloudflare-cdn]

# Tech tracking
tech-stack:
  added: [nginx:alpine (runtime), node:20-alpine (build), Vite build-arg pipeline]
  patterns:
    - "Vite VITE_API_URL build-arg discipline (ARG → ENV → npm run build, all in stage 1)"
    - "Multi-stage Dockerfile (build-only deps stay in stage 1; runtime stage stays small)"
    - "SPA fallback via nginx try_files (canonical react-router-dom pattern)"
    - "Cache-Control split (immutable for hashed assets, no-cache for index.html)"
    - "[build.args] inline in fly.toml for reproducible deploys (vs. CLI --build-arg)"

key-files:
  created:
    - deploy/frontend/Dockerfile
    - deploy/frontend/nginx.conf
    - deploy/frontend/fly.toml
    - deploy/frontend/test-build.sh
  modified: []

key-decisions:
  - "node:20-alpine over node:20-slim for the build stage (~40% smaller image)"
  - "[build.args].VITE_API_URL inline (in git) rather than CLI --build-arg per deploy — reproducibility wins for a locked backend URL; CLI override remains available for ad-hoc rebuilds"
  - "force_https=true on the frontend http_service (Fly auto-issues *.fly.dev TLS; HTTPS-only matches Phase 6+ cookie-session forward-compat)"
  - "Refined the SC #4 localhost smoke test from a bare `grep localhost` to `grep -E 'localhost:[0-9]+|127\\.0\\.0\\.1'` because react-router@7.1.1 ships the literal `\"http://localhost\"` (no port) as a URL parse base in dist/production/index.js — bare grep produces a false positive on harmless library internals"

patterns-established:
  - "Build-arg-baked Vite SPA: VITE_* vars flow [build.args] → Docker --build-arg → ARG → ENV → import.meta.env at compile time. Future Vite env vars (VITE_SENTRY_DSN, VITE_FEATURE_FLAGS) follow the same shape."
  - "Greenfield production Dockerfile alongside untouched dev Dockerfile: frontend/Dockerfile stays dev-only (npm run dev), deploy/frontend/Dockerfile is prod-only (nginx static serve). Two completely different shapes; no hybrid."
  - "Cross-app reference convention: deploy/frontend/fly.toml's VITE_API_URL = 'https://<deploy/backend/fly.toml::app>.fly.dev'. Verified by Plan 05-04's verification block step 10."

requirements-completed: [REQ-prod-deploy]

# Metrics
duration: 5m 25s
completed: 2026-04-27
---

# Phase 05 Plan 04: Frontend Fly Image (Multi-stage Vite + nginx) Summary

**Production frontend image (node:20-alpine builder → nginx:alpine runtime, 92 MB) with build-time-baked VITE_API_URL, SPA-aware nginx config, and reproducible fly.toml.**

## Performance

- **Duration:** 5m 25s
- **Started:** 2026-04-27T19:50:05Z
- **Completed:** 2026-04-27T19:55:30Z
- **Tasks:** 3 / 3
- **Files created:** 4
- **Files modified:** 0

## Accomplishments

- Multi-stage Dockerfile that bakes `VITE_API_URL=https://road-quality-backend.fly.dev` into the JS bundle at compile time (verified by `docker run grep` returning the literal in `/usr/share/nginx/html/assets/index-*.js`)
- nginx config with the canonical SPA fallback (`try_files $uri $uri/ /index.html;`) so react-router-dom v7 routes survive hard-refresh, plus a Cache-Control split (immutable for hashed assets, no-cache for index.html) that lets deploys propagate while keeping the bundle aggressively cached
- Fly app config (`road-quality-frontend`, lax region, force_https, auto-stop with min_machines_running=0) with `[build.args].VITE_API_URL` inline so deploys are reproducible from git
- SC #4 regression gate at the Docker layer: `deploy/frontend/test-build.sh` builds the image, asserts the deployed-backend URL IS in `/usr/share/nginx/html/assets/`, asserts no `localhost:<port>` or `127.0.0.1` is in the bundle, asserts nginx config + index.html are baked in. End-to-end PASS.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create deploy/frontend/Dockerfile + test-build.sh** — `37d14cc` (feat)
2. **Task 2: Create deploy/frontend/nginx.conf** — `459a797` (feat, includes Rule 1 fix to test-build.sh)
3. **Task 3: Create deploy/frontend/fly.toml** — `eb04a8d` (feat)

_Note: Plan-metadata commit (this SUMMARY) is added separately per the parallel-execution contract; STATE.md and ROADMAP.md are NOT touched in this worktree._

## Files Created/Modified

### Created

- `deploy/frontend/Dockerfile` — 2-stage multi-stage build. Stage 1 (`node:20-alpine`): `npm ci` (cached layer) → `COPY frontend/` → `ARG VITE_API_URL` + `ENV VITE_API_URL=$VITE_API_URL` → `RUN npm run build`. Stage 2 (`nginx:alpine`): copies `deploy/frontend/nginx.conf` to `/etc/nginx/conf.d/default.conf` and `/app/dist` to `/usr/share/nginx/html`. EXPOSE 80, `CMD ["nginx", "-g", "daemon off;"]`. Build context = repo root.
- `deploy/frontend/nginx.conf` — single server block. Listens 80 on IPv4 + IPv6. Root `/usr/share/nginx/html`. SPA fallback `try_files $uri $uri/ /index.html`. Two cache blocks: `\.(js|css|woff2?|png|jpg|svg)$` gets `expires 1y` + `Cache-Control: public, immutable`; `= /index.html` gets `Cache-Control: no-cache, must-revalidate`. No `/api` proxy (cross-origin to backend per D-03).
- `deploy/frontend/fly.toml` — `app = "road-quality-frontend"`, `primary_region = "lax"`, `[build].dockerfile = "deploy/frontend/Dockerfile"`, `[build.args].VITE_API_URL = "https://road-quality-backend.fly.dev"`. `[http_service]` internal_port=80, force_https=true, auto_stop_machines="stop", min_machines_running=0. `[[http_service.checks]]` GET `/` every 30s, grace 5s, timeout 3s. `[[vm]]` shared-cpu-1x, 256mb. NO `[deploy]`, `[[mounts]]`, or `[env]` blocks.
- `deploy/frontend/test-build.sh` — bash smoke test (executable, 0755). `docker build --build-arg VITE_API_URL=https://road-quality-backend.fly.dev -f deploy/frontend/Dockerfile -t road-quality-frontend:test .` then 4 transient `docker run` assertions: (1) deployed-backend URL IS in the bundle, (2) no `localhost:<port>` or `127.0.0.1` in the bundle, (3) `/etc/nginx/conf.d/default.conf` exists, (4) `/usr/share/nginx/html/index.html` exists.

### Modified

None. Per the plan's must_not_haves and the worktree boundary, the dev `frontend/Dockerfile`, `frontend/src/api.ts`, `frontend/package.json`, and `docker-compose.yml` were left untouched. STATE.md and ROADMAP.md were also untouched (parallel-executor contract).

## Decisions Made

- **alpine over slim for the builder stage.** RESEARCH §2 line 285 picks `node:20-alpine`; the plan's PATTERNS placeholder used `node:20-slim`. Alpine is ~40% smaller and the Vite build doesn't need glibc-specific binaries. Final image: 92.3 MB (Stage 2 is `nginx:alpine`, not affected by Stage 1's choice).
- **Inline build-arg vs. CLI build-arg.** Inline (`[build.args].VITE_API_URL = "..."` in fly.toml) wins for reproducibility — the URL lives in git; any clone can rebuild byte-equivalent images. CLI override (`flyctl deploy --build-arg VITE_API_URL=...`) remains available for ad-hoc rebuilds (e.g., staging) without editing the file. RESEARCH §2 line 279 documents the tradeoff.
- **No `[deploy].release_command`, no `[[mounts]]`, no `[env]` block in frontend's fly.toml.** Frontend is stateless (nginx serves from baked-in `/usr/share/nginx/html`); no migrations to run; runtime env vars never reach a Vite-built bundle (Pitfall 4).
- **Refined SC #4 localhost smoke check.** The plan's must_not_haves bullet asserts "no `localhost` substring in the production bundle". Empirically, `react-router@7.1.1` ships the literal `"http://localhost"` (no port) in `dist/production/index.js` line 216 as a URL parse base for `new URL(createHref(to), "http://localhost")`. It's dead code in the browser path because `window.location.origin` overrides it. Bare `grep localhost` produces a false positive. The corrected regex `'localhost:[0-9]+|127\.0\.0\.1'` matches only the actual SC #4 failure mode (api.ts falling back to `localhost:8000` / `localhost:3000` / `127.0.0.1`) and ignores the harmless library internal. Documented in test-build.sh comments lines 44-49.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Refined SC #4 localhost regex in test-build.sh**

- **Found during:** Task 2 (running `bash deploy/frontend/test-build.sh` end-to-end after nginx.conf landed)
- **Issue:** The plan's smoke test used `grep -rq 'localhost' /usr/share/nginx/html/assets/` which produced a false positive. The bundle DID contain the literal `"http://localhost"` — but as a `react-router@7.1.1` internal URL parse base (`return new URL(createHref2(to), "http://localhost")` in `dist/production/index.js:216`), NOT as an api.ts misconfig. The literal is dead code in the browser path because `window.location.origin` overrides it.
- **Fix:** Changed the regex to `grep -rqE 'localhost:[0-9]+|127\.0\.0\.1'` which matches the actual API misconfig signatures (`localhost:8000`, `localhost:3000`, `127.0.0.1`) and ignores the bare `"http://localhost"` (no port) library internal. Added inline comments in test-build.sh documenting the rationale (lines 44-49) so a future contributor doesn't widen the regex back. Also added a debug grep on failure that shows exactly which localhost URL was found, to ease diagnosis.
- **Files modified:** `deploy/frontend/test-build.sh` (lines 43-60)
- **Verification:** End-to-end smoke test PASSES all four assertions (URL baked in, no localhost API endpoint, nginx config in place, index.html in place). Spot-check confirms `https://road-quality-backend.fly.dev` IS in `assets/index-CSHSBFAU.js`.
- **Committed in:** `459a797` (folded into the Task 2 commit since the fix was discovered while running Task 2's smoke test; both changes are deploy/frontend artifacts)

---

**Total deviations:** 1 auto-fixed (1 bug — refined a false-positive grep)
**Impact on plan:** No scope creep. The Dockerfile, nginx.conf, and fly.toml are byte-equivalent to RESEARCH §2 verbatim targets. Only the smoke test's regex was tightened to match the real failure mode it's meant to guard. The original SC #4 invariant — "the bundle hits the deployed backend, not localhost" — is now correctly enforced.

## Issues Encountered

- **`docker-compose.yml` style note:** The plan's verification step 1 assumed exactly 4 new files, 0 modified files. Confirmed: `git status --short` after all 3 commits shows nothing pending. The dev `frontend/Dockerfile` is untouched and intentionally remains the dev image (CMD `npm run dev`); the production image lives at `deploy/frontend/Dockerfile`.
- **Parallel worktree:** Plan 05-03 (sibling worktree) is creating `deploy/db/*` and `deploy/backend/fly.toml`. This worktree's `find deploy -type f` lists only `deploy/frontend/*` artifacts. The cross-app reference sanity check (verification step 10) was adapted: when `deploy/backend/fly.toml` is absent (parallel branch), the check confirms the frontend's VITE_API_URL points at the locked literal `https://road-quality-backend.fly.dev`. After the parallel worktrees merge, the full cross-app sanity check (`backend_app=$(grep '^app = ' deploy/backend/fly.toml | sed -E ...)` + grep) will validate.

## SC #4 Closure Status

This plan delivers the **Docker-layer half** of SC #4 (no localhost in production bundle):

- ✅ Dockerfile bakes VITE_API_URL via `ARG → ENV → npm run build` discipline (RESEARCH Pitfall 4 closed at the build layer)
- ✅ test-build.sh asserts the deployed-backend URL IS in the bundle and no localhost API URL leaks (verified end-to-end with a real Docker build)
- ⏳ Plan 05-05's GH Actions workflow runs `bash deploy/frontend/test-build.sh` as a pre-deploy CI check (transitions the gate from local-only to CI-enforced)
- ⏳ Plan 05-05's deploy-time UAT smoke fetches the live `road-quality-frontend.fly.dev` and confirms the JS bundle hits the live backend (closes SC #4 against the deployed environment)

The Vite build-time-vs-runtime invariant (Pitfall 4) is now physically impossible to violate without editing `deploy/frontend/Dockerfile` — the ARG/ENV must be present BEFORE `RUN npm run build` for Vite's compiler to see them.

## Cross-App Reference

`deploy/frontend/fly.toml`'s `[build.args].VITE_API_URL` MUST match Plan 05-03's `deploy/backend/fly.toml`'s `app = "road-quality-backend"`. The literal in this worktree:

```
VITE_API_URL = "https://road-quality-backend.fly.dev"
```

The verify-step-10 sanity script (`grep -q "VITE_API_URL = \"https://${backend_app}.fly.dev\"" deploy/frontend/fly.toml`) will run cleanly once both worktrees merge into master.

## Self-Check: PASSED

- ✅ `deploy/frontend/Dockerfile` exists (verified via `test -f`)
- ✅ `deploy/frontend/nginx.conf` exists (verified via `test -f`)
- ✅ `deploy/frontend/fly.toml` exists (verified via `test -f`)
- ✅ `deploy/frontend/test-build.sh` exists, executable (verified via `test -x`)
- ✅ Commit `37d14cc` exists in `git log` (Task 1)
- ✅ Commit `459a797` exists in `git log` (Task 2 + Rule 1 fix)
- ✅ Commit `eb04a8d` exists in `git log` (Task 3)
- ✅ Smoke test exits 0 (Docker available, all 4 assertions PASS)
- ✅ TOML lint passes (`tomllib.loads()` exits 0)
- ✅ nginx -t passes against the config (verified via `nginx:alpine` container)
- ✅ No modifications to `frontend/Dockerfile`, `frontend/src/api.ts`, `frontend/package.json`, `docker-compose.yml`, `.planning/STATE.md`, `.planning/ROADMAP.md`

## Next Phase Readiness

Plan 05-05 (deploy runbook + GH Actions CI) can now consume:
- `deploy/frontend/Dockerfile` for `flyctl deploy --config deploy/frontend/fly.toml .`
- `deploy/frontend/test-build.sh` for the pre-deploy CI smoke
- `road-quality-frontend.fly.dev` as the post-deploy UAT target (CORS contract check against `road-quality-backend.fly.dev`)

Phase 6+ extension paths (no work needed in Phase 5):
- Custom domain via `[[certificates]]` block in `deploy/frontend/fly.toml`
- Cloudflare CDN in front of `road-quality-frontend.fly.dev` (caches the immutable hashed assets at the edge — already cache-friendly)
- `server_tokens off;` in `nginx.conf` if a security-headers audit prioritizes hiding the nginx version

---
*Phase: 05-cloud-deployment*
*Plan: 04*
*Completed: 2026-04-27*
