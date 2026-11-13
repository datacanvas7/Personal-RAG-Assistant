"""HTTP-level auth behavior, with the service wired to in-memory fakes."""

from collections.abc import AsyncIterator

import httpx2
import pytest

from app.api.deps import get_auth_service
from app.core.config import Settings
from app.main import create_app
from app.services.auth import AuthService
from tests.fakes import FakeTokenStore, FakeTransaction, FakeUserStore

PASSWORD = "a-reasonable-passphrase"
CREDENTIALS = {"email": "ada@example.com", "password": PASSWORD}


@pytest.fixture
async def client() -> AsyncIterator[httpx2.AsyncClient]:
    users, tokens, tx = FakeUserStore(), FakeTokenStore(), FakeTransaction()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        users=users, tokens=tokens, transaction=tx, settings=Settings()
    )
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _login(client: httpx2.AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=CREDENTIALS)
    response = await client.post("/api/v1/auth/login", json=CREDENTIALS)
    assert response.status_code == 200
    token: str = response.json()["access_token"]
    return token


async def test_register_returns_the_user_without_any_secret(client: httpx2.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/register", json=CREDENTIALS)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "ada@example.com"
    assert set(body) == {"id", "email", "created_at"}
    assert PASSWORD not in response.text


async def test_register_duplicate_returns_a_conflict_in_the_standard_error_shape(
    client: httpx2.AsyncClient,
) -> None:
    await client.post("/api/v1/auth/register", json=CREDENTIALS)

    response = await client.post("/api/v1/auth/register", json=CREDENTIALS)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "ada@example.com", "password": "short"},
        {"email": "not-an-email", "password": PASSWORD},
        {"email": "ada@example.com", "password": "x" * 129},
        {"email": "ada@example.com", "password": PASSWORD, "is_active": False},
        {"email": "ada@example.com"},
    ],
    ids=["short-password", "bad-email", "huge-password", "extra-field", "missing-password"],
)
async def test_register_validates_input(
    client: httpx2.AsyncClient, payload: dict[str, object]
) -> None:
    response = await client.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 422


async def test_login_sets_a_hardened_refresh_cookie(client: httpx2.AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=CREDENTIALS)

    response = await client.post("/api/v1/auth/login", json=CREDENTIALS)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert "refresh_token" not in body  # the refresh token is never in the JSON body
    cookie = response.headers["set-cookie"].lower()
    assert "refresh_token=" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/api/v1/auth" in cookie


async def test_wrong_password_returns_401_with_a_generic_message(
    client: httpx2.AsyncClient,
) -> None:
    await client.post("/api/v1/auth/register", json=CREDENTIALS)

    response = await client.post(
        "/api/v1/auth/login", json={**CREDENTIALS, "password": "not-the-password"}
    )

    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "unauthorized", "message": "Incorrect email or password."}
    }
    assert "set-cookie" not in response.headers


async def test_me_requires_a_valid_bearer_token(client: httpx2.AsyncClient) -> None:
    missing = await client.get("/api/v1/users/me")
    garbage = await client.get("/api/v1/users/me", headers={"Authorization": "Bearer nonsense"})
    wrong_scheme = await client.get("/api/v1/users/me", headers={"Authorization": "Basic abc"})

    for response in (missing, garbage, wrong_scheme):
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json()["error"]["code"] == "unauthorized"


async def test_me_returns_the_authenticated_user(client: httpx2.AsyncClient) -> None:
    token = await _login(client)

    response = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["email"] == "ada@example.com"


async def test_refresh_uses_the_cookie_and_rotates_it(client: httpx2.AsyncClient) -> None:
    await _login(client)
    before = client.cookies["refresh_token"]

    response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 200
    assert response.json()["access_token"]
    assert client.cookies["refresh_token"] != before


async def test_refresh_without_a_cookie_is_unauthorized(client: httpx2.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 401


async def test_logout_clears_the_cookie_and_ends_the_session(client: httpx2.AsyncClient) -> None:
    await _login(client)

    logout = await client.post("/api/v1/auth/logout")
    after = await client.post("/api/v1/auth/refresh")

    assert logout.status_code == 204
    assert "refresh_token" in logout.headers["set-cookie"]
    assert after.status_code == 401


async def test_logout_without_a_session_still_succeeds(client: httpx2.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 204
