import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)

SECRET = "unit-test-secret-unit-test-secret-0123"
NOW = datetime.now(UTC)


def _token(**overrides: object) -> str:
    payload = {
        "sub": str(uuid.uuid4()),
        "type": "access",
        "iat": NOW,
        "exp": NOW + timedelta(minutes=5),
    } | overrides
    return jwt.encode(payload, SECRET, algorithm="HS256")


def test_password_roundtrip_uses_argon2id_and_a_unique_salt() -> None:
    first = hash_password("correct horse battery")
    second = hash_password("correct horse battery")

    assert first.startswith("$argon2id$")
    assert first != second  # random salt
    assert verify_password(first, "correct horse battery")
    assert not verify_password(first, "wrong password!!")


def test_verify_password_treats_a_corrupt_hash_as_a_failed_login() -> None:
    assert verify_password("not-a-hash", "whatever") is False


def test_fresh_hash_does_not_need_rehash() -> None:
    assert password_needs_rehash(hash_password("some password")) is False


def test_access_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id, secret=SECRET, now=NOW, expires_in=timedelta(minutes=5))

    assert decode_access_token(token, secret=SECRET) == user_id


def test_expired_token_is_rejected() -> None:
    token = _token(exp=NOW - timedelta(seconds=1), iat=NOW - timedelta(minutes=5))

    with pytest.raises(InvalidTokenError):
        decode_access_token(token, secret=SECRET)


def test_token_signed_with_another_key_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "iat": NOW, "exp": NOW + timedelta(hours=1)},
        "a-completely-different-secret-key-000000",
        algorithm="HS256",
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(forged, secret=SECRET)


def test_unsigned_token_is_rejected() -> None:
    """The classic "alg": "none" attack."""
    unsigned = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "iat": NOW, "exp": NOW + timedelta(hours=1)},
        None,
        algorithm="none",
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(unsigned, secret=SECRET)


def test_token_of_the_wrong_type_is_rejected() -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token(_token(type="refresh"), secret=SECRET)


def test_token_without_expiry_is_rejected() -> None:
    payload = {"sub": str(uuid.uuid4()), "type": "access", "iat": NOW}
    token = jwt.encode(payload, SECRET, algorithm="HS256")

    with pytest.raises(InvalidTokenError):
        decode_access_token(token, secret=SECRET)


def test_token_with_a_non_uuid_subject_is_rejected() -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token(_token(sub="not-a-uuid"), secret=SECRET)


def test_garbage_is_rejected() -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token("not.a.jwt", secret=SECRET)


def test_refresh_tokens_are_unique_and_only_their_hash_is_derivable() -> None:
    first, second = generate_refresh_token(), generate_refresh_token()

    assert first != second
    assert len(first) >= 64
    digest = hash_refresh_token(first)
    assert len(digest) == 64
    assert first not in digest
    assert digest == hash_refresh_token(first)
