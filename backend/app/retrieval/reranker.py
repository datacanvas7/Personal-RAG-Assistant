"""Reranking: a second, more careful look at the few candidates retrieval returned.

First-stage retrieval has to be fast over every chunk, so it compares the question and a
chunk only through one vector or a word index. A reranker looks at each (question, chunk)
pair directly, which is too slow for the whole collection but affordable for the top
dozens. The usual production choice is a cross-encoder model; ``Reranker`` is the seam where
one plugs in. ``LexicalReranker`` is the dependency-free implementation shipped here: it
needs no model download, runs in microseconds and its effect is measurable (see
``docs/evaluation.md``).
"""

import re
from collections.abc import Sequence
from typing import Protocol

from app.retrieval.vector_store import ScoredChunk

# Words that say little about what a passage is about. A short list on purpose: the aim is
# to stop "the", "of" and "how" from counting as evidence, not to be a linguistics package.
_STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "may",
        "might",
        "must",
        "of",
        "on",
        "or",
        "our",
        "shall",
        "should",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "often",
        "every",
        "each",
        "any",
        "all",
    ]
)
_WORD = re.compile(r"[a-z0-9]+")


def _terms(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(text.casefold()) if w not in _STOP_WORDS]


def _stem(word: str) -> str:
    """A crude suffix stripper, enough to match "passwords" with "password" and
    "changing" with "change"."""
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


class Reranker(Protocol):
    def rerank(self, query: str, chunks: Sequence[ScoredChunk]) -> list[ScoredChunk]:
        """The same chunks, best first. ``score`` (cosine similarity) is left unchanged."""
        ...


class LexicalReranker:
    """Orders candidates by cosine similarity plus how completely they cover the question.

    ``coverage`` is the share of the question's distinct content words that the chunk
    contains. A chunk that mentions *every* thing asked about beats one that is merely
    close in meaning, which is the failure mode of vector search on specific questions.
    """

    def __init__(self, *, coverage_weight: float = 0.25) -> None:
        self._weight = coverage_weight

    def rerank(self, query: str, chunks: Sequence[ScoredChunk]) -> list[ScoredChunk]:
        wanted = set(_terms(query))
        if not wanted:
            return list(chunks)

        def combined(chunk: ScoredChunk) -> float:
            present = len(wanted & set(_terms(chunk.content)))
            return (1 - self._weight) * chunk.score + self._weight * present / len(wanted)

        return sorted(chunks, key=lambda c: (-combined(c), -c.score, str(c.chunk_id)))
