"""In-memory stand-ins for the repositories, used by service and API unit tests.

They implement only what the service layer calls. Behavior that needs a real database
(row locking, constraints, cascades) is covered by tests/integration instead.
"""

import hashlib
import math
import re
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.ingestion.chunking import Chunk
from app.llm.base import ChatMessage, LLMResult
from app.models import (
    Conversation,
    Document,
    DocumentStatus,
    Message,
    MessageSource,
    RefreshToken,
    User,
)
from app.repositories.documents import ClaimedDocument
from app.services.settings import DEFAULT_PREFERENCES, UserPreferences


class FakeUserStore:
    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.users.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self.users.values() if u.email == email), None)

    async def add(self, user: User) -> User:
        user.id = user.id or uuid.uuid4()
        if user.is_active is None:
            user.is_active = True  # the database default
        user.created_at = datetime.now(UTC)
        self.users[user.id] = user
        return user


class FakeTokenStore:
    def __init__(self) -> None:
        self.tokens: list[RefreshToken] = []

    async def add(self, token: RefreshToken) -> RefreshToken:
        token.id = token.id or uuid.uuid4()
        self.tokens.append(token)
        return token

    async def get_by_hash_for_update(self, token_hash: str) -> RefreshToken | None:
        return next((t for t in self.tokens if t.token_hash == token_hash), None)

    async def revoke_family(self, family_id: uuid.UUID, *, now: datetime) -> None:
        for token in self.tokens:
            if token.family_id == family_id and token.revoked_at is None:
                token.revoked_at = now


class FakeTransaction:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeDocumentStore:
    """Mirrors the repository, including its per-user filtering and unique hash."""

    def __init__(self) -> None:
        self.documents: dict[uuid.UUID, Document] = {}

    async def add(self, document: Document) -> Document:
        if any(
            d.user_id == document.user_id and d.content_sha256 == document.content_sha256
            for d in self.documents.values()
        ):
            raise IntegrityError("insert", {}, Exception("uq_documents_user_id_content_sha256"))
        now = datetime.now(UTC)
        document.created_at = now
        document.updated_at = now
        self.documents[document.id] = document
        return document

    async def get(self, user_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
        document = self.documents.get(document_id)
        return document if document and document.user_id == user_id else None

    async def get_by_hash(self, user_id: uuid.UUID, content_sha256: str) -> Document | None:
        return next(
            (
                d
                for d in self.documents.values()
                if d.user_id == user_id and d.content_sha256 == content_sha256
            ),
            None,
        )

    async def list_for_user(self, user_id: uuid.UUID, *, limit: int, offset: int) -> list[Document]:
        mine = [d for d in self.documents.values() if d.user_id == user_id]
        mine.sort(key=lambda d: d.created_at, reverse=True)
        return mine[offset : offset + limit]

    async def count_for_user(self, user_id: uuid.UUID) -> int:
        return sum(1 for d in self.documents.values() if d.user_id == user_id)

    async def filenames(
        self, user_id: uuid.UUID, document_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        return {
            i: d.filename
            for i in document_ids
            if (d := self.documents.get(i)) is not None and d.user_id == user_id
        }

    async def delete(self, document: Document) -> None:
        del self.documents[document.id]


class FakeEmbedder:
    """Deterministic embeddings without a model: a hashed bag of words, L2-normalized.

    Texts that share words get a high cosine similarity, which is all the retrieval tests
    need ("password reset" is close to "how do I reset my password")."""

    def __init__(self, dimension: int = 384, model_id: str = "fake:bag-of-words:384") -> None:
        self.dimension = dimension
        self.model_id = model_id
        self.fail_with: Exception | None = None
        self.calls = 0

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.sha256(word.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dimension] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        if self.fail_with:
            raise self.fail_with
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.calls += 1
        if self.fail_with:
            raise self.fail_with
        return self._embed(text)


class FakeFileStorage:
    """Keeps files in a dict. ``resolve`` is not needed by the API, only by the worker."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.fail_delete = False

    async def save(
        self, *, user_id: uuid.UUID, document_id: uuid.UUID, extension: str, data: bytes
    ) -> str:
        path = f"{user_id}/{document_id}{extension}"
        self.files[path] = data
        return path

    async def delete(self, relative_path: str) -> None:
        if self.fail_delete:
            raise OSError("disk unavailable")
        self.files.pop(relative_path, None)

    def resolve(self, relative_path: str) -> Path:
        raise NotImplementedError


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []
        self.fail = False

    async def enqueue(self, document_id: uuid.UUID) -> None:
        if self.fail:
            raise ConnectionError("broker unavailable")
        self.enqueued.append(document_id)


class FakeIngestionStore:
    """The worker-side store, with the same claim/replace/fail rules as the SQL version."""

    def __init__(
        self, storage_path: str = "u/d.txt", status: DocumentStatus = DocumentStatus.PENDING
    ):
        self.document_id = uuid.uuid4()
        self.user_id = uuid.uuid4()
        self.storage_path = storage_path
        self.status = status
        self.error_message: str | None = None
        self.total_pages: int | None = None
        self.total_chunks: int | None = None
        self.chunks: list[Chunk] = []
        self.embeddings: list[list[float]] = []
        self.embedding_model: str | None = None
        self.exists = True
        self.fail_on_replace: Exception | None = None

    def claim(self, document_id: uuid.UUID) -> ClaimedDocument | None:
        claimable = {DocumentStatus.PENDING, DocumentStatus.FAILED, DocumentStatus.PROCESSING}
        if not self.exists or document_id != self.document_id or self.status not in claimable:
            return None
        self.status = DocumentStatus.PROCESSING
        self.error_message = None
        extension = "." + self.storage_path.rsplit(".", 1)[-1]
        return ClaimedDocument(self.document_id, self.user_id, self.storage_path, extension)

    def replace_chunks(
        self,
        document_id: uuid.UUID,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
        *,
        embedding_model: str,
        total_pages: int | None,
    ) -> bool:
        if not self.exists:
            return False
        if self.fail_on_replace:
            raise self.fail_on_replace  # the real transaction rolls back: nothing changes
        assert len(chunks) == len(embeddings)
        self.chunks = list(chunks)
        self.embeddings = [list(e) for e in embeddings]
        self.embedding_model = embedding_model
        self.status = DocumentStatus.READY
        self.total_pages = total_pages
        self.total_chunks = len(chunks)
        return True

    def mark_failed(self, document_id: uuid.UUID, message: str) -> None:
        if self.status == DocumentStatus.PROCESSING:
            self.status = DocumentStatus.FAILED
            self.error_message = message


class Clock:
    """A controllable clock: tests move time instead of sleeping.

    It starts at the real current time because JWT validation (done by PyJWT) always
    compares against the real clock."""

    def __init__(self) -> None:
        self.current = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.current


class FakeChatStore:
    """In-memory conversations, messages and citations (both store interfaces in one).

    Like the SQL repositories, every lookup is filtered by ``user_id``; deleting a
    conversation removes its messages (the database does it through ON DELETE CASCADE)."""

    def __init__(self) -> None:
        self.conversations: dict[uuid.UUID, Conversation] = {}
        self.messages: list[Message] = []
        self.sources: list[MessageSource] = []
        self._last_stamp = datetime.now(UTC)

    def _stamp(self, at: datetime | None = None) -> datetime:
        # Strictly increasing, so ordering never depends on the resolution of the OS clock.
        self._last_stamp = max(
            at or datetime.now(UTC), self._last_stamp + timedelta(microseconds=1)
        )
        return self._last_stamp

    # --- conversations ---

    async def add(self, conversation: Conversation) -> Conversation:
        conversation.id = conversation.id or uuid.uuid4()
        conversation.created_at = conversation.updated_at = self._stamp()
        self.conversations[conversation.id] = conversation
        return conversation

    async def get(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation | None:
        found = self.conversations.get(conversation_id)
        return found if found and found.user_id == user_id else None

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> list[Conversation]:
        mine = [c for c in self.conversations.values() if c.user_id == user_id]
        mine.sort(key=lambda c: c.updated_at, reverse=True)
        return mine[offset : offset + limit]

    async def count_for_user(self, user_id: uuid.UUID) -> int:
        return sum(1 for c in self.conversations.values() if c.user_id == user_id)

    async def touch(
        self, conversation: Conversation, *, at: datetime, title: str | None = None
    ) -> Conversation:
        if title is not None:
            conversation.title = title
        conversation.updated_at = self._stamp(at)
        return conversation

    async def delete(self, conversation: Conversation) -> None:
        del self.conversations[conversation.id]
        gone = {m.id for m in self.messages if m.conversation_id == conversation.id}
        self.messages = [m for m in self.messages if m.id not in gone]
        self.sources = [s for s in self.sources if s.message_id not in gone]

    # --- messages ---

    async def add_all(self, messages: Sequence[Message], sources: Sequence[MessageSource]) -> None:
        if any(m.conversation_id not in self.conversations for m in messages):
            raise IntegrityError("insert", {}, Exception("fk_messages_conversation_id"))
        self.messages.extend(messages)
        self.sources.extend(sources)

    def _in(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> list[Message]:
        found = [
            m
            for m in self.messages
            if m.user_id == user_id and m.conversation_id == conversation_id
        ]
        return sorted(found, key=lambda m: m.created_at)

    async def list_for_conversation(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, *, limit: int, offset: int
    ) -> list[Message]:
        return self._in(user_id, conversation_id)[offset : offset + limit]

    async def count_for_conversation(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> int:
        return len(self._in(user_id, conversation_id))

    async def recent(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, *, limit: int
    ) -> list[Message]:
        return self._in(user_id, conversation_id)[-limit:]

    async def sources_for(
        self, user_id: uuid.UUID, message_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[MessageSource]]:
        grouped: dict[uuid.UUID, list[MessageSource]] = {}
        for source in sorted(self.sources, key=lambda s: s.position):
            if source.user_id == user_id and source.message_id in message_ids:
                grouped.setdefault(source.message_id, []).append(source)
        return grouped


class FakeLLM:
    """Scripted language model: returns the queued reply (or raises it) and records the prompt."""

    model_id = "fake-llm"

    def __init__(self, *replies: str | Exception) -> None:
        self.replies: list[str | Exception] = list(replies)
        self.calls: list[list[ChatMessage]] = []
        # For streaming tests: raise this after the first piece was delivered.
        self.fail_after_first_piece: Exception | None = None
        # Called when the model is asked something (tests use it to look at the world then).
        self.on_call: Callable[[], None] | None = None

    def _next_reply(self, messages: Sequence[ChatMessage]) -> str:
        if self.on_call is not None:
            self.on_call()
        self.calls.append(list(messages))
        reply = self.replies.pop(0) if self.replies else "Fine. [1]"
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def complete(self, messages: Sequence[ChatMessage]) -> LLMResult:
        return LLMResult(text=self._next_reply(messages), prompt_tokens=10, completion_tokens=5)

    async def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        reply = self._next_reply(messages)
        for index, piece in enumerate(re.findall(r"\S+\s*", reply)):
            yield piece
            if index == 0 and self.fail_after_first_piece is not None:
                raise self.fail_after_first_piece


class FakeSettingsStore:
    """The per-user preferences, in memory (the upsert only touches the given fields)."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, UserPreferences] = {}

    async def get(self, user_id: uuid.UUID) -> UserPreferences | None:
        return self.rows.get(user_id)

    async def upsert(self, user_id: uuid.UUID, values: Mapping[str, Any]) -> UserPreferences:
        current = self.rows.get(user_id) or DEFAULT_PREFERENCES
        self.rows[user_id] = replace(current, **values)
        return self.rows[user_id]
