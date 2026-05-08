"""Scoring constants and per-segment cost formula.

v0.4.0 (Phase 10) introduces locked outer weights replacing the user-tunable
sliders shipped in v0.2.0. The previous ``normalize_weights()`` function is
kept-but-unused for one milestone of confidence (D-10-03); both downstream
plans (10-02 ``compute_scores.py`` and 10-03 ``routing.py``) import the
constants below as the single source of truth.

Decision references:
- D-10-01: locked outer weights ``W_IRI/W_POT/W_CRASH`` (40/35/25, exact floats).
- D-10-02: ``compute_segment_cost`` 4-arg signature, no normalization step.
- D-10-03: ``normalize_weights`` deprecated-but-importable for one milestone.
- D-10-04: severity weights ``FATAL/INJURY/PDO`` = 8:3:1 (NOT academic 100:10:1; Pitfall 5).
- D-10-05: single-fatal cap = ``FATAL_CAP_K * FATAL_WEIGHT`` (K=3 → 24).
"""

# ---------------------------------------------------------------------------
# Locked outer weights (D-10-01)
# Sum to 1.0 by construction in IEEE 754; ``compute_segment_cost`` performs
# NO normalization step downstream (D-10-02). No env var overrides — these
# are exact float literals so behavior is identical between offline
# ``compute_scores.py`` and online ``routing.py``.
# ---------------------------------------------------------------------------
W_IRI: float = 0.40       # D-10-01
W_POT: float = 0.35       # D-10-01
W_CRASH: float = 0.25     # D-10-01

# ---------------------------------------------------------------------------
# Severity weights (D-10-04)
# Literature-converged routing-cost ratio. Explicitly NOT the academic
# EPDO 100:10:1 — that ratio saturates ``crash_norm`` at the bimodal
# 0/1 extremes (Pitfall 5 in PROJECT.md). 8:3:1 produces the long-tailed
# distribution that Pitfall 5's ≥50% in [0.05, 0.5] check verifies.
# ---------------------------------------------------------------------------
FATAL_WEIGHT: int = 8     # D-10-04 (Pitfall 5)
INJURY_WEIGHT: int = 3    # D-10-04 (Pitfall 5)
PDO_WEIGHT: int = 1       # D-10-04 (Pitfall 5)

# ---------------------------------------------------------------------------
# Single-fatal cap (D-10-05)
# Cap per-segment raw severity sum so one freak fatal cannot dominate a long
# arterial. K=3 means up to 3 equivalent-fatal units contribute fully;
# beyond that the segment plateaus. Researcher recommendation per
# RESEARCH.md §Alternatives Considered "whole-sum cap with K=3"; pinned in
# unit tests. Recalibration is a one-line constant change + re-run of
# ``compute_scores.py --source crash``.
# ---------------------------------------------------------------------------
FATAL_CAP_K: int = 3                          # D-10-05
FATAL_CAP: int = FATAL_CAP_K * FATAL_WEIGHT   # = 24


def compute_segment_cost(
    travel_time_s: float,
    iri_norm: float,
    pothole_total: float,
    crash_norm: float,
) -> float:
    """Compute the routing cost for a single segment (D-10-02).

    cost = travel_time_s + W_IRI*iri_norm + W_POT*pothole_total + W_CRASH*crash_norm

    No normalization step: ``W_IRI + W_POT + W_CRASH = 1.0`` by construction.
    All four arguments are positional; v0.2.0's ``w_iri`` / ``w_pot`` slider
    parameters were dropped in v0.4.0.
    """
    return (
        travel_time_s
        + W_IRI * iri_norm
        + W_POT * pothole_total
        + W_CRASH * crash_norm
    )


# DEPRECATED v0.4.0 — remove after one milestone of confidence (D-10-03)
def normalize_weights(
    include_iri: bool,
    include_potholes: bool,
    weight_iri: float,
    weight_potholes: float,
) -> tuple[float, float]:
    """[DEPRECATED v0.4.0] Use module constants W_IRI / W_POT / W_CRASH instead.

    Kept-but-unused for one milestone of confidence (D-10-03). Removal
    deferred — the existing v0.2.0 unit tests in ``TestNormalizeWeights``
    continue to import and exercise this function so we can detect any
    callers that still depend on the legacy slider behavior.

    Returns (w_iri, w_pot) that sum to 1.0 (or both 0.0 if neither enabled).
    """
    if not include_iri and not include_potholes:
        return 0.0, 0.0
    if include_iri and not include_potholes:
        return 1.0, 0.0
    if not include_iri and include_potholes:
        return 0.0, 1.0

    total = weight_iri + weight_potholes
    if total == 0:
        return 0.5, 0.5
    return weight_iri / total, weight_potholes / total
