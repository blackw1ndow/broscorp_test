"""A file is a document to remember (R3): validation, the first-time name, place and saving."""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from forest_bot.bot import texts
from forest_bot.bot.keyboards import CANCEL, Dialog, DocumentPlace, document_places_keyboard
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
    is_supported,
)
from forest_bot.qa.router import named_place

router = Router(name="documents")


@router.message(F.document)
async def on_document(
    message: Message,
    state: FSMContext,
    bot: Bot,
    ingestion: IngestionService,
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

    # A new document replaces whatever the previous one was waiting for
    await state.clear()
    if user_name is None:
        await state.set_state(Dialog.name_for_document)
        await state.set_data(
            {"file_id": document.file_id, "file_name": file_name, "caption": message.caption}
        )
        await message.answer(texts.ASK_NAME_FIRST_DOCUMENT)
        return
    await process_document(
        message, state, bot, ingestion, document.file_id, file_name, message.caption
    )


async def process_document(
    message: Message,
    state: FSMContext,
    bot: Bot,
    ingestion: IngestionService,
    file_id: str,
    file_name: str,
    caption: str | None,
) -> None:
    await message.answer(texts.READING_DOCUMENT)
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        data = await bot.download(file_id)
        outcome = await ingestion.receive(file_name, data.read(), caption, message.chat.id)
    await reply_outcome(message, state, outcome)


async def reply_outcome(message: Message, state: FSMContext, outcome: Outcome) -> None:
    match outcome:
        case Saved(title, place_code, replaced):
            await message.answer(texts.document_saved(title, place_code, replaced))
        case AlreadyKnown(document):
            await message.answer(texts.already_known(document))
        case NeedsPlace(pending, unknown_mitten):
            await state.set_state(Dialog.document_place)
            await state.set_data({"pending": pending.to_state()})
            text = (
                texts.unknown_mitten(unknown_mitten) if unknown_mitten else texts.ASK_DOCUMENT_PLACE
            )
            await message.answer(text, reply_markup=document_places_keyboard())
        case NeedsSplit(places):
            await message.answer(texts.needs_split(places))
        case NoText():
            await message.answer(texts.NO_TEXT)
        case Broken():
            await message.answer(texts.BROKEN_FILE)


@router.callback_query(Dialog.document_place, DocumentPlace.filter())
async def on_document_place(
    callback: CallbackQuery,
    callback_data: DocumentPlace,
    state: FSMContext,
    bot: Bot,
    ingestion: IngestionService,
) -> None:
    if callback_data.code != CANCEL and callback_data.code not in PLACES:
        await callback.answer(texts.STALE_BUTTON)
        return
    data = await state.get_data()
    await state.clear()
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    if callback_data.code == CANCEL:
        await callback.message.answer(texts.DOCUMENT_CANCELLED)
        return
    await _save_pending(callback.message, state, bot, ingestion, data, callback_data.code)


@router.message(Dialog.document_place, F.text & ~F.text.startswith("/"))
async def on_document_place_text(
    message: Message, state: FSMContext, bot: Bot, ingestion: IngestionService
) -> None:
    """The animal may type the place instead of pressing a button."""
    place = named_place(message.text)
    if place is None:
        await message.answer(texts.ASK_DOCUMENT_PLACE, reply_markup=document_places_keyboard())
        return
    data = await state.get_data()
    await state.clear()
    await _save_pending(message, state, bot, ingestion, data, place)


@router.callback_query(DocumentPlace.filter())
async def on_stale_document_place(callback: CallbackQuery) -> None:
    await callback.answer(texts.STALE_BUTTON)


async def _save_pending(
    message: Message,
    state: FSMContext,
    bot: Bot,
    ingestion: IngestionService,
    data: dict,
    place_code: str,
) -> None:
    pending = PendingDocument.from_state(data["pending"])
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        # In a private chat the chat id is the animal's Telegram id (R2)
        outcome = await ingestion.save(pending, place_code, message.chat.id)
    await reply_outcome(message, state, outcome)
