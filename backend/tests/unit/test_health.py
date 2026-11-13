from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_health_service
from app.core.config import Settings, get_settings
from app.main import create_app
from app.schemas.health import ComponentHealth, HealthResponse
from app.services.health import HealthService

SECRET_DRIVER_ERROR = "connection to server at 10.0.0.5 failed: password authentication failed"


class FakeHealthService:
    def __init__(self, report: HealthResponse) -> None:
        self._report = report

    async def check(self) -> HealthResponse:
        return self._report


def _report(status: str, **checks: str) -> HealthResponse:
    return HealthResponse(
        status=status,
        version="0.1.0",
        environment="test",
        checks={name: ComponentHealth(status=state) for name, state in checks.items()},
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def _use_service(client: TestClient, service: Any) -> None:
    client.app.dependency_overrides[get_health_service] = lambda: service  # type: ignore[attr-defined]


def test_health_returns_200_when_everything_is_up(client: TestClient) -> None:
    _use_service(client, FakeHealthService(_report("ok", database="ok", redis="ok")))

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert set(response.json()["checks"]) == {"database", "redis"}


def test_health_returns_503_with_body_when_a_dependency_is_down(client: TestClient) -> None:
    _use_service(client, FakeHealthService(_report("degraded", database="ok", redis="error")))

    response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json()["checks"]["redis"]["status"] == "error"


def test_openapi_docs_are_served_under_the_api_prefix(client: TestClient) -> None:
    assert client.get("/api/v1/openapi.json").status_code == 200
    assert client.get("/api/v1/docs").status_code == 200


# --- HealthService against failing infrastructure -------------------------------------


class BrokenEngine:
    def connect(self) -> Any:
        raise RuntimeError(SECRET_DRIVER_ERROR)


class BrokenRedis:
    async def ping(self) -> bool:
        raise ConnectionError(SECRET_DRIVER_ERROR)


async def test_health_service_reports_failures_without_leaking_error_text() -> None:
    service = HealthService(
        settings=Settings(postgres_password="x"),
        engine=BrokenEngine(),  # type: ignore[arg-type]
        redis=BrokenRedis(),  # type: ignore[arg-type]
    )

    report = await service.check()

    assert report.status == "degraded"
    assert report.checks["database"].status == "error"
    assert report.checks["redis"].status == "error"
    assert SECRET_DRIVER_ERROR not in report.model_dump_json()


def test_settings_are_cached() -> None:
    assert get_settings() is get_settings()
