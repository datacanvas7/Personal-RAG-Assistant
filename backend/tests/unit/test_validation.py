import io
import zipfile

import pytest

from app.core.errors import FileTooLargeError, InvalidFileError, UnsupportedFileTypeError
from app.ingestion.validation import sanitize_filename, validate_upload
from tests.samples import make_docx, make_pdf

LIMIT = 1024 * 1024


def test_valid_files_of_each_type_are_accepted_with_a_server_derived_type() -> None:
    cases = {
        "report.pdf": (make_pdf(["hi"]), "application/pdf"),
        "notes.txt": (b"plain text", "text/plain"),
        "readme.md": (b"# Title", "text/markdown"),
        "essay.docx": (
            make_docx(["hi"]),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    }
    for name, (data, content_type) in cases.items():
        result = validate_upload(name, data, max_bytes=LIMIT)
        assert result.content_type == content_type
        assert result.extension == name[name.index(".") :]


def test_extension_check_is_case_insensitive() -> None:
    assert validate_upload("NOTES.TXT", b"text", max_bytes=LIMIT).extension == ".txt"


@pytest.mark.parametrize("name", ["virus.exe", "page.html", "archive.zip", "noextension", None, ""])
def test_unsupported_extensions_are_rejected(name: str | None) -> None:
    with pytest.raises(UnsupportedFileTypeError):
        validate_upload(name, b"data", max_bytes=LIMIT)


def test_empty_file_is_rejected() -> None:
    with pytest.raises(InvalidFileError, match="empty"):
        validate_upload("a.txt", b"", max_bytes=LIMIT)


def test_oversized_file_is_rejected() -> None:
    with pytest.raises(FileTooLargeError):
        validate_upload("a.txt", b"x" * 11, max_bytes=10)


def test_file_exactly_at_the_limit_is_accepted() -> None:
    validate_upload("a.txt", b"x" * 10, max_bytes=10)


def test_pdf_extension_with_other_content_is_rejected() -> None:
    with pytest.raises(InvalidFileError):
        validate_upload("fake.pdf", b"MZ\x90\x00 this is an executable", max_bytes=LIMIT)


def test_pdf_header_is_found_within_the_first_kilobyte() -> None:
    validate_upload("a.pdf", b"junk" * 50 + b"%PDF-1.7\n...", max_bytes=LIMIT)


def test_docx_extension_with_a_plain_zip_is_rejected() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "hi")

    with pytest.raises(InvalidFileError):
        validate_upload("a.docx", buffer.getvalue(), max_bytes=LIMIT)


@pytest.mark.parametrize("data", [b"not a zip at all", b"PK\x03\x04truncated"])
def test_docx_extension_with_non_zip_content_is_rejected(data: bytes) -> None:
    with pytest.raises(InvalidFileError):
        validate_upload("a.docx", data, max_bytes=LIMIT)


def test_text_extension_with_binary_content_is_rejected() -> None:
    with pytest.raises(InvalidFileError):
        validate_upload("a.txt", b"abc\x00def", max_bytes=LIMIT)


def test_text_that_is_not_utf8_is_rejected() -> None:
    with pytest.raises(InvalidFileError, match="UTF-8"):
        validate_upload("a.md", "café".encode("latin-1"), max_bytes=LIMIT)


def test_whitespace_only_text_is_rejected() -> None:
    with pytest.raises(InvalidFileError, match="no text"):
        validate_upload("a.txt", b"  \n\t\n", max_bytes=LIMIT)


def test_text_with_a_byte_order_mark_is_accepted() -> None:
    validate_upload("a.txt", b"\xef\xbb\xbfhello", max_bytes=LIMIT)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd.txt", "passwd.txt"),
        ("C:\\Users\\me\\Documents\\cv.docx", "cv.docx"),
        ("  spaced name .md ", "spaced name .md"),
        ("bad\x00na\x1fme.txt", "badname.txt"),
        ("...hidden.txt", "hidden.txt"),
        (None, ""),
    ],
)
def test_sanitize_filename(raw: str | None, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_long_names_are_truncated_but_keep_their_extension() -> None:
    name = sanitize_filename("a" * 400 + ".pdf")

    assert len(name) == 255
    assert name.endswith(".pdf")


def test_display_name_never_contains_a_directory() -> None:
    result = validate_upload("../../secret/notes.txt", b"text", max_bytes=LIMIT)

    assert result.display_name == "notes.txt"
