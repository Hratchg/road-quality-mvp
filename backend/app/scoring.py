def normalize_weights(
    include_iri: bool,
    include_potholes: bool,
    weight_iri: float,
    weight_potholes: float,
) -> tuple[float, float]:
    """Normalize weights based on which parameters are enabled.

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


def compute_segment_cost(
    travel_time_s: float,
    iri_norm: float,
    pothole_score_total: float,
    w_iri: float,
    w_pot: float,
) -> float:
    """Compute cost for a single segment.

    cost = travel_time_s + w_iri * iri_norm + w_pot * pothole_score_total
    """
    return travel_time_s + w_iri * iri_norm + w_pot * pothole_score_total
