import io
import uuid
import zipfile
from pathlib import Path
from typing import Any

import pytest

from app.rag.chunking import normalize_text, split_text
from app.rag.loaders import DocumentValidationError, ExtractionError, extract_text, file_type_for
from app.rag.retrieval import DocumentRetriever, document_scope_filter, format_chunks
from app.rag.vector_store import DOCUMENTS_COLLECTION, ChromaVectorStore, VectorRecord
from app.services.document_service import display_filename
from app.storage import LocalStorage, S3Storage, StorageError


def _docx(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>",
        )
    return buffer.getvalue()


def _pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return out.getvalue()


@pytest.mark.parametrize("name", ["a.pdf", "A.DOCX", "notes.txt", "x.md", "s.py", "d.csv"])
def test_supported_extensions(name: str) -> None:
    assert file_type_for(name)


@pytest.mark.parametrize("name", ["x.exe", "x.pdf.exe", "noext", "x.html"])
def test_unsupported_extensions(name: str) -> None:
    with pytest.raises(DocumentValidationError):
        file_type_for(name)


def test_text_validation_rejects_binary_and_non_utf8() -> None:
    txt = file_type_for("a.txt")
    txt.validate(b"hello\nworld")
    with pytest.raises(DocumentValidationError):
        txt.validate(b"\x00\x01binary")
    with pytest.raises(DocumentValidationError):
        txt.validate("café".encode("latin-1"))


def test_pdf_magic_bytes_required() -> None:
    with pytest.raises(DocumentValidationError):
        file_type_for("a.pdf").validate(b"MZ\x90\x00 not a pdf")


def test_pdf_extraction() -> None:
    pdf = file_type_for("a.pdf")
    data = _pdf("Quarterly revenue grew")
    pdf.validate(data)
    assert "Quarterly revenue grew" in extract_text(data, pdf)


def test_corrupt_pdf_raises_extraction_error() -> None:
    with pytest.raises(ExtractionError):
        extract_text(b"%PDF-1.4 garbage", file_type_for("a.pdf"))


def test_docx_validation_and_extraction() -> None:
    docx = file_type_for("a.docx")
    data = _docx("Hello from Word")
    docx.validate(data)
    assert "Hello from Word" in extract_text(data, docx)
    with pytest.raises(DocumentValidationError):
        docx.validate(b"PK\x03\x04 broken zip")


def test_normalize_and_split() -> None:
    raw = "Title\r\n\r\n\r\n\r\nBody\x00 text   with   spaces \t\nend"
    assert normalize_text(raw) == "Title\n\nBody text with spaces\nend"
    chunks = split_text("word " * 1000, chunk_size=900, chunk_overlap=150)
    assert len(chunks) > 1
    assert all(len(c) <= 900 for c in chunks)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\boot.ini", "boot.ini"),
        ("report<1>.pdf", "report1.pdf"),
        ("", "document"),
        (None, "document"),
    ],
)
def test_display_filename_strips_paths(raw: str | None, expected: str) -> None:
    assert display_filename(raw) == expected


async def test_local_storage_roundtrip_and_traversal(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    await storage.save("users/u/doc.txt", b"data", "text/plain")
    assert await storage.read("users/u/doc.txt") == b"data"
    assert await storage.exists("users/u/doc.txt")
    await storage.delete("users/u/doc.txt")
    assert not await storage.exists("users/u/doc.txt")
    for bad in ["../escape.txt", "/etc/passwd", "users/../../x", "a//b"]:
        with pytest.raises(StorageError):
            await storage.save(bad, b"x", "text/plain")


class _FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:  # noqa: N803
        self.objects[Key] = Body

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        return {"Body": io.BytesIO(self.objects[Key])}

    def delete_object(self, Bucket: str, Key: str) -> None:  # noqa: N803
        self.objects.pop(Key, None)

    def head_object(self, Bucket: str, Key: str) -> None:  # noqa: N803
        if Key not in self.objects:
            raise KeyError(Key)


async def test_s3_storage_uses_prefix() -> None:
    client = _FakeS3()
    storage = S3Storage(client, "bucket", prefix="kaygpt/")
    await storage.save("users/u/a.pdf", b"pdf", "application/pdf")
    assert "kaygpt/users/u/a.pdf" in client.objects
    assert await storage.read("users/u/a.pdf") == b"pdf"
    await storage.delete("users/u/a.pdf")
    assert not await storage.exists("users/u/a.pdf")


async def test_retrieval_is_scoped_by_user_and_conversation(
    vector_store: ChromaVectorStore,
) -> None:
    alice, bob = uuid.uuid4(), uuid.uuid4()
    chat_a, chat_b = uuid.uuid4(), uuid.uuid4()

    def rec(user: uuid.UUID, conv: uuid.UUID | None, text: str) -> VectorRecord:
        return VectorRecord(
            id=f"{uuid.uuid4()}:0",
            text=text,
            metadata={
                "user_id": str(user),
                "conversation_id": str(conv) if conv else "",
                "document_id": str(uuid.uuid4()),
                "filename": f"{text}.txt",
                "chunk_index": 0,
            },
        )

    await vector_store.upsert(
        DOCUMENTS_COLLECTION,
        [
            rec(alice, chat_a, "alice chat a secret"),
            rec(alice, chat_b, "alice chat b secret"),
            rec(alice, None, "alice global note"),
            rec(bob, chat_a, "bob secret"),
        ],
    )
    retriever = DocumentRetriever(vector_store, top_k=10)
    found = {
        c.text
        for c in await retriever.search(user_id=alice, conversation_id=chat_a, query="secret")
    }
    assert found == {"alice chat a secret", "alice global note"}
    assert document_scope_filter(alice, None)["$and"][1] == {"conversation_id": {"$in": [""]}}
    assert format_chunks([]) == "No relevant uploaded document content found."
