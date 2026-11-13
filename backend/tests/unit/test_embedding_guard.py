"""The startup check that the configured embedding model matches the stored index."""

import pytest

from app.embeddings.guard import EmbeddingConfigurationError, IndexState, evaluate
from tests.fakes import FakeEmbedder

MODEL = "fake:bag-of-words:384"


def test_an_empty_database_is_fine() -> None:
    assert evaluate(IndexState(384, {}), FakeEmbedder()) == []


def test_documents_embedded_by_the_configured_model_are_fine() -> None:
    state = IndexState(384, {MODEL: 12})

    assert evaluate(state, FakeEmbedder()) == []


def test_a_different_column_dimension_refuses_to_start() -> None:
    with pytest.raises(EmbeddingConfigurationError, match=r"vector\(1536\)"):
        evaluate(IndexState(1536, {}), FakeEmbedder())


def test_documents_from_another_model_refuse_to_start_and_say_how_to_fix_it() -> None:
    state = IndexState(384, {"openai:text-embedding-3-small:384": 3, MODEL: 1})

    with pytest.raises(EmbeddingConfigurationError) as raised:
        evaluate(state, FakeEmbedder())

    message = str(raised.value)
    assert "openai:text-embedding-3-small:384 (3 documents)" in message
    assert "app.scripts.reindex" in message


def test_documents_without_vectors_only_warn() -> None:
    warnings = evaluate(IndexState(384, {None: 2}), FakeEmbedder())

    assert len(warnings) == 1
    assert "2 ready document(s)" in warnings[0]
    assert "app.scripts.reindex" in warnings[0]
