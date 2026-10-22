"""Applies numbered .sql files from migrations/ exactly once, in order."""

import asyncio
import logging
from pathlib import Path

import asyncpg

log = logging.getLogger(__name__)

# Any constant works; it only has to be the same for every bot instance
_LOCK_ID = 42_1013


async def run_migrations(database_url: str, migrations_dir: Path) -> list[str]:
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute("SELECT pg_advisory_lock($1)", _LOCK_ID)
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        applied = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
        newly_applied = []
        for path in await asyncio.to_thread(lambda: sorted(migrations_dir.glob("*.sql"))):
            if path.stem in applied:
                continue
            sql = await asyncio.to_thread(path.read_text, encoding="utf-8")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", path.stem)
            log.info("Applied migration %s", path.name)
            newly_applied.append(path.stem)
        return newly_applied
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", _LOCK_ID)
        await conn.close()
