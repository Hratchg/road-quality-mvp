"""Unit tests for backend/app/auth/passwords.py — argon2id hash/verify helpers.

No DB, no HTTP, no FastAPI app import. Pure-function tests with ~6 argon2id
hash calls (~1-2s total). Phase 4 SC #4 regression guard: passwords are
hashed, never stored as plaintext.
"""

from __future__ import annotations

from app.auth.passwords import (
    hash_password,
    verify_password,
    verify_and_maybe_rehash,
)


def test_hash_password_returns_argon2id_encoded_string():
    encoded = hash_password("hunter2")
    assert isinstance(encoded, str)
    assert encoded.startswith("$argon2id$"), (
        f"argon2id encoded form must start with $argon2id$; got prefix "
        f"{encoded[:20]!r}"
    )
    assert len(encoded) >= 60, (
        f"argon2id encoded form should be ~97 chars; got {len(encoded)}"
    )
    assert encoded != "hunter2"


def test_verify_password_roundtrip_succeeds():
    plaintext = "correct horse battery staple"
    encoded = hash_password(plaintext)
    assert verify_password(plaintext, encoded) is True


def test_verify_password_rejects_wrong_password():
    encoded = hash_password("hunter2")
    assert verify_password("hunter3", encoded) is False


def test_verify_password_rejects_corrupt_hash():
    """pwdlib swallows VerifyMismatchError + corrupt-hash errors into bool False
    (RESEARCH Pattern 4). Callers should NOT have to wrap in try/except."""
    assert verify_password("anything", "$argon2id$broken-not-real") is False


def test_hash_password_produces_different_hashes_for_same_input():
    """argon2id uses a per-call random salt. Same input → different output.
    Salt correctness regression guard."""
    a = hash_password("x")
    b = hash_password("x")
    assert a != b, (
        "argon2id must produce different encoded hashes for the same input "
        "due to per-call random salt"
    )


def test_verify_and_maybe_rehash_returns_tuple_with_no_rehash_for_fresh_hash():
    """A hash freshly produced with PasswordHash.recommended() needs no rehash.
    The (True, None) shape is the contract — None means 'don't write back'."""
    encoded = hash_password("hunter2")
    result = verify_and_maybe_rehash("hunter2", encoded)
    assert isinstance(result, tuple) and len(result) == 2
    valid, new_hash = result
    assert valid is True
    assert new_hash is None, (
        f"fresh hash should not need rehash; verify_and_maybe_rehash returned "
        f"new_hash={new_hash!r}"
    )


def test_no_plaintext_in_encoded_hash():
    """Paranoia guard: argon2id encodes the hash, salt, and params — but never
    the plaintext. SC #4 'never stored as plaintext'."""
    plaintext = "uniquePlainText12345"
    encoded = hash_password(plaintext)
    assert plaintext not in encoded, (
        "encoded hash must not contain the plaintext password"
    )
