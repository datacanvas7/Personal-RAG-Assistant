"""Full-text search, metadata filters and hybrid retrieval on a real PostgreSQL.

Vectors are hand-made unit vectors, so which chunk is "close in meaning" is under the test's
control; what is tested here is the SQL: the generated tsvector, ranking, the ownership
filter, the metadata filters and the way fusion combines the two searches.
"""

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.retrieval.fusion import fuse_rrf
from app.retrieval.keyword_store import PgKeywordStore
from app.retrieval.vector_store import PgVectorStore, ScoredChunk
from tests.integration.test_search import (
    _seed_document,
    _seed_user,
    _unit,
    _vector_literal,
)


@dataclass
class Seeded:
    ada: uuid.UUID
    bob: uuid.UUID
    manual_pdf: uuid.UUID
    notes_txt: uuid.UUID
    bobs_doc: uuid.UUID


def _chunk(
    conn: Connection,
    user: uuid.UUID,
    document: uuid.UUID,
    index: int,
    content: str,
    *,
    page: int | None = None,
    vector: list[float] | None = None,
) -> None:
    conn.execute(
        text(
            "INSERT INTO document_chunks (user_id, document_id, chunk_index, content, "
            "page_number, embedding) VALUES (:u, :d, :i, :c, :p, CAST(:v AS vector))"
        ),
        {
            "u": user,
            "d": document,
            "i": index,
            "c": content,
            "p": page,
            "v": None if vector is None else _vector_literal(vector),
        },
    )


@pytest.fixture
def seeded(migrated_engine: Engine) -> Seeded:
    with migrated_engine.begin() as conn:
        ada = _seed_user(conn, "ada@example.com")
        bob = _seed_user(conn, "bob@example.com")
        manual = _seed_document(conn, ada, filename="manual.pdf")
        notes = _seed_document(conn, ada, filename="notes.txt")
        bobs = _seed_document(conn, bob, filename="bobs.txt")
        conn.execute(
            text("UPDATE documents SET content_type = 'application/pdf' WHERE id = :d"),
            {"d": manual},
        )
        run = conn
        _chunk(
            run,
            ada,
            manual,
            0,
            "Passwords must be changed every ninety days.",
            page=1,
            vector=_unit(0),
        )
        _chunk(
            run,
            ada,
            manual,
            1,
            "Error code E-4471 means the pump has lost pressure.",
            page=2,
            vector=_unit(2),
        )
        _chunk(
            run,
            ada,
            manual,
            2,
            "The cafeteria serves lunch between noon and two.",
            page=3,
            vector=_unit(4),
        )
        _chunk(run, ada, notes, 0, "Remember to rotate the passwords next week.", vector=_unit(3))
        _chunk(run, ada, notes, 1, "Not embedded yet but mentions pressure.", vector=None)
        _chunk(run, bob, bobs, 0, "Bob also writes about passwords and pressure.", vector=_unit(0))
    return Seeded(ada, bob, manual, notes, bobs)


def _keyword(
    user: uuid.UUID,
    query: str,
    *,
    vector: list[float] | None = None,
    limit: int = 10,
    **filters: object,
) -> list[ScoredChunk]:
    async def run() -> list[ScoredChunk]:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine)() as session:
                return await PgKeywordStore(session).search(
                    user,
                    query,
                    vector or _unit(5),
                    limit=limit,
                    **filters,  # type: ignore[arg-type]
                )
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _vector(
    user: uuid.UUID, query_vector: list[float], *, top_k: int = 10, **filters: object
) -> list[ScoredChunk]:
    async def run() -> list[ScoredChunk]:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine)() as session:
                return await PgVectorStore(session).search(
                    user,
                    query_vector,
                    top_k=top_k,
                    **filters,  # type: ignore[arg-type]
                )
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _contents(chunks: Sequence[ScoredChunk]) -> list[str]:
    return [c.content for c in chunks]


# --- keyword search ----------------------------------------------------------------------


def test_the_search_vector_is_filled_in_by_the_database(
    migrated_engine: Engine, seeded: Seeded
) -> None:
    with migrated_engine.connect() as conn:
        missing = conn.execute(
            text("SELECT count(*) FROM document_chunks WHERE search_vector IS NULL")
        ).scalar_one()
    assert missing == 0


def test_an_exact_code_is_found_even_though_it_means_nothing_to_the_vector(
    seeded: Seeded,
) -> None:
    found = _keyword(seeded.ada, "E-4471")
    assert _contents(found) == ["Error code E-4471 means the pump has lost pressure."]


def test_words_match_across_inflections(seeded: Seeded) -> None:
    found = _contents(_keyword(seeded.ada, "password rotation"))
    assert "Remember to rotate the passwords next week." in found
    assert "Passwords must be changed every ninety days." in found


def test_a_chunk_matches_when_only_some_of_the_words_are_present(seeded: Seeded) -> None:
    found = _contents(_keyword(seeded.ada, "how often must the pump pressure be changed"))
    assert "Error code E-4471 means the pump has lost pressure." in found


def test_chunks_with_more_of_the_words_rank_higher(seeded: Seeded) -> None:
    found = _contents(_keyword(seeded.ada, "pump pressure"))
    assert found[0] == "Error code E-4471 means the pump has lost pressure."
    assert found[-1] == "Not embedded yet but mentions pressure."


def test_the_score_is_the_cosine_similarity_and_zero_without_a_vector(seeded: Seeded) -> None:
    found = {c.content: c.score for c in _keyword(seeded.ada, "pressure", vector=_unit(2))}
    assert found["Error code E-4471 means the pump has lost pressure."] == pytest.approx(1.0)
    assert found["Not embedded yet but mentions pressure."] == 0.0


def test_another_users_chunks_are_never_returned(seeded: Seeded) -> None:
    assert all("Bob" not in c.content for c in _keyword(seeded.ada, "passwords pressure"))
    assert _contents(_keyword(seeded.bob, "passwords")) == [
        "Bob also writes about passwords and pressure."
    ]


def test_the_limit_is_respected(seeded: Seeded) -> None:
    assert len(_keyword(seeded.ada, "passwords pressure pump", limit=1)) == 1


@pytest.mark.parametrize(
    "query",
    [
        "the of and",  # only stop words: nothing to search for
        "???",
        '"unbalanced quote',
        "'; DROP TABLE document_chunks; --",
        "a & b | c ! (d <-> e)",
        "-",
        "x" * 2000,
    ],
)
def test_any_text_is_a_safe_query(seeded: Seeded, query: str) -> None:
    _keyword(seeded.ada, query)  # must not raise
    assert len(_keyword(seeded.ada, "pump")) == 1  # and the table is still there


# --- metadata filters ----------------------------------------------------------------------


def test_the_keyword_search_can_be_limited_to_chosen_documents(seeded: Seeded) -> None:
    found = _keyword(seeded.ada, "passwords", document_ids=[seeded.notes_txt])
    assert _contents(found) == ["Remember to rotate the passwords next week."]


def test_another_users_document_id_matches_nothing(seeded: Seeded) -> None:
    assert _keyword(seeded.ada, "passwords", document_ids=[seeded.bobs_doc]) == []
    assert _vector(seeded.ada, _unit(0), document_ids=[seeded.bobs_doc]) == []


@pytest.mark.parametrize("search", ["keyword", "vector"])
def test_a_page_range_keeps_only_chunks_inside_it(seeded: Seeded, search: str) -> None:
    def run(**filters: Any) -> list[str]:
        if search == "keyword":
            return _contents(_keyword(seeded.ada, "passwords pressure cafeteria", **filters))
        # Every vector the seed uses, one query per axis, so the page filter alone decides.
        return [
            c
            for axis in (0, 2, 3, 4)
            for c in _contents(_vector(seeded.ada, _unit(axis), **filters))
        ]

    assert set(run(page_from=2, page_to=2)) == (
        {"Error code E-4471 means the pump has lost pressure."}
    )
    assert "Passwords must be changed every ninety days." not in run(page_from=2)
    assert "The cafeteria serves lunch between noon and two." not in run(page_to=2)
    # Chunks without a page number (a TXT file) never match a page filter.
    assert "Remember to rotate the passwords next week." not in run(page_from=1)


def test_the_file_type_filter_keeps_only_those_documents(seeded: Seeded) -> None:
    by_words = _keyword(seeded.ada, "passwords", content_types=["application/pdf"])
    assert _contents(by_words) == ["Passwords must be changed every ninety days."]
    by_words = _keyword(seeded.ada, "passwords", content_types=["text/plain"])
    assert _contents(by_words) == ["Remember to rotate the passwords next week."]

    # The vector search ranks every chunk of the allowed documents, so compare the sets.
    # (notes.txt also has a chunk without a vector, which vector search cannot return.)
    pdf = _vector(seeded.ada, _unit(0), content_types=["application/pdf"])
    assert {c.page_number for c in pdf} == {1, 2, 3}
    plain = _vector(seeded.ada, _unit(3), content_types=["text/plain"])
    assert _contents(plain) == ["Remember to rotate the passwords next week."]


def test_a_file_type_nobody_has_matches_nothing(seeded: Seeded) -> None:
    assert _keyword(seeded.ada, "passwords", content_types=["application/zip"]) == []


# --- hybrid: the two searches complement each other -------------------------------------------


def test_fusion_returns_both_the_semantic_match_and_the_exact_term_match(seeded: Seeded) -> None:
    # The query vector points at the "passwords" chunk (axis 0) but the words are the error
    # code, which only keyword search can find.
    vector_hits = _vector(seeded.ada, _unit(0), top_k=1)
    keyword_hits = _keyword(seeded.ada, "E-4471", vector=_unit(0), limit=1)

    assert _contents(vector_hits) == ["Passwords must be changed every ninety days."]
    assert _contents(keyword_hits) == ["Error code E-4471 means the pump has lost pressure."]
    fused = _contents(fuse_rrf([vector_hits, keyword_hits]))
    assert set(fused) == set(_contents(vector_hits)) | set(_contents(keyword_hits))
