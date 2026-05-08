"""In-memory TTL cache for expensive database queries.

Two separate caches:
- segments_cache: for GET /segments bbox queries (TTL 5 min)
- route_cache: for POST /route computations (TTL 2 min)
"""

import hashlib
import json

from cachetools import TTLCache

segments_cache: TTLCache = TTLCache(maxsize=256, ttl=300)
route_cache: TTLCache = TTLCache(maxsize=128, ttl=120)


def get_segments_cached(bbox_key: str) -> dict | None:
    """Return cached segment response for a bbox key, or None on miss."""
    return segments_cache.get(bbox_key)


def set_segments_cached(bbox_key: str, data: dict) -> None:
    """Store a segment response in the cache."""
    segments_cache[bbox_key] = data


def get_route_cached(request_hash: str) -> dict | None:
    """Return cached route response for a request hash, or None on miss."""
    return route_cache.get(request_hash)


def set_route_cached(request_hash: str, data: dict) -> None:
    """Store a route response in the cache."""
    route_cache[request_hash] = data


def clear_all_caches() -> None:
    """Evict all entries from both caches."""
    segments_cache.clear()
    route_cache.clear()


def make_route_cache_key(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    max_extra_minutes: float,
) -> str:
    """Build a deterministic hash key from the route request parameters
    that AFFECT THE COMPUTED RESPONSE.

    Phase 10 (D-10-14, Pitfall 2): include_iri, include_potholes,
    weight_iri, weight_potholes were dropped from this signature because
    the locked outer weights (W_IRI=0.40, W_POT=0.35, W_CRASH=0.25)
    apply unconditionally — those fields no longer affect total_cost,
    so they should not fragment the cache.
    """
    raw = json.dumps(
        {
            "origin_lat": origin_lat,
            "origin_lon": origin_lon,
            "dest_lat": dest_lat,
            "dest_lon": dest_lon,
            "max_extra_minutes": max_extra_minutes,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode()).hexdigest()
