"""Text normalisation applied to every page before chunking."""

import re
import unicodedata

# C0 control characters except tab (\x09) and newline (\x0a), DEL and C1 controls.
# PostgreSQL rejects NUL in text columns outright; the rest only add noise.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
# Soft hyphen, zero-width characters and the byte-order mark: invisible, but they split
# words for the embedding model and for search.
_INVISIBLE = re.compile("[­​‌‍⁠﻿]")
# "exam-\nple" -> "example": a hyphen at a line break inside a lowercase word. A hyphen
# before a capital or a digit ("Smith-\nJones", "COVID-\n19") is kept.
_LINE_BREAK_HYPHEN = re.compile(r"(?<=[a-z])-\n(?=[a-z])")
_SPACES = re.compile(r"[^\S\n]+")  # any whitespace except newline, including NBSP
_SPACE_AROUND_NEWLINE = re.compile(r" ?\n ?")
_BLANK_LINES = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Return ``text`` with consistent Unicode, newlines and spacing.

    Paragraph breaks (blank lines) are preserved because the chunker uses them as the
    preferred place to split.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _INVISIBLE.sub("", text)
    text = _CONTROL_CHARS.sub("", text)
    text = _LINE_BREAK_HYPHEN.sub("", text)
    text = _SPACES.sub(" ", text)
    text = _SPACE_AROUND_NEWLINE.sub("\n", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()
