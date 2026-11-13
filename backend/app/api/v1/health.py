from fastapi import APIRouter, Response, status

from app.api.deps import HealthServiceDep
from app.schemas.health import HealthResponse

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def health(response: Response, service: HealthServiceDep) -> HealthResponse:
    """Report whether the API can reach PostgreSQL (with pgvector) and Redis.

    Returns 503 with the same body when any dependency is down, so container
    orchestrators and load balancers can act on the status code alone.
    """
    report = await service.check()
    if report.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report
