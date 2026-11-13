"""Reject oversized request bodies before they are read.

Without this, the server would accept and spool a multi-gigabyte upload before any
endpoint code ran. The check uses the ``Content-Length`` header, which honest clients
always send; the endpoint additionally caps how many bytes it reads, which covers
clients that omit or lie about the header (chunked transfer encoding).
"""

import json

from starlette.types import ASGIApp, Receive, Scope, Send

# Multipart framing (boundaries, part headers) adds a little on top of the file itself.
_MULTIPART_OVERHEAD = 64 * 1024


class MaxBodySizeMiddleware:
    def __init__(self, app: ASGIApp, *, path_suffix: str, max_body_bytes: int) -> None:
        self.app = app
        self._suffix = path_suffix
        self._limit = max_body_bytes + _MULTIPART_OVERHEAD

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not scope["path"].endswith(self._suffix)
        ):
            await self.app(scope, receive, send)
            return

        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    too_big = int(value) > self._limit
                except ValueError:
                    too_big = True
                if too_big:
                    await self._reject(send)
                    return
                break
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send: Send) -> None:
        body = json.dumps(
            {"error": {"code": "file_too_large", "message": "The uploaded file is too large."}}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
