"""Checks applied to an upload before anything is written to disk.

The client controls the file name, the declared content type and the bytes. Only the
bytes are trusted, and only after checking them against the extension.
"""

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.core.errors import FileTooLargeError, InvalidFileError, UnsupportedFileTypeError

ALLOWED_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

_MAX_DISPLAY_NAME = 255
_PDF_MAGIC = b"%PDF-"
_PDF_MAGIC_WINDOW = 1024  # readers accept the header anywhere in the first KiB
_ZIP_MAGIC = b"PK\x03\x04"
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


@dataclass(frozen=True)
class ValidatedUpload:
    display_name: str  # for showing to the user only; never used to build a path
    extension: str  # one of ALLOWED_TYPES, lowercase
    content_type: str  # derived from the extension, not from the client


def sanitize_filename(raw: str | None) -> str:
    """Reduce a client-supplied name to a harmless label.

    Strips directories (both separators; browsers on Windows send backslashes), control
    characters and surrounding whitespace, and bounds the length while keeping the
    extension. The result is only displayed; storage uses a generated name.
    """
    name = (raw or "").replace("\\", "/")
    name = PurePosixPath(name).name
    name = _CONTROL_CHARS.sub("", name).strip().strip(".")
    if len(name) > _MAX_DISPLAY_NAME:
        suffix = PurePosixPath(name).suffix[:16]
        name = name[: _MAX_DISPLAY_NAME - len(suffix)] + suffix
    return name


def validate_upload(filename: str | None, data: bytes, *, max_bytes: int) -> ValidatedUpload:
    name = sanitize_filename(filename)
    extension = PurePosixPath(name).suffix.lower()
    if extension not in ALLOWED_TYPES:
        raise UnsupportedFileTypeError(
            "Only PDF, DOCX, TXT and Markdown (.md) files are supported."
        )
    if not data:
        raise InvalidFileError("The file is empty.")
    if len(data) > max_bytes:
        raise FileTooLargeError(
            f"The file is larger than the {max_bytes // (1024 * 1024)} MB limit."
        )

    if extension == ".pdf":
        _check_pdf(data)
    elif extension == ".docx":
        _check_docx(data)
    else:
        _check_text(data)

    return ValidatedUpload(
        display_name=name, extension=extension, content_type=ALLOWED_TYPES[extension]
    )


def _check_pdf(data: bytes) -> None:
    if _PDF_MAGIC not in data[:_PDF_MAGIC_WINDOW]:
        raise InvalidFileError("The file is not a valid PDF.")


def _check_docx(data: bytes) -> None:
    if not data.startswith(_ZIP_MAGIC):
        raise InvalidFileError("The file is not a valid Word (.docx) document.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        raise InvalidFileError("The file is not a valid Word (.docx) document.") from None
    if "word/document.xml" not in names:
        raise InvalidFileError("The file is not a valid Word (.docx) document.")


def _check_text(data: bytes) -> None:
    if b"\x00" in data:  # NUL bytes mean a binary file with a text extension
        raise InvalidFileError("The file does not look like a text file.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InvalidFileError(
            "The file is not valid UTF-8 text. Save it as UTF-8 and retry."
        ) from None
    if not text.strip():
        raise InvalidFileError("The file contains no text.")
