"""Seed (or rotate) the public-demo user account.

04-CONTEXT.md D-05 locks:
- email: demo@road-quality-mvp.dev
- password: rotatable; documented in README and frontend SignInModal; the
  current value MUST be passed via --password on every invocation so the
  literal does not live in this script's source (WR-04 rotation drift fix).

Idempotent via ON CONFLICT (email) DO UPDATE — re-running with the same
credentials updates the password_hash to a freshly-computed argon2id hash.
This means future pwdlib param bumps (RESEARCH Pitfall 4) re-strengthen the
demo hash on each re-run, transparently.

Usage:
  python scripts/seed_demo_user.py --password demo1234
  python scripts/seed_demo_user.py --email demo@road-quality-mvp.dev --password demo1234
  python scripts/seed_demo_user.py --password $NEW_DEMO_PW   # rotation

Prerequisite: migration 003_users.sql has been applied (the ON CONFLICT
target is the users_email_key UNIQUE index, which the migration creates).

Note: this script does NOT need AUTH_SIGNING_KEY set — it only writes a
password_hash, never an issued token. The first /auth/login call after
seeding is what exercises AUTH_SIGNING_KEY.

Exit codes:
  0  success
  2  DB unreachable (psycopg2.OperationalError)
  3  users table missing — apply migration 003_users.sql first
"""
from __future__ import annotations

import argparse
import os
import sys

import psycopg2

# Reuse backend's password helper. backend/ is a sibling of scripts/ — adjust
# sys.path so this file can be invoked from repo root without installing the
# backend as a package. Mirrors scripts/compute_scores.py and
# scripts/ingest_mapillary.py.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app.auth.passwords import hash_password  # noqa: E402


DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)
DEFAULT_EMAIL = "demo@road-quality-mvp.dev"  # 04-CONTEXT.md D-05


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--email", default=DEFAULT_EMAIL,
                    help=f"Demo email (default: {DEFAULT_EMAIL})")
    # WR-04: --password is required; the literal must NOT live in this
    # script's source. README is the single human-readable truth source
    # for the current demo password value; SignInModal.tsx hardcodes it
    # for the 'Try as demo' UX. Rotating the demo password = update those
    # two sites + re-run this script with the new value.
    ap.add_argument("--password", required=True,
                    help="Demo password (rotatable; see README for current value)")
    args = ap.parse_args()

    email = args.email.strip().lower()  # mirror app-layer normalization (Pitfall 3)
    pwd_hash = hash_password(args.password)  # ~150-300ms argon2id

    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # ON CONFLICT for idempotency. UPDATE password_hash on re-run so
                # rotations and pwdlib param upgrades are one command.
                cur.execute(
                    "INSERT INTO users (email, password_hash) VALUES (%s, %s) "
                    "ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash "
                    "RETURNING id",
                    (email, pwd_hash),
                )
                row = cur.fetchone()
                user_id = row[0]
                conn.commit()
    except psycopg2.OperationalError as e:
        print(f"ERROR: cannot connect to DB at {DATABASE_URL}: {e}", file=sys.stderr)
        print(
            "Hint: is the DB container up? "
            "docker compose up -d db && wait for healthy",
            file=sys.stderr,
        )
        return 2
    except psycopg2.errors.UndefinedTable as e:
        print(f"ERROR: users table missing — apply migration 003 first: {e}",
              file=sys.stderr)
        print(
            "Hint: docker compose exec -T db psql -U rq -d roadquality "
            "< db/migrations/003_users.sql",
            file=sys.stderr,
        )
        return 3

    # NEVER print the password or password_hash. Only id + email.
    print(f"Demo user seeded: id={user_id}, email={email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
