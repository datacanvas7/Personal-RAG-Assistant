"""Document upload and ingestion against a real database and a real file system.

The queue is replaced by one that runs the ingestion job inline (same code the Celery task
runs), so the whole path - upload, storage, parsing, chunking, atomic write - is exercised
without a broker.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx2
import pytest
from alembic import command
from fastapi import FastAPI
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.api.deps import get_embedder, get_file_storage, get_ingestion_queue
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.ingestion.chunking import Chunk
from app.ingestion.pipeline import IngestionOutcome, run_ingestion
from app.main import create_app
from app.repositories.documents import SqlIngestionStore
from app.services.storage import LocalFileStorage
from tests.fakes import FakeEmbedder
from tests.integration.conftest import alembic_config, reset_schema
from tests.samples import long_text, make_docx, make_pdf

PASSWORD = "a-reasonable-passphrase"
BASE = "/api/v1/documents"
SETTINGS = Settings(chunk_size_chars=400, chunk_overlap_chars=60)
MODEL = FakeEmbedder().model_id


def _vectors(count: int) -> list[list[float]]:
    return [[1.0] + [0.0] * 383 for _ in range(count)]


class InlineQueue:
    """Runs the ingestion job immediately, the way the Celery task would later."""

    def __init__(self, engine: Engine, storage: LocalFileStorage) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._storage = storage
        self.fail = False

    async def enqueue(self, document_id: uuid.UUID) -> None:
        if self.fail:
            raise ConnectionError("broker unavailable")
        await asyncio.to_thread(self.run, document_id)

    def run(self, document_id: uuid.UUID) -> IngestionOutcome:
        with self._sessions() as session:
            return run_ingestion(
                document_id,
                store=SqlIngestionStore(session),
                storage=self._storage,
                embedder=FakeEmbedder(),
                settings=SETTINGS,
            )


@dataclass
class Stack:
    client: httpx2.AsyncClient
    engine: Engine
    storage: LocalFileStorage
    queue: InlineQueue
    root: Path


@pytest.fixture
async def stack(migrated_engine: Engine, tmp_path: Path) -> AsyncIterator[Stack]:
    async_engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    sessions = async_sessionmaker(async_engine, expire_on_commit=False)
    storage = LocalFileStorage(tmp_path)
    queue = InlineQueue(migrated_engine, storage)

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app: FastAPI = create_app()
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_file_storage] = lambda: storage
    app.dependency_overrides[get_ingestion_queue] = lambda: queue
    app.dependency_overrides[get_embedder] = FakeEmbedder  # same model as the inline worker
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Stack(client, migrated_engine, storage, queue, tmp_path)
    await async_engine.dispose()


async def _login(client: httpx2.AsyncClient, email: str) -> dict[str, str]:
    credentials = {"email": email, "password": PASSWORD}
    await client.post("/api/v1/auth/register", json=credentials)
    response = await client.post("/api/v1/auth/login", json=credentials)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _upload(stack: Stack, headers: dict[str, str], name: str, data: bytes) -> httpx2.Response:
    return await stack.client.post(f"{BASE}/upload", headers=headers, files={"file": (name, data)})


def _chunks(engine: Engine, document_id: str) -> list[tuple[int, int | None, str]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT chunk_index, page_number, content FROM document_chunks "
                "WHERE document_id = :id ORDER BY chunk_index"
            ),
            {"id": document_id},
        ).all()
    return [(r.chunk_index, r.page_number, r.content) for r in rows]


def _status(engine: Engine, document_id: str) -> tuple[str, str | None, int | None, int | None]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT status, error_message, total_pages, total_chunks "
                "FROM documents WHERE id = :id"
            ),
            {"id": document_id},
        ).one()
    return row.status, row.error_message, row.total_pages, row.total_chunks


async def _api_status(stack: Stack, headers: dict[str, str], document_id: str) -> dict[str, object]:
    response = await stack.client.get(f"{BASE}/{document_id}/status", headers=headers)
    assert response.status_code == 200
    body: dict[str, object] = response.json()
    return body


# --- exit criterion: each file type yields correct chunks with page numbers ---------------


async def test_pdf_upload_yields_chunks_with_correct_page_numbers(stack: Stack) -> None:
    headers = await _login(stack.client, "ada@example.com")
    pages = [f"First page. {long_text(8)}", f"Second page. {long_text(8)}", "Third page."]

    response = await _upload(stack, headers, "report.pdf", make_pdf(pages))

    assert response.status_code == 202
    document_id = response.json()["id"]
    state = await _api_status(stack, headers, document_id)
    assert state["status"] == "ready"
    assert state["total_pages"] == 3
    rows = _chunks(stack.engine, document_id)
    assert state["total_chunks"] == len(rows)
    assert [r[0] for r in rows] == list(range(len(rows)))
    assert {r[1] for r in rows} == {1, 2, 3}
    for _, page, content in rows:
        for number, word in ((1, "First"), (2, "Second"), (3, "Third")):
            if f"{word} page." in content:
                assert page == number
    assert [r[1] for r in rows] == sorted(r[1] for r in rows if r[1] is not None)


async def test_docx_upload_yields_chunks_without_page_numbers(stack: Stack) -> None:
    headers = await _login(stack.client, "ada@example.com")
    data = make_docx([long_text(12)], table=[["Name", "Role"], ["Ada", "Engineer"]])

    document_id = (await _upload(stack, headers, "cv.docx", data)).json()["id"]

    assert (await _api_status(stack, headers, document_id))["status"] == "ready"
    rows = _chunks(stack.engine, document_id)
    assert len(rows) > 1
    assert all(page is None for _, page, _ in rows)
    assert "Ada | Engineer" in " ".join(content for *_, content in rows)


@pytest.mark.parametrize("name", ["notes.txt", "readme.md"])
async def test_text_and_markdown_uploads_yield_chunks(stack: Stack, name: str) -> None:
    headers = await _login(stack.client, "ada@example.com")

    document_id = (
        await _upload(stack, headers, name, ("# Heading\n\n" + long_text(30)).encode())
    ).json()["id"]

    assert (await _api_status(stack, headers, document_id))["status"] == "ready"
    assert len(_chunks(stack.engine, document_id)) > 1


# --- exit criterion: failed or repeated jobs leave no partial or duplicate chunks ---------


async def test_scanned_pdf_fails_with_a_message_and_no_chunks(stack: Stack) -> None:
    headers = await _login(stack.client, "ada@example.com")

    document_id = (await _upload(stack, headers, "scan.pdf", make_pdf(["", ""]))).json()["id"]

    state = await _api_status(stack, headers, document_id)
    assert state["status"] == "failed"
    assert "OCR" in str(state["error_message"])
    assert _chunks(stack.engine, document_id) == []


async def test_running_the_job_again_never_duplicates_chunks(stack: Stack) -> None:
    headers = await _login(stack.client, "ada@example.com")
    document_id = (await _upload(stack, headers, "a.txt", long_text(30).encode())).json()["id"]
    before = _chunks(stack.engine, document_id)

    # A duplicate delivery of an already finished job.
    assert stack.queue.run(uuid.UUID(document_id)) is IngestionOutcome.SKIPPED
    assert _chunks(stack.engine, document_id) == before

    # A redelivery after a worker died mid-job: the document is stuck "processing".
    with stack.engine.begin() as conn:
        conn.execute(
            text("UPDATE documents SET status = 'processing' WHERE id = :i"), {"i": document_id}
        )
    assert stack.queue.run(uuid.UUID(document_id)) is IngestionOutcome.READY
    assert _chunks(stack.engine, document_id) == before
    assert _status(stack.engine, document_id)[0] == "ready"


async def test_a_broker_outage_is_recoverable_with_retry(stack: Stack) -> None:
    headers = await _login(stack.client, "ada@example.com")
    stack.queue.fail = True
    document_id = (await _upload(stack, headers, "a.txt", long_text(30).encode())).json()["id"]
    assert (await _api_status(stack, headers, document_id))["status"] == "failed"
    assert _chunks(stack.engine, document_id) == []

    stack.queue.fail = False
    response = await stack.client.post(f"{BASE}/{document_id}/retry", headers=headers)

    assert response.status_code == 202
    state = await _api_status(stack, headers, document_id)
    assert state["status"] == "ready"
    assert state["error_message"] is None
    assert len(_chunks(stack.engine, document_id)) == state["total_chunks"]


def test_a_write_that_fails_midway_keeps_the_previous_chunks(migrated_engine: Engine) -> None:
    user_id, document_id = uuid.uuid4(), uuid.uuid4()
    with migrated_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (:u, 'a@b.co', 'x')"),
            {"u": user_id},
        )
        conn.execute(
            text(
                "INSERT INTO documents (id, user_id, filename, content_type, size_bytes, "
                "storage_path, content_sha256, status) VALUES (:d, :u, 'a.txt', 'text/plain', "
                "1, 'p.txt', 'abc', 'processing')"
            ),
            {"d": document_id, "u": user_id},
        )
    good = [Chunk(0, None, "first"), Chunk(1, None, "second")]
    with Session(migrated_engine) as session:
        assert SqlIngestionStore(session).replace_chunks(
            document_id, good, _vectors(2), embedding_model=MODEL, total_pages=None
        )

    # The second chunk is rejected by PostgreSQL (NUL is not allowed in text).
    bad = [Chunk(0, None, "fine"), Chunk(1, None, "bro\x00ken")]
    with Session(migrated_engine) as session, pytest.raises((DBAPIError, ValueError)):
        SqlIngestionStore(session).replace_chunks(
            document_id, bad, _vectors(2), embedding_model=MODEL, total_pages=None
        )

    with migrated_engine.connect() as conn:
        contents = (
            conn.execute(
                text(
                    "SELECT content FROM document_chunks "
                    "WHERE document_id = :d ORDER BY chunk_index"
                ),
                {"d": document_id},
            )
            .scalars()
            .all()
        )
    assert contents == ["first", "second"]


def test_a_document_deleted_during_ingestion_is_reported_not_resurrected(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        assert (
            SqlIngestionStore(session).replace_chunks(
                uuid.uuid4(),
                [Chunk(0, None, "x")],
                _vectors(1),
                embedding_model=MODEL,
                total_pages=None,
            )
            is False
        )


# --- API behavior on the real database -----------------------------------------------------


async def test_duplicate_upload_is_a_conflict_enforced_by_the_database(stack: Stack) -> None:
    headers = await _login(stack.client, "ada@example.com")
    data = long_text(5).encode()
    assert (await _upload(stack, headers, "a.txt", data)).status_code == 202

    response = await _upload(stack, headers, "b.txt", data)

    assert response.status_code == 409
    files = await asyncio.to_thread(lambda: [p for p in stack.root.rglob("*") if p.is_file()])
    assert len(files) == 1


async def test_users_are_isolated(stack: Stack) -> None:
    ada = await _login(stack.client, "ada@example.com")
    bob = await _login(stack.client, "bob@example.com")
    document_id = (await _upload(stack, ada, "a.txt", long_text(5).encode())).json()["id"]

    assert (await stack.client.get(f"{BASE}/{document_id}", headers=bob)).status_code == 404
    assert (await stack.client.delete(f"{BASE}/{document_id}", headers=bob)).status_code == 404
    assert (await stack.client.get(BASE, headers=bob)).json()["total"] == 0
    # The same file is a separate document for another user.
    assert (await _upload(stack, bob, "a.txt", long_text(5).encode())).status_code == 202
    assert (await stack.client.get(BASE, headers=ada)).json()["total"] == 1
    assert _status(stack.engine, document_id)[0] == "ready"


async def test_delete_removes_document_chunks_and_file(stack: Stack) -> None:
    headers = await _login(stack.client, "ada@example.com")
    document_id = (await _upload(stack, headers, "a.txt", long_text(30).encode())).json()["id"]
    assert _chunks(stack.engine, document_id)

    response = await stack.client.delete(f"{BASE}/{document_id}", headers=headers)

    assert response.status_code == 204
    assert _chunks(stack.engine, document_id) == []
    with stack.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM documents")).scalar_one() == 0
    files = await asyncio.to_thread(lambda: [p for p in stack.root.rglob("*") if p.is_file()])
    assert files == []


async def test_list_returns_the_users_documents_newest_first(stack: Stack) -> None:
    headers = await _login(stack.client, "ada@example.com")
    for n in range(3):
        await _upload(stack, headers, f"n{n}.txt", f"document number {n}".encode())

    body = (await stack.client.get(BASE, headers=headers, params={"limit": 2})).json()

    assert body["total"] == 3
    assert [d["filename"] for d in body["items"]] == ["n2.txt", "n1.txt"]


# --- migration 0002 ------------------------------------------------------------------------


def test_migration_0002_adds_and_removes_its_columns_and_constraint(engine: Engine) -> None:
    reset_schema(engine)
    command.upgrade(alembic_config(), "head")
    columns = {c["name"] for c in inspect(engine).get_columns("documents")}
    constraints = {c["name"] for c in inspect(engine).get_unique_constraints("documents")}
    assert {"total_pages", "total_chunks"} <= columns
    assert "uq_documents_user_id_content_sha256" in constraints

    command.downgrade(alembic_config(), "0001")

    columns = {c["name"] for c in inspect(engine).get_columns("documents")}
    constraints = {c["name"] for c in inspect(engine).get_unique_constraints("documents")}
    assert not {"total_pages", "total_chunks"} & columns
    assert "uq_documents_user_id_content_sha256" not in constraints
