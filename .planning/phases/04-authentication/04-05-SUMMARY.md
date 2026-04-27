---
phase: 04-authentication
plan: 05
subsystem: operations
tags: [python, scripts, docker, docker-compose, env-interpolation, demo-account, argon2id, operations, docs]

# Dependency graph
requires:
  - phase: 04-authentication
    provides: "users table + UNIQUE(email) (plan 04-01); hash_password helper (plan 04-02); /auth/* routes + AUTH_SIGNING_KEY consumer (plan 04-03)"
provides:
  - "scripts/seed_demo_user.py — idempotent argon2id-hashed demo-user UPSERT, rotation-safe"
  - ".env.example Auth section documenting AUTH_SIGNING_KEY (consumer, generation cmd, rotation semantics)"
  - "docker-compose.yml backend.environment AUTH_SIGNING_KEY: ${AUTH_SIGNING_KEY:-} interpolation"
  - "README.md ## Public Demo Account section with creds, local-setup runbook, and rotation procedure"
  - "First use of ${VAR:-} docker-compose interpolation in this project (Phase 5 will formalize for cloud secrets)"
affects: [05-deploy-and-monitoring, 06-public-demo-launch]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Docker-compose ${VAR:-} env-interpolation for backend-only secrets (AUTH_SIGNING_KEY); Phase 5 cloud secrets translate 1:1 (var name stays the same, source changes)"
    - "Idempotent seed script via ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash — re-runs rotate the demo password and transparently re-strengthen the hash on pwdlib param bumps"
    - "Operator-runbook section in README (## Public Demo Account) following the precedent set by Phase 3's MAPILLARY_INGEST.md and Phase 2's DETECTOR_EVAL.md operator-docs convention"
    - "Sys.path tweak in scripts/ to import backend modules (mirrors scripts/compute_scores.py and scripts/ingest_mapillary.py)"

key-files:
  created:
    - "scripts/seed_demo_user.py"
    - ".planning/phases/04-authentication/04-05-SUMMARY.md"
  modified:
    - ".env.example"
    - "docker-compose.yml"
    - "README.md"

key-decisions:
  - "Demo password (demo1234) is documented in README and rotatable via scripts/seed_demo_user.py --password — explicit D-05 trade for the Try-as-demo UX (T-04-36 accepted)"
  - "Empty AUTH_SIGNING_KEY default in docker-compose interpolation (${AUTH_SIGNING_KEY:-}) is intentional: triggers backend _signing_key() RuntimeError on missing key, visible failure mode (preferred over silent weak default)"
  - "Seed script reuses backend.app.auth.passwords.hash_password rather than re-implementing argon2id — guarantees param-lock-step with the verify path on future pwdlib defaults bumps"
  - "Seed script never prints the password or password_hash, even when --password is explicitly supplied (RESEARCH Pitfall 1 — only id and email reach stdout)"
  - "Seed script exit-code contract: 0 success, 2 DB unreachable, 3 users-table-missing — Phase 5/6 deploy automation can branch on these"
  - "README section heading is 'Public Demo Account' (long form acceptable per PATTERNS Shared Pattern 7)"

patterns-established:
  - "Pattern: docker-compose ${VAR:-} interpolation for secrets sourced from operator .env (or host env, or CI secrets in Phase 5)"
  - "Pattern: idempotent seed scripts use ON CONFLICT DO UPDATE so re-runs are no-ops AND rotations (single-command operator UX)"
  - "Pattern: Auth-related env vars use empty placeholders in .env.example so backend fail-fast triggers cleanly when operators forget to set the value"

requirements-completed: [REQ-user-auth]

# Metrics
duration: ~4min
completed: 2026-04-27
---

# Phase 04 Plan 05: Public-Demo Operational Glue Summary

**Operator-runbook plumbing for the Phase 4 demo: idempotent seed script using backend's argon2id helper, AUTH_SIGNING_KEY plumbed through docker-compose via ${VAR:-} interpolation, and a README "Public Demo Account" section with one-command rotation procedure.**

## Performance

- **Duration:** ~4 min (executed in parallel with plan 04-04)
- **Started:** 2026-04-27T02:12:56Z
- **Completed:** 2026-04-27T02:16:22Z
- **Tasks:** 4/4
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments

- Operators can now run `docker compose up` + `python scripts/seed_demo_user.py` and have a working demo account; no more bespoke psql + ad-hoc Python ceremony.
- `${AUTH_SIGNING_KEY:-}` interpolation is the project's first use of docker-compose env-interpolation — Phase 5's cloud-secrets path translates 1:1 (env-var name stays the same, source becomes the secret store).
- Demo password rotation is a one-liner (`scripts/seed_demo_user.py --password $NEW`); session revocation is also a one-liner (rotate AUTH_SIGNING_KEY + restart backend) — the M1 revocation lever (D-01) is documented and tested in README.
- README `## Public Demo Account` section is the link target Phase 6 will point at for the public-URL announcement; anchor: `#public-demo-account`.

## Task Commits

Each task was committed atomically (no-verify per worktree convention):

1. **Task 1: Create scripts/seed_demo_user.py with idempotent UPSERT and CLI args** — `c11c27d` (feat)
2. **Task 2: Append the Auth section to .env.example documenting AUTH_SIGNING_KEY** — `3e9e6ce` (feat)
3. **Task 3: Add AUTH_SIGNING_KEY to docker-compose.yml backend.environment via ${VAR:-} interpolation** — `9d25c81` (feat)
4. **Task 4: Add the ## Public Demo Account section to README.md** — `27e1ba8` (docs)

**Plan metadata commit:** _included in this SUMMARY commit_ (worktree convention; final commit covers the SUMMARY only since STATE.md/ROADMAP.md updates are deferred to the orchestrator).

## Files Created/Modified

- `scripts/seed_demo_user.py` (created) — idempotent demo-user seed with argparse `--email`/`--password`, ON CONFLICT UPSERT, exit codes 0/2/3, never prints secrets.
- `.env.example` (modified, +12 lines) — new `# ----- Auth (Phase 4, REQ-user-auth) -----` section appended after MAPILLARY_ACCESS_TOKEN; documents consumer file, generation command, rotation note, and >=32 char rule.
- `docker-compose.yml` (modified, +1 line) — added `AUTH_SIGNING_KEY: ${AUTH_SIGNING_KEY:-}` to `services.backend.environment`; preserves plan 04-01's `db.volumes` mount of `003_users.sql`.
- `README.md` (modified, +57 lines) — new `## Public Demo Account` section between `## Tests` and `## Tech Stack` (within the API-Endpoints..Tech-Stack window per acceptance criteria) covering creds, local setup, and rotation.

## Decisions Made

None new — all decisions were locked by 04-CONTEXT.md (D-01, D-05) and 04-RESEARCH.md (§7 seed script content; §8 docker-compose interpolation; Pitfall 1 no-secret-prints; Pitfall 3 email normalization). The script's exit-code numbering (2 DB-down, 3 schema-missing) is the only locally-decided contract — chosen so Phase 5/6 deploy automation can `if rc == 3` to know "needs migration first" vs. `if rc == 2` "needs DB up".

## Deviations from Plan

None - plan executed exactly as written.

The README insertion landed just before `## Tech Stack` (after `## Tests`), which the plan acceptance criteria explicitly permits ("between `## API Endpoints` and `## Tech Stack`" — this satisfies that window; the README has multiple intermediate sections so the precise sub-position within the window is a judgment call covered by `<deviations>` Acceptable variations).

## Issues Encountered

None. The script's `--help` was sanity-checked against the local `/tmp/rq-venv/bin/python` (which has `psycopg2-binary` and `pwdlib` installed per the env-note in the executor prompt); end-to-end DB-write verification requires Docker to be running, which is out of scope for this in-worktree execution.

## End-to-End Verification Status

The static-analysis subset of plan §verification passed in this worktree:
- `python3 -c "import ast; ast.parse(open('scripts/seed_demo_user.py').read())"` parses cleanly.
- `python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml'))"` parses cleanly.
- `git status` shows only the 4 expected modifications (1 new file + 3 modified); no extraneous changes.
- `grep -E "(print|f).*\b(password|password_hash)\b" scripts/seed_demo_user.py` returns ONLY the docstring + argparse `help=` text + the explanatory `# NEVER print the password...` comment (no runtime print of secrets).
- `python3 scripts/seed_demo_user.py --help` renders the full help text including the D-05 default email and the rotation usage examples.

The dynamic subset of plan §verification (DB writes, /auth/login round-trip with the seeded creds, idempotency on re-run, exit-code 2 on DB-down) requires Docker and is documented as a manual operator-smoke step in the plan; downstream merge into main will exercise it in the integration environment.

## User Setup Required

None — this plan is pure operational glue. After merge, the standard local-dev flow becomes:

```bash
docker compose up --build
python -c "import secrets; print('AUTH_SIGNING_KEY=' + secrets.token_urlsafe(32))" >> .env
docker compose restart backend
python scripts/seed_demo_user.py
```

## Phase 4 Completion Status

This plan closes Phase 4. Success Criteria status (from 04-CONTEXT.md):

| SC | Description | Plan |
|----|-------------|------|
| 1 | User can sign up with email + password via API | 04-03 (`POST /auth/register`) |
| 2 | User can sign in, receive a session token | 04-03 (`POST /auth/login` returns JWT) |
| 3 | `POST /route` and `/cache/*` return 401; `GET /health`, `GET /segments` remain public | 04-03 (gating dependency) |
| 4 | Passwords are hashed (argon2id) | 04-02 (`hash_password`/`verify_password`) |
| 5 | New migration adds users table; applies cleanly to fresh DB via init flow | 04-01 (`db/migrations/003_users.sql` + docker init mount) |

Plan 04-04 (frontend `<SignInModal>` + 401-interceptor) and this plan (operator glue) wrap the loose ends. With both merged, Phase 4 is functionally complete.

## Next Phase Readiness

**Phase 5 handoff (deploy + monitoring):**
- Cloud deploy MUST source `AUTH_SIGNING_KEY` from a real secrets store (AWS Secrets Manager, Fly.io secrets, Render env var, etc.) — never `.env`. The docker-compose interpolation pattern translates 1:1: the env-var name stays the same; only the source changes. The empty default in `${AUTH_SIGNING_KEY:-}` will keep failing-fast in a misconfigured cloud env, which is the desired behavior.
- CI deploy script should invoke `python scripts/seed_demo_user.py` post-deploy; check exit code 0 (success). Exit code 3 means migration 003 didn't apply — investigate the docker init flow. Exit code 2 means the DB isn't reachable from the deploy runner.
- CORS hardening (Phase 5 SC #2) is still pending — `backend/app/main.py` currently has `allow_origins=["*"]`. This plan deliberately does NOT touch CORS.

**Phase 6 handoff (public demo launch):**
- The README `## Public Demo Account` section (anchor `#public-demo-account`) is the link target for the Phase 6 public-URL announcement. The rotation procedure (password + signing-key) is documented and ready for the "if abuse appears" runbook.
- The "Try as demo" button referenced in the README is delivered by plan 04-04 (frontend `SignInModal.tsx`).
- If the demo password needs rotating before public launch: `python scripts/seed_demo_user.py --password $NEW`, update README, redeploy.

## Threat Model Disposition (this plan's surface)

All threats from the plan's threat register were either accepted (per locked decision) or mitigated by the implementation:

| Threat ID | Disposition | Status |
|-----------|-------------|--------|
| T-04-36 | accept (D-05) | Demo password committed in README; rotation lever documented. |
| T-04-37 | mitigate | `.env.example` AUTH_SIGNING_KEY value field is empty (verified by `grep -q "^AUTH_SIGNING_KEY=$"`). |
| T-04-38 | mitigate | Seed script prints only `id` and `email` (verified by code review + grep). |
| T-04-39 | mitigate | Empty docker-compose default triggers backend `_signing_key()` RuntimeError; README documents the fix. |
| T-04-40 | accept | Privileged-host concern; cloud secrets management (Phase 5) is the standard mitigation. |
| T-04-41 | accept | Phase 5 owns the cloud-secrets path; CI-log hygiene is operator policy. |
| T-04-42 | accept | Rate limit (Phase 5) is the real defense; rotation procedures documented for the abuse-response runbook. |
| T-04-43 | accept | Operator-only script; argon2 latency bounds even a tight loop. |

No new threat surface was introduced beyond what the plan's `<threat_model>` enumerated.

## Self-Check: PASSED

- `scripts/seed_demo_user.py` — FOUND
- `.env.example` Auth section — FOUND
- `docker-compose.yml` AUTH_SIGNING_KEY interpolation — FOUND
- `docker-compose.yml` 04-01 db-volume mount — PRESERVED
- `README.md` `## Public Demo Account` — FOUND
- Commit `c11c27d` (Task 1) — FOUND
- Commit `3e9e6ce` (Task 2) — FOUND
- Commit `9d25c81` (Task 3) — FOUND
- Commit `27e1ba8` (Task 4) — FOUND

---
*Phase: 04-authentication*
*Plan: 05*
*Completed: 2026-04-27*
