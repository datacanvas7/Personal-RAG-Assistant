"""In-memory stand-ins for the repositories, used by service and API unit tests.

They implement only what the service layer calls. Behavior that needs a real database
(row locking, constraints, cascades) is covered by tests/integration instead.
"""

import uuid
from datetime import UTC, datetime

from app.models import RefreshToken, User


class FakeUserStore:
    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.users.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self.users.values() if u.email == email), None)

    async def add(self, user: User) -> User:
        user.id = user.id or uuid.uuid4()
        if user.is_active is None:
            user.is_active = True  # the database default
        user.created_at = datetime.now(UTC)
        self.users[user.id] = user
        return user


class FakeTokenStore:
    def __init__(self) -> None:
        self.tokens: list[RefreshToken] = []

    async def add(self, token: RefreshToken) -> RefreshToken:
        token.id = token.id or uuid.uuid4()
        self.tokens.append(token)
        return token

    async def get_by_hash_for_update(self, token_hash: str) -> RefreshToken | None:
        return next((t for t in self.tokens if t.token_hash == token_hash), None)

    async def revoke_family(self, family_id: uuid.UUID, *, now: datetime) -> None:
        for token in self.tokens:
            if token.family_id == family_id and token.revoked_at is None:
                token.revoked_at = now


class FakeTransaction:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class Clock:
    """A controllable clock: tests move time instead of sleeping.

    It starts at the real current time because JWT validation (done by PyJWT) always
    compares against the real clock."""

    def __init__(self) -> None:
        self.current = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.current
