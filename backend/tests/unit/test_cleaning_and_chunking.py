import pytest

from app.ingestion.chunking import chunk_pages
from app.ingestion.cleaning import clean_text
from app.ingestion.loaders import PageText
from tests.samples import long_text

# --- cleaning --------------------------------------------------------------------------


def test_clean_normalises_newlines_and_spacing() -> None:
    assert clean_text("a  b\r\nc \t d\r\n\r\n\r\n\r\ne") == "a b\nc d\n\ne"


def test_clean_removes_nul_and_invisible_characters() -> None:
    assert clean_text("he\x00llo​ wor­ld﻿") == "hello world"


def test_clean_joins_words_hyphenated_at_a_line_break() -> None:
    assert clean_text("an exam-\nple of it") == "an example of it"


def test_clean_keeps_hyphens_before_capitals_and_digits() -> None:
    assert clean_text("Smith-\nJones and COVID-\n19") == "Smith-\nJones and COVID-\n19"


def test_clean_applies_unicode_nfc() -> None:
    assert clean_text("café") == "café"


def test_clean_of_whitespace_only_is_empty() -> None:
    assert clean_text(" \n\t \n ") == ""


# --- chunking --------------------------------------------------------------------------


def test_short_page_is_a_single_chunk_with_its_page_number() -> None:
    chunks = chunk_pages([PageText(3, "Hello there.")], size=100, overlap=10)

    assert [(c.index, c.page_number, c.content) for c in chunks] == [(0, 3, "Hello there.")]


def test_chunks_never_cross_pages_and_indexes_are_continuous() -> None:
    pages = [PageText(1, long_text(20)), PageText(2, long_text(20)), PageText(3, "Short.")]

    chunks = chunk_pages(pages, size=200, overlap=40)

    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert {c.page_number for c in chunks} == {1, 2, 3}
    page_numbers = [c.page_number for c in chunks]
    assert page_numbers == sorted(page_numbers, key=lambda n: n or 0)
    assert chunks[-1].content == "Short."


def test_every_chunk_respects_the_size_limit() -> None:
    chunks = chunk_pages([PageText(1, long_text(200))], size=300, overlap=60)

    assert len(chunks) > 5
    assert all(0 < len(c.content) <= 300 for c in chunks)


def test_consecutive_chunks_on_a_page_overlap() -> None:
    chunks = chunk_pages([PageText(1, long_text(60))], size=300, overlap=80)

    for previous, current in zip(chunks, chunks[1:], strict=False):
        shared = current.content[:40]
        assert shared in previous.content


def test_zero_overlap_produces_no_shared_text() -> None:
    paragraphs = "\n\n".join(f"Paragraph number {n} " + "word " * 30 for n in range(6))

    chunks = chunk_pages([PageText(None, paragraphs)], size=250, overlap=0)

    assert len(chunks) > 1
    assert "".join(c.content for c in chunks).count("Paragraph number 2") == 1


def test_paragraphs_are_kept_whole_when_they_fit() -> None:
    text = "First paragraph here.\n\nSecond paragraph here."

    chunks = chunk_pages([PageText(1, text)], size=30, overlap=0)

    assert [c.content for c in chunks] == ["First paragraph here.", "Second paragraph here."]


def test_a_word_longer_than_the_chunk_size_is_hard_cut() -> None:
    chunks = chunk_pages([PageText(1, "x" * 1050)], size=400, overlap=50)

    assert [len(c.content) for c in chunks] == [400, 400, 250]


def test_blank_pages_produce_no_chunks() -> None:
    chunks = chunk_pages(
        [PageText(1, ""), PageText(2, "  \n "), PageText(3, "Text.")], size=50, overlap=5
    )

    assert [(c.index, c.page_number) for c in chunks] == [(0, 3)]


def test_pages_without_numbers_keep_none() -> None:
    chunks = chunk_pages([PageText(None, long_text(30))], size=200, overlap=20)

    assert chunks
    assert all(c.page_number is None for c in chunks)


@pytest.mark.parametrize(("size", "overlap"), [(0, 0), (100, -1), (100, 51)])
def test_invalid_parameters_are_rejected(size: int, overlap: int) -> None:
    with pytest.raises(ValueError, match="overlap"):
        chunk_pages([PageText(1, "x")], size=size, overlap=overlap)


def test_no_text_is_lost_without_overlap() -> None:
    text = long_text(40)

    chunks = chunk_pages([PageText(1, text)], size=250, overlap=0)

    assert " ".join(c.content for c in chunks).split() == text.split()
