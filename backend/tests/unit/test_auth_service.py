from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.core.errors import AuthenticationError, ConflictError
from app.core.security import create_access_token, hash_refresh_token
from app.models import User
from app.services.auth import AuthService
from tests.fakes import Clock, FakeTokenStore, FakeTransaction, FakeUserStore

PASSWORD = "a-reasonable-passphrase"


class Harness:
    def __init__(self) -> None:
        self.users = FakeUserStore()
        self.tokens = FakeTokenStore()
        self.tx = FakeTransaction()
        self.clock = Clock()
        self.settings = Settings()  # reads the test environment from tests/conftest.py
        self.service = AuthService(
            users=self.users,
            tokens=self.tokens,
            transaction=self.tx,
            settings=self.settings,
            now=self.clock,
        )


@pytest.fixture
def h() -> Harness:
    return Harness()


async def _registered(h: Harness, email: str = "ada@example.com") -> User:
    return await h.service.register(email=email, password=PASSWORD)


# --- registration ------------------------------------------------------------------


async def test_register_stores_a_hash_never_the_password(h: Harness) -> None:
    user = await _registered(h)

    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash
    assert h.tx.commits == 1


async def test_register_normalizes_the_email(h: Harness) -> None:
    user = await _registered(h, "  Ada@Example.COM ")

    assert user.email == "ada@example.com"


async def test_register_rejects_a_duplicate_email_in_any_case(h: Harness) -> None:
    await _registered(h, "ada@example.com")

    with pytest.raises(ConflictError):
        await _registered(h, "ADA@example.com")


# --- login ---------------------------------------------------------------------------


async def test_login_issues_tokens_and_stores_only_the_refresh_hash(h: Harness) -> None:
    user = await _registered(h)

    logged_in, pair = await h.service.login(email="ada@example.com", password=PASSWORD)

    assert logged_in.id == user.id
    assert pair.expires_in == h.settings.access_token_expire_minutes * 60
    (stored,) = h.tokens.tokens
    assert stored.token_hash == hash_refresh_token(pair.refresh_token)
    assert pair.refresh_token not in stored.token_hash
    assert stored.expires_at == h.clock.current + timedelta(
        days=h.settings.refresh_token_expire_days
    )


async def test_login_accepts_the_email_in_a_different_case(h: Harness) -> None:
    await _registered(h)

    await h.service.login(email="ADA@Example.com", password=PASSWORD)


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("ada@example.com", "the-wrong-password"),
        ("nobody@example.com", PASSWORD),
    ],
    ids=["wrong-password", "unknown-email"],
)
async def test_login_failures_are_indistinguishable(h: Harness, email: str, password: str) -> None:
    await _registered(h)

    with pytest.raises(AuthenticationError) as caught:
        await h.service.login(email=email, password=password)

    assert caught.value.message == "Incorrect email or password."
    assert h.tokens.tokens == []


async def test_inactive_user_cannot_log_in(h: Harness) -> None:
    user = await _registered(h)
    user.is_active = False

    with pytest.raises(AuthenticationError):
        await h.service.login(email="ada@example.com", password=PASSWORD)


# --- refresh rotation ------------------------------------------------------------------


async def _login(h: Harness) -> str:
    await _registered(h)
    _, pair = await h.service.login(email="ada@example.com", password=PASSWORD)
    return pair.refresh_token


async def test_refresh_rotates_the_token_within_the_same_family(h: Harness) -> None:
    first = await _login(h)

    pair = await h.service.refresh(refresh_token=first)

    assert pair.refresh_token != first
    old, new = h.tokens.tokens
    assert old.rotated_at == h.clock.current
    assert new.rotated_at is None
    assert new.family_id == old.family_id


async def test_rotated_token_replayed_after_the_grace_window_revokes_the_family(
    h: Harness,
) -> None:
    first = await _login(h)
    second = (await h.service.refresh(refresh_token=first)).refresh_token
    h.clock.current += timedelta(seconds=h.settings.refresh_reuse_grace_seconds + 1)

    with pytest.raises(AuthenticationError):
        await h.service.refresh(refresh_token=first)  # the thief replays the old token

    assert all(t.revoked_at is not None for t in h.tokens.tokens)
    with pytest.raises(AuthenticationError):  # the legitimate holder is logged out too
        await h.service.refresh(refresh_token=second)


async def test_replay_inside_the_grace_window_is_rejected_without_revoking(h: Harness) -> None:
    """Two tabs refreshing at once must not log the user out."""
    first = await _login(h)
    second = (await h.service.refresh(refresh_token=first)).refresh_token
    h.clock.current += timedelta(seconds=1)

    with pytest.raises(AuthenticationError):
        await h.service.refresh(refresh_token=first)

    assert all(t.revoked_at is None for t in h.tokens.tokens)
    await h.service.refresh(refresh_token=second)  # the winner's token still works


async def test_unknown_refresh_token_is_rejected(h: Harness) -> None:
    with pytest.raises(AuthenticationError):
        await h.service.refresh(refresh_token="never-issued")


async def test_expired_refresh_token_is_rejected(h: Harness) -> None:
    first = await _login(h)
    h.clock.current += timedelta(days=h.settings.refresh_token_expire_days, seconds=1)

    with pytest.raises(AuthenticationError):
        await h.service.refresh(refresh_token=first)


async def test_refresh_fails_for_a_deactivated_user(h: Harness) -> None:
    first = await _login(h)
    next(iter(h.users.users.values())).is_active = False

    with pytest.raises(AuthenticationError):
        await h.service.refresh(refresh_token=first)


# --- logout --------------------------------------------------------------------------------


async def test_logout_revokes_the_whole_family(h: Harness) -> None:
    first = await _login(h)
    second = (await h.service.refresh(refresh_token=first)).refresh_token

    await h.service.logout(refresh_token=second)

    assert all(t.revoked_at is not None for t in h.tokens.tokens)
    with pytest.raises(AuthenticationError):
        await h.service.refresh(refresh_token=second)


@pytest.mark.parametrize("token", [None, "", "never-issued"])
async def test_logout_is_idempotent(h: Harness, token: str | None) -> None:
    await h.service.logout(refresh_token=token)


# --- access-token authentication ------------------------------------------------------------


async def test_authenticate_returns_the_token_owner(h: Harness) -> None:
    user = await _registered(h)
    _, pair = await h.service.login(email="ada@example.com", password=PASSWORD)

    assert await h.service.authenticate(access_token=pair.access_token) is user


async def test_authenticate_rejects_a_token_for_a_deleted_or_inactive_user(h: Harness) -> None:
    user = await _registered(h)
    _, pair = await h.service.login(email="ada@example.com", password=PASSWORD)
    user.is_active = False

    with pytest.raises(AuthenticationError):
        await h.service.authenticate(access_token=pair.access_token)


async def test_authenticate_rejects_an_expired_token(h: Harness) -> None:
    user = await _registered(h)
    long_ago = datetime.now(UTC) - timedelta(hours=1)
    expired = create_access_token(
        user.id,
        secret=h.settings.jwt_secret_key.get_secret_value(),
        now=long_ago,
        expires_in=timedelta(minutes=15),
    )

    with pytest.raises(AuthenticationError):
        await h.service.authenticate(access_token=expired)
