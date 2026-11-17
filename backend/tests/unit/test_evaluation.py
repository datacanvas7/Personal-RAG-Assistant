"""The evaluation harness itself: metrics, the dataset's integrity and the report tables.

Whether a retrieval configuration is *good* is measured by running the harness against a
database (tests/integration/test_evaluation.py and docs/evaluation.md); here we check that the
yardstick is correct, because a wrong yardstick makes every comparison meaningless.
"""

import pytest

from app.evaluation.dataset import DOCUMENTS, QUESTIONS
from app.evaluation.metrics import (
    first_relevant_rank,
    mean_reciprocal_rank,
    recall_at,
    score,
)
from app.evaluation.report import category_table, comparison_table, misses
from app.evaluation.runner import (
    CachingEmbedder,
    EvaluationResult,
    QuestionResult,
    RetrievalConfig,
)
from tests.fakes import FakeEmbedder

# --- metrics -------------------------------------------------------------------------------


def test_recall_counts_questions_answered_within_k() -> None:
    ranks = [1, 2, 5, None]
    assert recall_at(ranks, 1) == 0.25
    assert recall_at(ranks, 2) == 0.5
    assert recall_at(ranks, 5) == 0.75
    assert recall_at(ranks, 10) == 0.75  # a miss never counts, however deep we look


def test_mrr_rewards_earlier_ranks_and_scores_misses_zero() -> None:
    assert mean_reciprocal_rank([1, 2, None, 4]) == pytest.approx((1 + 0.5 + 0 + 0.25) / 4)
    assert mean_reciprocal_rank([1, 1]) == 1.0
    assert mean_reciprocal_rank([None]) == 0.0


def test_no_questions_scores_zero_instead_of_dividing_by_zero() -> None:
    assert recall_at([], 3) == 0.0
    assert mean_reciprocal_rank([]) == 0.0
    assert score([]).questions == 0


def test_first_relevant_rank_ignores_case_and_spacing() -> None:
    contents = ["nothing here", "The pump  has LOST\npressure.", "pump has lost pressure"]
    assert first_relevant_rank(contents, "pump has lost pressure") == 2
    assert first_relevant_rank(contents, "absent phrase") is None
    assert first_relevant_rank([], "anything") is None


def test_score_bundles_the_headline_numbers() -> None:
    scores = score([1, 3, None, 2])
    assert scores.questions == 4
    assert scores.recall_at_1 == 0.25
    assert scores.recall_at_3 == 0.75
    assert scores.recall_at_5 == 0.75
    assert scores.mrr == pytest.approx((1 + 1 / 3 + 0 + 0.5) / 4)


# --- dataset integrity ---------------------------------------------------------------------


def _squash(text: str) -> str:
    return " ".join(text.casefold().split())


def test_every_question_is_answered_by_exactly_one_place_in_the_corpus() -> None:
    corpus = [_squash(page) for document in DOCUMENTS for page in document.pages]
    for question in QUESTIONS:
        occurrences = sum(page.count(_squash(question.marker)) for page in corpus)
        assert occurrences == 1, f"{question.text!r}: marker found {occurrences} times"


def test_questions_are_unique_and_cover_every_category() -> None:
    texts = [q.text for q in QUESTIONS]
    assert len(texts) == len(set(texts))
    assert {q.category for q in QUESTIONS} == {"paraphrase", "exact", "natural", "confusable"}


def test_document_names_are_unique_and_pages_are_not_blank() -> None:
    names = [d.filename for d in DOCUMENTS]
    assert len(names) == len(set(names))
    assert all(page.strip() for d in DOCUMENTS for page in d.pages)


# --- report --------------------------------------------------------------------------------


def _result(name: str, ranks: list[int | None]) -> EvaluationResult:
    questions = [QUESTIONS[i % len(QUESTIONS)] for i in range(len(ranks))]
    results = [QuestionResult(q, r) for q, r in zip(questions, ranks, strict=True)]
    return EvaluationResult(
        config=RetrievalConfig(name),
        chunks=7,
        overall=score(ranks),
        by_category={"natural": score(ranks)},
        results=results,
        median_search_ms=1.5,
    )


def test_comparison_table_marks_the_best_value_in_each_column() -> None:
    table = comparison_table([_result("weak", [3, None]), _result("strong", [1, 1])]).splitlines()
    weak, strong = table[2], table[3]
    assert weak.startswith("| weak | 7 | 0% | 50% | 50% | 0.167 |")
    assert "**100%**" in strong and "**1.000**" in strong
    assert "**" not in weak


def test_category_table_has_one_column_per_category() -> None:
    table = category_table([_result("only", [1, 2])])
    assert "natural (n=2)" in table.splitlines()[0]
    assert table.splitlines()[2].startswith("| only | 100% |")


def test_misses_lists_questions_not_in_the_top_three() -> None:
    lines = misses(_result("r", [1, 4, None]))
    assert len(lines) == 2
    assert lines[0].endswith("rank 4")
    assert lines[1].endswith("not retrieved")


# --- embedding cache -----------------------------------------------------------------------


def test_caching_embedder_embeds_each_text_once() -> None:
    inner = FakeEmbedder()
    cached = CachingEmbedder(inner)

    first = cached.embed_documents(["a b", "c d", "a b"])
    again = cached.embed_documents(["c d"])
    query = cached.embed_query("a b")
    cached.embed_query("a b")
    calls_made = inner.calls

    assert first[0] == first[2]
    assert again[0] == first[1]
    assert query == inner.embed_query("a b")
    # One call for the first batch (duplicates collapsed), none for the repeated text,
    # one for the query, none for the repeated query.
    assert calls_made == 2


def test_caching_embedder_exposes_the_model_identity() -> None:
    cached = CachingEmbedder(FakeEmbedder(dimension=16, model_id="fake:x:16"))
    assert (cached.model_id, cached.dimension) == ("fake:x:16", 16)
