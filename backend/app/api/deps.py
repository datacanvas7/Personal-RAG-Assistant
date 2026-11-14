"""FastAPI dependencies: the single place where services are wired to infrastructure.

Routers ask for a service; tests replace the provider with
``app.dependency_overrides`` to substitute a fake.
"""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError
from app.db.session import get_engine, get_session
from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import get_embedding_provider
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.models import User
from app.rag.service import RagService
from app.repositories.auth import RefreshTokenRepository, UserRepository
from app.repositories.documents import DocumentRepository
from app.retrieval.service import SearchService
from app.retrieval.vector_store import PgVectorStore
from app.services.auth import AuthService
from app.services.documents import DocumentService
from app.services.health import HealthService
from app.services.queue import CeleryIngestionQueue, IngestionQueue
from app.services.storage import FileStorage, LocalFileStorage

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]

# auto_error=False: a missing header is reported through our own error format
# (and a consistent 401) instead of FastAPI's default 403.
_bearer = HTTPBearer(auto_error=False, description="Access token from /auth/login")


def get_health_service(request: Request, settings: SettingsDep) -> HealthService:
    return HealthService(settings=settings, engine=get_engine(), redis=request.app.state.redis)


def get_auth_service(session: SessionDep, settings: SettingsDep) -> AuthService:
    return AuthService(
        users=UserRepository(session),
        tokens=RefreshTokenRepository(session),
        transaction=session,
        settings=settings,
    )


def get_file_storage(settings: SettingsDep) -> FileStorage:
    return LocalFileStorage(settings.upload_dir)


def get_ingestion_queue() -> IngestionQueue:
    return CeleryIngestionQueue()


FileStorageDep = Annotated[FileStorage, Depends(get_file_storage)]
IngestionQueueDep = Annotated[IngestionQueue, Depends(get_ingestion_queue)]


def get_document_service(
    session: SessionDep,
    settings: SettingsDep,
    storage: FileStorageDep,
    queue: IngestionQueueDep,
) -> DocumentService:
    return DocumentService(
        documents=DocumentRepository(session),
        storage=storage,
        queue=queue,
        transaction=session,
        settings=settings,
    )


def get_embedder() -> EmbeddingProvider:
    return get_embedding_provider()


EmbedderDep = Annotated[EmbeddingProvider, Depends(get_embedder)]


def get_search_service(session: SessionDep, embedder: EmbedderDep) -> SearchService:
    return SearchService(
        embedder=embedder,
        vectors=PgVectorStore(session),
        documents=DocumentRepository(session),
    )


def get_llm() -> LLMProvider | None:
    return get_llm_provider()


LlmDep = Annotated[LLMProvider | None, Depends(get_llm)]


def get_rag_service(
    search: Annotated[SearchService, Depends(get_search_service)],
    llm: LlmDep,
    settings: SettingsDep,
) -> RagService:
    return RagService(
        searcher=search,
        llm=llm,
        top_k=settings.retrieval_top_k,
        score_threshold=settings.retrieval_score_threshold,
        max_context_chars=settings.max_context_chars,
        history_max_messages=settings.chat_history_max_messages,
    )


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]
RagServiceDep = Annotated[RagService, Depends(get_rag_service)]


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    auth: AuthServiceDep,
) -> User:
    """Every protected endpoint depends on this. The user id used for data access comes
    from here (the verified token) and never from the request body or URL."""
    if credentials is None:
        raise AuthenticationError()
    return await auth.authenticate(access_token=credentials.credentials)


CurrentUserDep = Annotated[User, Depends(get_current_user)]
