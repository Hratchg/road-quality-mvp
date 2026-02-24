import pytest
from app.scoring import normalize_weights, compute_segment_cost


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


class TestComputeSegmentCost:
    def test_basic_cost(self):
        cost = compute_segment_cost(
            travel_time_s=100.0,
            iri_norm=0.5,
            pothole_score_total=2.0,
            w_iri=0.6,
            w_pot=0.4,
        )
        # 100 + 0.6*0.5 + 0.4*2.0 = 100 + 0.3 + 0.8 = 101.1
        assert abs(cost - 101.1) < 1e-9

    def test_zero_weights_equals_travel_time(self):
        cost = compute_segment_cost(
            travel_time_s=200.0,
            iri_norm=0.9,
            pothole_score_total=5.0,
            w_iri=0.0,
            w_pot=0.0,
        )
        assert abs(cost - 200.0) < 1e-9

    def test_only_iri(self):
        cost = compute_segment_cost(
            travel_time_s=50.0,
            iri_norm=0.8,
            pothole_score_total=3.0,
            w_iri=1.0,
            w_pot=0.0,
        )
        # 50 + 1.0*0.8 + 0.0*3.0 = 50.8
        assert abs(cost - 50.8) < 1e-9
