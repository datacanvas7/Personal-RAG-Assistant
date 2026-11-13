"""In-memory stand-ins for the repositories, used by service and API unit tests.

They implement only what the service layer calls. Behavior that needs a real database
(row locking, constraints, cascades) is covered by tests/integration instead.
"""

import hashlib
import math
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.exc import IntegrityError

from app.ingestion.chunking import Chunk
from app.models import Document, DocumentStatus, RefreshToken, User
from app.repositories.documents import ClaimedDocument


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
