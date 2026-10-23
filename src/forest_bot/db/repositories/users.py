import asyncpg


async def ensure_user(conn: asyncpg.Connection, telegram_id: int) -> str | None:
    """Creates the user on first contact. Returns the real name (R15) if it is known."""
    return await conn.fetchval(
        """
        INSERT INTO users (telegram_id) VALUES ($1)
        ON CONFLICT (telegram_id) DO UPDATE SET telegram_id = EXCLUDED.telegram_id
        RETURNING display_name
        """,
        telegram_id,
    )


async def set_display_name(conn: asyncpg.Connection, telegram_id: int, name: str) -> None:
    await conn.execute(
        """
        INSERT INTO users (telegram_id, display_name) VALUES ($1, $2)
        ON CONFLICT (telegram_id) DO UPDATE SET display_name = $2, updated_at = now()
        """,
        telegram_id,
        name,
    )
