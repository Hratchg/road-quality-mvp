from fastapi import APIRouter
from app.cache import segments_cache, route_cache, clear_all_caches

router = APIRouter()


@router.get("/cache/stats")
def cache_stats():
    return {
        "segments_cache_size": segments_cache.currsize,
        "route_cache_size": route_cache.currsize,
        "segments_cache_maxsize": segments_cache.maxsize,
        "route_cache_maxsize": route_cache.maxsize,
    }


@router.post("/cache/clear")
def cache_clear():
    clear_all_caches()
    return {"cleared": True}
