---
phase: 05-cloud-deployment
fixed_at: 2026-04-25T00:00:00Z
review_path: .planning/phases/05-cloud-deployment/05-REVIEW.md
iteration: 1
findings_in_scope: 7
fixed: 7
skipped: 0
status: all_fixed
---

# Phase 5: Code Review Fix Report

**Fixed at:** 2026-04-25T00:00:00Z
**Source review:** `.planning/phases/05-cloud-deployment/05-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 7 (2 Critical + 5 Warning; Info deferred per fix_scope=critical_warning)
- Fixed: 7
- Skipped: 0

Pre-fix baseline: 209 backend tests passing (`pytest -q -m "not integration"`).
Post-fix verification: 209 backend tests passing — no regression.

## Fixed Issues

### CR-01: Backend Dockerfile build-context mismatch (DEPLOY-BLOCKING)

**Files modified:** `deploy/backend/fly.toml`, `.github/workflows/deploy.yml`
**Commit:** `54dffb9`
**Applied fix:** Adopted the smaller-diff Option B from REVIEW (per user prompt's
"recommended fix" directive): point `[build].dockerfile = "Dockerfile"` at a
backend-rooted build context, and pass `backend/` as the last positional arg of
`flyctl deploy` so the existing `COPY requirements.txt .` / `COPY . .`
directives resolve the same way they do under `docker compose build`
(`build: ./backend`). Preserves dev parity — the local Dockerfile is unchanged.

Also rewrote `seed-on-demand` to run `scripts/seed_data.py` from the host venv
on the GitHub runner (matches the pre-deploy pytest gate). Open a `flyctl proxy
5432:5432 --app road-quality-db` tunnel in the background, install
`scripts/requirements.txt`, then run the seed against `localhost` with the DB
password sourced from the `PG_PASSWORD` GH Actions secret. This sidesteps the
"scripts/ is not in the backend image" question entirely.

### CR-02: CI bypass when test job fails (DEPLOY-BLOCKING)

**Files modified:** `.github/workflows/deploy.yml`
**Commit:** `be31c4f`
**Applied fix:** Added `test` to `needs:` for both `deploy-frontend` and
`seed-on-demand`, and gated their `if:` on `(needs.test.result == 'success' ||
needs.test.result == 'skipped')`. Mirrors the existing pattern on `deploy-db`
and `deploy-backend`. Closes the `skipped`-fallback bypass: a failing pytest
gate now correctly blocks frontend deploys and seed runs.

### WR-01: nginx.conf missing security headers + add_header inheritance gotcha

**Files modified:** `deploy/frontend/nginx.conf`
**Commit:** `01ce5de`
**Applied fix:** Added the four cheap defense-in-depth headers
(`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin`,
`Strict-Transport-Security: max-age=31536000; includeSubDomains`) at the server
level with the `always` flag. Because nginx's `add_header` does NOT inherit
into a `location` block once that block sets any `add_header` of its own, also
repeated all four headers inside the regex assets block and the `/index.html`
exact-match block (which already set `Cache-Control`). Switched the existing
`Cache-Control` directives to use `always` for consistency. Comment in the
config explains the inheritance gotcha for future readers.

### WR-02: test_routing_pool_release.py reaches into pool._used (private API)

**Files modified:** `backend/app/db.py`, `backend/tests/test_routing_pool_release.py`
**Commit:** `bc41d92`
**Applied fix:** Added a public `get_pool_stats()` helper to `backend/app/db.py`
that returns `{"used": ..., "available": ...}`. Updated both `pool._used`
accesses in `test_routing_pool_release.py` to call the helper. A future
psycopg2 release that renames or removes the private attribute is now isolated
to the helper — the SC #9 leak-detection regression gate stays stable.

### WR-03: README /health docs stale

**Files modified:** `README.md`
**Commit:** `5666f7b`
**Applied fix:** Replaced the one-line `Returns {"status": "ok"}` with the
full Phase 5 contract: `200` + `{"status": "ok", "db": "reachable"}` on
success, `503` + `{"detail": {"status": "unhealthy", "db": "unreachable"}}`
on DB failure. Noted that the PRD M0 contract is preserved as an additive
superset and explained the Fly health-check semantics (depool, no restart).

### WR-04: AUTH_SIGNING_KEY length floor undocumented in CI

**Files modified:** `.github/workflows/deploy.yml`
**Commit:** `9c4231f`
**Applied fix:** Added an inline comment to the test step's `env:` block
spelling out the >= 32-char floor enforced by `backend/app/auth/tokens.py`,
linking to the production-secret generation pattern (`secrets.token_urlsafe(32)`),
and noting that trimming the literal will fail loud with a startup-time
validation error. The literal itself was already 44 chars and is unchanged.

### WR-05: dorny/paths-filter base ref undefined

**Files modified:** `.github/workflows/deploy.yml`
**Commit:** `f40e7af`
**Applied fix:** Pinned `base: ${{ github.event.before || 'main' }}` on the
`dorny/paths-filter@v3` step. On normal pushes, `github.event.before` is the
previous commit; on the first push and on `workflow_dispatch`, the fallback to
`main` provides a stable diff target. Comment notes that manual
`workflow_dispatch` against current main produces empty changesets (all outputs
`false`), which is the desired behaviour for a seed-only trigger — deploy jobs
skip, only `seed-on-demand` runs.

---

_Fixed: 2026-04-25T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
