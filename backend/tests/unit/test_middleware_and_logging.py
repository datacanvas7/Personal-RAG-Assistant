"""Request ids, security headers, the last-resort 500 and the log formats."""

import json
import logging
from collections.abc import AsyncIterator

import httpx2
import pytest
from fastapi import FastAPI

from app.core.logging import JsonFormatter, RequestIdFilter, request_id_var
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=create_app())
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_every_response_has_a_request_id(client: httpx2.AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert len(response.headers[REQUEST_ID_HEADER]) == 32


async def test_a_harmless_incoming_request_id_is_kept(client: httpx2.AsyncClient) -> None:
    response = await client.get("/api/v1/health", headers={REQUEST_ID_HEADER: "trace-abc-12345"})

    assert response.headers[REQUEST_ID_HEADER] == "trace-abc-12345"


@pytest.mark.parametrize(
    "value",
    ["short", "has spaces in it!!", "x" * 65, "semi;colon-in-it", "<script>alert(1)</script>"],
)
async def test_an_unsafe_incoming_request_id_is_replaced(
    client: httpx2.AsyncClient, value: str
) -> None:
    response = await client.get("/api/v1/health", headers={REQUEST_ID_HEADER: value})

    assert response.headers[REQUEST_ID_HEADER] != value
    assert len(response.headers[REQUEST_ID_HEADER]) == 32


async def test_security_headers_are_present(client: httpx2.AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert "strict-transport-security" not in response.headers


async def test_security_headers_are_on_error_responses_too(client: httpx2.AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.headers["x-content-type-options"] == "nosniff"
    assert REQUEST_ID_HEADER in response.headers


async def test_the_docs_page_keeps_working_under_the_security_headers(
    client: httpx2.AsyncClient,
) -> None:
    response = await client.get("/api/v1/docs")

    assert response.status_code == 200
    assert "content-security-policy" not in response.headers  # Swagger UI loads its assets
    assert response.headers["x-content-type-options"] == "nosniff"


def _app_that_raises(*, hsts: bool = False) -> FastAPI:
    app = FastAPI()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    @app.get("/ok")
    async def ok() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(RequestContextMiddleware, hsts=hsts)
    return app


async def test_an_unhandled_error_becomes_a_uniform_500_without_internals(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = httpx2.ASGITransport(app=_app_that_raises(), raise_app_exceptions=False)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/boom", headers={REQUEST_ID_HEADER: "request-id-0001"})

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "request-id-0001" in body["error"]["message"]
    assert "hunter2" not in response.text
    assert response.headers[REQUEST_ID_HEADER] == "request-id-0001"
    assert response.headers["x-content-type-options"] == "nosniff"
    # The traceback is in the log, for the operator.
    assert any("hunter2" in (r.exc_text or "") or r.exc_info for r in caplog.records)


async def test_hsts_is_sent_only_when_enabled() -> None:
    for hsts in (False, True):
        transport = httpx2.ASGITransport(app=_app_that_raises(hsts=hsts))
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ok")
        assert ("strict-transport-security" in response.headers) is hsts


async def test_the_access_log_has_the_path_but_never_the_query_string(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = httpx2.ASGITransport(app=_app_that_raises())
    with caplog.at_level(logging.INFO, logger="app.request"):
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/ok?token=super-secret-value")

    lines = [r.getMessage() for r in caplog.records if r.name == "app.request"]
    assert lines
    assert "/ok" in lines[0]
    assert "super-secret-value" not in lines[0]
    assert "-> 200" in lines[0]


async def test_the_request_id_is_available_to_log_records_during_the_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = FastAPI()
    seen: list[str] = []

    @app.get("/x")
    async def handler() -> None:
        seen.append(request_id_var.get())

    app.add_middleware(RequestContextMiddleware)
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/x")

    assert seen == [response.headers[REQUEST_ID_HEADER]]
    assert request_id_var.get() == "-"  # reset once the request is over


def _record(message: str = "hello %s", args: tuple[object, ...] = ("world",), **extra: object):  # type: ignore[no-untyped-def]
    record = logging.LogRecord("app.test", logging.WARNING, __file__, 1, message, args, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_request_id_filter_stamps_records() -> None:
    record = _record()
    token = request_id_var.set("req-123456")
    try:
        RequestIdFilter().filter(record)
    finally:
        request_id_var.reset(token)

    assert record.request_id == "req-123456"


def test_json_formatter_emits_one_object_with_the_standard_fields_and_extras() -> None:
    record = _record(request_id="req-123456", status=200, duration_ms=1.5)

    entry = json.loads(JsonFormatter().format(record))

    assert entry["level"] == "WARNING"
    assert entry["logger"] == "app.test"
    assert entry["message"] == "hello world"
    assert entry["request_id"] == "req-123456"
    assert entry["status"] == 200
    assert entry["duration_ms"] == 1.5
    assert entry["time"].endswith("+00:00")


def test_json_formatter_includes_the_traceback_and_stays_single_line() -> None:
    try:
        raise ValueError("bad")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "app.test", logging.ERROR, __file__, 1, "failed", (), sys.exc_info()
        )

    line = JsonFormatter().format(record)

    assert "\n" not in line
    assert "ValueError: bad" in json.loads(line)["exception"]
