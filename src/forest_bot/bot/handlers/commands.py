"""/start, /help, /docs and /my_docs with deletion (D5, D18, D25)."""

import asyncpg
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from forest_bot.bot import texts
from forest_bot.bot.keyboards import DeleteDocument, delete_keyboard
from forest_bot.db.repositories import documents

router = Router(name="commands")


@router.message(CommandStart())
async def on_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.START)


@router.message(Command("help"))
async def on_help(message: Message) -> None:
    await message.answer(texts.HELP)


@router.message(Command("docs"))
async def on_docs(message: Message, pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        docs = await documents.list_active(conn)
    if not docs:
        await message.answer(texts.NO_DOCUMENTS)
        return
    for part in texts.split_message(texts.all_documents(docs)):
        await message.answer(part)


@router.message(Command("my_docs"))
async def on_my_docs(message: Message, pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        docs = await documents.list_active(conn, author_id=message.from_user.id)
    if not docs:
        await message.answer(texts.NO_OWN_DOCUMENTS)
        return
    await message.answer(texts.own_documents(docs), reply_markup=delete_keyboard(docs))


@router.callback_query(DeleteDocument.filter())
async def on_delete(
    callback: CallbackQuery, callback_data: DeleteDocument, pool: asyncpg.Pool
) -> None:
    user_id = callback.from_user.id
    async with pool.acquire() as conn:
        async with conn.transaction():
            deleted, restored = await documents.delete_own(conn, callback_data.id, user_id)
        remaining = await documents.list_active(conn, author_id=user_id)
    if deleted is None:
        # Already deleted, or not this animal's document (D5)
        await callback.answer(texts.STALE_BUTTON)
        return
    await callback.answer()
    if remaining:
        await callback.message.edit_text(
            texts.own_documents(remaining), reply_markup=delete_keyboard(remaining)
        )
    else:
        await callback.message.edit_text(texts.NO_OWN_DOCUMENTS)
    await callback.message.answer(texts.document_deleted(deleted.title, restored))
