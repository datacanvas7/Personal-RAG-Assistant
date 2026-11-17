"""The real API on a real PostgreSQL, with deterministic stand-ins for the slow or paid parts.

Used by the browser (Playwright) tests: ``python -m tests.e2e_server``.

What is real: FastAPI app, routers, services, repositories, migrations, authentication,
file storage and the PostgreSQL/pgvector database.

What is replaced, so a test run needs no model download, API key or Redis/Celery:
* embeddings -> ``FakeEmbedder`` (hashed bag of words; shared words mean similar vectors),
* the language model -> ``ExtractiveLLM`` below (answers from the retrieved passages),
* the Celery queue -> a thread that runs the real ingestion pipeline in this process.

Never use this to serve real users: answers are not produced by a language model.
"""

import asyncio
import os
import re
import sys
import threading
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config
from fastapi import FastAPI

from app.api import deps
from app.core.config import get_settings
from app.db.session import get_sync_sessionmaker
from app.ingestion.pipeline import run_ingestion
from app.llm.base import ChatMessage, LLMResult
from app.rag.prompt_builder import CONDENSE_QUESTION_LABEL, CONDENSE_SYSTEM_PROMPT, NOT_FOUND_ANSWER
from app.repositories.documents import SqlIngestionStore
from app.services.storage import LocalFileStorage
from tests.fakes import FakeEmbedder

BACKEND_DIR = Path(__file__).resolve().parents[1]
PASSAGE = re.compile(r'<passage number="(\d+)"[^>]*>\n(.*?)\n</passage>', re.DOTALL)
QUESTION = re.compile(r"Question:\s*(.*)\s*$", re.DOTALL)

_EMBEDDER = FakeEmbedder()


class ExtractiveLLM:
    """Replies with the best passage it was given, cited as [1] (passages arrive ranked).

    Magic questions let tests exercise the error paths: a question containing ``/fail``
    makes generation fail after the first piece has been streamed.
    """

    model_id = "e2e-extractive"
    piece_delay_seconds = float(os.environ.get("E2E_PIECE_DELAY", "0.03"))

    def _reply(self, messages: Sequence[ChatMessage]) -> str:
        last = messages[-1].content
        if messages[0].content == CONDENSE_SYSTEM_PROMPT:
            # Query rewriting: a stand-in that returns the follow-up unchanged.
            return last.rsplit(CONDENSE_QUESTION_LABEL, 1)[1].strip()
        passages = PASSAGE.findall(last)
        if not passages:
            return NOT_FOUND_ANSWER
        number, text = passages[0]
        sentence = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
        return f"According to your documents: **{sentence}** [{number}]"

    def _check_failure(self, messages: Sequence[ChatMessage]) -> bool:
        match = QUESTION.search(messages[-1].content)
        return bool(match and "/fail" in match.group(1))

    async def complete(self, messages: Sequence[ChatMessage]) -> LLMResult:
        if self._check_failure(messages):
            raise RuntimeError("scripted failure")
        return LLMResult(text=self._reply(messages), prompt_tokens=1, completion_tokens=1)

    async def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        fail = self._check_failure(messages)
        for index, piece in enumerate(re.findall(r"\S+\s*", self._reply(messages))):
            yield piece
            await asyncio.sleep(self.piece_delay_seconds)
            if fail and index == 1:
                raise RuntimeError("scripted failure")


class ThreadQueue:
    """Runs the real ingestion pipeline on a background thread instead of Celery."""

    def __init__(self) -> None:
        self._delay = float(os.environ.get("E2E_INGEST_DELAY", "0.5"))

    async def enqueue(self, document_id: uuid.UUID) -> None:
        threading.Thread(target=self._run, args=(document_id,), daemon=True).start()

    def _run(self, document_id: uuid.UUID) -> None:
        time.sleep(self._delay)  # long enough for a test to see the "processing" state
        settings = get_settings()
        with get_sync_sessionmaker()() as session:
            run_ingestion(
                document_id,
                store=SqlIngestionStore(session),
                storage=LocalFileStorage(settings.upload_dir),
                embedder=_EMBEDDER,
                settings=settings,
            )


def build_app() -> FastAPI:
    # The startup check would otherwise load the real embedding model.
    import app.main as main

    main.get_embedding_provider = lambda: _EMBEDDER  # type: ignore[attr-defined,assignment]
    application = main.create_app()
    llm = ExtractiveLLM()
    queue = ThreadQueue()
    application.dependency_overrides[deps.get_llm] = lambda: llm
    application.dependency_overrides[deps.get_embedder] = lambda: _EMBEDDER
    application.dependency_overrides[deps.get_ingestion_queue] = lambda: queue
    return application


def main() -> None:
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
    port = int(os.environ.get("E2E_PORT", "8000"))
    config = uvicorn.Config(
        build_app(), host="127.0.0.1", port=port, log_level="warning", loop="none"
    )
    server = uvicorn.Server(config)
    if sys.platform == "win32":
        # psycopg's async mode cannot run on the default Proactor loop (local Windows only).
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    main()
