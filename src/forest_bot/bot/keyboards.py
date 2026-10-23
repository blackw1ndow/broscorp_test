from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from forest_bot.db.repositories.documents import DocumentInfo
from forest_bot.forest import FOREST, MITTENS, PARTS, PLACES


class Dialog(StatesGroup):
    """What the animal's next text means. Waiting documents are not here but in
    waiting_documents: several can wait at once, each with its own buttons (D26)."""

    name_for_document = State()  # documents wait until the animal gives its name (R15)
    name = State()  # /name without an argument
    question_mitten = State()  # the question waits for the mitten (R10a)


class QuestionPlace(CallbackData, prefix="qp"):
    code: str
    asked_in: int  # id of the question's message: an earlier question's buttons stop working


class DocumentPlace(CallbackData, prefix="dp"):
    id: int  # the waiting document these buttons belong to
    code: str  # a place code or CANCEL


class DeleteDocument(CallbackData, prefix="del"):
    id: int


CANCEL = "cancel"


def mittens_keyboard(asked_in: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for mitten in MITTENS:
        builder.button(
            text=mitten.name, callback_data=QuestionPlace(code=mitten.code, asked_in=asked_in)
        )
    builder.adjust(2)
    return builder.as_markup()


def document_places_keyboard(waiting_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for place in (*MITTENS, *PARTS, FOREST):
        builder.button(text=place.name, callback_data=DocumentPlace(id=waiting_id, code=place.code))
    builder.button(text="Скасувати", callback_data=DocumentPlace(id=waiting_id, code=CANCEL))
    builder.adjust(2, 2, 2, 2, 3, 1, 1)
    return builder.as_markup()


def delete_keyboard(docs: list[DocumentInfo]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for doc in docs:
        label = f"🗑 {doc.title} · {PLACES[doc.place_code].name}"
        builder.button(text=label, callback_data=DeleteDocument(id=doc.id))
    builder.adjust(1)
    return builder.as_markup()
