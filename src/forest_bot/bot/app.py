"""Dispatcher setup: private chats only, the user middleware, routers and error replies."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg
from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import ExceptionTypeFilter
from aiogram.types import BotCommand, ErrorEvent, TelegramObject, User

from forest_bot.bot import texts
from forest_bot.bot.handlers import commands, documents, fallback, names, questions
from forest_bot.db.fsm_storage import PostgresStorage
from forest_bot.db.repositories import users
from forest_bot.ingestion.service import IngestionService
from forest_bot.llm.client import LLMBusyError
from forest_bot.qa.service import QAService

log = logging.getLogger(__name__)


class UserMiddleware(BaseMiddleware):
    """Registers the animal on first contact and passes its real name as `user_name`."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is not None:
            async with self._pool.acquire() as conn:
                data["user_name"] = await users.ensure_user(conn, user.id)
        return await handler(event, data)


def create_dispatcher(pool: asyncpg.Pool, qa: QAService, ingestion: IngestionService) -> Dispatcher:
    dp = Dispatcher(storage=PostgresStorage(pool), pool=pool, qa=qa, ingestion=ingestion)

    # Private chats only (R2): updates from groups are not handled at all
    dp.message.filter(F.chat.type == ChatType.PRIVATE)
    dp.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

    # Inner middlewares run after the filters, so group chats never reach the database
    dp.message.middleware(UserMiddleware(pool))
    dp.callback_query.middleware(UserMiddleware(pool))

    # Order matters: state-specific handlers before plain text, the catch-all last
    dp.include_routers(
        commands.router, names.router, documents.router, questions.router, fallback.router
    )
    dp.errors.register(on_busy, ExceptionTypeFilter(LLMBusyError))
    dp.errors.register(on_error)
    return dp


async def on_busy(event: ErrorEvent) -> None:
    log.warning("Groq is busy: %s", event.exception)
    await _reply(event, texts.BUSY)


async def on_error(event: ErrorEvent) -> None:
    log.exception("Update %s failed", event.update.update_id, exc_info=event.exception)
    await _reply(event, texts.ERROR)


async def _reply(event: ErrorEvent, text: str) -> None:
    update = event.update
    if update.message is not None:
        await update.message.answer(text)
    elif update.callback_query is not None and update.callback_query.message is not None:
        await update.callback_query.message.answer(text)


async def run_bot(
    token: str, pool: asyncpg.Pool, qa: QAService, ingestion: IngestionService
) -> None:
    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = create_dispatcher(pool, qa, ingestion)
    await bot.set_my_commands(
        [BotCommand(command=name, description=text) for name, text in texts.COMMANDS.items()]
    )
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
