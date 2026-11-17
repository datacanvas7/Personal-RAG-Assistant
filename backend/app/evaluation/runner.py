"""Run one retrieval configuration over the evaluation set and score it.

The run uses the real pieces, not stand-ins: the corpus is chunked by the production chunker,
embedded by the configured embedding provider, stored in PostgreSQL (pgvector + full-text
index) and searched through ``SearchService``, exactly as the API does. Each run seeds its own
temporary user and removes it afterwards, so it can be pointed at a development database.
"""

import asyncio
import statistics
import sys
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import URL, create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.embeddings.base import EmbeddingProvider
from app.evaluation.dataset import DOCUMENTS, QUESTIONS, EvalDocument, EvalQuestion
from app.evaluation.metrics import Scores, first_relevant_rank, score
from app.ingestion.chunking import chunk_pages
from app.ingestion.loaders import PageText
from app.repositories.documents import DocumentRepository
from app.retrieval.keyword_store import PgKeywordStore
from app.retrieval.reranker import LexicalReranker
from app.retrieval.service import RetrievalMode, SearchService
from app.retrieval.vector_store import PgVectorStore

# How many results every configuration returns; recall@1/3/5 and MRR are read from them.
DEPTH = 10


@dataclass(frozen=True)
class RetrievalConfig:
    name: str
    mode: RetrievalMode = "hybrid"
    rerank: bool = True
    chunk_size: int = 1500
    chunk_overlap: int = 200
    candidate_multiplier: int = 4
    coverage_weight: float = 0.25


@dataclass(frozen=True)
class QuestionResult:
    question: EvalQuestion
    rank: int | None  # position of the first relevant chunk, None if not retrieved


@dataclass(frozen=True)
class EvaluationResult:
    config: RetrievalConfig
    chunks: int
    overall: Scores
    by_category: dict[str, Scores]
    results: list[QuestionResult] = field(repr=False)
    median_search_ms: float


class CachingEmbedder:
    """Remembers vectors so that comparing many configurations embeds each text once."""

    def __init__(self, inner: EmbeddingProvider) -> None:
        self._inner = inner
        self._documents: dict[str, list[float]] = {}
        self._queries: dict[str, list[float]] = {}

    @property
    def model_id(self) -> str:
        return self._inner.model_id

    @property
    def dimension(self) -> int:
        return self._inner.dimension

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        missing = [t for t in dict.fromkeys(texts) if t not in self._documents]
        if missing:
            for text_, vector in zip(missing, self._inner.embed_documents(missing), strict=True):
                self._documents[text_] = vector
        return [self._documents[t] for t in texts]

    def embed_query(self, text: str) -> list[float]:
        if text not in self._queries:
            self._queries[text] = self._inner.embed_query(text)
        return self._queries[text]


def _vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in values) + "]"


def _seed(
    database_url: str | URL,
    embedder: EmbeddingProvider,
    documents: Sequence[EvalDocument],
    config: RetrievalConfig,
) -> tuple[uuid.UUID, int]:
    """Create a temporary user owning the chunked, embedded corpus. Returns (user, #chunks)."""
    user_id = uuid.uuid4()
    engine = create_engine(database_url)
    total = 0
    try:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'x')"),
                {"id": user_id, "email": f"evaluation-{user_id.hex}@example.invalid"},
            )
            for document in documents:
                is_pdf = document.filename.endswith(".pdf")
                pages = [
                    PageText(page_number=number if is_pdf else None, text=body)
                    for number, body in enumerate(document.pages, start=1)
                ]
                chunks = chunk_pages(pages, size=config.chunk_size, overlap=config.chunk_overlap)
                vectors = embedder.embed_documents([c.content for c in chunks])
                document_id = uuid.uuid4()
                conn.execute(
                    text(
                        "INSERT INTO documents (id, user_id, filename, content_type, "
                        "size_bytes, storage_path, content_sha256, status, embedding_model) "
                        "VALUES (:d, :u, :f, :t, 1, :p, :h, 'ready', :m)"
                    ),
                    {
                        "d": document_id,
                        "u": user_id,
                        "f": document.filename,
                        "t": "application/pdf" if is_pdf else "text/plain",
                        "p": f"evaluation/{document_id}",
                        "h": document_id.hex,
                        "m": embedder.model_id,
                    },
                )
                for chunk, vector in zip(chunks, vectors, strict=True):
                    conn.execute(
                        text(
                            "INSERT INTO document_chunks (user_id, document_id, chunk_index, "
                            "content, page_number, embedding) "
                            "VALUES (:u, :d, :i, :c, :p, CAST(:v AS vector))"
                        ),
                        {
                            "u": user_id,
                            "d": document_id,
                            "i": chunk.index,
                            "c": chunk.content,
                            "p": chunk.page_number,
                            "v": _vector_literal(vector),
                        },
                    )
                total += len(chunks)
    finally:
        engine.dispose()
    return user_id, total


def _remove(database_url: str | URL, user_id: uuid.UUID) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            # Documents and chunks go with the user (ON DELETE CASCADE).
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
    finally:
        engine.dispose()


async def _search_all(
    database_url: str | URL,
    embedder: EmbeddingProvider,
    config: RetrievalConfig,
    user_id: uuid.UUID,
    questions: Sequence[EvalQuestion],
) -> tuple[list[QuestionResult], list[float]]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    results: list[QuestionResult] = []
    timings: list[float] = []
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            service = SearchService(
                embedder=embedder,
                vectors=PgVectorStore(session),
                keywords=PgKeywordStore(session),
                documents=DocumentRepository(session),
                reranker=LexicalReranker(coverage_weight=config.coverage_weight)
                if config.rerank
                else None,
                mode=config.mode,
                candidate_multiplier=config.candidate_multiplier,
            )
            for question in questions:
                embedder.embed_query(question.text)  # warm the cache: time the search only
                started = time.perf_counter()
                hits = await service.search(user_id=user_id, query=question.text, top_k=DEPTH)
                timings.append((time.perf_counter() - started) * 1000)
                rank = first_relevant_rank([h.content for h in hits], question.marker)
                results.append(QuestionResult(question, rank))
    finally:
        await engine.dispose()
    return results, timings


def evaluate(
    config: RetrievalConfig,
    *,
    database_url: str | URL,
    embedder: EmbeddingProvider,
    documents: Sequence[EvalDocument] = DOCUMENTS,
    questions: Sequence[EvalQuestion] = QUESTIONS,
) -> EvaluationResult:
    user_id, chunk_count = _seed(database_url, embedder, documents, config)
    try:
        # psycopg's async mode cannot use Windows' default (Proactor) event loop.
        results, timings = asyncio.run(
            _search_all(database_url, embedder, config, user_id, questions),
            loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None,
        )
    finally:
        _remove(database_url, user_id)

    categories = sorted({r.question.category for r in results})
    return EvaluationResult(
        config=config,
        chunks=chunk_count,
        overall=score([r.rank for r in results]),
        by_category={
            category: score([r.rank for r in results if r.question.category == category])
            for category in categories
        },
        results=results,
        median_search_ms=statistics.median(timings) if timings else 0.0,
    )
