"""Text normalization and chunking."""

from __future__ import annotations

import re
import unicodedata

from langchain_text_splitters import RecursiveCharacterTextSplitter

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TRAILING_WS = re.compile(r"[ \t]+\n")
_MANY_BLANK_LINES = re.compile(r"\n{3,}")
_MANY_SPACES = re.compile(r"[ \t]{2,}")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    text = _TRAILING_WS.sub("\n", text)
    text = _MANY_SPACES.sub(" ", text)
    text = _MANY_BLANK_LINES.sub("\n\n", text)
    return text.strip()


def split_text(text: str, *, chunk_size: int = 900, chunk_overlap: int = 150) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return [chunk for chunk in splitter.split_text(text) if chunk.strip()]
