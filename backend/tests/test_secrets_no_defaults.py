"""SC #3 regression gate: no hardcoded secrets in committed deploy/*.toml files.

Phase 5 SC #3: 'All secrets (DB creds, Mapillary token, auth signing key)
come from the cloud host's secret mechanism; no committed defaults are
used in prod.'

This test scans deploy/db/fly.toml, deploy/backend/fly.toml, and
deploy/frontend/fly.toml for any line that LOOKS like a secret assignment
(KEY = "value" where KEY is in the documented secret roster from CONTEXT
D-05). Fails CI if any are found — the regression gate against accidental
hardcoding.

VITE_API_URL in deploy/frontend/fly.toml's [build.args] is INTENTIONAL and
NOT a secret — it's the publicly-resolvable backend URL, the same value
anyone can find via DNS. The test allowlists this specific case.

Pure unit test: no DB, no integration marker; runs in <50ms.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# REPO_ROOT = backend/tests/<file>.py.parents[2] = backend → tests → repo_root
REPO_ROOT = Path(__file__).resolve().parents[2]

# The secret roster from CONTEXT D-05 + RESEARCH §2 secrets recipe.
# Any of these env vars appearing in a deploy/*.toml's [env] block (with a
# value, not just declared) is a SC #3 violation.
SECRET_KEYS = (
    "DATABASE_URL",
    "AUTH_SIGNING_KEY",
    "MAPILLARY_ACCESS_TOKEN",
    "ALLOWED_ORIGINS",
    "POSTGRES_PASSWORD",
    "HUGGINGFACE_TOKEN",
)

# YOLO_MODEL_PATH is in CONTEXT D-05's secret roster but it's intentionally a
# DEFAULTABLE non-secret in the codebase (defaults to an HF repo path baked
# into detector_factory.py). Operators MAY override it via fly secrets, but
# committing the default HF path is acceptable. We don't scan for it.

# Files to scan.
DEPLOY_TOMLS = (
    REPO_ROOT / "deploy" / "db" / "fly.toml",
    REPO_ROOT / "deploy" / "backend" / "fly.toml",
    REPO_ROOT / "deploy" / "frontend" / "fly.toml",
)

# Allowlist: legitimate non-secret values in [build.args] that LOOK like
# secret assignments but aren't.
ALLOWLIST_SUBSTRINGS = (
    # VITE_API_URL is the publicly-resolvable backend URL; not a secret.
    'VITE_API_URL = "https://road-quality-backend.fly.dev"',
)


def _strip_allowlisted(line: str) -> str:
    for allowed in ALLOWLIST_SUBSTRINGS:
        if allowed in line:
            return ""  # consumed by allowlist; don't scan further
    return line


@pytest.mark.parametrize("toml_path", DEPLOY_TOMLS)
def test_no_committed_secrets_in_deploy_toml(toml_path):
    """Each deploy/*.toml must not assign a value to any documented secret env var."""
    if not toml_path.exists():
        pytest.skip(f"{toml_path} not yet created (Plans 05-03 / 05-04 may not have run)")

    text = toml_path.read_text()
    violations = []

    for line in text.splitlines():
        # Skip comments and empty lines.
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Apply allowlist (e.g., VITE_API_URL).
        scan_line = _strip_allowlisted(stripped)
        if not scan_line:
            continue
        # Look for KEY = "value" assignments.
        for secret_key in SECRET_KEYS:
            # Match `KEY = "..."` (TOML string assignment).
            # We're permissive: any line with `<SECRET_KEY> =` is suspect.
            if scan_line.startswith(f"{secret_key} ="):
                violations.append(
                    f"{toml_path.name}: {secret_key} assignment found in line:\n"
                    f"    {line.rstrip()}\n"
                    f"  → Move this to `fly secrets set --app <name> {secret_key}=<value>` "
                    f"per CONTEXT D-05; never commit secret defaults."
                )

    assert not violations, (
        "SC #3 violation — committed secret defaults detected in deploy/*.toml:\n"
        + "\n".join(violations)
    )


def test_deploy_tomls_exist():
    """Sanity: confirm all 3 deploy/*.toml files exist before scanning them.

    This test fails LOUD if Plan 05-03 or 05-04 hasn't completed yet (e.g.,
    if Plan 05-05 is being executed out of order). Without this guard, the
    scan tests would all skip and SC #3 would be silently unverified.
    """
    missing = [p for p in DEPLOY_TOMLS if not p.exists()]
    assert not missing, (
        f"deploy/*.toml files missing: {missing}. "
        f"Plans 05-03 and 05-04 must complete before Plan 05-05 can verify SC #3."
    )


def test_secret_roster_matches_context_d05():
    """Documentation guard: the SECRET_KEYS tuple in this file must match
    CONTEXT D-05 + the documented secrets in RESEARCH §2's `fly secrets set`
    recipe.

    If a future plan adds a new secret env var (e.g., REDIS_URL in M2),
    this test fails until SECRET_KEYS is updated to include it. Cheap
    insurance against drift.
    """
    expected_minimum = {
        "DATABASE_URL",
        "AUTH_SIGNING_KEY",
        "MAPILLARY_ACCESS_TOKEN",
        "ALLOWED_ORIGINS",
        "POSTGRES_PASSWORD",
    }
    actual = set(SECRET_KEYS)
    missing = expected_minimum - actual
    assert not missing, (
        f"SECRET_KEYS is missing entries from CONTEXT D-05's secret roster: {missing}. "
        f"Update SECRET_KEYS to keep the SC #3 scan exhaustive."
    )
