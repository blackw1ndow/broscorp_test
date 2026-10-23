"""A file is a document to remember (R3): validation, the first-time name, place and saving.

Every document that needs an answer from the animal waits on its own (D26): an album of several
files loses nothing, and each place prompt's buttons belong to that prompt's document.
"""

import asyncpg
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from forest_bot.bot import texts
from forest_bot.bot.edits import drop_keyboard
from forest_bot.bot.keyboards import CANCEL, Dialog, DocumentPlace, document_places_keyboard
from forest_bot.db.repositories import waiting
from forest_bot.forest import PLACES
from forest_bot.ingestion.service import (
    MAX_FILE_SIZE,
    AlreadyKnown,
    Broken,
    IngestionService,
    NeedsPlace,
    NeedsSplit,
    NoText,
    Outcome,
    PendingDocument,
    Saved,
    TooLong,
    is_supported,
)

router = Router(name="documents")


@router.message(F.document)
async def on_document(
    message: Message,
    state: FSMContext,
    bot: Bot,
    ingestion: IngestionService,
    pool: asyncpg.Pool,
    user_name: str | None,
) -> None:
    document = message.document
    file_name = document.file_name or "document"
    if not is_supported(file_name):
        await message.answer(texts.UNSUPPORTED_FILE)
        return
    if (document.file_size or 0) > MAX_FILE_SIZE:
        await message.answer(texts.FILE_TOO_BIG)
        return

    if user_name is None:
        file = {"file_id": document.file_id, "file_name": file_name, "caption": message.caption}
        async with pool.acquire() as conn:
            await waiting.add(conn, message.chat.id, waiting.NAME, file)
        await state.set_state(Dialog.name_for_document)
        await message.answer(texts.ASK_NAME_FIRST_DOCUMENT)
        return
    await process_document(
        message, bot, ingestion, pool, document.file_id, file_name, message.caption
    )


async def process_document(
    message: Message,
    bot: Bot,
    ingestion: IngestionService,
    pool: asyncpg.Pool,
    file_id: str,
    file_name: str,
    caption: str | None,
) -> None:
    await message.answer(texts.READING_DOCUMENT)
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        data = await bot.download(file_id)
        outcome = await ingestion.receive(file_name, data.read(), caption, message.chat.id)
    await reply_outcome(message, pool, outcome)


async def reply_outcome(message: Message, pool: asyncpg.Pool, outcome: Outcome) -> None:
    match outcome:
        case Saved(title, place_code, replaced):
            await message.answer(texts.document_saved(title, place_code, replaced))
        case AlreadyKnown(document):
            await message.answer(texts.already_known(document))
        case NeedsPlace(pending, unknown_mitten):
            # In a private chat the chat id is the animal's Telegram id (R2)
            async with pool.acquire() as conn:
                waiting_id = await waiting.add(
                    conn, message.chat.id, waiting.PLACE, pending.to_state()
                )
            text = (
                texts.unknown_mitten(unknown_mitten) if unknown_mitten else texts.ASK_DOCUMENT_PLACE
            )
            await message.answer(text, reply_markup=document_places_keyboard(waiting_id))
        case NeedsSplit(places):
            await message.answer(texts.needs_split(places))
        case NoText():
            await message.answer(texts.NO_TEXT)
        case TooLong():
            await message.answer(texts.TOO_LONG)
        case Broken():
            await message.answer(texts.BROKEN_FILE)


@router.callback_query(DocumentPlace.filter())
async def on_document_place(
    callback: CallbackQuery,
    callback_data: DocumentPlace,
    bot: Bot,
    ingestion: IngestionService,
    pool: asyncpg.Pool,
) -> None:
    """The place is chosen only with these buttons: any text is a question (D27)."""
    if callback_data.code != CANCEL and callback_data.code not in PLACES:
        await callback.answer(texts.STALE_BUTTON)
        return
    async with pool.acquire() as conn:
        data = await waiting.take(conn, callback.from_user.id, waiting.PLACE, callback_data.id)
    # Taken from waiting above: nothing may fail between here and saving it
    await drop_keyboard(callback)
    if data is None:
        # Already chosen or cancelled, or dropped with /start (D28)
        await callback.answer(texts.STALE_BUTTON)
        return
    await callback.answer()
    if callback_data.code == CANCEL:
        await callback.message.answer(texts.DOCUMENT_CANCELLED)
        return

    message = callback.message
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        outcome = await ingestion.save(
            PendingDocument.from_state(data), callback_data.code, message.chat.id
        )
    await reply_outcome(message, pool, outcome)
