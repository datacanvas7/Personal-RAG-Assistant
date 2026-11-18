from fastapi import APIRouter, Depends

from app.api.deps import CurrentUserDep, RagServiceDep, limit_by_user
from app.llm.base import ChatMessage
from app.schemas.ask import AskRequest, AskResponse, SourceOut

router = APIRouter(prefix="/ask", tags=["ask"])


@router.post("", response_model=AskResponse, dependencies=[Depends(limit_by_user("ask_user"))])
async def ask(body: AskRequest, user: CurrentUserDep, service: RagServiceDep) -> AskResponse:
    """Answer a question from the caller's own documents, with citations.

    Stateless: nothing is stored. The client sends earlier turns as ``history``; saved
    conversations and streaming arrive with the chat API (Phase 6).
    """
    answer = await service.answer(
        user_id=user.id,
        question=body.question,
        history=[ChatMessage(m.role, m.content) for m in body.history],
        document_ids=body.document_ids,
        top_k=body.top_k,
    )
    return AskResponse(
        answer=answer.text,
        grounded=answer.grounded,
        sources=[SourceOut(**vars(source)) for source in answer.sources],
    )
