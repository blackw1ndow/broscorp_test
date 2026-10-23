import asyncio
import logging
import sys

from forest_bot.bot.app import run_bot
from forest_bot.config import Settings
from forest_bot.db.migrate import run_migrations
from forest_bot.db.pool import create_pool
from forest_bot.embeddings import Embedder
from forest_bot.ingestion.archive_seed import seed_archive
from forest_bot.ingestion.service import IngestionService
from forest_bot.llm.client import LLMClient
from forest_bot.qa.service import QAService

log = logging.getLogger("forest_bot")


async def main() -> None:
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    if settings.telegram_bot_token is None or settings.groq_api_key is None:
        log.error("TELEGRAM_BOT_TOKEN and GROQ_API_KEY must be set (see .env.example)")
        sys.exit(1)

    await run_migrations(settings.database_url, settings.migrations_dir)
    pool = await create_pool(settings.database_url)
    try:
        embedder = Embedder()
        await seed_archive(pool, embedder, settings.archive_dir)

        llm = LLMClient(settings.groq_api_key.get_secret_value())
        qa = QAService(
            pool,
            embedder,
            llm,
            router_model=settings.groq_fast_model,
            answer_model=settings.groq_answer_model,
        )
        ingestion = IngestionService(pool, embedder, llm, settings.groq_fast_model)
        log.info("Starting the bot")
        await run_bot(settings.telegram_bot_token.get_secret_value(), pool, qa, ingestion)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
