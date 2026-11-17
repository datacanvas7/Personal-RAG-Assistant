"""The RAG use case: retrieve the caller's passages, ask the model, resolve citations.

Two entry points share the same retrieval, prompt and citation logic: ``answer`` (one
response) and ``stream_answer`` (text pieces as the model produces them, then the final,
citation-checked answer).
"""

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from app.core.errors import ServiceUnavailableError
from app.llm.base import ChatMessage, LLMError, LLMProvider, LLMUnavailableError
from app.rag.citations import resolve_citations
from app.rag.prompt_builder import (
    NOT_FOUND_ANSWER,
    ContextPassage,
    build_condense_messages,
    build_messages,
    select_within_budget,
)
from app.schemas.search import SearchHit

logger = logging.getLogger(__name__)

_EXCERPT_CHARS = 300
# A rewritten question longer than this is not a question; the original is used instead.
_MAX_CONDENSED_CHARS = 500


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


@dataclass(frozen=True)
class TextPiece:
    """A fragment of the answer as it is being written. It is a preview: the final text
    (in ``StreamFinished``) can differ because invented citation markers are removed."""

    text: str


@dataclass(frozen=True)
class StreamFinished:
    answer: Answer


StreamEvent = TextPiece | StreamFinished


@dataclass(frozen=True)
class _Prepared:
    messages: list[ChatMessage]
    hits_by_number: dict[int, SearchHit]
    offered_numbers: set[int]


def _is_not_found(text: str) -> bool:
    return text.casefold().startswith(NOT_FOUND_ANSWER.casefold().rstrip("."))


_NOT_FOUND = Answer(NOT_FOUND_ANSWER, grounded=False, sources=[])


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
        condense_queries: bool = False,
        release_connection: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._searcher = searcher
        self._llm = llm
        self._top_k = top_k
        self._threshold = score_threshold
        self._max_context_chars = max_context_chars
        self._history_max = history_max_messages
        self._condense = condense_queries
        # Called once retrieval is done, before the (slow) model call, so the database
        # connection goes back to the pool instead of idling for the whole generation.
        self._release = release_connection

    async def _search_query(self, question: str, history: Sequence[ChatMessage]) -> str:
        """The text to search for: the question itself, or a standalone rewrite of a follow-up.

        "And what about the second one?" means nothing to a search engine. With history, the
        model first rewrites it using the conversation. This is an optimisation, never a
        requirement: any failure or odd answer falls back to the user's own words.
        """
        if not self._condense or not history or self._llm is None:
            return question
        try:
            result = await self._llm.complete(
                build_condense_messages(
                    question=question, history=history, history_max_messages=self._history_max
                )
            )
        except LLMError:
            logger.warning(
                "rewriting the follow-up question failed; using it as asked", exc_info=True
            )
            return question
        # Models sometimes wrap the answer in quotes or add a second line of commentary.
        lines = result.text.strip().splitlines()
        rewritten = lines[0].strip().strip("\"'").strip() if lines else ""
        if not rewritten or len(rewritten) > _MAX_CONDENSED_CHARS:
            return question
        return rewritten

    async def _prepare(
        self,
        *,
        user_id: uuid.UUID,
        question: str,
        history: Sequence[ChatMessage],
        document_ids: Sequence[uuid.UUID] | None,
        top_k: int | None,
    ) -> _Prepared | None:
        """Retrieve and build the prompt. ``None`` means nothing relevant was found."""
        hits = await self._searcher.search(
            user_id=user_id,
            query=await self._search_query(question, history),
            top_k=top_k or self._top_k,
            document_ids=document_ids,
        )
        if self._release is not None:
            await self._release()
        relevant = [hit for hit in hits if hit.score >= self._threshold]
        if not relevant:
            return None

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
        return _Prepared(messages, by_number, {p.number for p in passages})

    @staticmethod
    def _finish(raw_text: str, prepared: _Prepared) -> Answer:
        if _is_not_found(raw_text):
            return _NOT_FOUND
        text, cited = resolve_citations(raw_text, prepared.offered_numbers)
        by_number = prepared.hits_by_number
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

    @staticmethod
    def _unavailable(error: LLMError) -> ServiceUnavailableError:
        # The provider's own text stays in the server log; clients get a fixed message.
        if isinstance(error, LLMUnavailableError):
            logger.warning("language model temporarily unavailable", exc_info=True)
            return ServiceUnavailableError(
                "The language model is busy or unavailable. Try again shortly."
            )
        logger.exception("language model request failed")
        return ServiceUnavailableError("The language model could not answer right now.")

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

        prepared = await self._prepare(
            user_id=user_id,
            question=question,
            history=history,
            document_ids=document_ids,
            top_k=top_k,
        )
        if prepared is None:
            # Nothing to ground an answer on: do not ask the model (it would improvise).
            return _NOT_FOUND

        try:
            result = await self._llm.complete(prepared.messages)
        except LLMError as error:
            raise self._unavailable(error) from None
        return self._finish(result.text, prepared)

    async def stream_answer(
        self,
        *,
        user_id: uuid.UUID,
        question: str,
        history: Sequence[ChatMessage] = (),
        document_ids: Sequence[uuid.UUID] | None = None,
        top_k: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Yield ``TextPiece`` events, then exactly one ``StreamFinished``.

        When nothing relevant is found the model is not called: the not-found sentence is
        yielded as a single piece. Errors raise ``ServiceUnavailableError``, possibly after
        some pieces were yielded."""
        if self._llm is None:
            raise ServiceUnavailableError("The language model is not configured.")

        prepared = await self._prepare(
            user_id=user_id,
            question=question,
            history=history,
            document_ids=document_ids,
            top_k=top_k,
        )
        if prepared is None:
            yield TextPiece(NOT_FOUND_ANSWER)
            yield StreamFinished(_NOT_FOUND)
            return

        pieces: list[str] = []
        try:
            async for piece in self._llm.stream(prepared.messages):
                pieces.append(piece)
                yield TextPiece(piece)
        except LLMError as error:
            raise self._unavailable(error) from None
        yield StreamFinished(self._finish("".join(pieces).strip(), prepared))
