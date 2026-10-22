import asyncio
import logging

from forest_bot.config import Settings
from forest_bot.db.migrate import run_migrations
from forest_bot.db.pool import create_pool
from forest_bot.embeddings import Embedder
from forest_bot.ingestion.archive_seed import seed_archive

log = logging.getLogger("forest_bot")


async def main() -> None:
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    await run_migrations(settings.database_url, settings.migrations_dir)
    pool = await create_pool(settings.database_url)
    try:
        embedder = Embedder()
        await seed_archive(pool, embedder, settings.archive_dir)
        # The Telegram part is the next step; for now the process stops after indexing
        log.info("Archive is indexed; the bot itself is not implemented yet")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
