"""The auth API against a real database: real transactions, locks and constraints."""

import asyncio
import re
from collections.abc import AsyncIterator

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app

PASSWORD = "a-reasonable-passphrase"
CREDENTIALS = {"email": "ada@example.com", "password": PASSWORD}


@pytest.fixture
async def app(migrated_engine: Engine) -> AsyncIterator[FastAPI]:
    # A dedicated engine per test: pooled connections are bound to the event loop that
    # opened them, and every test runs in its own loop.
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    application = create_app()
    application.dependency_overrides[get_session] = session_override
    yield application
    await engine.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _login(client: httpx2.AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=CREDENTIALS)
    response = await client.post("/api/v1/auth/login", json=CREDENTIALS)
    assert response.status_code == 200, response.text
    return client.cookies["refresh_token"]


def _cookie_value(response: httpx2.Response) -> str:
    match = re.search(r"refresh_token=([^;]+)", response.headers["set-cookie"])
    assert match, response.headers
    return match.group(1)


def _refresh_with(client: httpx2.AsyncClient, token: str) -> "asyncio.Future[httpx2.Response]":
    return asyncio.ensure_future(
        client.post("/api/v1/auth/refresh", headers={"Cookie": f"refresh_token={token}"})
    )


async def test_full_session_lifecycle(client: httpx2.AsyncClient) -> None:
    register = await client.post("/api/v1/auth/register", json=CREDENTIALS)
    assert register.status_code == 201, register.text

    login = await client.post("/api/v1/auth/login", json=CREDENTIALS)
    assert login.status_code == 200
    access = login.json()["access_token"]

    me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    assert me.json()["email"] == "ada@example.com"

    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200

    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_registering_the_same_email_twice_conflicts(client: httpx2.AsyncClient) -> None:
    first = await client.post("/api/v1/auth/register", json=CREDENTIALS)
    second = await client.post(
        "/api/v1/auth/register", json={**CREDENTIALS, "email": "ADA@example.com"}
    )

    assert (first.status_code, second.status_code) == (201, 409)


async def test_simultaneous_registrations_create_exactly_one_account(
    client: httpx2.AsyncClient, migrated_engine: Engine
) -> None:
    """Both requests pass the "email is free" check; the UNIQUE constraint decides."""
    responses = await asyncio.gather(
        *(client.post("/api/v1/auth/register", json=CREDENTIALS) for _ in range(2))
    )

    assert sorted(r.status_code for r in responses) == [201, 409]
    with migrated_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM users")).scalar_one() == 1


async def test_password_is_stored_as_an_argon2_hash(
    client: httpx2.AsyncClient, migrated_engine: Engine
) -> None:
    await client.post("/api/v1/auth/register", json=CREDENTIALS)

    with migrated_engine.connect() as c:
        stored = c.execute(text("SELECT password_hash FROM users")).scalar_one()
    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored


async def test_refresh_token_is_stored_hashed(
    client: httpx2.AsyncClient, migrated_engine: Engine
) -> None:
    token = await _login(client)

    with migrated_engine.connect() as c:
        stored = c.execute(text("SELECT token_hash FROM refresh_tokens")).scalar_one()
    assert token != stored
    assert len(stored) == 64


async def test_two_simultaneous_refreshes_with_one_token_yield_one_session(
    client: httpx2.AsyncClient,
) -> None:
    """The row lock serializes the race: one tab wins, the other is refused politely,
    and the session is not revoked (it is inside the reuse grace window)."""
    token = await _login(client)
    client.cookies.clear()

    first, second = await asyncio.gather(_refresh_with(client, token), _refresh_with(client, token))

    assert sorted([first.status_code, second.status_code]) == [200, 401]
    winner = first if first.status_code == 200 else second
    new_token = _cookie_value(winner)
    client.cookies.clear()
    follow_up = await _refresh_with(client, new_token)
    assert follow_up.status_code == 200


async def test_replaying_a_stolen_token_after_the_grace_window_revokes_the_session(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(refresh_reuse_grace_seconds=0)
    token = await _login(client)
    client.cookies.clear()
    legitimate = await _refresh_with(client, token)
    successor = _cookie_value(legitimate)
    await asyncio.sleep(0.05)

    replay = await _refresh_with(client, token)  # the thief presents the old token
    victim = await _refresh_with(client, successor)  # the family is now dead

    assert legitimate.status_code == 200
    assert replay.status_code == 401
    assert victim.status_code == 401
