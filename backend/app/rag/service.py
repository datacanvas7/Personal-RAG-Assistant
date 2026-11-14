"""The RAG use case: retrieve the caller's passages, ask the model, resolve citations."""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.core.errors import ServiceUnavailableError
from app.llm.base import ChatMessage, LLMError, LLMProvider, LLMUnavailableError
from app.rag.citations import resolve_citations
from app.rag.prompt_builder import (
    NOT_FOUND_ANSWER,
    ContextPassage,
    build_messages,
    select_within_budget,
)
from app.schemas.search import SearchHit

logger = logging.getLogger(__name__)

_EXCERPT_CHARS = 300


class Searcher(Protocol):
    async def search(
        self,
        *,
        user_id: uuid.UUID,
        query: str,
        top_k: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[SearchHit]: ...


@dataclass(frozen=True)
class Source:
    number: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_number: int | None
    excerpt: str
    score: float


@dataclass(frozen=True)
class Answer:
    text: str
    # True only when the model answered and cited at least one retrieved passage.
    grounded: bool
    sources: list[Source]


def _is_not_found(text: str) -> bool:
    return text.casefold().startswith(NOT_FOUND_ANSWER.casefold().rstrip("."))


class RagService:
    def __init__(
        self,
        *,
        searcher: Searcher,
        llm: LLMProvider | None,
        top_k: int,
        score_threshold: float,
        max_context_chars: int,
        history_max_messages: int,
    ) -> None:
        self._searcher = searcher
        self._llm = llm
        self._top_k = top_k
        self._threshold = score_threshold
        self._max_context_chars = max_context_chars
        self._history_max = history_max_messages

    async def answer(
        self,
        *,
        user_id: uuid.UUID,
        question: str,
        history: Sequence[ChatMessage] = (),
        document_ids: Sequence[uuid.UUID] | None = None,
        top_k: int | None = None,
    ) -> Answer:
        if self._llm is None:
            raise ServiceUnavailableError("The language model is not configured.")

        hits = await self._searcher.search(
            user_id=user_id,
            query=question,
            top_k=top_k or self._top_k,
            document_ids=document_ids,
        )
        relevant = [hit for hit in hits if hit.score >= self._threshold]
        if not relevant:
            # Nothing to ground an answer on: do not ask the model (it would improvise).
            return Answer(NOT_FOUND_ANSWER, grounded=False, sources=[])

        by_number = dict(enumerate(relevant, start=1))
        passages = select_within_budget(
            [
                ContextPassage(number, hit.filename, hit.page_number, hit.content)
                for number, hit in by_number.items()
            ],
            self._max_context_chars,
        )
        messages = build_messages(
            question=question,
            passages=passages,
            history=history,
            history_max_messages=self._history_max,
        )

        try:
            result = await self._llm.complete(messages)
        except LLMUnavailableError:
            logger.warning("language model temporarily unavailable", exc_info=True)
            raise ServiceUnavailableError(
                "The language model is busy or unavailable. Try again shortly."
            ) from None
        except LLMError:
            logger.exception("language model request failed")
            raise ServiceUnavailableError(
                "The language model could not answer right now."
            ) from None

        if _is_not_found(result.text):
            return Answer(NOT_FOUND_ANSWER, grounded=False, sources=[])

        text, cited = resolve_citations(result.text, {p.number for p in passages})
        sources = [
            Source(
                number=n,
                chunk_id=by_number[n].chunk_id,
                document_id=by_number[n].document_id,
                filename=by_number[n].filename,
                page_number=by_number[n].page_number,
                excerpt=by_number[n].content[:_EXCERPT_CHARS],
                score=by_number[n].score,
            )
            for n in cited
        ]
        return Answer(text, grounded=bool(sources), sources=sources)
