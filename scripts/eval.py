"""Runs the scenarios from docs/requirements.md §3 against the real Groq and prints the answers.

    docker compose run --rm bot python scripts/eval.py [number ...]

Manual quality check, not a test: it spends the Groq quota (~2 questions a minute on the free
tier). Every scenario runs as a separate animal, so the history of one does not leak into another.
"""

import asyncio
import logging
import sys

from forest_bot.bot import texts
from forest_bot.config import Settings
from forest_bot.db.migrate import run_migrations
from forest_bot.db.pool import create_pool
from forest_bot.db.repositories import users
from forest_bot.embeddings import Embedder
from forest_bot.ingestion.archive_seed import seed_archive
from forest_bot.llm.client import LLMClient
from forest_bot.qa.service import QAService

SCENARIOS = [
    ("Як перейти річку біля бобрової греблі?", "Тільки по греблі, вбрід — ніколи (R10)"),
    ("Коли йти по гриби під вербою?", "Обидві поради: листяний 4–5 день, річка — наступного (D15)"),
    ("Коли йти по гриби на узліссі?", "Лише загальна: після дощу, земля волога, не хлюпає (R18)"),
    ("Коли йти по гриби у соснах?", "На 2–3 день після дощу (хвойний путівник)"),
    ("Як утеплити рукавичку під дубом?", "Сухим дубовим листям у дві лапи, до першого снігу"),
    ("Коли утеплювати рукавичку?", "Перепитати про рукавичку (R10a)"),
    ("Скільки внесок під дубом?", "4 жолуді до 10 числа Кабанові; 2 горіхи; малеча не платить"),
    ("Скільки внесок?", "Перепитати про рукавичку (R10a)"),
    ("Що робити при пожежі?", "Бігти до річки проти вітру, збір біля бобрової греблі"),
    ("Хто голова ОСМД у соснах?", "Вовчик"),
    ("Хто приймає внески у соснах?", "Синиця, 2 шишки щотижня, взимку вдвічі менше (скан)"),
    ("Що означає, коли Сорока скрекоче двічі у ліщині?", "Поруч чужий звір (скан)"),
    ("Чи можна зараз збирати гриби?", "Сьогоднішня дата + Календар сезонів (D9)"),
    ("Як приготувати борщ?", "В архіві такої поради немає (D3, D12)"),
]


async def main(selected: set[int]) -> None:
    settings = Settings()
    logging.basicConfig(level=logging.WARNING)
    await run_migrations(settings.database_url, settings.migrations_dir)
    pool = await create_pool(settings.database_url)
    try:
        embedder = Embedder()
        await seed_archive(pool, embedder, settings.archive_dir)
        qa = QAService(
            pool,
            embedder,
            LLMClient(settings.groq_api_key.get_secret_value()),
            router_model=settings.groq_fast_model,
            answer_model=settings.groq_answer_model,
        )
        for number, (question, expected) in enumerate(SCENARIOS, start=1):
            if selected and number not in selected:
                continue
            user_id = -number  # Telegram ids are positive: no clash with real animals
            async with pool.acquire() as conn:
                await users.ensure_user(conn, user_id)
            print(f"\n=== {number}. {question}\nОчікується: {expected}")
            route = await qa.route(user_id, question)
            print(f"Розбір: {route}")
            if not route.is_forest_question:
                print(f"Бот: {texts.NOT_ABOUT_FOREST}")
            elif route.must_ask_place:
                print(f"Бот: {texts.ASK_MITTEN}")
            else:
                answer = await qa.answer(
                    user_id, question, route.question, route.place, route.doc_types
                )
                print(f"Бот: {texts.answer(answer) if answer.found else texts.NOT_FOUND}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main({int(arg) for arg in sys.argv[1:]}))
