"""Markdown tables for evaluation results."""

from collections.abc import Sequence

from app.evaluation.runner import EvaluationResult


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def comparison_table(results: Sequence[EvaluationResult]) -> str:
    """One row per configuration; the best value in each metric column is bold."""
    columns = {
        "Recall@1": [r.overall.recall_at_1 for r in results],
        "Recall@3": [r.overall.recall_at_3 for r in results],
        "Recall@5": [r.overall.recall_at_5 for r in results],
        "MRR": [r.overall.mrr for r in results],
    }
    best = {name: max(values) for name, values in columns.items()}
    lines = [
        "| Configuration | Chunks | Recall@1 | Recall@3 | Recall@5 | MRR | Median search (ms) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for index, result in enumerate(results):
        cells = []
        for name, values in columns.items():
            text = f"{values[index]:.3f}" if name == "MRR" else _pct(values[index])
            cells.append(f"**{text}**" if values[index] == best[name] else text)
        lines.append(
            f"| {result.config.name} | {result.chunks} | {' | '.join(cells)} "
            f"| {result.median_search_ms:.1f} |"
        )
    return "\n".join(lines)


def category_table(results: Sequence[EvaluationResult]) -> str:
    """Recall@3 per question category, one column per category."""
    categories = sorted({c for r in results for c in r.by_category})
    counts = {
        c: next(r.by_category[c].questions for r in results if c in r.by_category)
        for c in categories
    }
    header = "| Configuration | " + " | ".join(f"{c} (n={counts[c]})" for c in categories) + " |"
    lines = [header, "|---|" + "---:|" * len(categories)]
    for result in results:
        cells = [
            _pct(result.by_category[c].recall_at_3) if c in result.by_category else "-"
            for c in categories
        ]
        lines.append(f"| {result.config.name} | {' | '.join(cells)} |")
    return "\n".join(lines)


def misses(result: EvaluationResult, *, limit: int = 10) -> list[str]:
    """The questions whose answer was not in the top 3, for the error analysis."""
    return [
        f"{r.question.text} -> rank {r.rank if r.rank is not None else 'not retrieved'}"
        for r in result.results
        if r.rank is None or r.rank > 3
    ][:limit]
