import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import StreamingResponse

from app.api.deps import ChatServiceDep, CurrentUserDep
from app.api.sse import format_event
from app.core.errors import AppError
from app.schemas.chat import (
    ChatResponse,
    ConversationCreate,
    ConversationList,
    ConversationRead,
    ConversationUpdate,
    MessageList,
    MessageRead,
    SendMessageRequest,
)
from app.services.chat import DoneEvent, TokenEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/conversations", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate, user: CurrentUserDep, service: ChatServiceDep
) -> ConversationRead:
    conversation = await service.create_conversation(user_id=user.id, title=body.title)
    return ConversationRead.model_validate(conversation)


@router.get("/conversations", response_model=ConversationList)
async def list_conversations(
    user: CurrentUserDep,
    service: ChatServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConversationList:
    """Most recently active first."""
    items, total = await service.list_conversations(user_id=user.id, limit=limit, offset=offset)
    return ConversationList(
        items=[ConversationRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationRead)
async def get_conversation(
    conversation_id: uuid.UUID, user: CurrentUserDep, service: ChatServiceDep
) -> ConversationRead:
    return ConversationRead.model_validate(
        await service.get_conversation(user_id=user.id, conversation_id=conversation_id)
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationRead)
async def rename_conversation(
    conversation_id: uuid.UUID,
    body: ConversationUpdate,
    user: CurrentUserDep,
    service: ChatServiceDep,
) -> ConversationRead:
    return ConversationRead.model_validate(
        await service.rename_conversation(
            user_id=user.id, conversation_id=conversation_id, title=body.title
        )
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, user: CurrentUserDep, service: ChatServiceDep
) -> Response:
    await service.delete_conversation(user_id=user.id, conversation_id=conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/conversations/{conversation_id}/messages", response_model=MessageList)
async def list_messages(
    conversation_id: uuid.UUID,
    user: CurrentUserDep,
    service: ChatServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MessageList:
    """The conversation's messages, oldest first, each answer with its sources."""
    items, total = await service.list_messages(
        user_id=user.id, conversation_id=conversation_id, limit=limit, offset=offset
    )
    return MessageList(
        items=[MessageRead.from_stored(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=ChatResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    conversation_id: uuid.UUID,
    body: SendMessageRequest,
    user: CurrentUserDep,
    service: ChatServiceDep,
) -> ChatResponse:
    """Ask a question in a conversation. Returns the saved question and answer when the
    answer is complete (use ``/stream`` to receive it while it is written)."""
    exchange = await service.send(
        user_id=user.id,
        conversation_id=conversation_id,
        content=body.content,
        document_ids=body.document_ids,
    )
    return ChatResponse.from_exchange(exchange)


@router.post(
    "/{conversation_id}/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": (
                "Server-Sent Events: ``token`` {text} for each piece of the answer, then "
                "``done`` (the saved messages, same body as the non-streaming endpoint) or "
                "``error`` {error: {code, message}} if generation fails midway."
            ),
        }
    },
)
async def stream_message(
    conversation_id: uuid.UUID,
    body: SendMessageRequest,
    user: CurrentUserDep,
    service: ChatServiceDep,
) -> StreamingResponse:
    events = service.stream(
        user_id=user.id,
        conversation_id=conversation_id,
        content=body.content,
        document_ids=body.document_ids,
    )
    # Run the service up to its first event *before* answering. Problems found early (not
    # your conversation, no model configured, retrieval down) are then ordinary HTTP errors
    # (404/503) instead of a 200 with an error event inside it.
    first = await anext(events)

    async def encode() -> AsyncIterator[str]:
        try:
            event = first
            while True:
                if isinstance(event, TokenEvent):
                    yield format_event("token", {"text": event.text})
                elif isinstance(event, DoneEvent):
                    yield format_event(
                        "done", ChatResponse.from_exchange(event.exchange).model_dump(mode="json")
                    )
                try:
                    event = await anext(events)
                except StopAsyncIteration:
                    return
        except AppError as error:
            yield format_event("error", {"error": {"code": error.code, "message": error.message}})
        except Exception:
            logger.exception("chat stream failed")
            yield format_event(
                "error",
                {"error": {"code": "internal_error", "message": "Something went wrong."}},
            )
        finally:
            # Also runs when the client disconnects: stop the model call and release resources.
            await events.aclose()

    return StreamingResponse(
        encode(),
        media_type="text/event-stream",
        # No caching, and tell nginx-style proxies not to buffer, or tokens arrive in bulk.
        # no-transform stops intermediaries (notably the gzip layer of `next start`, which
        # sits between the browser and this API) from compressing and thereby buffering the
        # stream; X-Accel-Buffering does the same for nginx.
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
