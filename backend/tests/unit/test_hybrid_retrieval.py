"""Reciprocal Rank Fusion, the lexical reranker and the SearchService retrieval modes."""

import uuid
from collections.abc import Sequence

import pytest

from app.retrieval.fusion import fuse_rrf
from app.retrieval.reranker import LexicalReranker
from app.retrieval.service import RetrievalMode, SearchService
from app.retrieval.vector_store import ScoredChunk
from tests.fakes import FakeEmbedder

USER = uuid.uuid4()
DOC = uuid.uuid4()


def chunk(label: str, score: float, content: str | None = None) -> ScoredChunk:
    # Deterministic id per label so the same "chunk" can appear in several rankings.
    return ScoredChunk(
        chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, label),
        document_id=DOC,
        chunk_index=0,
        page_number=None,
        content=content or label,
        score=score,
    )


def contents(chunks: Sequence[ScoredChunk]) -> list[str]:
    return [c.content for c in chunks]


# --- fusion ---------------------------------------------------------------------------


def test_a_chunk_ranked_well_by_both_lists_beats_one_ranked_first_by_only_one() -> None:
    vector = [chunk("a", 0.9), chunk("b", 0.8), chunk("c", 0.7)]
    keyword = [chunk("d", 0.1), chunk("b", 0.8), chunk("a", 0.9)]
    assert contents(fuse_rrf([vector, keyword]))[:2] == ["a", "b"]


def test_every_chunk_from_every_list_appears_once() -> None:
    fused = fuse_rrf([[chunk("a", 0.5), chunk("b", 0.4)], [chunk("b", 0.4), chunk("c", 0.3)]])
    assert sorted(contents(fused)) == ["a", "b", "c"]


def test_fusion_keeps_the_cosine_score_not_a_rank_score() -> None:
    fused = fuse_rrf([[chunk("a", 0.62)], [chunk("a", 0.62)]])
    assert fused[0].score == 0.62


def test_ties_are_broken_by_cosine_score() -> None:
    # Same position in different lists -> same RRF weight; the higher cosine wins.
    fused = fuse_rrf([[chunk("low", 0.2)], [chunk("high", 0.9)]])
    assert contents(fused) == ["high", "low"]


def test_fusing_nothing_gives_nothing() -> None:
    assert fuse_rrf([]) == []
    assert fuse_rrf([[], []]) == []


# --- reranker -------------------------------------------------------------------------


def test_reranker_prefers_the_chunk_that_covers_every_term_asked_about() -> None:
    close_in_meaning = chunk("generic", 0.60, "Staff should keep their credentials safe.")
    complete = chunk("exact", 0.55, "Passwords expire after ninety days and must be changed.")
    ranked = LexicalReranker().rerank(
        "How long until passwords expire?", [close_in_meaning, complete]
    )
    assert contents(ranked) == [complete.content, close_in_meaning.content]


def test_reranker_matches_simple_word_forms() -> None:
    plural = chunk("plural", 0.5, "Passwords are rotated.")
    unrelated = chunk("other", 0.5, "Lunch is served at noon.")
    ranked = LexicalReranker().rerank("password rotation", [unrelated, plural])
    assert contents(ranked)[0] == plural.content


def test_reranker_keeps_the_input_order_when_the_query_has_no_content_words() -> None:
    chunks = [chunk("a", 0.3), chunk("b", 0.9)]
    assert LexicalReranker().rerank("how is it?", chunks) == chunks


def test_reranker_does_not_change_scores() -> None:
    chunks = [chunk("a", 0.3, "alpha"), chunk("b", 0.9, "beta")]
    reranked = LexicalReranker().rerank("alpha", chunks)
    assert {c.chunk_id: c.score for c in reranked} == {c.chunk_id: c.score for c in chunks}


# --- SearchService modes --------------------------------------------------------------


class ListVectors:
    def __init__(self, chunks: list[ScoredChunk]) -> None:
        self.chunks = chunks
        self.limits: list[int] = []

    async def search(
        self, user_id: uuid.UUID, query_embedding: Sequence[float], *, top_k: int, **_: object
    ) -> list[ScoredChunk]:
        self.limits.append(top_k)
        return self.chunks[:top_k]


class ListKeywords:
    def __init__(self, chunks: list[ScoredChunk]) -> None:
        self.chunks = chunks
        self.queries: list[str] = []

    async def search(
        self,
        user_id: uuid.UUID,
        query: str,
        query_embedding: Sequence[float],
        *,
        limit: int,
        **_: object,
    ) -> list[ScoredChunk]:
        self.queries.append(query)
        return self.chunks[:limit]


class Names:
    async def filenames(
        self, user_id: uuid.UUID, document_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        return {doc_id: "doc.txt" for doc_id in document_ids}


def build(
    vector: list[ScoredChunk],
    keyword: list[ScoredChunk],
    *,
    mode: RetrievalMode,
    reranker: LexicalReranker | None = None,
    candidate_multiplier: int = 4,
) -> tuple[SearchService, ListVectors, ListKeywords]:
    vectors, keywords = ListVectors(vector), ListKeywords(keyword)
    service = SearchService(
        embedder=FakeEmbedder(),
        vectors=vectors,
        keywords=keywords,
        documents=Names(),
        reranker=reranker,
        mode=mode,
        candidate_multiplier=candidate_multiplier,
    )
    return service, vectors, keywords


async def run(service: SearchService, top_k: int = 3) -> list[str]:
    hits = await service.search(user_id=USER, query="alpha question", top_k=top_k)
    return [hit.content for hit in hits]


async def test_vector_mode_never_touches_the_keyword_store() -> None:
    service, _, keywords = build([chunk("v1", 0.9)], [chunk("k1", 0.1)], mode="vector")
    assert await run(service) == ["v1"]
    assert keywords.queries == []


async def test_keyword_mode_uses_only_the_keyword_ranking() -> None:
    service, vectors, _ = build([chunk("v1", 0.9)], [chunk("k1", 0.1)], mode="keyword")
    assert await run(service) == ["k1"]
    assert vectors.limits == []


async def test_hybrid_mode_surfaces_a_chunk_only_the_keyword_search_found() -> None:
    vector = [chunk("v1", 0.9), chunk("v2", 0.8)]
    keyword = [chunk("exact-code", 0.5), chunk("v2", 0.8)]
    service, _, _ = build(vector, keyword, mode="hybrid")
    assert "exact-code" in await run(service)


async def test_hybrid_asks_each_search_for_a_wider_pool_but_returns_only_top_k() -> None:
    many = [chunk(f"c{i}", 0.9 - i / 100) for i in range(30)]
    service, vectors, _ = build(many, many, mode="hybrid", candidate_multiplier=4)
    assert len(await run(service, top_k=3)) == 3
    assert vectors.limits == [12]


async def test_the_reranker_runs_after_fusion_on_the_wider_pool() -> None:
    vector = [chunk("plain", 0.9, "nothing relevant"), chunk("match", 0.8, "alpha question")]
    service, vectors, _ = build(vector, [], mode="vector", reranker=LexicalReranker())
    assert await run(service, top_k=1) == ["alpha question"]
    assert vectors.limits == [4]


async def test_vector_mode_without_reranking_asks_for_exactly_top_k() -> None:
    service, vectors, _ = build([chunk("v1", 0.9)], [], mode="vector")
    await run(service, top_k=3)
    assert vectors.limits == [3]


def test_a_mode_that_needs_keywords_requires_a_keyword_store() -> None:
    with pytest.raises(ValueError, match="keyword store"):
        SearchService(
            embedder=FakeEmbedder(), vectors=ListVectors([]), documents=Names(), mode="hybrid"
        )
