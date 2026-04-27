from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import health, segments, routing, auth
from app.routes.cache_routes import router as cache_router

app = FastAPI(title="Road Quality Tracker", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(segments.router)
app.include_router(routing.router)
app.include_router(cache_router)
app.include_router(auth.router)
