"""Auth endpoints: /auth/register, /auth/login, /auth/logout (D-06).

Pitfalls actively defended:
- Pitfall 1: never log req.password, password_hash, or full request body.
- Pitfall 3: emails are normalized via .strip().lower() before insert + lookup.
- Pitfall 5: missing-user login path runs argon2 against _DUMMY_HASH so the
  wall-clock time matches the wrong-password path (no enumeration oracle).
"""
import logging
from contextlib import closing

from fastapi import APIRouter, HTTPException, status, Response
from pydantic import BaseModel, EmailStr, Field
from psycopg2 import IntegrityError

from app.db import get_connection
from app.auth.passwords import hash_password, verify_password, verify_and_maybe_rehash
from app.auth.tokens import encode_token, Token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    # No min_length on login (existing users may have shorter pw if min ever
    # changes); cap max_length to bound argon2 work.
    password: str = Field(min_length=1, max_length=128)


class RegisterResponse(BaseModel):
    user_id: int
    email: EmailStr
    access_token: str
    token_type: str = "bearer"


def _normalize_email(raw: str) -> str:
    """Lowercase + strip — Pitfall 3. Pydantic EmailStr lowercases the domain
    but PRESERVES local-part case; we MUST normalize at the app layer so the
    DB UNIQUE index is correctness-preserving."""
    return raw.strip().lower()


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(req: RegisterRequest):
    email = _normalize_email(req.email)
    pwd_hash = hash_password(req.password)  # ~150-300ms argon2id (sync; FastAPI runs in threadpool)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (email, password_hash) "
                    "VALUES (%s, %s) RETURNING id",
                    (email, pwd_hash),
                )
                row = cur.fetchone()
                user_id = row["id"] if isinstance(row, dict) else row[0]
                conn.commit()
    except IntegrityError:
        # 23505 unique_violation on users_email_key. We catch the broader
        # IntegrityError (parent of UniqueViolation) for forward-compat.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    token = encode_token(user_id=user_id)
    # NEVER log req.password, pwd_hash, or token. Only user_id.
    logger.info("user registered: id=%d", user_id)
    return RegisterResponse(
        user_id=user_id, email=email, access_token=token,
    )


@router.post("/login", response_model=Token)
def login(req: LoginRequest):
    email = _normalize_email(req.email)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, password_hash FROM users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()
    if row is None:
        # Pitfall 5: burn ~150ms on argon2 to match the verify path's timing.
        verify_password(req.password, _DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    stored_hash = row["password_hash"] if isinstance(row, dict) else row[1]
    user_id = row["id"] if isinstance(row, dict) else row[0]
    valid, new_hash = verify_and_maybe_rehash(req.password, stored_hash)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    # Pitfall 4: pwdlib's recommended() params may bump over time. When they
    # do, verify_and_update returns a fresh hash so we can transparently
    # upgrade the stored hash on the user's next successful login.
    if new_hash is not None:
        with closing(get_connection()) as conn, conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET password_hash = %s WHERE id = %s",
                    (new_hash, user_id),
                )
    token = encode_token(user_id=user_id)
    return Token(access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout():
    """Stateless JWT: no server state to clear. Endpoint exists so the
    frontend has a single 'logout' call site for symmetry with /register and
    /login (D-06). Client must clear localStorage."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Module-level constant (Pitfall 5). Computed once at import — ~150ms cost
# spent during app startup, not on the request hot path.
_DUMMY_HASH = hash_password("__dummy_for_timing_safety_do_not_match__")
