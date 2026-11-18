from fastapi import APIRouter, Depends

from app.api.deps import CurrentUserDep, SearchServiceDep, limit_by_user
from app.schemas.search import SearchRequest, SearchResponse

router = APIRouter(prefix="/search", tags=["search"])


@router.post(
    "", response_model=SearchResponse, dependencies=[Depends(limit_by_user("search_user"))]
)
async def search(
    body: SearchRequest, user: CurrentUserDep, service: SearchServiceDep
) -> SearchResponse:
    """Semantic search over the caller's own ready documents, best match first.

    POST rather than GET so the query text stays out of URLs and access logs. Only chunks
    owned by the authenticated user are ever considered.
    """
    results = await service.search(
        user_id=user.id,
        query=body.query,
        top_k=body.top_k,
        document_ids=body.document_ids,
        content_types=body.content_types,
        page_from=body.page_from,
        page_to=body.page_to,
    )
    return SearchResponse(results=results)
