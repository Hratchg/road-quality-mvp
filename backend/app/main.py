import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import health, segments, routing, auth
from app.routes.cache_routes import router as cache_router

app = FastAPI(title="Road Quality Tracker", version="0.1.0")

# SC #2: CORS restricted to deployed frontend origin. Comma-separated allows
# adding a custom domain later without a code change. Default fallthrough to
# localhost dev origin so `docker compose up` keeps working without explicit
# ALLOWED_ORIGINS plumbing (PATTERNS P-2: mirror DATABASE_URL's safe default,
# NOT AUTH_SIGNING_KEY's fail-fast - fail-fast on CORS would break dev).
_allowed_origins_raw = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000")
ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,  # Forward-safe for Phase 6+ cookie sessions; CORS
                             # spec forbids credentials with origins=["*"], not
                             # with explicit origins (RESEARCH Pattern 3).
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(segments.router)
app.include_router(routing.router)
app.include_router(cache_router)
app.include_router(auth.router)
