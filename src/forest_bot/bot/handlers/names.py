"""The animal's real name (R15, R15a) and changing it with /name (D14)."""

import logging
import re

import asyncpg
from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from forest_bot.bot import texts
from forest_bot.bot.handlers.documents import process_document
from forest_bot.bot.keyboards import Dialog
from forest_bot.db.repositories import users, waiting
from forest_bot.ingestion.service import IngestionService

log = logging.getLogger(__name__)

router = Router(name="names")


def clean_name(text: str | None) -> str | None:
    name = re.sub(r"\s+", " ", text or "").strip()
    if not 2 <= len(name) <= 64 or name.startswith("/"):
        return None
    return name


@router.message(Command("name"))
async def on_name_command(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    bot: Bot,
    pool: asyncpg.Pool,
    ingestion: IngestionService,
) -> None:
    if not command.args:
        if await state.get_state() != Dialog.name_for_document.state:
            await state.set_state(Dialog.name)
        await message.answer(texts.ASK_NAME)
        return
    await _set_name(
        message, message_text=command.args, state=state, bot=bot, pool=pool, ingestion=ingestion
    )


@router.message(Dialog.name, F.text & ~F.text.startswith("/"))
@router.message(Dialog.name_for_document, F.text & ~F.text.startswith("/"))
async def on_name(
    message: Message, state: FSMContext, bot: Bot, pool: asyncpg.Pool, ingestion: IngestionService
) -> None:
    await _set_name(
        message, message_text=message.text, state=state, bot=bot, pool=pool, ingestion=ingestion
    )


async def _set_name(
    message: Message,
    *,
    message_text: str,
    state: FSMContext,
    bot: Bot,
    pool: asyncpg.Pool,
    ingestion: IngestionService,
) -> None:
    name = clean_name(message_text)
    if name is None:
        await message.answer(texts.BAD_NAME)
        return
    async with pool.acquire() as conn:
        await users.set_display_name(conn, message.from_user.id, name)
        # Documents sent before the animal had a name: all of them, not only the last (D26)
        files = await waiting.take_all(conn, message.from_user.id, waiting.NAME)
    await message.answer(texts.name_saved(name))

    if await state.get_state() in (Dialog.name.state, Dialog.name_for_document.state):
        # Only the state: a question waiting for its mitten stays in the data
        await state.set_state(None)
    for file in files:
        # They were all taken from waiting at once: one failure must not lose the others
        try:
            await process_document(
                message, bot, ingestion, pool, file["file_id"], file["file_name"], file["caption"]
            )
        except Exception:
            log.exception("Document %s waiting for the name failed", file["file_name"])
            await message.answer(texts.document_failed(file["file_name"]))
