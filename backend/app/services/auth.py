"""Registration, login, token refresh/rotation, logout.

Session design
--------------
* Access token: short-lived JWT, sent as ``Authorization: Bearer`` and kept in memory by
  the frontend. Never stored, never revocable individually (it expires in minutes).
* Refresh token: opaque random value in an httpOnly cookie. Only its SHA-256 is stored.
  Every use *rotates* it: the old row is marked rotated and a successor in the same
  family is issued.
* Reuse detection: presenting a token that was already rotated means two parties hold
  it. If that happens outside a short grace window (two tabs racing), the whole family
  is revoked and the user must log in again.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.errors import AuthenticationError, ConflictError
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    dummy_password_hash,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.models import RefreshToken, User

logger = logging.getLogger(__name__)

_INVALID_CREDENTIALS = "Incorrect email or password."
_INVALID_SESSION = "Your session is no longer valid. Please sign in again."


class UserStore(Protocol):
    async def get_by_id(self, user_id: uuid.UUID) -> User | None: ...
    async def get_by_email(self, email: str) -> User | None: ...
    async def add(self, user: User) -> User: ...


class RefreshTokenStore(Protocol):
    async def add(self, token: RefreshToken) -> RefreshToken: ...
    async def get_by_hash_for_update(self, token_hash: str) -> RefreshToken | None: ...
    async def revoke_family(self, family_id: uuid.UUID, *, now: datetime) -> None: ...


class Transaction(Protocol):
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int  # access token lifetime, seconds


def normalize_email(email: str) -> str:
    return email.strip().lower()


class AuthService:
    def __init__(
        self,
        *,
        users: UserStore,
        tokens: RefreshTokenStore,
        transaction: Transaction,
        settings: Settings,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._users = users
        self._tokens = tokens
        self._tx = transaction
        self._settings = settings
        self._now = now

    # --- Registration and login ----------------------------------------------------

    async def register(self, *, email: str, password: str) -> User:
        email = normalize_email(email)
        if await self._users.get_by_email(email) is not None:
            raise ConflictError("An account with this email already exists.")

        # Argon2 is deliberately slow (tens of ms of CPU). Run it off the event loop so
        # one registration does not stall every other request.
        password_hash = await asyncio.to_thread(hash_password, password)
        try:
            user = await self._users.add(User(email=email, password_hash=password_hash))
            await self._tx.commit()
        except IntegrityError:
            # Lost a race with a concurrent registration of the same email.
            await self._tx.rollback()
            raise ConflictError("An account with this email already exists.") from None
        return user

    async def login(self, *, email: str, password: str) -> tuple[User, TokenPair]:
        user = await self._users.get_by_email(normalize_email(email))

        # Verify against a dummy hash when the account does not exist so that an
        # unknown email and a wrong password take the same time.
        stored_hash = user.password_hash if user else dummy_password_hash()
        password_ok = await asyncio.to_thread(verify_password, stored_hash, password)
        if user is None or not password_ok or not user.is_active:
            raise AuthenticationError(_INVALID_CREDENTIALS)

        if password_needs_rehash(user.password_hash):
            user.password_hash = await asyncio.to_thread(hash_password, password)

        pair = await self._issue_tokens(user.id, family_id=uuid.uuid4())
        await self._tx.commit()
        return user, pair

    # --- Refresh, logout --------------------------------------------------------------

    async def refresh(self, *, refresh_token: str) -> TokenPair:
        now = self._now()
        stored = await self._tokens.get_by_hash_for_update(hash_refresh_token(refresh_token))
        if stored is None or stored.revoked_at is not None:
            await self._tx.rollback()
            raise AuthenticationError(_INVALID_SESSION)

        if stored.rotated_at is not None:
            grace = timedelta(seconds=self._settings.refresh_reuse_grace_seconds)
            if now - stored.rotated_at > grace:
                # A rotated token came back well after rotation: someone copied it.
                # Kill every token descended from this login.
                logger.warning("Refresh token reuse detected; revoking family %s", stored.family_id)
                await self._tokens.revoke_family(stored.family_id, now=now)
                await self._tx.commit()
            else:
                await self._tx.rollback()
            raise AuthenticationError(_INVALID_SESSION)

        user = await self._users.get_by_id(stored.user_id)
        if stored.expires_at <= now or user is None or not user.is_active:
            await self._tx.rollback()
            raise AuthenticationError(_INVALID_SESSION)

        stored.rotated_at = now
        pair = await self._issue_tokens(user.id, family_id=stored.family_id)
        await self._tx.commit()
        return pair

    async def logout(self, *, refresh_token: str | None) -> None:
        """End the session this token belongs to. Idempotent: unknown tokens are ignored."""
        if refresh_token:
            stored = await self._tokens.get_by_hash_for_update(hash_refresh_token(refresh_token))
            if stored is not None:
                await self._tokens.revoke_family(stored.family_id, now=self._now())
                await self._tx.commit()
                return
        await self._tx.rollback()

    # --- Access-token authentication ----------------------------------------------------

    async def authenticate(self, *, access_token: str) -> User:
        try:
            user_id = decode_access_token(
                access_token, secret=self._settings.jwt_secret_key.get_secret_value()
            )
        except InvalidTokenError:
            raise AuthenticationError("Invalid or expired token.") from None
        user = await self._users.get_by_id(user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Invalid or expired token.")
        return user

    # --- Internals --------------------------------------------------------------------------

    async def _issue_tokens(self, user_id: uuid.UUID, *, family_id: uuid.UUID) -> TokenPair:
        now = self._now()
        lifetime = timedelta(minutes=self._settings.access_token_expire_minutes)
        raw_refresh = generate_refresh_token()
        await self._tokens.add(
            RefreshToken(
                user_id=user_id,
                family_id=family_id,
                token_hash=hash_refresh_token(raw_refresh),
                expires_at=now + timedelta(days=self._settings.refresh_token_expire_days),
            )
        )
        access = create_access_token(
            user_id,
            secret=self._settings.jwt_secret_key.get_secret_value(),
            now=now,
            expires_in=lifetime,
        )
        return TokenPair(
            access_token=access,
            refresh_token=raw_refresh,
            expires_in=int(lifetime.total_seconds()),
        )
