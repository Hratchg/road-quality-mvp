"""Argon2id password hashing helpers (D-03).

pwdlib's PasswordHash.recommended() ships with m=65536 (64 MiB), t=3, p=4,
~3x the OWASP minimum (m=19456, t=2, p=1). See OWASP Password Storage Cheat
Sheet for parameter rationale: https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html

The PasswordHash instance is module-level (instantiated once at import). Its
hashers carry no per-call state — safe to share across requests/threads.

NEVER log password, encoded_hash, or any value passed to these functions.
RESEARCH §3 Pitfall 1.
"""
from pwdlib import PasswordHash

_ph = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Hash a plaintext password (~150-300ms on a modern laptop).

    The returned string encodes the algorithm + parameters + salt + hash
    (e.g., '$argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>'), so verification
    needs only this string, not the parameters separately.
    """
    return _ph.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    """Return True if password matches encoded_hash; False otherwise.

    Does NOT raise on mismatch — argon2-cffi raises VerifyMismatchError but
    pwdlib swallows that into a bool. Other failures (corrupt hash, bad
    encoding) also return False — we don't distinguish.
    """
    try:
        return _ph.verify(password, encoded_hash)
    except Exception:
        # pwdlib's verify swallows VerifyMismatchError into bool, but a
        # genuinely corrupt hash (bad base64, wrong segments, unknown algo)
        # raises InvalidHashError. Callers should NOT have to wrap — we
        # treat any failure as "not a valid password match".
        return False


def verify_and_maybe_rehash(
    password: str, encoded_hash: str
) -> tuple[bool, str | None]:
    """Verify + return new hash if pwdlib's recommended() params have changed.

    Returns (valid, new_hash_or_None). If new_hash is not None, the caller
    should UPDATE users SET password_hash = new_hash WHERE id = ... — this
    transparently upgrades hashes when pwdlib's defaults are bumped.

    Use this on /auth/login (plan 04-03). Don't bother on /auth/register
    (the hash is fresh from the current params).
    """
    return _ph.verify_and_update(password, encoded_hash)
