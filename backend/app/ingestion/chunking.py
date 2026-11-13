"""Page-aware chunking.

Chunks never span a page boundary, so every chunk has one trustworthy page number and a
citation can say "page 7" without guessing. Within a page the text is split at the
largest natural boundary that fits: paragraphs, then sentences, then words.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.ingestion.loaders import PageText

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    index: int  # position in the document, starting at 0
    page_number: int | None
    content: str


def chunk_pages(pages: Iterable[PageText], *, size: int, overlap: int) -> list[Chunk]:
    """Split cleaned pages into chunks of at most ``size`` characters.

    Consecutive chunks on the same page share up to ``overlap`` characters, so a sentence
    cut by a boundary is still whole in one of the two chunks. Blank pages produce
    nothing. ``Chunk.index`` is continuous across pages.
    """
    if size < 1 or overlap < 0 or overlap * 2 > size:
        raise ValueError("size must be positive and overlap at most half of size")

    chunks: list[Chunk] = []
    for page in pages:
        for content in _split(page.text, size=size, overlap=overlap):
            chunks.append(Chunk(index=len(chunks), page_number=page.page_number, content=content))
    return chunks


def _split(text: str, *, size: int, overlap: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for unit, separator in _units(text, size):
        if not current:
            current = unit
        elif len(current) + len(separator) + len(unit) <= size:
            current += separator + unit
        else:
            pieces.append(current)
            seed = _overlap_tail(current, overlap)
            if seed and len(seed) + len(separator) + len(unit) <= size:
                current = seed + separator + unit
            else:
                current = unit
    if current.strip():
        pieces.append(current)
    return pieces


def _units(text: str, size: int) -> Iterable[tuple[str, str]]:
    """Yield ``(text, separator_to_put_before_it)`` pieces, each at most ``size`` long."""
    first = True
    for paragraph in _PARAGRAPH_BREAK.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        separator = "" if first else "\n\n"
        first = False
        if len(paragraph) <= size:
            yield paragraph, separator
            continue
        for sentence in _SENTENCE_END.split(paragraph):
            if len(sentence) <= size:
                yield sentence, separator
            else:
                for words in _pack_words(sentence, size):
                    yield words, separator
                    separator = " "
            separator = " "


def _pack_words(text: str, size: int) -> Iterable[str]:
    """Split one over-long sentence at word boundaries; cut words longer than ``size``."""
    line = ""
    for word in text.split():
        while len(word) > size:  # e.g. a long URL or a run of characters without spaces
            if line:
                yield line
                line = ""
            yield word[:size]
            word = word[size:]
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= size:
            line += " " + word
        else:
            yield line
            line = word
    if line:
        yield line


def _overlap_tail(text: str, overlap: int) -> str:
    """The last ``overlap`` characters of ``text``, starting at a word boundary."""
    if overlap <= 0 or len(text) <= overlap:
        return ""
    tail = text[-overlap:]
    boundary = min((i for i in (tail.find(" "), tail.find("\n")) if i != -1), default=-1)
    if boundary == -1:
        return ""
    return tail[boundary + 1 :].strip()
