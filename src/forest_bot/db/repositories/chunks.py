from dataclasses import dataclass
from datetime import datetime

import asyncpg
import numpy as np


@dataclass(frozen=True)
class Fragment:
    chunk_id: int
    content: str
    document_id: int
    title: str
    place_code: str
    source: str
    author: str | None
    uploaded_at: datetime
    distance: float


async def search(
    conn: asyncpg.Connection,
    embedding: np.ndarray,
    places: list[str] | None,
    limit: int,
    doc_types: list[str] | None = None,
) -> list[Fragment]:
    """Nearest chunks of active documents; `places` is the SQL filter of applicable places (R9),
    `doc_types` optionally narrows it to documents of these types."""
    rows = await conn.fetch(
        """
        SELECT c.id AS chunk_id, c.content, d.id AS document_id, d.title, d.place_code, d.source,
               u.display_name AS author, d.uploaded_at, c.embedding <=> $1 AS distance
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        LEFT JOIN users u ON u.telegram_id = d.author_id
        WHERE d.status = 'active'
          AND ($2::text[] IS NULL OR d.place_code = ANY($2))
          AND ($4::text[] IS NULL OR d.doc_type = ANY($4))
        ORDER BY distance
        LIMIT $3
        """,
        embedding,
        places,
        limit,
        doc_types,
    )
    return [Fragment(**dict(row)) for row in rows]
