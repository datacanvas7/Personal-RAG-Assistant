"""Rate limiting as the client sees it: 429 with Retry-After, and what each limit keys on.

The limiter itself is covered in test_ratelimit.py; here an in-memory limiter is wired into
the real routes with tiny limits.
"""

import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

import httpx2
import pytest

from app.api.deps import get_auth_service, get_embedder, get_search_service
from app.core.config import Settings, get_settings
from app.core.ratelimit import InMemoryRateLimiter
from app.main import create_app
from app.retrieval.service import SearchService
from app.retrieval.vector_store import ScoredChunk
from app.services.auth import AuthService
from tests.fakes import (
    FakeDocumentStore,
    FakeEmbedder,
    FakeTokenStore,
    FakeTransaction,
    FakeUserStore,
)

PASSWORD = "a-reasonable-passphrase"


class EmptyVectorStore:
    async def search(
        self, user_id: uuid.UUID, query_embedding: Sequence[float], **_: Any
    ) -> list[ScoredChunk]:
        return []


@dataclass
class Env:
    client: httpx2.AsyncClient


@pytest.fixture
async def env() -> AsyncIterator[Env]:
    settings = Settings(
        rate_limit_enabled=True,
        rate_limit_login_ip="100/1m",
        rate_limit_login_email="3/15m",
        rate_limit_register_ip="2/1h",
        rate_limit_search_user="2/1m",
    )
    users, tokens, embedder = FakeUserStore(), FakeTokenStore(), FakeEmbedder()
    app = create_app()
    app.state.rate_limiter = InMemoryRateLimiter()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        users=users, tokens=tokens, transaction=FakeTransaction(), settings=settings
    )
    app.dependency_overrides[get_embedder] = lambda: embedder
    app.dependency_overrides[get_search_service] = lambda: SearchService(
        embedder=embedder, vectors=EmptyVectorStore(), documents=FakeDocumentStore()
    )
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Env(client)


def _credentials(email: str, password: str = PASSWORD) -> dict[str, str]:
    return {"email": email, "password": password}


async def test_register_is_limited_per_ip(env: Env) -> None:
    first = await env.client.post("/api/v1/auth/register", json=_credentials("a@example.com"))
    second = await env.client.post("/api/v1/auth/register", json=_credentials("b@example.com"))
    third = await env.client.post("/api/v1/auth/register", json=_credentials("c@example.com"))

    assert (first.status_code, second.status_code) == (201, 201)
    assert third.status_code == 429


async def test_a_429_has_the_uniform_error_shape_and_a_retry_after_header(env: Env) -> None:
    for name in ("a", "b"):
        await env.client.post("/api/v1/auth/register", json=_credentials(f"{name}@example.com"))

    response = await env.client.post("/api/v1/auth/register", json=_credentials("c@example.com"))

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["retry-after"]) >= 1
    assert response.headers["x-content-type-options"] == "nosniff"  # middleware still applies


async def test_repeated_failed_logins_for_one_email_are_stopped(env: Env) -> None:
    await env.client.post("/api/v1/auth/register", json=_credentials("ada@example.com"))
    wrong = _credentials("ada@example.com", "definitely-the-wrong-one")

    statuses = [
        (await env.client.post("/api/v1/auth/login", json=wrong)).status_code for _ in range(5)
    ]

    assert statuses == [401, 401, 401, 429, 429]


async def test_the_email_limit_ignores_case_and_whitespace(env: Env) -> None:
    await env.client.post("/api/v1/auth/register", json=_credentials("ada@example.com"))
    attempts = ["ada@example.com", "ADA@example.com", " ada@example.com", "Ada@Example.com"]

    statuses = [
        (
            await env.client.post(
                "/api/v1/auth/login", json=_credentials(email, "wrong-wrong-wrong")
            )
        ).status_code
        for email in attempts
    ]

    assert statuses[-1] == 429


async def test_one_email_being_limited_does_not_lock_out_another(env: Env) -> None:
    await env.client.post("/api/v1/auth/register", json=_credentials("ada@example.com"))
    for _ in range(4):
        await env.client.post(
            "/api/v1/auth/login", json=_credentials("ada@example.com", "wrong-wrong-wrong")
        )

    other = await env.client.post("/api/v1/auth/login", json=_credentials("bob@example.com"))

    assert other.status_code == 401  # wrong credentials, but not rate limited


async def _token(env: Env, email: str) -> dict[str, str]:
    # Register/login are limited too, so reset by using a fresh app limiter is not possible;
    # the fixture's register limit (2/1h) allows two users per test.
    await env.client.post("/api/v1/auth/register", json=_credentials(email))
    response = await env.client.post("/api/v1/auth/login", json=_credentials(email))
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_search_is_limited_per_user(env: Env) -> None:
    ada = await _token(env, "ada@example.com")
    bob = await _token(env, "bob@example.com")
    body = {"query": "anything"}

    ada_statuses = [
        (await env.client.post("/api/v1/search", headers=ada, json=body)).status_code
        for _ in range(3)
    ]
    bob_status = (await env.client.post("/api/v1/search", headers=bob, json=body)).status_code

    assert ada_statuses == [200, 200, 429]
    assert bob_status == 200  # another user has their own budget


async def test_unauthenticated_requests_are_rejected_before_they_are_counted(env: Env) -> None:
    statuses = [
        (await env.client.post("/api/v1/search", json={"query": "x"})).status_code for _ in range(5)
    ]

    assert statuses == [401] * 5


async def test_rate_limiting_can_be_switched_off() -> None:
    settings = Settings(rate_limit_enabled=False, rate_limit_register_ip="1/1h")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        users=FakeUserStore(),
        tokens=FakeTokenStore(),
        transaction=FakeTransaction(),
        settings=settings,
    )
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        statuses = [
            (
                await client.post("/api/v1/auth/register", json=_credentials(f"u{i}@example.com"))
            ).status_code
            for i in range(3)
        ]

    assert statuses == [201, 201, 201]
