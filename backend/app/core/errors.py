"""Application errors and their translation to a uniform JSON response.

Every error this application raises on purpose reaches the client as
``{"error": {"code": "...", "message": "..."}}``. Messages are written for end users and
never contain internals.
"""

from typing import cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.headers = headers


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthorized"

    def __init__(self, message: str = "Authentication required.") -> None:
        super().__init__(message, headers={"WWW-Authenticate": "Bearer"})


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class NotFoundError(AppError):
    """Also used for resources that exist but belong to someone else: the API never
    reveals which ids are taken by other users."""

    status_code = 404
    code = "not_found"


class InvalidFileError(AppError):
    status_code = 400
    code = "invalid_file"


class UnsupportedFileTypeError(AppError):
    status_code = 415
    code = "unsupported_file_type"


class FileTooLargeError(AppError):
    status_code = 413
    code = "file_too_large"


class ServiceUnavailableError(AppError):
    """A dependency this request needs (e.g. the embedding model) is not working. The
    message never names the dependency or its error; those go to the log."""

    status_code = 503
    code = "service_unavailable"


async def _handle_app_error(_request: Request, exc: Exception) -> JSONResponse:
    app_error = cast(AppError, exc)  # registered for AppError only
    return JSONResponse(
        status_code=app_error.status_code,
        content={"error": {"code": app_error.code, "message": app_error.message}},
        headers=app_error.headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
