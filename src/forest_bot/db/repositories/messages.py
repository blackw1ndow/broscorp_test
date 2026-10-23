"""Short conversation history, so follow-ups like «а під ялиною?» make sense (D8)."""

from dataclasses import dataclass
from datetime import timedelta

import asyncpg


@dataclass(frozen=True)
class HistoryMessage:
    role: str  # 'user' | 'assistant'
    content: str


async def add_message(conn: asyncpg.Connection, user_id: int, role: str, content: str) -> None:
    await conn.execute(
        "INSERT INTO messages (user_id, role, content) VALUES ($1, $2, $3)", user_id, role, content
    )


async def recent_messages(
    conn: asyncpg.Connection, user_id: int, limit: int, max_age: timedelta
) -> list[HistoryMessage]:
    """The last `limit` messages not older than `max_age`, oldest first."""
    rows = await conn.fetch(
        """
        SELECT role, content FROM messages
        WHERE user_id = $1 AND created_at > now() - $3::interval
        ORDER BY created_at DESC, id DESC
        LIMIT $2
        """,
        user_id,
        limit,
        max_age,
    )
    return [HistoryMessage(r["role"], r["content"]) for r in reversed(rows)]
