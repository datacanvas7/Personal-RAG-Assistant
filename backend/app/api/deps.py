"""FastAPI dependencies: the single place where services are wired to infrastructure.

Routers ask for a service; tests replace the provider with
``app.dependency_overrides`` to substitute a fake.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError, RateLimitedError
from app.core.ratelimit import RateLimiter, Rule
from app.db.session import get_engine, get_session
from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import get_embedding_provider
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.models import User
from app.rag.service import RagService
from app.repositories.analytics import AnalyticsRepository
from app.repositories.auth import RefreshTokenRepository, UserRepository
from app.repositories.conversations import ConversationRepository, MessageRepository
from app.repositories.documents import DocumentRepository
from app.repositories.user_settings import UserSettingsRepository
from app.retrieval.keyword_store import PgKeywordStore
from app.retrieval.reranker import LexicalReranker
from app.retrieval.service import SearchService
from app.retrieval.vector_store import PgVectorStore
from app.services.analytics import AnalyticsService
from app.services.auth import AuthService
from app.services.chat import ChatService
from app.services.documents import DocumentService
from app.services.health import HealthService
from app.services.queue import CeleryIngestionQueue, IngestionQueue
from app.services.settings import SettingsService
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


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


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


# --- Rate limiting -------------------------------------------------------------------------


def get_rate_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


class RateLimits:
    """Looks a rule up by name in the settings and counts one request against it."""

    def __init__(self, limiter: RateLimiter, settings: Settings) -> None:
        self._limiter = limiter
        self._settings = settings

    async def enforce(self, rule_name: str, identity: str) -> None:
        rule = Rule.parse(getattr(self._settings, f"rate_limit_{rule_name}"))
        decision = await self._limiter.hit(f"{rule_name}:{identity}", rule)
        if not decision.allowed:
            raise RateLimitedError(decision.retry_after_seconds)


def get_rate_limits(
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)], settings: SettingsDep
) -> RateLimits:
    return RateLimits(limiter, settings)


RateLimitsDep = Annotated[RateLimits, Depends(get_rate_limits)]


def client_ip(request: Request) -> str:
    """The caller's address. Behind a reverse proxy this is the proxy's address unless
    uvicorn is told to trust its X-Forwarded-For (``--forwarded-allow-ips``); see
    docs/operations.md."""
    return request.client.host if request.client else "unknown"


def limit_by_ip(rule_name: str) -> Callable[..., Awaitable[None]]:
    """A route dependency: ``dependencies=[Depends(limit_by_ip("login_ip"))]``."""

    async def dependency(request: Request, limits: RateLimitsDep) -> None:
        await limits.enforce(rule_name, client_ip(request))

    return dependency


def limit_by_user(rule_name: str) -> Callable[..., Awaitable[None]]:
    """Like ``limit_by_ip`` but per signed-in user (runs after authentication)."""

    async def dependency(user: CurrentUserDep, limits: RateLimitsDep) -> None:
        await limits.enforce(rule_name, str(user.id))

    return dependency


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


def get_search_service(
    session: SessionDep, embedder: EmbedderDep, settings: SettingsDep
) -> SearchService:
    return SearchService(
        embedder=embedder,
        vectors=PgVectorStore(session),
        keywords=PgKeywordStore(session),
        documents=DocumentRepository(session),
        reranker=LexicalReranker() if settings.retrieval_rerank else None,
        mode=settings.retrieval_mode,
        candidate_multiplier=settings.retrieval_candidate_multiplier,
    )


def get_llm() -> LLMProvider | None:
    return get_llm_provider()


LlmDep = Annotated[LLMProvider | None, Depends(get_llm)]


def get_settings_service(session: SessionDep, settings: SettingsDep) -> SettingsService:
    return SettingsService(
        store=UserSettingsRepository(session), transaction=session, settings=settings
    )


SettingsServiceDep = Annotated[SettingsService, Depends(get_settings_service)]


async def get_rag_service(
    search: Annotated[SearchService, Depends(get_search_service)],
    llm: LlmDep,
    settings: SettingsDep,
    session: SessionDep,
    user: CurrentUserDep,
    user_settings: SettingsServiceDep,
) -> RagService:
    # The caller's own retrieval preferences (or the server's defaults).
    retrieval = await user_settings.retrieval(user_id=user.id)
    return RagService(
        searcher=search,
        llm=llm,
        top_k=retrieval.top_k,
        score_threshold=retrieval.score_threshold,
        max_context_chars=settings.max_context_chars,
        history_max_messages=settings.chat_history_max_messages,
        condense_queries=settings.query_condensing,
        # Retrieval only reads; ending its transaction returns the connection to the pool
        # before the slow model call (a no-op if nothing was read).
        release_connection=session.commit,
    )


RagServiceDep = Annotated[RagService, Depends(get_rag_service)]


def get_chat_service(session: SessionDep, rag: RagServiceDep, settings: SettingsDep) -> ChatService:
    return ChatService(
        conversations=ConversationRepository(session),
        messages=MessageRepository(session),
        rag=rag,
        transaction=session,
        history_max_messages=settings.chat_history_max_messages,
    )


def get_analytics_service(session: SessionDep) -> AnalyticsService:
    return AnalyticsService(store=AnalyticsRepository(session))


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]
ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]
AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]
