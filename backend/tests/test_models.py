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


def test_route_request_unknown_field_silently_dropped():
    """D-10-13: unknown extra fields should be silently dropped (no 422).
    Pinned by Pitfall 7 — 'accepted' is necessary but not sufficient;
    Plan 10-03 also pins the SEMANTIC ignore via test_route.py.
    """
    req = RouteRequest(
        origin=LatLon(lat=34.05, lon=-118.24),
        destination=LatLon(lat=34.06, lon=-118.25),
        evil_field=True,            # extra=ignore should drop this
        weight_iri=99,              # legacy field — preserved as Field default
        weight_potholes=1,          # legacy field — preserved as Field default
    )
    # The model accepts the request without raising ValidationError
    assert req.weight_iri == 99    # legacy field still readable
    assert req.weight_potholes == 1
    # The unknown field should NOT appear in model_dump()
    dump = req.model_dump()
    assert "evil_field" not in dump


def test_route_request_extra_ignored_does_not_raise_for_random_keys():
    """Random extra keys do not 422-reject the request (D-10-13)."""
    req = RouteRequest(
        origin=LatLon(lat=34.05, lon=-118.24),
        destination=LatLon(lat=34.06, lon=-118.25),
        foo="bar",
        nested={"a": 1, "b": [2, 3]},
        number=42.5,
    )
    dump = req.model_dump()
    assert "foo" not in dump
    assert "nested" not in dump
    assert "number" not in dump
