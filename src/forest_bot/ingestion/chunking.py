"""Splits a document into chunks for vector search.

Archive documents are about a page long and stay whole. Long guides are split by paragraphs;
every chunk starts with the document title so it keeps its context when retrieved alone.
"""

import re
from collections.abc import Iterator

SINGLE_CHUNK_MAX_CHARS = 1500
TARGET_CHUNK_CHARS = 800


def chunk_text(title: str, text: str) -> list[str]:
    body = text.strip()
    if body.startswith(title):
        body = body[len(title) :].strip()
    if len(body) <= SINGLE_CHUNK_MAX_CHARS:
        return [f"{title}\n\n{body}".strip()]

    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in _paragraphs(body):
        if current and size + len(paragraph) > TARGET_CHUNK_CHARS:
            chunks.append("\n\n".join(current))
            # Overlap: the last paragraph also opens the next chunk
            current = [current[-1]] if len(current[-1]) < TARGET_CHUNK_CHARS // 2 else []
            size = sum(len(p) for p in current)
        current.append(paragraph)
        size += len(paragraph)
    if current:
        chunks.append("\n\n".join(current))
    return [f"{title}\n\n{chunk}" for chunk in chunks]


def _paragraphs(text: str) -> list[str]:
    paragraphs = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        if len(block) <= TARGET_CHUNK_CHARS:
            paragraphs.append(block)
            continue
        # A huge paragraph is split by sentences and lines (a DOCX table has only lines)
        piece = ""
        for separator, part in _pieces(block):
            if piece and len(piece) + len(separator) + len(part) > TARGET_CHUNK_CHARS:
                paragraphs.append(piece)
                piece = ""
            piece = f"{piece}{separator}{part}" if piece else part
        if piece:
            paragraphs.append(piece)
    return paragraphs


def _pieces(block: str) -> Iterator[tuple[str, str]]:
    """(separator, piece) pairs, none longer than a chunk, so no chunk grows without bound."""
    for line in block.split("\n"):
        separator = "\n"
        for sentence in re.split(r"(?<=[.!?])\s+", line.strip()):
            for part in _cut(sentence):
                yield separator, part
                separator = " "


def _cut(text: str) -> Iterator[str]:
    """A sentence longer than a chunk is cut at spaces, or anywhere if it has none."""
    while len(text) > TARGET_CHUNK_CHARS:
        cut = text.rfind(" ", 0, TARGET_CHUNK_CHARS)
        if cut <= 0:
            cut = TARGET_CHUNK_CHARS
        yield text[:cut]
        text = text[cut:].lstrip()
    if text:
        yield text
