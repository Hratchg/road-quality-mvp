import inspect

import pytest

from app.scoring import (
    FATAL_CAP,
    FATAL_CAP_K,
    FATAL_WEIGHT,
    INJURY_WEIGHT,
    PDO_WEIGHT,
    W_CRASH,
    W_IRI,
    W_POT,
    compute_segment_cost,
    normalize_weights,
)


class TestNormalizeWeights:
    def test_both_enabled_normalizes_to_sum_1(self):
        w_iri, w_pot = normalize_weights(
            include_iri=True, include_potholes=True,
            weight_iri=60, weight_potholes=40,
        )
        assert abs(w_iri - 0.6) < 1e-9
        assert abs(w_pot - 0.4) < 1e-9

    def test_both_enabled_equal_weights(self):
        w_iri, w_pot = normalize_weights(
            include_iri=True, include_potholes=True,
            weight_iri=50, weight_potholes=50,
        )
        assert abs(w_iri - 0.5) < 1e-9
        assert abs(w_pot - 0.5) < 1e-9

    def test_only_iri_enabled(self):
        w_iri, w_pot = normalize_weights(
            include_iri=True, include_potholes=False,
            weight_iri=30, weight_potholes=70,
        )
        assert w_iri == 1.0
        assert w_pot == 0.0

    def test_only_potholes_enabled(self):
        w_iri, w_pot = normalize_weights(
            include_iri=False, include_potholes=True,
            weight_iri=80, weight_potholes=20,
        )
        assert w_iri == 0.0
        assert w_pot == 1.0

    def test_neither_enabled_returns_zeros(self):
        w_iri, w_pot = normalize_weights(
            include_iri=False, include_potholes=False,
            weight_iri=50, weight_potholes=50,
        )
        assert w_iri == 0.0
        assert w_pot == 0.0

    def test_zero_weights_both_enabled(self):
        w_iri, w_pot = normalize_weights(
            include_iri=True, include_potholes=True,
            weight_iri=0, weight_potholes=0,
        )
        assert abs(w_iri - 0.5) < 1e-9
        assert abs(w_pot - 0.5) < 1e-9


class TestLockedConstants:
    """Pin the v0.4.0 locked outer weights (D-10-01).

    These constants are exact float literals — no env var overrides, no
    normalization step downstream. Plans 10-02 and 10-03 import them as
    a single source of truth.
    """

    def test_outer_weights_exact_floats(self):
        # Exact literal float comparison — D-10-01 mandates exact values.
        assert W_IRI == 0.40
        assert W_POT == 0.35
        assert W_CRASH == 0.25

    def test_outer_weights_sum_to_one(self):
        # Floating-point safety belt: 0.40 + 0.35 + 0.25 == 1.0 exactly in
        # IEEE 754, but the assertion documents the invariant for downstream.
        assert abs((W_IRI + W_POT + W_CRASH) - 1.0) < 1e-9


class TestCrashScoringMath:
    """Pin the severity weights and the fatal cap (D-10-04, D-10-05).

    Task 2 extends this class with cap-arithmetic, length-floor, and
    p95-clip helper tests that mirror the SQL primitives Plan 10-02 will use.
    """

    # --- Severity weight ratios (D-10-04) ---

    def test_severity_weight_ratios(self):
        # Pitfall 5: locked at literature-converged 8:3:1 (NOT academic 100:10:1).
        assert FATAL_WEIGHT == 8 * PDO_WEIGHT
        assert INJURY_WEIGHT == 3 * PDO_WEIGHT
        # FATAL_WEIGHT / INJURY_WEIGHT == 8/3 — pin without floats:
        assert FATAL_WEIGHT * 3 == INJURY_WEIGHT * 8

    def test_severity_constants_are_named_integers(self):
        # RESEARCH Code Example 1 + D-10-19 use int literals for severity.
        assert isinstance(FATAL_WEIGHT, int)
        assert isinstance(INJURY_WEIGHT, int)
        assert isinstance(PDO_WEIGHT, int)

    # --- Fatal cap (D-10-05) ---

    def test_fatal_cap_value(self):
        # Researcher recommendation: K=3 → cap=24 raw severity units.
        assert FATAL_CAP_K == 3
        assert FATAL_CAP == 24
        assert FATAL_CAP == FATAL_CAP_K * FATAL_WEIGHT


class TestComputeSegmentCostV4:
    """Pin the new 4-arg compute_segment_cost (D-10-02): no normalization
    step, exact arithmetic over locked outer weights.
    """

    def test_basic_arithmetic(self):
        # 100 + 0.40*0.5 + 0.35*2.0 + 0.25*0.3
        # = 100 + 0.20 + 0.70 + 0.075 = 100.975
        cost = compute_segment_cost(
            travel_time_s=100.0,
            iri_norm=0.5,
            pothole_total=2.0,
            crash_norm=0.3,
        )
        assert abs(cost - 100.975) < 1e-9

    def test_signature_is_four_args_no_kwargs(self):
        # D-10-02: drop the v0.2.0 w_iri/w_pot params. Pin exact parameter
        # names + count to guard against accidental signature drift.
        params = list(inspect.signature(compute_segment_cost).parameters)
        assert params == [
            "travel_time_s",
            "iri_norm",
            "pothole_total",
            "crash_norm",
        ]
        assert len(params) == 4

    def test_zero_inputs_equal_travel_time(self):
        # Sanity belt: zero-quality-data segments cost exactly travel time.
        cost = compute_segment_cost(
            travel_time_s=200.0,
            iri_norm=0.0,
            pothole_total=0.0,
            crash_norm=0.0,
        )
        assert abs(cost - 200.0) < 1e-9

    def test_no_normalization_step(self):
        # D-10-02: constants already sum to 1.0; no renormalization.
        # If the implementer accidentally divided by (W_IRI+W_POT+W_CRASH)
        # this case alone wouldn't catch it (1.0 stays 1.0), but combined
        # with test_basic_arithmetic above (heterogeneous values diverge
        # under double-normalization) the contract is fully pinned.
        cost = compute_segment_cost(
            travel_time_s=0.0,
            iri_norm=1.0,
            pothole_total=1.0,
            crash_norm=1.0,
        )
        assert abs(cost - 1.0) < 1e-9

    def test_iri_only_contribution(self):
        # 10 * W_IRI = 10 * 0.40 = 4.0. Confirms multiply-not-add.
        cost = compute_segment_cost(
            travel_time_s=0.0,
            iri_norm=10.0,
            pothole_total=0.0,
            crash_norm=0.0,
        )
        assert abs(cost - 4.0) < 1e-9

    def test_pothole_only_contribution(self):
        # 10 * W_POT = 10 * 0.35 = 3.5.
        cost = compute_segment_cost(
            travel_time_s=0.0,
            iri_norm=0.0,
            pothole_total=10.0,
            crash_norm=0.0,
        )
        assert abs(cost - 3.5) < 1e-9

    def test_crash_only_contribution(self):
        # 10 * W_CRASH = 10 * 0.25 = 2.5.
        cost = compute_segment_cost(
            travel_time_s=0.0,
            iri_norm=0.0,
            pothole_total=0.0,
            crash_norm=10.0,
        )
        assert abs(cost - 2.5) < 1e-9


class TestNormalizeWeightsDeprecated:
    """Pin D-10-03: normalize_weights is kept-but-deprecated for one
    milestone of confidence. Function MUST remain importable so the
    existing v0.2.0 unit tests in TestNormalizeWeights keep passing.
    """

    def test_still_importable(self):
        # Smoke import is at module top of this test file; this assertion
        # documents the contract explicitly.
        assert callable(normalize_weights)

    def test_deprecation_marker_present(self):
        # Marker may live in the docstring OR a sibling source comment;
        # either is acceptable per D-10-03.
        marker = "DEPRECATED v0.4.0"
        in_doc = marker in (normalize_weights.__doc__ or "")
        in_src = marker in inspect.getsource(normalize_weights)
        assert in_doc or in_src
