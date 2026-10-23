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


@dataclass(frozen=True)
class DocumentInfo:
    id: int
    title: str
    doc_type: str
    place_code: str
    source: str
    author: str | None  # the author's current real name (D14); None for the archive
    uploaded_at: datetime


_INFO_COLUMNS = """
    d.id, d.title, d.doc_type, d.place_code, d.source, u.display_name AS author, d.uploaded_at
"""
_INFO_FROM = "FROM documents d LEFT JOIN users u ON u.telegram_id = d.author_id"


def _info(row: asyncpg.Record | None) -> DocumentInfo | None:
    return DocumentInfo(**dict(row)) if row else None


async def find_active(
    conn: asyncpg.Connection, doc_type: str, place_code: str
) -> DocumentInfo | None:
    row = await conn.fetchrow(
        f"SELECT {_INFO_COLUMNS} {_INFO_FROM}"
        " WHERE d.status = 'active' AND d.doc_type = $1 AND d.place_code = $2",
        doc_type,
        place_code,
    )
    return _info(row)


async def find_active_by_hash(
    conn: asyncpg.Connection, file_sha256: str, place_code: str
) -> DocumentInfo | None:
    row = await conn.fetchrow(
        f"SELECT {_INFO_COLUMNS} {_INFO_FROM}"
        " WHERE d.status = 'active' AND d.file_sha256 = $1 AND d.place_code = $2",
        file_sha256,
        place_code,
    )
    return _info(row)


async def list_active(
    conn: asyncpg.Connection, place_code: str | None = None, author_id: int | None = None
) -> list[DocumentInfo]:
    rows = await conn.fetch(
        f"SELECT {_INFO_COLUMNS} {_INFO_FROM}"
        """
        WHERE d.status = 'active'
          AND ($1::text IS NULL OR d.place_code = $1)
          AND ($2::bigint IS NULL OR d.author_id = $2)
        ORDER BY d.title
        """,
        place_code,
        author_id,
    )
    return [DocumentInfo(**dict(row)) for row in rows]


# D29: the catalog goes into the prompt of every question. Types made from animals' titles are
# bounded: only the most recent ones, and only short ones (the longest archive type is ~40 chars)
ROUTER_USER_TYPES = 20
ROUTER_TYPE_MAX_CHARS = 60


async def doc_types_by_level(conn: asyncpg.Connection) -> dict[str, list[str]]:
    """Active document types grouped by place level: tells the router which advice differs
    between places (R10a). Archive types always; types only animals use, within D29 bounds."""
    rows = await conn.fetch(
        """
        WITH types AS (
            SELECT p.level, d.doc_type, max(d.uploaded_at) AS latest,
                   EXISTS (
                       SELECT 1 FROM documents a
                       WHERE a.source = 'archive' AND a.doc_type = d.doc_type
                   ) AS from_archive
            FROM documents d JOIN places p ON p.code = d.place_code
            WHERE d.status = 'active'
            GROUP BY p.level, d.doc_type
        ), user_types AS (
            SELECT level, doc_type FROM types
            WHERE NOT from_archive AND length(doc_type) <= $2
            ORDER BY latest DESC
            LIMIT $1
        )
        SELECT level, doc_type FROM types WHERE from_archive
        UNION
        SELECT level, doc_type FROM user_types
        ORDER BY level, doc_type
        """,
        ROUTER_USER_TYPES,
        ROUTER_TYPE_MAX_CHARS,
    )
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(row["level"], []).append(row["doc_type"])
    return result


async def supersede(conn: asyncpg.Connection, document_id: int) -> bool:
    """Marks the old version as replaced (R11). Call inside the transaction of the new insert."""
    status = await conn.execute(
        "UPDATE documents SET status = 'superseded' WHERE id = $1 AND status = 'active'",
        document_id,
    )
    return status == "UPDATE 1"


async def delete_own(
    conn: asyncpg.Connection, document_id: int, author_id: int
) -> tuple[DocumentInfo | None, DocumentInfo | None]:
    """Deletes an active document of this author (D5) and makes the version it replaced active
    again (D25). Returns (deleted, restored). Call inside a transaction."""
    deleted = await conn.fetchrow(
        """
        UPDATE documents SET status = 'deleted'
        WHERE id = $1 AND author_id = $2 AND status = 'active'
        RETURNING id, replaces_id
        """,
        document_id,
        author_id,
    )
    if deleted is None:
        return None, None
    restored = None
    if deleted["replaces_id"] is not None:
        status = await conn.execute(
            "UPDATE documents SET status = 'active' WHERE id = $1 AND status = 'superseded'",
            deleted["replaces_id"],
        )
        if status == "UPDATE 1":
            restored = await get_info(conn, deleted["replaces_id"])
    return await get_info(conn, document_id), restored


async def get_info(conn: asyncpg.Connection, document_id: int) -> DocumentInfo | None:
    row = await conn.fetchrow(f"SELECT {_INFO_COLUMNS} {_INFO_FROM} WHERE d.id = $1", document_id)
    return _info(row)
