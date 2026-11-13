import httpx2
import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from app.core.limits import MaxBodySizeMiddleware


class Probe:
    """Stands in for the application and records whether it was reached."""

    def __init__(self) -> None:
        self.reached = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.reached = True
        request = Request(scope, receive)
        await JSONResponse({"bytes": len(await request.body())})(scope, receive, send)


def _client(probe: Probe) -> httpx2.AsyncClient:
    app = MaxBodySizeMiddleware(probe, path_suffix="/documents/upload", max_body_bytes=1000)
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test")


async def test_a_body_over_the_limit_is_rejected_without_reaching_the_app() -> None:
    probe = Probe()
    async with _client(probe) as client:
        response = await client.post("/api/v1/documents/upload", content=b"x" * 200_000)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    assert probe.reached is False


async def test_a_body_within_the_limit_passes_through() -> None:
    probe = Probe()
    async with _client(probe) as client:
        response = await client.post("/api/v1/documents/upload", content=b"x" * 500)

    assert response.status_code == 200
    assert response.json() == {"bytes": 500}


@pytest.mark.parametrize(
    ("method", "path"), [("POST", "/api/v1/auth/login"), ("GET", "/api/v1/documents/upload")]
)
async def test_other_requests_are_not_limited(method: str, path: str) -> None:
    probe = Probe()
    async with _client(probe) as client:
        response = await client.request(method, path, content=b"x" * 200_000)

    assert response.status_code == 200
    assert probe.reached is True
