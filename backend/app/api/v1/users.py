from fastapi import APIRouter

from app.api.deps import CurrentUserDep
from app.schemas.auth import UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def read_me(user: CurrentUserDep) -> UserRead:
    return UserRead.model_validate(user)
