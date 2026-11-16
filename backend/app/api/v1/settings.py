from fastapi import APIRouter

from app.api.deps import CurrentUserDep, SettingsDep, SettingsServiceDep
from app.schemas.settings import SettingsRead, SettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsRead)
async def read_settings(
    user: CurrentUserDep, service: SettingsServiceDep, settings: SettingsDep
) -> SettingsRead:
    """The caller's preferences, the defaults they fall back to, and the server's own
    configuration (read-only)."""
    return SettingsRead.build(await service.get(user_id=user.id), settings)


@router.patch("", response_model=SettingsRead)
async def update_settings(
    body: SettingsUpdate, user: CurrentUserDep, service: SettingsServiceDep, settings: SettingsDep
) -> SettingsRead:
    saved = await service.update(user_id=user.id, changes=body.changes())
    return SettingsRead.build(saved, settings)
