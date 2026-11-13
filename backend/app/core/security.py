"""Password hashing, access tokens (JWT) and refresh-token helpers.

Pure functions with no database or HTTP knowledge, so they are easy to test and
cannot accidentally depend on request state.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from functools import cache
from typing import Final

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# The only accepted algorithm. Never read it from the token header or from settings.
_JWT_ALGORITHM: Final = "HS256"
_ACCESS_TOKEN_TYPE: Final = "access"  # noqa: S105 - a claim value, not a credential

# argon2-cffi's defaults are the RFC 9106 "low memory" profile of Argon2id.
_hasher = PasswordHasher()


class InvalidTokenError(Exception):
    """The access token is malformed, expired, forged, or not an access token."""


# --- Passwords ------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Hash with Argon2id. The salt and parameters are embedded in the returned string."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        # VerifyMismatchError is a VerificationError. A corrupt stored hash is treated
        # as a failed login rather than a server error.
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True when the stored hash uses weaker parameters than the current policy."""
    return _hasher.check_needs_rehash(password_hash)


@cache
def dummy_password_hash() -> str:
    """A valid hash of a random value, used to spend the same time as a real check.

    Logging in with an unknown email verifies against this so that response time does
    not reveal whether the account exists.
    """
    return _hasher.hash(secrets.token_urlsafe(16))


# --- Access tokens --------------------------------------------------------------------


def create_access_token(
    user_id: uuid.UUID, *, secret: str, now: datetime, expires_in: timedelta
) -> str:
    payload = {
        "sub": str(user_id),
        "type": _ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + expires_in,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, secret, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str, *, secret: str) -> uuid.UUID:
    """Validate signature, expiry and token type; return the user id.

    Raises ``InvalidTokenError`` for every failure, without saying which, so callers
    cannot leak the reason to a client.
    """
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[_JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub"]},
        )
        if claims.get("type") != _ACCESS_TOKEN_TYPE:
            raise InvalidTokenError
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise InvalidTokenError from exc


# --- Refresh tokens -------------------------------------------------------------------


def generate_refresh_token() -> str:
    """An opaque 384-bit random value. It carries no data and cannot be decoded."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """SHA-256 is enough here: the input already has 384 bits of entropy, so there is
    nothing to brute-force and no need for a slow hash. Only this digest is stored, so
    a database leak does not yield usable tokens."""
    return hashlib.sha256(token.encode()).hexdigest()
