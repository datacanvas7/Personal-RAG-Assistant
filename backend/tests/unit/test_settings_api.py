"""GET/PATCH /settings: defaults, partial updates, resets, validation, isolation and effect."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx2
import pytest

from app.api.deps import get_auth_service, get_settings_service
from app.core.config import Settings
from app.main import create_app
from app.services.auth import AuthService
from app.services.settings import SettingsService
from tests.fakes import FakeSettingsStore, FakeTokenStore, FakeTransaction, FakeUserStore

PASSWORD = "a-reasonable-passphrase"
URL = "/api/v1/settings"


@dataclass
class Env:
    client: httpx2.AsyncClient
    users: FakeUserStore
    store: FakeSettingsStore
    tx: FakeTransaction
    service: SettingsService


@pytest.fixture
async def env() -> AsyncIterator[Env]:
    settings = Settings()
    users, tokens = FakeUserStore(), FakeTokenStore()
    store, tx = FakeSettingsStore(), FakeTransaction()
    service = SettingsService(store=store, transaction=tx, settings=settings)
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        users=users, tokens=tokens, transaction=FakeTransaction(), settings=settings
    )
    app.dependency_overrides[get_settings_service] = lambda: service
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Env(client, users, store, tx, service)


async def _login(env: Env, email: str) -> tuple[dict[str, str], uuid.UUID]:
    credentials = {"email": email, "password": PASSWORD}
    await env.client.post("/api/v1/auth/register", json=credentials)
    response = await env.client.post("/api/v1/auth/login", json=credentials)
    user = await env.users.get_by_email(email)
    assert user is not None
    return {"Authorization": f"Bearer {response.json()['access_token']}"}, user.id


async def test_settings_require_authentication(env: Env) -> None:
    assert (await env.client.get(URL)).status_code == 401
    assert (await env.client.patch(URL, json={"theme": "dark"})).status_code == 401
    assert env.store.rows == {}


async def test_a_new_user_gets_the_defaults_and_nothing_is_stored(env: Env) -> None:
    headers, _ = await _login(env, "ada@example.com")

    response = await env.client.get(URL, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["theme"] == "system"
    assert body["retrieval_top_k"] is None
    assert body["retrieval_score_threshold"] is None
    assert body["defaults"] == {"top_k": 5, "score_threshold": 0.45}
    assert env.store.rows == {}  # reading creates no row


async def test_read_shows_the_server_configuration_but_no_secret(env: Env) -> None:
    headers, _ = await _login(env, "ada@example.com")

    body = (await env.client.get(URL, headers=headers)).json()

    server = body["server"]
    assert server["llm_model"] == Settings().llm_model
    assert server["llm_configured"] is False  # no key in the test environment
    assert server["chunk_size_chars"] == Settings().chunk_size_chars
    assert server["embedding_model"]
    assert "key" not in " ".join(server).replace("llm_configured", "")


async def test_update_is_partial_and_persists(env: Env) -> None:
    headers, user_id = await _login(env, "ada@example.com")

    first = await env.client.patch(URL, headers=headers, json={"theme": "dark"})
    second = await env.client.patch(URL, headers=headers, json={"retrieval_top_k": 8})

    assert first.status_code == 200 and first.json()["theme"] == "dark"
    body = second.json()
    assert body["theme"] == "dark"  # the earlier change survives
    assert body["retrieval_top_k"] == 8
    assert body["retrieval_score_threshold"] is None
    assert env.store.rows[user_id].retrieval_top_k == 8
    assert env.tx.commits >= 2
    assert (await env.client.get(URL, headers=headers)).json()["retrieval_top_k"] == 8


async def test_null_resets_a_retrieval_value_to_the_server_default(env: Env) -> None:
    headers, _ = await _login(env, "ada@example.com")
    await env.client.patch(
        URL, headers=headers, json={"retrieval_top_k": 3, "retrieval_score_threshold": 0.6}
    )

    response = await env.client.patch(URL, headers=headers, json={"retrieval_top_k": None})

    body = response.json()
    assert body["retrieval_top_k"] is None
    assert body["retrieval_score_threshold"] == 0.6


async def test_an_empty_update_changes_and_commits_nothing(env: Env) -> None:
    headers, _ = await _login(env, "ada@example.com")

    response = await env.client.patch(URL, headers=headers, json={})

    assert response.status_code == 200
    assert env.store.rows == {}
    assert env.tx.commits == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"theme": "purple"},
        {"theme": None},
        {"retrieval_top_k": 0},
        {"retrieval_top_k": 21},
        {"retrieval_top_k": 2.5},
        {"retrieval_score_threshold": -0.1},
        {"retrieval_score_threshold": 1.1},
        {"user_id": "someone-else"},
        {"llm_model": "anything"},  # server configuration is not user-editable
    ],
)
async def test_invalid_updates_are_rejected_and_store_nothing(
    env: Env, payload: dict[str, object]
) -> None:
    headers, _ = await _login(env, "ada@example.com")

    response = await env.client.patch(URL, headers=headers, json=payload)

    assert response.status_code == 422
    assert env.store.rows == {}


async def test_users_never_see_or_change_each_others_settings(env: Env) -> None:
    ada, _ = await _login(env, "ada@example.com")
    bob, _ = await _login(env, "bob@example.com")
    await env.client.patch(URL, headers=ada, json={"theme": "dark", "retrieval_top_k": 9})

    bobs = (await env.client.get(URL, headers=bob)).json()

    assert bobs["theme"] == "system"
    assert bobs["retrieval_top_k"] is None


async def test_the_effective_retrieval_numbers_are_the_users_or_the_servers(env: Env) -> None:
    _, ada_id = await _login(env, "ada@example.com")
    _, bob_id = await _login(env, "bob@example.com")
    await env.service.update(user_id=ada_id, changes={"retrieval_top_k": 2})

    ada = await env.service.retrieval(user_id=ada_id)
    bob = await env.service.retrieval(user_id=bob_id)

    assert (ada.top_k, ada.score_threshold) == (2, 0.45)  # own top-k, server threshold
    assert (bob.top_k, bob.score_threshold) == (5, 0.45)


async def test_a_threshold_of_zero_is_a_real_choice_not_a_missing_value(env: Env) -> None:
    _, user_id = await _login(env, "ada@example.com")
    await env.service.update(user_id=user_id, changes={"retrieval_score_threshold": 0.0})

    assert (await env.service.retrieval(user_id=user_id)).score_threshold == 0.0
