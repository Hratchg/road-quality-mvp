"""FastAPI dependency for authenticated routes (RESEARCH Pattern 1).

Endpoints that require authentication declare:
    user_id: int = Depends(get_current_user_id)

Or (preferred for grouped routes like /cache/*):
    router = APIRouter(dependencies=[Depends(get_current_user_id)])

Tests bypass real JWT verification by overriding the dependency:
    app.dependency_overrides[get_current_user_id] = lambda: 42
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.auth.tokens import decode_token, TokenError

# auto_error=True → FastAPI 0.115+ returns 401 with {"detail": "Not authenticated"}
# on missing or non-Bearer Authorization header. RESEARCH §3 Pitfall 10 verified
# this on the installed FastAPI 0.136 runtime.
_bearer = HTTPBearer(auto_error=True)


def get_current_user_id(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> int:
    """Resolve user_id from JWT. Raises 401 on any failure.

    Returns just the user_id (int). Endpoints that need full user fields
    can do their own SELECT — most don't (the JWT IS the proof).

    We deliberately do NOT distinguish "expired" from "bad signature" in the
    error detail — leaking that gives an attacker a valid-token-shape oracle.
    """
    try:
        payload = decode_token(creds.credentials)
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )
