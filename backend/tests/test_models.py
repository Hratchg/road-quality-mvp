import pytest
from pydantic import ValidationError
from app.models import LatLon, RouteRequest


def test_route_request_valid():
    req = RouteRequest(
        origin=LatLon(lat=34.05, lon=-118.24),
        destination=LatLon(lat=34.06, lon=-118.25),
        include_iri=True,
        include_potholes=True,
        weight_iri=60,
        weight_potholes=40,
        max_extra_minutes=5,
    )
    assert req.origin.lat == 34.05
    assert req.max_extra_minutes == 5


def test_route_request_defaults():
    req = RouteRequest(
        origin=LatLon(lat=34.05, lon=-118.24),
        destination=LatLon(lat=34.06, lon=-118.25),
    )
    assert req.include_iri is True
    assert req.include_potholes is True
    assert req.weight_iri == 50
    assert req.weight_potholes == 50
    assert req.max_extra_minutes == 5


def test_route_request_rejects_invalid_lat():
    with pytest.raises(ValidationError):
        LatLon(lat=100.0, lon=-118.24)
