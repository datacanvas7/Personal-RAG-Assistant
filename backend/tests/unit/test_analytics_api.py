"""GET /analytics/overview: auth, scoping to the caller, and the shape of the numbers.

The counting SQL itself runs against PostgreSQL in tests/integration/test_chat.py.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx2
import pytest

from app.api.deps import get_analytics_service, get_auth_service
from app.core.config import Settings
from app.main import create_app
from app.models import DocumentStatus
from app.repositories.analytics import OverviewCounts
from app.services.analytics import AnalyticsService
from app.services.auth import AuthService
from tests.fakes import FakeTokenStore, FakeTransaction, FakeUserStore

PASSWORD = "a-reasonable-passphrase"
URL = "/api/v1/analytics/overview"


@dataclass
class FakeOverviewStore:
    counts: OverviewCounts
    asked: list[tuple[uuid.UUID, datetime]] = field(default_factory=list)

    async def overview(self, user_id: uuid.UUID, *, since: datetime) -> OverviewCounts:
        self.asked.append((user_id, since))
        return self.counts


@dataclass
class Env:
    client: httpx2.AsyncClient
    users: FakeUserStore
    store: FakeOverviewStore


@pytest.fixture
async def env() -> AsyncIterator[Env]:
    settings = Settings()
    users, tokens = FakeUserStore(), FakeTokenStore()
    store = FakeOverviewStore(
        OverviewCounts(
            documents_by_status={
                DocumentStatus.READY: 3,
                DocumentStatus.PENDING: 1,
                DocumentStatus.PROCESSING: 1,
                DocumentStatus.FAILED: 2,
            },
            chunks=120,
            conversations=4,
            user_messages=9,
            assistant_messages=9,
            cited_answers=7,
            documents_since=2,
            conversations_since=1,
            questions_since=5,
        )
    )
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        users=users, tokens=tokens, transaction=FakeTransaction(), settings=settings
    )
    app.dependency_overrides[get_analytics_service] = lambda: AnalyticsService(store=store)
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Env(client, users, store)


async def _login(env: Env, email: str) -> tuple[dict[str, str], uuid.UUID]:
    credentials = {"email": email, "password": PASSWORD}
    await env.client.post("/api/v1/auth/register", json=credentials)
    response = await env.client.post("/api/v1/auth/login", json=credentials)
    user = await env.users.get_by_email(email)
    assert user is not None
    return {"Authorization": f"Bearer {response.json()['access_token']}"}, user.id


async def test_overview_requires_authentication(env: Env) -> None:
    response = await env.client.get(URL)

    assert response.status_code == 401
    assert env.store.asked == []


async def test_overview_reports_the_callers_totals_and_recent_activity(env: Env) -> None:
    headers, user_id = await _login(env, "ada@example.com")

    response = await env.client.get(URL, headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "documents": {"total": 7, "ready": 3, "processing": 2, "failed": 2},
        "chunks": 120,
        "conversations": 4,
        "messages": 18,
        "questions": 9,
        "answers": 9,
        "cited_answers": 7,
        "recent_activity": {
            "days": 7,
            "documents_uploaded": 2,
            "conversations_started": 1,
            "questions_asked": 5,
        },
    }
    [(asked_for, since)] = env.store.asked
    assert asked_for == user_id  # the id comes from the token, never from the request
    assert timedelta(days=6, hours=23) < datetime.now(UTC) - since < timedelta(days=7, minutes=1)


async def test_overview_of_a_new_user_is_all_zeros(env: Env) -> None:
    env.store.counts = OverviewCounts({}, 0, 0, 0, 0, 0, 0, 0, 0)
    headers, _ = await _login(env, "ada@example.com")

    body = (await env.client.get(URL, headers=headers)).json()

    assert body["documents"] == {"total": 0, "ready": 0, "processing": 0, "failed": 0}
    assert body["messages"] == body["chunks"] == body["conversations"] == 0
