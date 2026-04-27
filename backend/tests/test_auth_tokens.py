"""Unit tests for backend/app/auth/tokens.py — HS256 JWT encode/decode helpers.

Pitfall 2 regression guard: alg=none + alg-substitution attacks must fail.
RESEARCH §3 + Pattern 5.
"""

from __future__ import annotations

import base64
import json
from datetime import timedelta

import pytest

from app.auth.tokens import (
    encode_token,
    decode_token,
    Token,
    TokenError,
)


def test_encode_decode_roundtrip(monkeypatch):
    monkeypatch.setenv("AUTH_SIGNING_KEY", "x" * 48)
    tok = encode_token(user_id=42)
    payload = decode_token(tok)
    assert payload["sub"] == "42"  # str per OWASP
    assert isinstance(payload["iat"], int)
    assert isinstance(payload["exp"], int)
    assert payload["exp"] - payload["iat"] == 7 * 86400  # D-07: 7 days


def test_decode_token_with_wrong_key_raises_TokenError(monkeypatch):
    monkeypatch.setenv("AUTH_SIGNING_KEY", "a" * 48)
    tok = encode_token(user_id=1)
    monkeypatch.setenv("AUTH_SIGNING_KEY", "b" * 48)
    with pytest.raises(TokenError):
        decode_token(tok)


def test_decode_token_expired_raises_TokenError(monkeypatch):
    monkeypatch.setenv("AUTH_SIGNING_KEY", "x" * 48)
    tok = encode_token(user_id=1, expires_in=timedelta(seconds=-1))
    with pytest.raises(TokenError):
        decode_token(tok)


def test_decode_token_alg_none_rejected(monkeypatch):
    """Pitfall 2: a manually-crafted alg=none token must be rejected because
    decode_token uses algorithms=['HS256'] (LIST). If someone changes that to
    a string 'HS256', this test fails — exactly the regression we want to catch."""
    monkeypatch.setenv("AUTH_SIGNING_KEY", "x" * 48)

    def _b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    header = _b64({"alg": "none", "typ": "JWT"})
    body = _b64({"sub": "1", "iat": 0, "exp": 9_999_999_999})
    none_token = f"{header}.{body}."  # empty signature
    with pytest.raises(TokenError):
        decode_token(none_token)


def test_decode_token_malformed_raises_TokenError(monkeypatch):
    monkeypatch.setenv("AUTH_SIGNING_KEY", "x" * 48)
    with pytest.raises(TokenError):
        decode_token("not.a.jwt")


def test_signing_key_raises_when_env_unset(monkeypatch):
    monkeypatch.delenv("AUTH_SIGNING_KEY", raising=False)
    with pytest.raises(RuntimeError) as exc:
        encode_token(user_id=1)
    assert "AUTH_SIGNING_KEY" in str(exc.value)
    assert "secrets.token_urlsafe" in str(exc.value)


def test_signing_key_raises_on_short_key(monkeypatch):
    monkeypatch.setenv("AUTH_SIGNING_KEY", "tooShort")  # 8 chars < 32
    with pytest.raises(RuntimeError) as exc:
        encode_token(user_id=1)
    assert ">= 32" in str(exc.value) or "need" in str(exc.value)


def test_token_pydantic_model_default_token_type():
    t = Token(access_token="some.jwt.string")
    assert t.token_type == "bearer"
    assert t.access_token == "some.jwt.string"
