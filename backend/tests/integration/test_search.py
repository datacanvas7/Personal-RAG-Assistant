"""Vector search, the HNSW index, the startup guard and re-indexing, on a real PostgreSQL.

Embeddings come from ``FakeEmbedder`` (deterministic, no model download); what is tested
here is everything *around* the model: SQL, ownership filtering, index, guard, reindex.
"""

import asyncio
import uuid

import pytest
from alembic import command
from sqlalchemy import Connection, Engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.embeddings.guard import (
    EmbeddingConfigurationError,
    check_embedding_index,
    read_index_state,
)
from app.retrieval.vector_store import PgVectorStore
from app.scripts.reindex import mark_stale_documents
from tests.fakes import FakeEmbedder
from tests.integration.conftest import alembic_config, reset_schema
from tests.integration.test_documents_flow import Stack, _login, _upload, stack  # noqa: F401
from tests.samples import long_text

SEARCH = "/api/v1/search"
DIM = 384
HNSW_INDEX = "ix_document_chunks_embedding_hnsw"


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in values) + "]"


def _unit(axis: int, tilt: float = 0.0, tilt_axis: int = 1) -> list[float]:
    vector = [0.0] * DIM
    vector[axis] = 1.0
    vector[tilt_axis] = tilt
    return vector


def _seed_user(conn: Connection, email: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    conn.execute(
        text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'x')"),
        {"id": user_id, "email": email},
    )
    return user_id


def _seed_document(
    conn: Connection,
    user_id: uuid.UUID,
    *,
    status: str = "ready",
    model: str | None = None,
    filename: str = "doc.txt",
) -> uuid.UUID:
    document_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO documents (id, user_id, filename, content_type, size_bytes, "
            "storage_path, content_sha256, status, embedding_model) VALUES (:d, :u, :f, "
            "'text/plain', 1, :p, :h, :s, :m)"
        ),
        {
            "d": document_id,
            "u": user_id,
            "f": filename,
            "p": f"{document_id}.txt",
            "h": document_id.hex,
            "s": status,
            "m": model,
        },
    )
    return document_id


def _seed_chunks(
    conn: Connection, user_id: uuid.UUID, document_id: uuid.UUID, vectors: list[list[float] | None]
) -> None:
    for index, vector in enumerate(vectors):
        conn.execute(
            text(
                "INSERT INTO document_chunks (user_id, document_id, chunk_index, content, "
                "embedding) VALUES (:u, :d, :i, :c, CAST(:v AS vector))"
            ),
            {
                "u": user_id,
                "d": document_id,
                "i": index,
                "c": f"chunk {index}",
                "v": None if vector is None else _vector_literal(vector),
            },
        )


def _search(
    engine: Engine,
    user_id: uuid.UUID,
    query: list[float],
    *,
    top_k: int = 5,
    document_ids: list[uuid.UUID] | None = None,
    force_index: bool = False,
) -> list[str]:
    """Run PgVectorStore.search on its own async connection; returns chunk contents."""

    async def run() -> list[str]:
        async_engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with async_sessionmaker(async_engine)() as session:
                if force_index:
                    await session.execute(text("SET enable_seqscan = off"))
                hits = await PgVectorStore(session).search(
                    user_id, query, top_k=top_k, document_ids=document_ids
                )
                return [hit.content for hit in hits]
        finally:
            await async_engine.dispose()

    return asyncio.run(run())


# --- exit criterion: right chunks for the owner, nothing for anyone else ---------------------


async def test_search_finds_the_owners_chunks_and_nothing_for_another_user(stack: Stack) -> None:  # noqa: F811
    ada = await _login(stack.client, "ada@example.com")
    bob = await _login(stack.client, "bob@example.com")
    passwords = f"Passwords must be reset every ninety days. {long_text(1)}"
    lunch = "The cafeteria serves lunch between noon and two. " * 12
    await _upload(stack, ada, "security.txt", passwords.encode())
    await _upload(stack, ada, "canteen.txt", lunch.encode())
    await _upload(stack, bob, "bobs.txt", b"Bob keeps his own private notes about gardening. " * 12)

    as_ada = await stack.client.post(
        SEARCH, headers=ada, json={"query": "how often do I reset my password", "top_k": 5}
    )
    as_bob = await stack.client.post(
        SEARCH, headers=bob, json={"query": "how often do I reset my password"}
    )

    assert as_ada.status_code == 200
    results = as_ada.json()["results"]
    assert results[0]["filename"] == "security.txt"
    assert "reset every ninety days" in results[0]["content"]
    assert {r["filename"] for r in results} <= {"security.txt", "canteen.txt"}
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)
    # Bob only ever sees his own document, never ada's passwords chunk.
    assert all(r["filename"] == "bobs.txt" for r in as_bob.json()["results"])


async def test_search_can_be_limited_to_chosen_documents(stack: Stack) -> None:  # noqa: F811
    ada = await _login(stack.client, "ada@example.com")
    first = (await _upload(stack, ada, "a.txt", b"apples and oranges " * 30)).json()["id"]
    second = (await _upload(stack, ada, "b.txt", b"apples and pears " * 30)).json()["id"]

    response = await stack.client.post(
        SEARCH, headers=ada, json={"query": "apples", "top_k": 50, "document_ids": [second]}
    )

    assert {r["document_id"] for r in response.json()["results"]} == {second}
    assert first != second


async def test_a_deleted_document_disappears_from_search(stack: Stack) -> None:  # noqa: F811
    ada = await _login(stack.client, "ada@example.com")
    document_id = (await _upload(stack, ada, "a.txt", b"zebra crossing rules " * 30)).json()["id"]
    body = {"query": "zebra crossing"}
    assert (await stack.client.post(SEARCH, headers=ada, json=body)).json()["results"]

    await stack.client.delete(f"/api/v1/documents/{document_id}", headers=ada)

    assert (await stack.client.post(SEARCH, headers=ada, json=body)).json()["results"] == []


# --- the SQL itself ---------------------------------------------------------------------------


def test_results_are_ranked_by_cosine_similarity_and_limited_to_top_k(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as conn:
        user = _seed_user(conn, "ada@example.com")
        document = _seed_document(conn, user)
        # chunk 0 is the query itself, chunk 1 is close, chunk 2 is orthogonal.
        _seed_chunks(conn, user, document, [_unit(0), _unit(0, 0.3), _unit(2)])

    assert _search(migrated_engine, user, _unit(0), top_k=2) == ["chunk 0", "chunk 1"]


def test_chunks_without_a_vector_are_never_returned(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as conn:
        user = _seed_user(conn, "ada@example.com")
        document = _seed_document(conn, user)
        _seed_chunks(conn, user, document, [None, _unit(0)])

    assert _search(migrated_engine, user, _unit(0)) == ["chunk 1"]


def test_other_users_chunks_are_never_returned_even_when_they_are_the_closest(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as conn:
        ada, bob = _seed_user(conn, "ada@example.com"), _seed_user(conn, "bob@example.com")
        ada_doc, bob_doc = _seed_document(conn, ada), _seed_document(conn, bob)
        _seed_chunks(conn, bob, bob_doc, [_unit(0)])  # identical to the query
        _seed_chunks(conn, ada, ada_doc, [_unit(5)])  # unrelated

    assert _search(migrated_engine, ada, _unit(0)) == ["chunk 0"]  # ada's own, not bob's
    assert _search(migrated_engine, ada, _unit(0), document_ids=[bob_doc]) == []


def _pgvector_version(engine: Engine) -> tuple[int, ...]:
    with engine.connect() as conn:
        raw = conn.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
        return tuple(int(part) for part in raw.scalar_one().split("."))


def test_a_filtered_search_still_fills_top_k_when_other_users_dominate_the_index(
    migrated_engine: Engine,
) -> None:
    """Without iterative index scans the HNSW candidate list (40) would be all bob's."""
    if _pgvector_version(migrated_engine) < (0, 8, 0):
        pytest.skip("hnsw.iterative_scan needs pgvector >= 0.8 (CI and Docker have it)")
    with migrated_engine.begin() as conn:
        ada, bob = _seed_user(conn, "ada@example.com"), _seed_user(conn, "bob@example.com")
        ada_doc, bob_doc = _seed_document(conn, ada), _seed_document(conn, bob)
        # 300 chunks of bob's are all closer to the query than any of ada's 5.
        _seed_chunks(conn, bob, bob_doc, [_unit(0, 0.001 * i) for i in range(300)])
        _seed_chunks(conn, ada, ada_doc, [_unit(7, 0.01 * i) for i in range(5)])
        conn.execute(text("ANALYZE document_chunks"))

    found = _search(migrated_engine, ada, _unit(0), top_k=5, force_index=True)

    assert len(found) == 5


# --- the index --------------------------------------------------------------------------------


def test_the_hnsw_index_exists_and_serves_cosine_queries(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as conn:
        user = _seed_user(conn, "ada@example.com")
        document = _seed_document(conn, user)
        _seed_chunks(conn, user, document, [_unit(i) for i in range(20)])
        conn.execute(text("ANALYZE document_chunks"))
        conn.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            conn.execute(
                text(
                    "EXPLAIN SELECT id FROM document_chunks "
                    "ORDER BY embedding <=> CAST(:q AS vector) LIMIT 5"
                ),
                {"q": _vector_literal(_unit(0))},
            )
            .scalars()
            .all()
        )

    assert HNSW_INDEX in plan


# --- migration 0003 -----------------------------------------------------------------------------


def _index_exists(engine: Engine) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text("SELECT 1 FROM pg_indexes WHERE indexname = :n"), {"n": HNSW_INDEX}
            ).first()
        )


def _has_embedding_model_column(engine: Engine) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'documents' AND column_name = 'embedding_model'"
                )
            ).first()
        )


def test_migration_0003_adds_and_removes_the_index_and_model_column(engine: Engine) -> None:
    reset_schema(engine)
    command.upgrade(alembic_config(), "head")
    assert _index_exists(engine)
    assert _has_embedding_model_column(engine)

    command.downgrade(alembic_config(), "0002")
    assert not _index_exists(engine)
    assert not _has_embedding_model_column(engine)

    command.upgrade(alembic_config(), "head")
    assert _index_exists(engine)


# --- startup guard against the real schema ----------------------------------------------------


def test_guard_reads_the_real_column_dimension_and_accepts_a_matching_index(
    migrated_engine: Engine,
) -> None:
    embedder = FakeEmbedder()
    with migrated_engine.begin() as conn:
        user = _seed_user(conn, "ada@example.com")
        _seed_document(conn, user, model=embedder.model_id)

    with migrated_engine.connect() as conn:
        assert read_index_state(conn).column_dimension == DIM
    assert check_embedding_index(migrated_engine, embedder) == []


def test_guard_refuses_an_index_built_by_another_model(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as conn:
        user = _seed_user(conn, "ada@example.com")
        _seed_document(conn, user, model="openai:text-embedding-3-small:384")

    with pytest.raises(EmbeddingConfigurationError, match="reindex"):
        check_embedding_index(migrated_engine, FakeEmbedder())


def test_guard_ignores_documents_that_are_not_ready(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as conn:
        user = _seed_user(conn, "ada@example.com")
        _seed_document(conn, user, status="failed", model="some:other:384")

    assert check_embedding_index(migrated_engine, FakeEmbedder()) == []


# --- reindex ----------------------------------------------------------------------------------


def test_reindex_resets_only_stale_ready_documents_and_erases_their_vectors(
    migrated_engine: Engine,
) -> None:
    embedder = FakeEmbedder()
    with migrated_engine.begin() as conn:
        user = _seed_user(conn, "ada@example.com")
        stale = _seed_document(conn, user, model="old:model:384")
        legacy = _seed_document(conn, user, model=None)
        current = _seed_document(conn, user, model=embedder.model_id)
        pending = _seed_document(conn, user, status="pending")
        for document in (stale, legacy, current, pending):
            _seed_chunks(conn, user, document, [_unit(0), _unit(1)])

    reset = mark_stale_documents(migrated_engine, embedder)

    assert set(reset) == {stale, legacy}
    with migrated_engine.connect() as conn:
        statuses: dict[uuid.UUID, str] = dict(
            conn.execute(text("SELECT id, status FROM documents")).all()
        )
        vectors: dict[uuid.UUID, int] = dict(
            conn.execute(
                text(
                    "SELECT document_id, count(embedding) FROM document_chunks GROUP BY document_id"
                )
            ).all()
        )
    assert statuses[stale] == statuses[legacy] == "pending"
    assert statuses[current] == "ready"
    assert vectors[stale] == vectors[legacy] == 0
    assert vectors[current] == vectors[pending] == 2
    # Running it again finds nothing more to do.
    assert mark_stale_documents(migrated_engine, embedder) == []
