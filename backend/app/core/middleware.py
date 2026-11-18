"""Per-request plumbing: request ids, access log, last-resort error response, security headers.

One pure-ASGI middleware (not ``BaseHTTPMiddleware``, which would buffer streamed
responses and break the SSE chat endpoint).

* **Request id**: taken from an incoming ``X-Request-ID`` when it looks harmless, otherwise
  generated. It is returned in the response header and attached to every log line, so a user
  can quote it and an operator can find the whole story.
* **Access log**: one line per request with method, path (never the query string), status
  and duration. Request and response bodies are never logged.
* **Unhandled errors**: anything not already translated into an ``AppError`` is logged with
  its traceback and answered with the uniform JSON shape and no internals. This is also the
  hook for an error-monitoring service (see docs/operations.md).
* **Security headers** on every response.
"""

import json
import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"
# Accept only plain tokens: the value ends up in logs and response headers.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

# Paths whose pages load third-party assets (Swagger UI) and must not get a strict policy.
_DOCS_SUFFIXES = ("/docs", "/docs/oauth2-redirect")


def _security_headers(path: str, *, hsts: bool) -> list[tuple[str, str]]:
    headers = [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "no-referrer"),
        # The API returns user data: nothing here may be stored by a shared cache.
        ("Cache-Control", "no-store"),
    ]
    if not path.endswith(_DOCS_SUFFIXES):
        # A JSON API has no business loading anything.
        headers.append(("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"))
    if hsts:
        headers.append(("Strict-Transport-Security", "max-age=63072000; includeSubDomains"))
    return headers


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self._hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = MutableHeaders(scope=scope).get(REQUEST_ID_HEADER, "")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        path: str = scope["path"]
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
                for name, value in _security_headers(path, hsts=self._hsts):
                    if name not in headers:
                        headers[name] = value
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception("unhandled error: %s %s", scope["method"], path)
            if response_started:
                # Too late to change the response (e.g. a stream already began).
                raise
            await self._internal_error(send_wrapper, request_id)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            level = logging.WARNING if status >= 500 else logging.INFO
            logger.log(
                level,
                "%s %s -> %s (%s ms)",
                scope["method"],
                path,
                status,
                duration_ms,
                extra={
                    "method": scope["method"],
                    "path": path,
                    "status": status,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)

    @staticmethod
    async def _internal_error(send: Send, request_id: str) -> None:
        body = json.dumps(
            {
                "error": {
                    "code": "internal_error",
                    "message": f"Something went wrong on our side. Reference: {request_id}.",
                }
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
