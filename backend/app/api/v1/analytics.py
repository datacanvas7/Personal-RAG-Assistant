from fastapi import APIRouter

from app.api.deps import AnalyticsServiceDep, CurrentUserDep
from app.schemas.analytics import OverviewResponse

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=OverviewResponse)
async def overview(user: CurrentUserDep, service: AnalyticsServiceDep) -> OverviewResponse:
    """Counts of the caller's own documents, chunks, conversations and messages."""
    return OverviewResponse.from_overview(await service.overview(user_id=user.id))
