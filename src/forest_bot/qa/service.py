"""Answering a question: history, routing, place-filtered search and the answer (flow 3.1)."""

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta

import asyncpg

from forest_bot.config import KYIV_TZ
from forest_bot.db.repositories import chunks, documents, messages
from forest_bot.embeddings import Embedder
from forest_bot.forest import applicable_places
from forest_bot.llm.client import LLMClient
from forest_bot.llm.prompts import ANSWER_SYSTEM
from forest_bot.qa.answer import NOT_FOUND, Answer, build_answer_prompt, parse_answer
from forest_bot.qa.router import Route, route_question

log = logging.getLogger(__name__)

TOP_K = 6
# Chunks of the document types the router named come first
TYPED_K = 4
MAX_FRAGMENTS = 7
HISTORY_MESSAGES = 6
HISTORY_MAX_AGE = timedelta(hours=1)


def today_in_kyiv() -> date:
    return datetime.now(KYIV_TZ).date()


class QAService:
    def __init__(
        self,
        pool: asyncpg.Pool,
        embedder: Embedder,
        llm: LLMClient,
        *,
        router_model: str,
        answer_model: str,
        today: Callable[[], date] = today_in_kyiv,
    ) -> None:
        self._pool = pool
        self._embedder = embedder
        self._llm = llm
        self._router_model = router_model
        self._answer_model = answer_model
        self._today = today

    async def route(self, user_id: int, text: str) -> Route:
        async with self._pool.acquire() as conn:
            history = await messages.recent_messages(
                conn, user_id, HISTORY_MESSAGES, HISTORY_MAX_AGE
            )
            doc_types = await documents.doc_types_by_level(conn)
        return await route_question(self._llm, self._router_model, text, history, doc_types)

    async def answer(
        self,
        user_id: int,
        asked: str,
        question: str,
        place: str | None,
        doc_types: tuple[str, ...] = (),
    ) -> Answer:
        """`asked` is what goes into the history; `question` is the standalone question."""
        [embedding] = await self._embedder.embed([question])
        places = applicable_places(place) if place else None
        async with self._pool.acquire() as conn:
            typed = (
                await chunks.search(conn, embedding, places, TYPED_K, list(doc_types))
                if doc_types
                else []
            )
            nearest = await chunks.search(conn, embedding, places, TOP_K)
        unique = {f.chunk_id: f for f in [*typed, *nearest]}
        fragments = list(unique.values())[:MAX_FRAGMENTS]

        answer = NOT_FOUND
        if fragments:
            raw = await self._llm.complete_json(
                self._answer_model,
                ANSWER_SYSTEM,
                build_answer_prompt(question, place, fragments, self._today()),
            )
            answer = parse_answer(raw, fragments)
        log.info(
            "Answer for %r (place %s): %d fragments, sources %s",
            question,
            place,
            len(fragments),
            [s.title for s in answer.sources],
        )

        async with self._pool.acquire() as conn, conn.transaction():
            await messages.add_message(conn, user_id, "user", asked)
            await messages.add_message(
                conn, user_id, "assistant", answer.text or "В архіві такої поради немає."
            )
        return answer

    async def remember_clarification(self, user_id: int, asked: str, reply: str) -> None:
        """The bot asked for the mitten: a reply like «під дубом» is then a follow-up (D8)."""
        async with self._pool.acquire() as conn, conn.transaction():
            await messages.add_message(conn, user_id, "user", asked)
            await messages.add_message(conn, user_id, "assistant", reply)
