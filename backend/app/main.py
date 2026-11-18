"""FastAPI application entry point."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.limits import MaxBodySizeMiddleware
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.ratelimit import DisabledRateLimiter, RedisRateLimiter
from app.db.session import get_engine, get_sync_engine
from app.embeddings.factory import get_embedding_provider
from app.embeddings.guard import check_embedding_index

logger = logging.getLogger(__name__)


async def _check_embedding_index() -> None:
    """Refuse to start if the configured embedding model does not match the stored index.

    A database that is unreachable or not yet migrated is not this check's business (the
    readiness probe reports it), so those cases are logged and skipped; only a real
    model/dimension mismatch stops the API.
    """
    try:
        # Blocking DB calls: keep them off the event loop.
        await asyncio.to_thread(check_embedding_index, get_sync_engine(), get_embedding_provider())
    except SQLAlchemyError:
        logger.warning("embedding index check skipped: database not ready", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    await _check_embedding_index()
    # One shared client with its own connection pool; no connection is opened until
    # the first command.
    app.state.redis = Redis.from_url(settings.redis_url)
    yield
    await app.state.redis.aclose()
    await get_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title=settings.project_name,
        version=settings.version,
        # Docs live under the API prefix so they are reachable through the same
        # proxy path as the API itself.
        # (Off in production unless ENABLE_API_DOCS is set: no reason to publish the schema.)
        docs_url=f"{settings.api_v1_prefix}/docs" if settings.api_docs_enabled else None,
        redoc_url=None,
        openapi_url=(
            f"{settings.api_v1_prefix}/openapi.json" if settings.api_docs_enabled else None
        ),
        lifespan=lifespan,
    )

    # Counters live in Redis; the client is created in the lifespan, hence the lambda.
    app.state.rate_limiter = (
        RedisRateLimiter(lambda: app.state.redis)
        if settings.rate_limit_enabled
        else DisabledRateLimiter()
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    app.add_middleware(
        MaxBodySizeMiddleware,
        path_suffix="/documents/upload",
        max_body_bytes=settings.max_upload_bytes,
    )

    # Added last = outermost: every response, including the 413 above, gets a request id.
    app.add_middleware(RequestContextMiddleware, hsts=settings.environment == "production")

    register_error_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
