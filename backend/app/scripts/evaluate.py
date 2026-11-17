"""Compare retrieval configurations on the built-in evaluation set.

    python -m app.scripts.evaluate                 # retrieval modes + chunking variants
    python -m app.scripts.evaluate --only modes    # just vector / keyword / hybrid / rerank

It needs a migrated PostgreSQL (the one in ``POSTGRES_*``) and the configured embedding
model. Every run creates a temporary user and deletes it again; no other data is touched.
Results are printed as Markdown: paste them into docs/evaluation.md.
"""

import argparse
import sys

from app.core.config import get_settings
from app.embeddings.factory import get_embedding_provider
from app.evaluation.report import category_table, comparison_table, misses
from app.evaluation.runner import CachingEmbedder, EvaluationResult, RetrievalConfig, evaluate

MODES = [
    RetrievalConfig("vector only", mode="vector", rerank=False),
    RetrievalConfig("keyword only", mode="keyword", rerank=False),
    RetrievalConfig("vector + rerank", mode="vector", rerank=True),
    RetrievalConfig("hybrid (RRF)", mode="hybrid", rerank=False),
    RetrievalConfig("hybrid + rerank", mode="hybrid", rerank=True),
]

CHUNKING = [
    RetrievalConfig(f"hybrid + rerank, {size}/{overlap}", chunk_size=size, chunk_overlap=overlap)
    for size, overlap in ((300, 50), (600, 100), (1000, 150), (1500, 200), (2500, 300))
]


RERANK_WEIGHTS = [
    RetrievalConfig(f"hybrid + rerank, weight {weight}", coverage_weight=weight)
    for weight in (0.1, 0.25, 0.5, 0.75)
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--only", choices=["modes", "chunking", "reranker"], help="run one comparison only"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    embedder = CachingEmbedder(get_embedding_provider())
    print(f"Embedding model: {embedder.model_id}\n")

    groups: list[tuple[str, list[RetrievalConfig]]] = []
    if args.only in (None, "modes"):
        groups.append(("Retrieval modes (chunks of 1500 characters, overlap 200)", MODES))
    if args.only in (None, "reranker"):
        groups.append(("Reranker weight (hybrid + rerank)", RERANK_WEIGHTS))
    if args.only in (None, "chunking"):
        groups.append(("Chunking (hybrid + rerank)", CHUNKING))

    for title, configs in groups:
        results: list[EvaluationResult] = [
            evaluate(config, database_url=settings.database_url, embedder=embedder)
            for config in configs
        ]
        print(f"### {title}\n")
        print(comparison_table(results))
        print("\nRecall@3 by question type:\n")
        print(category_table(results))
        for result in results:
            missed = misses(result)
            if missed:
                print(f"\nNot in the top 3 for `{result.config.name}`:")
                for line in missed:
                    print(f"- {line}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
