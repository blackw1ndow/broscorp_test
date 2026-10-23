"""Documents waiting for the animal's answer: its real name (R15) or the place (R16, D26).

Each document is a separate row, so an album processed in parallel loses nothing, and taking a
document deletes it, so a button pressed twice does nothing the second time.
"""

import json
from typing import Any, Literal

import asyncpg

WaitsFor = Literal["name", "place"]
NAME: WaitsFor = "name"
PLACE: WaitsFor = "place"


async def add(
    conn: asyncpg.Connection, user_id: int, waits_for: WaitsFor, data: dict[str, Any]
) -> int:
    return await conn.fetchval(
        "INSERT INTO waiting_documents (user_id, waits_for, data) VALUES ($1, $2, $3::jsonb)"
        " RETURNING id",
        user_id,
        waits_for,
        json.dumps(data, ensure_ascii=False),
    )


async def take(
    conn: asyncpg.Connection, user_id: int, waits_for: WaitsFor, waiting_id: int
) -> dict[str, Any] | None:
    """The document stops waiting; None if it was already taken or belongs to someone else."""
    raw = await conn.fetchval(
        """
        DELETE FROM waiting_documents
        WHERE id = $1 AND user_id = $2 AND waits_for = $3
        RETURNING data
        """,
        waiting_id,
        user_id,
        waits_for,
    )
    return json.loads(raw) if raw else None


async def take_all(
    conn: asyncpg.Connection, user_id: int, waits_for: WaitsFor
) -> list[dict[str, Any]]:
    """Every such document of the animal, in the order they were sent."""
    rows = await conn.fetch(
        """
        WITH taken AS (
            DELETE FROM waiting_documents WHERE user_id = $1 AND waits_for = $2
            RETURNING id, data
        )
        SELECT data FROM taken ORDER BY id
        """,
        user_id,
        waits_for,
    )
    return [json.loads(r["data"]) for r in rows]


async def drop_all(conn: asyncpg.Connection, user_id: int) -> int:
    """/start (D28): forget every waiting document. Returns how many were dropped."""
    return await conn.fetchval(
        """
        WITH dropped AS (DELETE FROM waiting_documents WHERE user_id = $1 RETURNING 1)
        SELECT count(*) FROM dropped
        """,
        user_id,
    )
