"""Checks that the services the API depends on are reachable."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.schemas.health import ComponentHealth, HealthResponse

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 3.0


class HealthService:
    def __init__(self, settings: Settings, engine: AsyncEngine, redis: Redis) -> None:
        self._settings = settings
        self._engine = engine
        self._redis = redis

    async def check(self) -> HealthResponse:
        database, redis = await asyncio.gather(
            self._guarded("database", self._check_database),
            self._guarded("redis", self._check_redis),
        )
        checks = {**database, **redis}
        healthy = all(component.status == "ok" for component in checks.values())
        return HealthResponse(
            status="ok" if healthy else "degraded",
            version=self._settings.version,
            environment=self._settings.environment,
            checks=checks,
        )

    async def _guarded(
        self, name: str, check: Callable[[], Awaitable[dict[str, ComponentHealth]]]
    ) -> dict[str, ComponentHealth]:
        """Run one check with a timeout and turn any failure into an ``error`` entry.

        The exception goes to the server log only. The response carries a fixed
        message, because driver errors can contain hostnames and credentials.
        """
        try:
            async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
                return await check()
        except Exception:
            logger.exception("Health check failed: %s", name)
            return {name: ComponentHealth(status="error", detail="unreachable")}

    async def _check_database(self) -> dict[str, ComponentHealth]:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
            pgvector_version = result.scalar_one_or_none()

        pgvector = (
            ComponentHealth(status="ok", detail=str(pgvector_version))
            if pgvector_version is not None
            else ComponentHealth(status="error", detail="extension not installed")
        )
        return {"database": ComponentHealth(status="ok"), "pgvector": pgvector}

    async def _check_redis(self) -> dict[str, ComponentHealth]:
        await self._redis.ping()
        return {"redis": ComponentHealth(status="ok")}
