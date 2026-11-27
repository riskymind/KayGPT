"""Upload validation and text extraction for supported document types."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from dataclasses import dataclass


class DocumentValidationError(ValueError):
    pass


class ExtractionError(ValueError):
    pass


@dataclass(frozen=True)
class FileType:
    extension: str
    content_type: str
    validate: Callable[[bytes], None]
    extract: Callable[[bytes], str]


def _validate_pdf(data: bytes) -> None:
    if not data[:1024].lstrip().startswith(b"%PDF-"):
        raise DocumentValidationError("File is not a valid PDF.")


def _validate_docx(data: bytes) -> None:
    if not data.startswith(b"PK\x03\x04"):
        raise DocumentValidationError("File is not a valid DOCX document.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            if "word/document.xml" not in names:
                raise DocumentValidationError("File is not a valid DOCX document.")
            # Zip-bomb guard: refuse archives that inflate past 50x or 200 MB.
            inflated = sum(info.file_size for info in archive.infolist())
            if inflated > max(len(data) * 50, 1) or inflated > 200 * 1024 * 1024:
                raise DocumentValidationError("DOCX archive is too large when decompressed.")
    except zipfile.BadZipFile as exc:
        raise DocumentValidationError("File is not a valid DOCX document.") from exc


def _validate_text(data: bytes) -> None:
    if b"\x00" in data:
        raise DocumentValidationError("Text file contains binary data.")
    try:
        data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentValidationError("Text files must be UTF-8 encoded.") from exc


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractionError("Encrypted PDFs are not supported.")
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError("Could not read the PDF.") from exc


def _extract_docx(data: bytes) -> str:
    import docx2txt

    try:
        return str(docx2txt.process(io.BytesIO(data)) or "")
    except Exception as exc:
        raise ExtractionError("Could not read the DOCX document.") from exc


def _extract_text(data: bytes) -> str:
    return data.decode("utf-8-sig")


FILE_TYPES: dict[str, FileType] = {
    ".pdf": FileType(".pdf", "application/pdf", _validate_pdf, _extract_pdf),
    ".docx": FileType(
        ".docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        _validate_docx,
        _extract_docx,
    ),
    ".txt": FileType(".txt", "text/plain", _validate_text, _extract_text),
    ".md": FileType(".md", "text/markdown", _validate_text, _extract_text),
    ".py": FileType(".py", "text/x-python", _validate_text, _extract_text),
    ".csv": FileType(".csv", "text/csv", _validate_text, _extract_text),
}

SUPPORTED_EXTENSIONS = tuple(FILE_TYPES)


def file_type_for(filename: str) -> FileType:
    name = filename.lower().strip()
    for extension, file_type in FILE_TYPES.items():
        if name.endswith(extension):
            return file_type
    raise DocumentValidationError("Unsupported file type. Upload PDF, DOCX, TXT, MD, PY, or CSV.")


def extract_text(data: bytes, file_type: FileType) -> str:
    return file_type.extract(data)
