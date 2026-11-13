"""FastAPI dependencies: the single place where services are wired to infrastructure.

Routers ask for a service; tests replace the provider with
``app.dependency_overrides`` to substitute a fake.
"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.db.session import get_engine
from app.services.health import HealthService

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_health_service(request: Request, settings: SettingsDep) -> HealthService:
    return HealthService(settings=settings, engine=get_engine(), redis=request.app.state.redis)


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
