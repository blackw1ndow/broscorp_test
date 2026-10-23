"""/start, /help, /docs and /my_docs with deletion (D5, D18, D25)."""

import asyncpg
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from forest_bot.bot import texts
from forest_bot.bot.edits import edit_text
from forest_bot.bot.keyboards import (
    OWN_DOCUMENTS_PER_PAGE,
    DeleteDocument,
    OwnDocumentsPage,
    own_documents_keyboard,
)
from forest_bot.db.repositories import documents, waiting
from forest_bot.db.repositories.documents import DocumentInfo

router = Router(name="commands")


@router.message(CommandStart())
async def on_start(message: Message, state: FSMContext, pool: asyncpg.Pool) -> None:
    # Begin again (D28): forget the waiting question and documents, and say what was dropped
    await state.clear()
    async with pool.acquire() as conn:
        dropped = await waiting.drop_all(conn, message.from_user.id)
    await message.answer(texts.START)
    if dropped:
        await message.answer(texts.waiting_dropped(dropped))


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
    text, markup = _own_page(docs, 0)
    await message.answer(text, reply_markup=markup)


@router.callback_query(OwnDocumentsPage.filter())
async def on_own_documents_page(
    callback: CallbackQuery, callback_data: OwnDocumentsPage, pool: asyncpg.Pool
) -> None:
    async with pool.acquire() as conn:
        docs = await documents.list_active(conn, author_id=callback.from_user.id)
    await callback.answer()
    if not docs:
        await edit_text(callback, texts.NO_OWN_DOCUMENTS)
        return
    text, markup = _own_page(docs, callback_data.page)
    await edit_text(callback, text, reply_markup=markup)


def _own_page(docs: list[DocumentInfo], page: int) -> tuple[str, InlineKeyboardMarkup]:
    """One page of /my_docs; a page past the end (after deleting) shows the last one."""
    pages = -(-len(docs) // OWN_DOCUMENTS_PER_PAGE)
    page = min(max(page, 0), pages - 1)
    shown = docs[page * OWN_DOCUMENTS_PER_PAGE : (page + 1) * OWN_DOCUMENTS_PER_PAGE]
    return texts.own_documents(shown, page, pages), own_documents_keyboard(shown, page, pages)


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
        text, markup = _own_page(remaining, callback_data.page)
        await edit_text(callback, text, reply_markup=markup)
    else:
        await edit_text(callback, texts.NO_OWN_DOCUMENTS)
    await callback.message.answer(texts.document_deleted(deleted.title, restored))
