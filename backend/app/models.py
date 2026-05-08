from pydantic import BaseModel, ConfigDict, Field


class LatLon(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class RouteRequest(BaseModel):
    # D-10-13: silent ignore of legacy weight_iri/weight_potholes + any
    # other extra fields. Field defaults below are PRESERVED for v0.2.0
    # test compat (RouteRequest().weight_iri == 50) but UNUSED at runtime
    # since the locked outer weights apply unconditionally.
    model_config = ConfigDict(extra='ignore')

    origin: LatLon
    destination: LatLon
    include_iri: bool = True
    include_potholes: bool = True
    weight_iri: float = Field(default=50, ge=0, le=100)        # PRESERVED for v0.2.0 test compat (D-10-13); unused at runtime
    weight_potholes: float = Field(default=50, ge=0, le=100)   # PRESERVED for v0.2.0 test compat (D-10-13); unused at runtime
    max_extra_minutes: float = Field(default=5, ge=0)


class SegmentMetric(BaseModel):
    id: int
    iri_norm: float | None
    pothole_score: float | None


class RouteInfo(BaseModel):
    geojson: dict
    total_time_s: float
    total_cost: float
    avg_iri_norm: float | None = None
    total_moderate_score: float | None = None
    total_severe_score: float | None = None


class RouteResponse(BaseModel):
    fastest_route: RouteInfo
    best_route: RouteInfo
    warning: str | None = None
    per_segment_metrics: list[SegmentMetric]
