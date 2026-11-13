"""Builders for small, real files of each supported type.

Tests generate their inputs with the same libraries the application uses to read them, so
no binary fixtures are committed to the repository.
"""

import io
from typing import Any

import docx
import pymupdf

# The libraries' type stubs are incomplete; Any keeps the helpers simple and honest.
_pymupdf: Any = pymupdf
_docx: Any = docx


def make_pdf(pages: list[str]) -> bytes:
    """A PDF with one text page per string. An empty string gives a blank page."""
    document = _pymupdf.open()
    for text in pages:
        page = document.new_page()
        if text:
            page.insert_textbox(_pymupdf.Rect(50, 50, 550, 780), text, fontsize=11)
    data: bytes = document.tobytes()
    document.close()
    return data


def make_encrypted_pdf(text: str) -> bytes:
    document = _pymupdf.open()
    document.new_page().insert_text((72, 72), text)
    data: bytes = document.tobytes(
        encryption=_pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner-pw", user_pw="user-pw"
    )
    document.close()
    return data


def make_docx(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    """A Word document: the paragraphs, then optionally a table, then a closing paragraph."""
    document = _docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    if table:
        grid = document.add_table(rows=len(table), cols=len(table[0]))
        for row_index, row in enumerate(table):
            for column_index, value in enumerate(row):
                grid.cell(row_index, column_index).text = value
        document.add_paragraph("After the table.")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


SENTENCE = "The quick brown fox jumps over the lazy dog near the river bank. "


def long_text(sentences: int) -> str:
    return (SENTENCE * sentences).strip()
