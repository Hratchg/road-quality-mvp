"""HS256 JWT encode/decode for road-quality-mvp auth.

Locked decisions (04-CONTEXT.md D-01, D-07):
- HS256 (symmetric, single signing key)
- Payload = {sub: str(user_id), iat, exp}
- exp = 7 days from issue
- Signing key from AUTH_SIGNING_KEY env var; fail-fast on missing/short

Anti-footgun (04-RESEARCH.md Pitfall 2): jwt.decode() takes algorithms= as a
LIST. Passing a string would silently allow alg substitution attacks (CVEs in
this category have hit auth0/jsonwebtoken, node-jsonwebtoken). Always
algorithms=[ALGORITHM].

NEVER log AUTH_SIGNING_KEY, full token bodies, or decoded payloads.
RESEARCH §3 Pitfall 1.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from jose import jwt
from jose.exceptions import (
    JWTError,
    ExpiredSignatureError,
    JWTClaimsError,
)

ALGORITHM = "HS256"
EXPIRE_DAYS = 7  # D-07


def _signing_key() -> str:
    """Read AUTH_SIGNING_KEY at call time (so tests can monkeypatch the env).

    Fails LOUD on missing key — never default to a placeholder. A weak default
    here is the #1 way HS256 deployments get pwned.
    """
    key = os.environ.get("AUTH_SIGNING_KEY", "")
    if not key:
        raise RuntimeError(
            "AUTH_SIGNING_KEY env var is not set. Generate a 32-byte key with: "
            "python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )
    if len(key) < 32:
        raise RuntimeError(
            f"AUTH_SIGNING_KEY too short ({len(key)} chars; need >= 32). "
            "Generate with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )
    return key


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenError(Exception):
    """Raised on any JWT decode failure (expired, bad sig, malformed, alg confusion)."""


def encode_token(user_id: int, expires_in: timedelta | None = None) -> str:
    now = datetime.now(timezone.utc)
    exp = now + (expires_in if expires_in is not None else timedelta(days=EXPIRE_DAYS))
    payload = {
        "sub": str(user_id),  # OWASP: sub is conventionally a string
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, _signing_key(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode + verify HS256 token. Raises TokenError on any failure.

    Note algorithms=[ALGORITHM] (LIST, single element). DO NOT pass the
    bare string ALGORITHM — that's a silent footgun that allows alg
    substitution. Pitfall 2.
    """
    try:
        return jwt.decode(token, _signing_key(), algorithms=[ALGORITHM])
    except (ExpiredSignatureError, JWTClaimsError, JWTError) as e:
        raise TokenError(str(e)) from e
