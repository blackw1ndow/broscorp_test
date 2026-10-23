"""The animal's real name (R15, R15a) and changing it with /name (D14)."""

import re

import asyncpg
from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from forest_bot.bot import texts
from forest_bot.bot.handlers.documents import process_document
from forest_bot.bot.keyboards import Dialog
from forest_bot.db.repositories import users
from forest_bot.ingestion.service import IngestionService

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
    await message.answer(texts.name_saved(name))

    # The first document was waiting for the name: carry on with it
    if await state.get_state() == Dialog.name_for_document.state:
        data = await state.get_data()
        await state.clear()
        await process_document(
            message, state, bot, ingestion, data["file_id"], data["file_name"], data["caption"]
        )
    elif await state.get_state() == Dialog.name.state:
        await state.clear()
