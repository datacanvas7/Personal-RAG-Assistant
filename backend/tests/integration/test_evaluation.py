"""The evaluation runner against a real PostgreSQL, with a fake embedder.

A bag-of-words embedder cannot say anything about retrieval *quality* (docs/evaluation.md
does that with the real model); this checks the machinery: it seeds, searches in every mode,
scores, and leaves nothing behind.
"""

import pytest
from sqlalchemy import Engine, text

from app.core.config import get_settings
from app.evaluation.runner import CachingEmbedder, RetrievalConfig, evaluate
from tests.fakes import FakeEmbedder


@pytest.mark.parametrize(
    "config",
    [
        RetrievalConfig("vector", mode="vector", rerank=False),
        RetrievalConfig("keyword", mode="keyword", rerank=False),
        RetrievalConfig("hybrid", mode="hybrid", rerank=False),
        RetrievalConfig("hybrid+rerank", mode="hybrid", rerank=True),
        RetrievalConfig("small chunks", chunk_size=300, chunk_overlap=50),
    ],
    ids=lambda config: config.name,
)
def test_every_configuration_runs_and_scores(
    migrated_engine: Engine, config: RetrievalConfig
) -> None:
    result = evaluate(
        config,
        database_url=get_settings().database_url,
        embedder=CachingEmbedder(FakeEmbedder()),
    )

    assert result.chunks > 0
    assert result.overall.questions == len(result.results) > 0
    assert 0.0 <= result.overall.recall_at_1 <= result.overall.recall_at_5 <= 1.0
    # Questions that reuse the document's own words are found by word matching alone, so even
    # a toy embedder must get most of the natural-language ones right once keywords help.
    if config.mode != "vector":
        assert result.by_category["natural"].recall_at_5 >= 0.8
    assert result.median_search_ms >= 0


def test_smaller_chunks_make_more_chunks(migrated_engine: Engine) -> None:
    embedder = CachingEmbedder(FakeEmbedder())
    url = get_settings().database_url

    big = evaluate(
        RetrievalConfig("big", chunk_size=2500, chunk_overlap=300),
        database_url=url,
        embedder=embedder,
    )
    small = evaluate(
        RetrievalConfig("small", chunk_size=300, chunk_overlap=50),
        database_url=url,
        embedder=embedder,
    )

    assert small.chunks > big.chunks


def test_a_run_leaves_no_data_behind(migrated_engine: Engine) -> None:
    evaluate(
        RetrievalConfig("cleanup"),
        database_url=get_settings().database_url,
        embedder=CachingEmbedder(FakeEmbedder()),
    )

    with migrated_engine.connect() as conn:
        counts = [
            conn.execute(text("SELECT count(*) FROM users")).scalar_one(),
            conn.execute(text("SELECT count(*) FROM documents")).scalar_one(),
            conn.execute(text("SELECT count(*) FROM document_chunks")).scalar_one(),
        ]
    assert counts == [0, 0, 0]
