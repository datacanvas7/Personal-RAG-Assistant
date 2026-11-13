"""POST /search with the vector store replaced by an in-memory one.

The SQL itself (user filter, ordering, HNSW) is covered against PostgreSQL in
tests/integration/test_search.py; here we test validation, auth, wiring and error handling.
"""

import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

import httpx2
import pytest

from app.api.deps import get_auth_service, get_embedder, get_search_service
from app.core.config import Settings
from app.embeddings.base import EmbeddingUnavailableError
from app.main import create_app
from app.retrieval.service import SearchService
from app.retrieval.vector_store import ScoredChunk
from app.services.auth import AuthService
from tests.fakes import (
    FakeDocumentStore,
    FakeEmbedder,
    FakeTokenStore,
    FakeTransaction,
    FakeUserStore,
)

PASSWORD = "a-reasonable-passphrase"
URL = "/api/v1/search"


@dataclass
class StoredChunk:
    user_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    content: str
    vector: list[float]


@dataclass
class InMemoryVectorStore:
    """Same contract as PgVectorStore: filter by user (and documents), rank by cosine."""

    embedder: FakeEmbedder
    chunks: list[StoredChunk] = field(default_factory=list)

    def add(self, user_id: uuid.UUID, document_id: uuid.UUID, index: int, content: str) -> None:
        vector = self.embedder.embed_documents([content])[0]
        self.chunks.append(StoredChunk(user_id, document_id, index, content, vector))

    async def search(
        self,
        user_id: uuid.UUID,
        query_embedding: Sequence[float],
        *,
        top_k: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[ScoredChunk]:
        scored = [
            ScoredChunk(
                chunk_id=uuid.uuid4(),
                document_id=c.document_id,
                chunk_index=c.chunk_index,
                page_number=None,
                content=c.content,
                score=sum(a * b for a, b in zip(c.vector, query_embedding, strict=True)),
            )
            for c in self.chunks
            if c.user_id == user_id and (document_ids is None or c.document_id in document_ids)
        ]
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:top_k]


@dataclass
class Env:
    client: httpx2.AsyncClient
    users: FakeUserStore
    documents: FakeDocumentStore
    vectors: InMemoryVectorStore
    embedder: FakeEmbedder


@pytest.fixture
async def env() -> AsyncIterator[Env]:
    settings = Settings()
    users, tokens = FakeUserStore(), FakeTokenStore()
    documents, embedder = FakeDocumentStore(), FakeEmbedder()
    vectors = InMemoryVectorStore(embedder)
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        users=users, tokens=tokens, transaction=FakeTransaction(), settings=settings
    )
    app.dependency_overrides[get_embedder] = lambda: embedder
    app.dependency_overrides[get_search_service] = lambda: SearchService(
        embedder=embedder, vectors=vectors, documents=documents
    )
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Env(client, users, documents, vectors, embedder)


async def _login(env: Env, email: str) -> tuple[dict[str, str], uuid.UUID]:
    credentials = {"email": email, "password": PASSWORD}
    await env.client.post("/api/v1/auth/register", json=credentials)
    response = await env.client.post("/api/v1/auth/login", json=credentials)
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    user = await env.users.get_by_email(email)
    assert user is not None
    return headers, user.id


def _document(env: Env, user_id: uuid.UUID, filename: str, chunks: list[str]) -> uuid.UUID:
    from app.models import Document

    document_id = uuid.uuid4()
    env.documents.documents[document_id] = Document(
        id=document_id, user_id=user_id, filename=filename
    )
    for index, content in enumerate(chunks):
        env.vectors.add(user_id, document_id, index, content)
    return document_id


async def test_search_requires_authentication(env: Env) -> None:
    response = await env.client.post(URL, json={"query": "anything"})

    assert response.status_code == 401


async def test_search_returns_the_best_matching_chunks_first_with_filenames(env: Env) -> None:
    headers, user_id = await _login(env, "ada@example.com")
    handbook = _document(
        env,
        user_id,
        "handbook.txt",
        ["Passwords must be reset every ninety days.", "The cafeteria opens at eight."],
    )
    _document(env, user_id, "travel.txt", ["Flights are booked through the travel portal."])

    response = await env.client.post(
        URL, headers=headers, json={"query": "how do I reset my password", "top_k": 2}
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 2
    assert results[0]["content"] == "Passwords must be reset every ninety days."
    assert results[0]["document_id"] == str(handbook)
    assert results[0]["filename"] == "handbook.txt"
    assert results[0]["chunk_index"] == 0
    assert results[0]["score"] >= results[1]["score"]
    assert {"chunk_id", "page_number"} <= results[0].keys()


async def test_search_never_returns_another_users_chunks(env: Env) -> None:
    ada, ada_id = await _login(env, "ada@example.com")
    bob, _ = await _login(env, "bob@example.com")
    _document(env, ada_id, "secret.txt", ["The launch code is swordfish."])

    as_bob = await env.client.post(URL, headers=bob, json={"query": "launch code swordfish"})
    as_ada = await env.client.post(URL, headers=ada, json={"query": "launch code swordfish"})

    assert as_bob.status_code == 200
    assert as_bob.json()["results"] == []
    assert len(as_ada.json()["results"]) == 1


async def test_document_filter_ignores_documents_the_caller_does_not_own(env: Env) -> None:
    ada, ada_id = await _login(env, "ada@example.com")
    bob, bob_id = await _login(env, "bob@example.com")
    ada_doc = _document(env, ada_id, "a.txt", ["shared topic apples"])
    bob_doc = _document(env, bob_id, "b.txt", ["shared topic apples"])

    response = await env.client.post(
        URL,
        headers=ada,
        json={"query": "apples", "document_ids": [str(bob_doc), str(uuid.uuid4())]},
    )
    assert response.status_code == 200  # no 404: ids owned by others are not revealed
    assert response.json()["results"] == []

    response = await env.client.post(
        URL, headers=ada, json={"query": "apples", "document_ids": [str(ada_doc), str(bob_doc)]}
    )
    assert [r["document_id"] for r in response.json()["results"]] == [str(ada_doc)]


async def test_top_k_limits_the_number_of_results(env: Env) -> None:
    headers, user_id = await _login(env, "ada@example.com")
    _document(env, user_id, "a.txt", [f"note number {i} about cats" for i in range(10)])

    response = await env.client.post(URL, headers=headers, json={"query": "cats", "top_k": 3})

    assert len(response.json()["results"]) == 3


async def test_no_documents_is_an_empty_result_not_an_error(env: Env) -> None:
    headers, _ = await _login(env, "ada@example.com")

    response = await env.client.post(URL, headers=headers, json={"query": "anything"})

    assert response.status_code == 200
    assert response.json() == {"results": []}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"query": ""},
        {"query": "   "},
        {"query": "x" * 2001},
        {"query": "ok", "top_k": 0},
        {"query": "ok", "top_k": 51},
        {"query": "ok", "document_ids": ["not-a-uuid"]},
    ],
    ids=["missing", "empty", "blank", "too-long", "top_k-zero", "top_k-large", "bad-id"],
)
async def test_invalid_requests_are_rejected(env: Env, body: dict[str, object]) -> None:
    headers, _ = await _login(env, "ada@example.com")

    response = await env.client.post(URL, headers=headers, json=body)

    assert response.status_code == 422
    assert env.embedder.calls == 0  # rejected before any embedding work


async def test_an_embedding_outage_is_a_503_without_internals(env: Env) -> None:
    headers, _ = await _login(env, "ada@example.com")
    env.embedder.fail_with = EmbeddingUnavailableError("openai down at 10.0.0.5 key=sk-secret")

    response = await env.client.post(URL, headers=headers, json={"query": "hello"})

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "service_unavailable"
    assert "sk-secret" not in response.text
    assert "10.0.0.5" not in response.text
