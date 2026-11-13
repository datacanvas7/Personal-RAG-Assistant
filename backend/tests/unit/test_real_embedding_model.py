"""The real BGE model, end to end through our provider.

Skipped when the optional ``local-embeddings`` extra is not installed (the CI backend job does
not install it; the Docker Compose smoke test covers the real model there). Locally the
first run downloads about 130 MB.
"""

import math

import pytest

pytest.importorskip("sentence_transformers")

from app.core.config import Settings  # noqa: E402
from app.embeddings.factory import build_embedding_provider  # noqa: E402


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_the_default_model_ranks_the_relevant_passage_first() -> None:
    provider = build_embedding_provider(Settings(postgres_password="x"))
    passages = [
        "Employees must change their password every ninety days.",
        "The cafeteria serves lunch between noon and two.",
        "Quarterly revenue grew by four percent.",
    ]

    documents = provider.embed_documents(passages)
    query = provider.embed_query("how often do I have to change my password?")

    scores = [_cosine(query, d) for d in documents]
    assert scores.index(max(scores)) == 0
    assert scores[0] - max(scores[1:]) > 0.2
    assert len(query) == provider.dimension == 384
    assert math.isclose(math.sqrt(sum(v * v for v in query)), 1.0, abs_tol=1e-4)
