"""The ingestion job's success, failure and repeat behavior, without a database."""

from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.ingestion.pipeline import IngestionOutcome, run_ingestion
from app.models import DocumentStatus
from app.services.storage import LocalFileStorage
from tests.fakes import FakeIngestionStore
from tests.samples import long_text, make_docx, make_pdf

SETTINGS = Settings(chunk_size_chars=400, chunk_overlap_chars=60)


def _setup(tmp_path: Path, name: str, data: bytes) -> tuple[FakeIngestionStore, LocalFileStorage]:
    (tmp_path / name).write_bytes(data)
    return FakeIngestionStore(storage_path=name), LocalFileStorage(tmp_path)


def _run(store: FakeIngestionStore, storage: LocalFileStorage) -> IngestionOutcome:
    return run_ingestion(store.document_id, store=store, storage=storage, settings=SETTINGS)


def test_pdf_chunks_carry_the_right_page_numbers(tmp_path: Path) -> None:
    pages = [f"Alpha page. {long_text(8)}", f"Bravo page. {long_text(8)}", "Charlie page."]
    store, storage = _setup(tmp_path, "d.pdf", make_pdf(pages))

    assert _run(store, storage) is IngestionOutcome.READY

    assert store.status is DocumentStatus.READY
    assert store.total_pages == 3
    assert store.total_chunks == len(store.chunks)
    by_page: dict[int | None, list[str]] = {}
    for chunk in store.chunks:
        by_page.setdefault(chunk.page_number, []).append(chunk.content)
    assert set(by_page) == {1, 2, 3}
    assert not any("Alpha" in c for c in by_page[2] + by_page[3])
    assert "Alpha page." in by_page[1][0]
    assert "Bravo page." in by_page[2][0]
    assert by_page[3] == ["Charlie page."]
    assert [c.index for c in store.chunks] == list(range(len(store.chunks)))


def test_docx_is_ingested_without_page_numbers(tmp_path: Path) -> None:
    store, storage = _setup(tmp_path, "d.docx", make_docx([long_text(10), "Second paragraph."]))

    assert _run(store, storage) is IngestionOutcome.READY

    assert store.total_pages is None
    assert store.chunks
    assert all(c.page_number is None for c in store.chunks)


@pytest.mark.parametrize("name", ["d.txt", "d.md"])
def test_text_and_markdown_are_ingested(tmp_path: Path, name: str) -> None:
    store, storage = _setup(tmp_path, name, ("# Title\n\n" + long_text(20)).encode())

    assert _run(store, storage) is IngestionOutcome.READY

    assert len(store.chunks) > 1
    assert store.status is DocumentStatus.READY


def test_a_bad_file_fails_the_document_with_a_readable_message(tmp_path: Path) -> None:
    store, storage = _setup(tmp_path, "d.pdf", make_pdf(["", ""]))

    assert _run(store, storage) is IngestionOutcome.FAILED

    assert store.status is DocumentStatus.FAILED
    assert store.error_message is not None
    assert "OCR" in store.error_message
    assert store.chunks == []


def test_a_missing_file_fails_the_document(tmp_path: Path) -> None:
    store = FakeIngestionStore(storage_path="gone.txt")

    assert _run(store, LocalFileStorage(tmp_path)) is IngestionOutcome.FAILED

    assert store.error_message is not None
    assert "missing" in store.error_message


def test_a_document_with_no_extractable_text_fails(tmp_path: Path) -> None:
    store, storage = _setup(tmp_path, "d.txt", b"\x0b\x0c\x01")

    assert _run(store, storage) is IngestionOutcome.FAILED

    assert store.status is DocumentStatus.FAILED
    assert store.chunks == []


def test_an_unexpected_crash_fails_the_document_without_leaking_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, storage = _setup(tmp_path, "d.txt", b"hello world")

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("secret internal detail /srv/app/x.py")

    monkeypatch.setattr("app.ingestion.pipeline.chunk_pages", explode)

    assert _run(store, storage) is IngestionOutcome.FAILED

    assert store.status is DocumentStatus.FAILED
    assert store.error_message is not None
    assert "secret" not in store.error_message


def test_running_twice_leaves_exactly_one_set_of_chunks(tmp_path: Path) -> None:
    store, storage = _setup(tmp_path, "d.txt", long_text(30).encode())
    assert _run(store, storage) is IngestionOutcome.READY
    first = list(store.chunks)

    # A duplicate delivery of the same job: the document is already ready.
    assert _run(store, storage) is IngestionOutcome.SKIPPED

    assert store.chunks == first


def test_redelivery_after_a_crash_replaces_rather_than_duplicates(tmp_path: Path) -> None:
    store, storage = _setup(tmp_path, "d.txt", long_text(30).encode())
    assert _run(store, storage) is IngestionOutcome.READY
    expected = list(store.chunks)
    # A worker died after the claim: the document is stuck "processing" with stale chunks.
    store.status = DocumentStatus.PROCESSING
    store.chunks = expected[:2]

    assert _run(store, storage) is IngestionOutcome.READY

    assert store.chunks == expected


def test_retrying_a_failed_document_can_succeed(tmp_path: Path) -> None:
    store, storage = _setup(tmp_path, "d.txt", b"")
    assert _run(store, storage) is IngestionOutcome.FAILED

    (tmp_path / "d.txt").write_bytes(long_text(5).encode())

    assert _run(store, storage) is IngestionOutcome.READY
    assert store.error_message is None


def test_a_document_deleted_before_the_job_starts_is_skipped(tmp_path: Path) -> None:
    store, storage = _setup(tmp_path, "d.txt", b"hello")
    store.exists = False

    assert _run(store, storage) is IngestionOutcome.SKIPPED


def test_a_document_deleted_during_the_job_is_skipped(tmp_path: Path) -> None:
    store, storage = _setup(tmp_path, "d.txt", b"hello")
    original_claim = store.claim

    def claim_then_delete(document_id):  # type: ignore[no-untyped-def]
        claimed = original_claim(document_id)
        store.exists = False
        return claimed

    store.claim = claim_then_delete  # type: ignore[method-assign]

    assert _run(store, storage) is IngestionOutcome.SKIPPED
    assert store.chunks == []


def test_database_errors_propagate_so_the_task_can_retry(tmp_path: Path) -> None:
    store, storage = _setup(tmp_path, "d.txt", b"hello world")
    store.fail_on_replace = OperationalError("insert", {}, Exception("connection lost"))

    with pytest.raises(OperationalError):
        _run(store, storage)

    # Nothing partial was written, and the document is still claimable for the retry.
    assert store.chunks == []
    assert store.status is DocumentStatus.PROCESSING
    store.fail_on_replace = None
    assert _run(store, storage) is IngestionOutcome.READY
