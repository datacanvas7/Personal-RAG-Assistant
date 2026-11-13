import asyncio
import uuid
import zipfile
from pathlib import Path

import pytest

from app.ingestion.errors import IngestionError
from app.ingestion.loaders import LoadLimits, load_document
from app.services.storage import LocalFileStorage
from tests.samples import make_docx, make_encrypted_pdf, make_pdf

LIMITS = LoadLimits(max_pdf_pages=50, max_extracted_chars=100_000, ocr_min_chars_per_page=20)
TEXT_PAGE = "This page has plenty of selectable text for the extractor to find. " * 3


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


# --- PDF -------------------------------------------------------------------------------


def test_pdf_pages_are_numbered_from_one(tmp_path: Path) -> None:
    pdf = make_pdf([f"Page {n} " + TEXT_PAGE for n in (1, 2, 3)])

    loaded = load_document(_write(tmp_path, "a.pdf", pdf), ".pdf", LIMITS)

    assert loaded.total_pages == 3
    assert [p.page_number for p in loaded.pages] == [1, 2, 3]
    assert all(f"Page {p.page_number}" in p.text for p in loaded.pages)


def test_pdf_with_one_blank_page_in_a_text_document_is_accepted(tmp_path: Path) -> None:
    pdf = make_pdf([TEXT_PAGE, "", TEXT_PAGE])

    loaded = load_document(_write(tmp_path, "a.pdf", pdf), ".pdf", LIMITS)

    assert loaded.total_pages == 3
    assert loaded.pages[1].text.strip() == ""


def test_scanned_pdf_without_a_text_layer_asks_for_ocr(tmp_path: Path) -> None:
    pdf = make_pdf(["", "", ""])

    with pytest.raises(IngestionError, match="OCR"):
        load_document(_write(tmp_path, "scan.pdf", pdf), ".pdf", LIMITS)


def test_corrupt_pdf_is_a_clean_error(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="could not be read"):
        load_document(_write(tmp_path, "bad.pdf", b"%PDF-1.4 not really a pdf"), ".pdf", LIMITS)


def test_encrypted_pdf_is_rejected_with_a_helpful_message(tmp_path: Path) -> None:
    pdf = make_encrypted_pdf("secret text")

    with pytest.raises(IngestionError, match="password"):
        load_document(_write(tmp_path, "locked.pdf", pdf), ".pdf", LIMITS)


def test_pdf_over_the_page_limit_is_rejected(tmp_path: Path) -> None:
    pdf = make_pdf([TEXT_PAGE] * 4)
    limits = LoadLimits(max_pdf_pages=3, max_extracted_chars=100_000, ocr_min_chars_per_page=20)

    with pytest.raises(IngestionError, match="more than 3 pages"):
        load_document(_write(tmp_path, "long.pdf", pdf), ".pdf", limits)


def test_text_over_the_extraction_cap_is_rejected(tmp_path: Path) -> None:
    limits = LoadLimits(max_pdf_pages=50, max_extracted_chars=100, ocr_min_chars_per_page=20)

    with pytest.raises(IngestionError, match="too much text"):
        load_document(_write(tmp_path, "big.txt", b"x" * 500), ".txt", limits)


# --- DOCX ------------------------------------------------------------------------------


def test_docx_paragraphs_and_tables_are_extracted_in_order(tmp_path: Path) -> None:
    data = make_docx(["Intro paragraph."], table=[["Name", "Role"], ["Ada", "Engineer"]])

    loaded = load_document(_write(tmp_path, "a.docx", data), ".docx", LIMITS)

    assert loaded.total_pages is None
    assert len(loaded.pages) == 1
    assert loaded.pages[0].page_number is None
    lines = [line for line in loaded.pages[0].text.splitlines() if line]
    assert lines[0] == "Intro paragraph."
    assert "Name | Role" in lines
    assert "Ada | Engineer" in lines
    assert lines[-1] == "After the table."


def test_corrupt_docx_is_a_clean_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", "<not valid xml")

    with pytest.raises(IngestionError, match="could not be read"):
        load_document(path, ".docx", LIMITS)


def test_docx_that_expands_beyond_the_cap_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.ingestion.loaders._MAX_DOCX_UNCOMPRESSED_BYTES", 100)
    path = _write(tmp_path, "a.docx", make_docx(["hello " * 100]))

    with pytest.raises(IngestionError, match="too large"):
        load_document(path, ".docx", LIMITS)


# --- text and Markdown -----------------------------------------------------------------


def test_txt_and_markdown_are_loaded_as_a_single_unnumbered_page(tmp_path: Path) -> None:
    for name in ("a.txt", "a.md"):
        loaded = load_document(
            _write(tmp_path, name, "# Héllo\n\nbody".encode()), Path(name).suffix, LIMITS
        )
        assert loaded.pages[0].text == "# Héllo\n\nbody"
        assert loaded.pages[0].page_number is None
        assert loaded.total_pages is None


def test_byte_order_mark_is_dropped(tmp_path: Path) -> None:
    loaded = load_document(_write(tmp_path, "a.txt", b"\xef\xbb\xbfhello"), ".txt", LIMITS)

    assert loaded.pages[0].text == "hello"


def test_text_in_the_wrong_encoding_is_a_clean_error(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="UTF-8"):
        load_document(_write(tmp_path, "a.txt", "café".encode("latin-1")), ".txt", LIMITS)


def test_unknown_extension_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="not supported"):
        load_document(_write(tmp_path, "a.exe", b"x"), ".exe", LIMITS)


# --- storage ---------------------------------------------------------------------------


async def test_storage_saves_under_generated_names_and_reads_back(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    user_id, document_id = uuid.uuid4(), uuid.uuid4()

    relative = await storage.save(
        user_id=user_id, document_id=document_id, extension=".txt", data=b"hello"
    )

    assert relative == f"{user_id}/{document_id}.txt"
    assert storage.resolve(relative).read_bytes() == b"hello"
    assert [p.name for p in (tmp_path / str(user_id)).iterdir()] == [f"{document_id}.txt"]


async def test_storage_delete_removes_the_file_and_tolerates_a_missing_one(
    tmp_path: Path,
) -> None:
    storage = LocalFileStorage(tmp_path)
    relative = await storage.save(
        user_id=uuid.uuid4(), document_id=uuid.uuid4(), extension=".md", data=b"x"
    )

    await storage.delete(relative)
    await storage.delete(relative)

    assert not storage.resolve(relative).exists()


@pytest.mark.parametrize("path", ["../outside.txt", "a/../../outside.txt", "/etc/passwd"])
def test_storage_refuses_paths_outside_its_root(tmp_path: Path, path: str) -> None:
    storage = LocalFileStorage(tmp_path / "root")

    with pytest.raises(ValueError, match="escapes"):
        storage.resolve(path)


async def test_failed_write_leaves_no_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalFileStorage(tmp_path)

    def broken_fsync(_fd: int) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("app.services.storage.os.fsync", broken_fsync)

    with pytest.raises(OSError, match="disk full"):
        await storage.save(
            user_id=uuid.uuid4(), document_id=uuid.uuid4(), extension=".txt", data=b"data"
        )

    leftovers = await asyncio.to_thread(lambda: [p for p in tmp_path.rglob("*") if p.is_file()])
    assert leftovers == []
