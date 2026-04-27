"""FastAPI dependency for authenticated routes (RESEARCH Pattern 1).

Endpoints that require authentication declare:
    user_id: int = Depends(get_current_user_id)

Or (preferred for grouped routes like /cache/*):
    router = APIRouter(dependencies=[Depends(get_current_user_id)])

Tests bypass real JWT verification by overriding the dependency:
    app.dependency_overrides[get_current_user_id] = lambda: 42
"""
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.auth.tokens import decode_token, TokenError

# auto_error=False → we explicitly raise 401 when the header is missing.
# RESEARCH §3 Pitfall 10 claimed FastAPI 0.115+ auto-returns 401, but the
# installed runtime returned 403; tracked back to HTTPBearer's default
# behavior on missing-bearer-header. SC #3 mandates 401, so we own the raise.
_bearer = HTTPBearer(auto_error=False)


def get_current_user_id(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> int:
    """Resolve user_id from JWT. Raises 401 on any failure.

    Returns just the user_id (int). Endpoints that need full user fields
    can do their own SELECT — most don't (the JWT IS the proof).

    We deliberately do NOT distinguish "expired" from "bad signature" in the
    error detail — leaking that gives an attacker a valid-token-shape oracle.
    """
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
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
