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


# ---------------------------------------------------------------------------
# Quality penalty scaling (pothole-detour fix)
#
# The v0.4.0 formula added the weighted quality terms to travel_time_s as
# raw numbers: ``t + 0.40*iri + 0.35*pot + 0.25*crash``. Segment travel
# times are tens of seconds while the quality terms are ~0..1, so a road
# full of potholes cost about one extra second. The "best" route therefore
# never differed from the fastest one.
#
# The cost is now *proportional to travel time*: each second spent on a bad
# road counts as (1 + QUALITY_PENALTY_SCALE * penalty) seconds, where
# ``penalty`` is the weighted 0..1 badness of the segment. A long rough
# segment hurts more than a short one, and the locked outer weights still
# set the relative importance of roughness, potholes and crashes.
#
# QUALITY_PENALTY_SCALE = 5 -> the worst possible segment costs 6x its
# travel time; a segment with a saturated pothole score alone costs
# 1 + 5*0.35 = 2.75x. Tuned on a grid with the live demo's score
# distribution (30% of segments potholed, IRI spread 0.1-0.85): best routes
# cross ~40% fewer potholed segments for ~20 s of extra driving, and differ
# from the fastest route on most trips. Scales above 5 add time without
# avoiding many more potholes. The user's time budget still caps detours.
#
# POTHOLE_SATURATION: pothole_score_total is unbounded (sum of
# count*confidence over detections). Clamp it to 0..1 by dividing by this
# value so one heavily-photographed segment cannot dominate.
# ---------------------------------------------------------------------------
QUALITY_PENALTY_SCALE: float = 5.0
POTHOLE_SATURATION: float = 2.0


def _clamp01(x: float) -> float:
    return 0.0 if x <= 0.0 else 1.0 if x >= 1.0 else x


def segment_quality_penalty(
    iri_norm: float,
    pothole_total: float,
    crash_norm: float,
) -> float:
    """Weighted 0..1 badness of a segment (0 = perfect, 1 = worst)."""
    return (
        W_IRI * _clamp01(iri_norm or 0.0)
        + W_POT * _clamp01((pothole_total or 0.0) / POTHOLE_SATURATION)
        + W_CRASH * _clamp01(crash_norm or 0.0)
    )


def compute_segment_cost(
    travel_time_s: float,
    iri_norm: float,
    pothole_total: float,
    crash_norm: float,
) -> float:
    """Compute the routing cost for a single segment.

    cost = travel_time_s * (1 + QUALITY_PENALTY_SCALE * penalty)
    penalty = W_IRI*iri_norm + W_POT*min(pothole_total/POTHOLE_SATURATION, 1)
              + W_CRASH*crash_norm        (each term clamped to 0..1)

    Must stay in lockstep with ``quality_cost_sql`` below, which computes the
    same value inside pgRouting so the quality-aware Dijkstra optimizes
    exactly what the API reports as ``total_cost``.
    """
    return travel_time_s * (
        1.0
        + QUALITY_PENALTY_SCALE
        * segment_quality_penalty(iri_norm, pothole_total, crash_norm)
    )


def quality_penalty_sql(
    iri: str = "iri_norm",
    pothole: str = "pothole_score_total",
    crash: str = "crash_norm",
) -> str:
    """SQL expression equivalent to ``segment_quality_penalty`` (0..1).

    Arguments are trusted column names (never user input).
    """
    def clamp(expr: str) -> str:
        return f"LEAST(GREATEST(COALESCE({expr}, 0), 0), 1)"

    return (
        f"({float(W_IRI)} * {clamp(iri)}"
        f" + {float(W_POT)} * {clamp(f'{pothole} / {float(POTHOLE_SATURATION)}')}"
        f" + {float(W_CRASH)} * {clamp(crash)})"
    )


def quality_cost_sql(
    travel_time: str = "travel_time_s",
    iri: str = "iri_norm",
    pothole: str = "pothole_score_total",
    crash: str = "crash_norm",
    scale: float = QUALITY_PENALTY_SCALE,
) -> str:
    """SQL expression equivalent to ``compute_segment_cost`` (at the default
    scale). Arguments are trusted column names (never user input).
    """
    return (
        f"({travel_time} * (1 + {float(scale)} * "
        f"{quality_penalty_sql(iri, pothole, crash)}))"
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
