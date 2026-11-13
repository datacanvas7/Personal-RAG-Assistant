"""Extract text from stored files, one loader per format.

Uploaded files are untrusted input, so each loader bounds the work a hostile file can cause
(page count, decompressed size, extracted text) and turns every parser failure into an
``IngestionError`` with a message that is safe to show to the user.
"""

import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from docx import Document as open_docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.ingestion.errors import IngestionError

# A DOCX is a ZIP archive; a small file can expand to gigabytes ("zip bomb").
_MAX_DOCX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024


@dataclass(frozen=True)
class PageText:
    page_number: int | None  # 1-based; None for formats that have no pages
    text: str


@dataclass(frozen=True)
class LoadedDocument:
    pages: list[PageText]
    total_pages: int | None


@dataclass(frozen=True)
class LoadLimits:
    max_pdf_pages: int
    max_extracted_chars: int
    ocr_min_chars_per_page: int


def load_document(path: Path, extension: str, limits: LoadLimits) -> LoadedDocument:
    """Dispatch on the (server-validated) extension and enforce the extracted-text cap."""
    loaders: dict[str, Callable[[Path, LoadLimits], LoadedDocument]] = {
        ".pdf": load_pdf,
        ".docx": load_docx,
        ".txt": load_text,
        ".md": load_text,
    }
    loader = loaders.get(extension)
    if loader is None:
        raise IngestionError("This file type is not supported.")

    loaded = loader(path, limits)
    if sum(len(page.text) for page in loaded.pages) > limits.max_extracted_chars:
        raise IngestionError("This document contains too much text to process.")
    return loaded


def load_pdf(path: Path, limits: LoadLimits) -> LoadedDocument:
    try:
        document = pymupdf.open(path, filetype="pdf")  # type: ignore[no-untyped-call]
    except (pymupdf.FileDataError, pymupdf.EmptyFileError, RuntimeError, ValueError):
        raise IngestionError("The PDF could not be read. The file may be corrupted.") from None

    with document:
        if document.needs_pass:
            raise IngestionError("The PDF is password-protected. Remove the password and retry.")
        if document.page_count > limits.max_pdf_pages:
            raise IngestionError(f"The PDF has more than {limits.max_pdf_pages} pages.")
        try:
            pages = [
                PageText(
                    index + 1,
                    str(document.load_page(index).get_text("text", sort=True)),  # type: ignore[no-untyped-call]
                )
                for index in range(document.page_count)
            ]
        except (RuntimeError, ValueError):
            raise IngestionError("The PDF could not be read. The file may be corrupted.") from None

    _reject_if_image_only(pages, limits.ocr_min_chars_per_page)
    return LoadedDocument(pages=pages, total_pages=len(pages))


def _reject_if_image_only(pages: list[PageText], min_chars: int) -> None:
    """A scanned PDF has pages but no text layer; indexing it would store nothing useful."""
    if not pages:
        raise IngestionError("The PDF has no pages.")
    image_only = sum(1 for page in pages if len(page.text.strip()) < min_chars)
    if image_only * 2 >= len(pages):
        raise IngestionError(
            "This PDF looks like a scan (it has little or no selectable text). "
            "OCR is required and is not supported yet."
        )


def load_docx(path: Path, _limits: LoadLimits) -> LoadedDocument:
    try:
        with zipfile.ZipFile(path) as archive:
            if sum(info.file_size for info in archive.infolist()) > _MAX_DOCX_UNCOMPRESSED_BYTES:
                raise IngestionError("The document is too large once unpacked.")
        document = open_docx(str(path))
        lines: list[str] = []
        # Walk the body in order so tables stay where they appear in the document.
        for element in document.element.body.iterchildren():
            if element.tag == qn("w:p"):
                lines.append(Paragraph(element, document).text)
            elif element.tag == qn("w:tbl"):
                table = Table(element, document)
                lines.extend(" | ".join(cell.text for cell in row.cells) for row in table.rows)
    except IngestionError:
        raise
    except Exception:  # python-docx surfaces many unrelated error types
        raise IngestionError("The Word document could not be read. It may be corrupted.") from None

    return LoadedDocument(pages=[PageText(None, "\n".join(lines))], total_pages=None)


def load_text(path: Path, _limits: LoadLimits) -> LoadedDocument:
    try:
        # utf-8-sig drops the byte-order mark that Windows editors add.
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise IngestionError(
            "The file is not valid UTF-8 text. Save it as UTF-8 and retry."
        ) from None
    return LoadedDocument(pages=[PageText(None, text)], total_pages=None)
