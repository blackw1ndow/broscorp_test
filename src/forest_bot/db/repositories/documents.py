from dataclasses import dataclass
from datetime import datetime

import asyncpg
import numpy as np


@dataclass(frozen=True)
class NewDocument:
    title: str
    doc_type: str
    place_code: str
    source: str  # 'archive' | 'user'
    author_id: int | None
    file_name: str
    file_sha256: str
    extraction: str  # 'text' | 'ocr'
    full_text: str
    uploaded_at: datetime


async def archive_hashes(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("SELECT file_sha256 FROM documents WHERE source = 'archive'")
    return {row["file_sha256"] for row in rows}


async def insert_document(
    conn: asyncpg.Connection,
    doc: NewDocument,
    chunks: list[str],
    embeddings: list[np.ndarray],
    replaces_id: int | None = None,
) -> int:
    """Inserts a document with its chunks. Call inside a transaction."""
    document_id: int = await conn.fetchval(
        """
        INSERT INTO documents (title, doc_type, place_code, source, author_id, file_name,
                               file_sha256, extraction, full_text, uploaded_at, replaces_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        RETURNING id
        """,
        doc.title,
        doc.doc_type,
        doc.place_code,
        doc.source,
        doc.author_id,
        doc.file_name,
        doc.file_sha256,
        doc.extraction,
        doc.full_text,
        doc.uploaded_at,
        replaces_id,
    )
    await conn.executemany(
        "INSERT INTO chunks (document_id, position, content, embedding) VALUES ($1, $2, $3, $4)",
        [
            (document_id, position, content, embedding)
            for position, (content, embedding) in enumerate(zip(chunks, embeddings, strict=True))
        ],
    )
    return document_id
