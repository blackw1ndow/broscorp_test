import asyncpg


async def ensure_user(conn: asyncpg.Connection, telegram_id: int) -> str | None:
    """Creates the user on first contact. Returns the real name (R15) if it is known.

    Runs for every update, so a known user is only read: DO UPDATE would write a new row
    version each time. A new user has no name yet, so losing an insert race returns None too.
    """
    return await conn.fetchval(
        """
        WITH existing AS (
            SELECT display_name FROM users WHERE telegram_id = $1
        ), inserted AS (
            INSERT INTO users (telegram_id)
            SELECT $1 WHERE NOT EXISTS (SELECT 1 FROM existing)
            ON CONFLICT (telegram_id) DO NOTHING
            RETURNING display_name
        )
        SELECT display_name FROM existing
        UNION ALL
        SELECT display_name FROM inserted
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
