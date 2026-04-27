---
phase: 04-authentication
fixed_at: 2026-04-25T00:00:00Z
review_path: .planning/phases/04-authentication/04-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 4: Code Review Fix Report

**Fixed at:** 2026-04-25
**Source review:** `.planning/phases/04-authentication/04-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope (Critical + Warning): 4
- Fixed: 4
- Skipped: 0

Info findings (IN-01 through IN-07) were out of scope for this iteration and
remain open in 04-REVIEW.md for future polish work.

## Fixed Issues

### WR-01: Login path does not use `verify_and_maybe_rehash`

**Files modified:** `backend/app/routes/auth.py`
**Commit:** `fef6e9d`
**Applied fix:**
- Added `verify_and_maybe_rehash` to the `app.auth.passwords` import line.
- Added `from contextlib import closing` (also consumed by WR-03; introduced
  here because WR-01 introduces the first call site).
- Replaced `verify_password(req.password, stored_hash)` in `login()` with
  `verify_and_maybe_rehash(...)`, capturing the `(valid, new_hash)` tuple.
- When `new_hash is not None`, run an `UPDATE users SET password_hash = %s
  WHERE id = %s` inside a `with closing(get_connection()) as conn, conn:`
  block so future pwdlib param bumps (Pitfall 4) transparently re-strengthen
  stored hashes on the user's next successful login.
- Comment notes the Pitfall 4 rationale at the rehash UPDATE site.

### WR-02: SignInModal mode-toggle buttons missing `type="button"`

**Files modified:** `frontend/src/components/SignInModal.tsx`
**Commit:** `6d5f1a7`
**Applied fix:**
- Added `type="button"` to the "Try as demo" button (line ~104).
- Added `type="button"` to the "Create one" mode-toggle button (login-mode
  branch).
- Added `type="button"` to the "Sign in" mode-toggle button (register-mode
  branch).
- Real submit button keeps `type="submit"`.
- Tier 2 verification: `npx -p typescript@5.7.3 tsc --noEmit` reports only
  pre-existing errors caused by an empty local `node_modules` (missing
  `react`/`leaflet` types). No new diagnostics on `SignInModal.tsx` from the
  attribute additions.

### WR-03: DB connection leak in `auth.py`

**Files modified:** `backend/app/routes/auth.py`
**Commit:** `ab3d552`
**Applied fix:**
- Wrapped `register()`'s INSERT block in
  `with closing(get_connection()) as conn, conn:` so the socket is released
  even after a successful commit. Inner `with conn:` continues to manage
  the transaction (commit on clean exit, rollback on exception).
- Removed the now-redundant explicit `conn.commit()` from the register
  block (the inner `with conn:` commits automatically on clean exit, matching
  the canonical pattern in `scripts/compute_scores.py`).
- Wrapped `login()`'s SELECT lookup block in the same
  `with closing(get_connection()) as conn, conn:` idiom.
- The rehash UPDATE block (introduced by WR-01) was already wrapped in
  `closing(...)` so it inherits this fix.
- Pattern matches the WR-04 fix from Phase 3 in `scripts/compute_scores.py`
  (commit `fd9c24f`).
- **Out of scope (per fix instructions):** `backend/app/routes/routing.py`
  shares the same pre-existing pattern from Phase 0. Not touched in this
  fix; worth a follow-up phase to apply the same wrapping across all
  request handlers that hit Postgres.

### WR-04: `seed_demo_user.py` defaults password to `"demo1234"` literal

**Files modified:** `scripts/seed_demo_user.py`
**Commit:** `74d8e3a`
**Applied fix:**
- Removed the `DEFAULT_PASSWORD = "demo1234"` constant.
- Removed the `default=DEFAULT_PASSWORD` from the argparse `--password`
  argument; set `required=True` so operators MUST pass the current demo
  password explicitly each invocation.
- Updated the module docstring (D-05 lock + Usage examples) to reflect the
  new requirement: README is the single human-readable truth source for the
  demo password value; `SignInModal.tsx` hardcodes it for the "Try as demo"
  UX (intrinsic to that flow); the seed script no longer carries a literal.
- Added an in-code comment near `--password` explaining the rotation
  procedure: update README + `SignInModal.tsx` + re-run with `--password
  $NEW`.
- Tier 2 verification: `python3 -c "import ast; ast.parse(...)"` reports
  SYNTAX OK. Direct `--help` execution fails on a pre-existing
  `ModuleNotFoundError: pwdlib` (backend deps not installed in this shell)
  unrelated to the WR-04 change.

## Skipped Issues

None — all four in-scope warnings were fixed cleanly.

---

_Fixed: 2026-04-25_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
