"""LAPD MO-Code → KABCO severity mapper for d5tf-ez2w (LA City crash dataset).

Source for the catalog: MO_CODES_Numerical_20180627.pdf hosted at
  https://data.lacity.org/api/views/d5tf-ez2w/files/8957b3b1-771a-4686-8f19-281d23a11f1b
[VERIFIED 09-RESEARCH.md: extracted via PDF text extraction 2026-05-08;
codes 3024-3028 are the literal KABCO scale embedded in LAPD's MO catalog.]

The mocodes field on each LA City crash row carries multiple codes (vehicle type,
PCF, location, weather, sobriety, etc.). Exactly ONE of {3024, 3025, 3026, 3027,
3028} is normally present per row; multi-victim crashes can carry BOTH a Fatal
(3027) and an Injury (3024/3025/3026) code — we resolve to the highest tier.

Live sample (verified 2026-05-08):
    mocodes="3004 3027 3034 4027 3036 3101 3401 3701"
    → only 3027 is a severity code → "fatal"
    (3004/3034/3036 vehicle, 4027 location, 3101 PCF, 3401/3701 weather)

Per D-09-13 (REVISED per 09-RESEARCH.md / 09-CONTEXT.md): the mapper IGNORES
non-KABCO codes (they are expected and benign) and raises ValueError ONLY when
ZERO severity codes appear — fail-loud on operator drift in the SEVERITY scale,
not on every non-severity LAPD code in normal data (Pitfall 2 / KEY LESSON 2).

Defensive separator: live data is space-separated, but we accept comma+whitespace
mixes too via `.replace(",", " ").split()` — future-proofs against schema drift.
"""

from __future__ import annotations

from typing import Final

# D-09-13 REVISED: explicit KABCO catalog. KEEP IT EXPLICIT — silently defaulting
# to pdo on unknown codes is the v0.3.0 Phase 7 operator-drift failure mode
# (PITFALLS Pitfall 2 / KEY LESSON 2). The 5 codes below are the literal KABCO
# scale per the LAPD MO catalog.
MOCODE_SEVERITY_MAP: Final[dict[str, str]] = {
    "3027": "fatal",   # T/C - (K) Fatal Injury
    "3024": "injury",  # T/C - (A) Severe Injury
    "3025": "injury",  # T/C - (B) Visible Injury
    "3026": "injury",  # T/C - (C) Complaint of Injury
    "3028": "pdo",     # T/C - (N) Non Injury (Property Damage Only)
}

# Severity ordering for tie-break resolution (Pitfall A: multi-victim crashes).
_SEVERITY_RANK: Final[dict[str, int]] = {"fatal": 3, "injury": 2, "pdo": 1}


def map_mocodes_to_severity(mocodes_str: str) -> str:
    """Map a (space- or comma-separated) mocode string to the highest severity tier.

    Args:
        mocodes_str: e.g. "3004 3027 3034 4027 3036 3101 3401 3701".
                     Live LA City data is SPACE-separated [VERIFIED 2026-05-08].
                     The defensive split also handles comma-separated and mixed
                     whitespace via `.replace(",", " ").split()`.

    Returns:
        One of "fatal" | "injury" | "pdo". For multi-severity rows (e.g. "3024 3027"),
        the highest tier wins (fatal > injury > pdo).

    Raises:
        ValueError: if NO known KABCO severity code (3024-3028) is present in the
            string. Per D-09-13 REVISED — non-severity LAPD codes (vehicle 3001-3023,
            PCF 3101-3104, weather 3401, location 4001-4027, etc.) are IGNORED;
            only zero-severity-codes triggers loud failure (matches Pitfall 2 /
            KEY LESSON 2 intent: catch SEVERITY scale drift, not benign codes).
    """
    # Defensive split: handle space, comma, or mixed.
    raw_codes = mocodes_str.replace(",", " ").split()
    severities_present = [
        MOCODE_SEVERITY_MAP[c] for c in raw_codes if c in MOCODE_SEVERITY_MAP
    ]
    if not severities_present:
        raise ValueError(
            f"no KABCO severity mocode (3024-3028) in: {mocodes_str!r}; "
            f"recognized codes are {set(MOCODE_SEVERITY_MAP)}"
        )
    return max(severities_present, key=_SEVERITY_RANK.__getitem__)
