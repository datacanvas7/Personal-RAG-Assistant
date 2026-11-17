"""Retrieval metrics.

Every evaluation question has exactly one answer-bearing fact, so for each question the only
thing that matters is the *rank* of the first relevant chunk (1 = best, ``None`` = not in
the returned list). All metrics follow from that:

* ``recall@k``  - share of questions whose answer is within the first k results. This is
  what the language model can use: if the fact is not in the passages it is given, the
  answer is lost no matter how good the model is.
* ``mrr``       - mean reciprocal rank: 1 for rank 1, 0.5 for rank 2, ... and 0 when missed.
  It also rewards putting the answer first, which matters when the context budget cuts the
  list short.
"""

from collections.abc import Sequence
from dataclasses import dataclass


def recall_at(ranks: Sequence[int | None], k: int) -> float:
    """Share of questions answered within the top ``k`` results (0.0 for no questions)."""
    if not ranks:
        return 0.0
    return sum(1 for rank in ranks if rank is not None and rank <= k) / len(ranks)


def mean_reciprocal_rank(ranks: Sequence[int | None]) -> float:
    if not ranks:
        return 0.0
    return sum(1.0 / rank for rank in ranks if rank is not None) / len(ranks)


def first_relevant_rank(contents: Sequence[str], marker: str) -> int | None:
    """1-based position of the first result containing ``marker`` (case and spacing ignored)."""
    wanted = _normalise(marker)
    for position, content in enumerate(contents, start=1):
        if wanted in _normalise(content):
            return position
    return None


def _normalise(text: str) -> str:
    return " ".join(text.casefold().split())


@dataclass(frozen=True)
class Scores:
    questions: int
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    mrr: float


def score(ranks: Sequence[int | None]) -> Scores:
    return Scores(
        questions=len(ranks),
        recall_at_1=recall_at(ranks, 1),
        recall_at_3=recall_at(ranks, 3),
        recall_at_5=recall_at(ranks, 5),
        mrr=mean_reciprocal_rank(ranks),
    )
