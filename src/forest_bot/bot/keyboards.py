from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from forest_bot.db.repositories.documents import DocumentInfo
from forest_bot.forest import FOREST, MITTENS, PARTS, PLACES


class Dialog(StatesGroup):
    name_for_document = State()  # the document waits until the animal gives its name (R15)
    name = State()  # /name without an argument
    document_place = State()  # the document waits for its place (R16, D16)
    question_mitten = State()  # the question waits for the mitten (R10a)


class QuestionPlace(CallbackData, prefix="qp"):
    code: str


class DocumentPlace(CallbackData, prefix="dp"):
    code: str  # a place code or CANCEL


class DeleteDocument(CallbackData, prefix="del"):
    id: int


CANCEL = "cancel"


def mittens_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for mitten in MITTENS:
        builder.button(text=mitten.name, callback_data=QuestionPlace(code=mitten.code))
    builder.adjust(2)
    return builder.as_markup()


def document_places_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for mitten in MITTENS:
        builder.button(text=mitten.name, callback_data=DocumentPlace(code=mitten.code))
    for part in PARTS:
        builder.button(text=part.name, callback_data=DocumentPlace(code=part.code))
    builder.button(text=FOREST.name, callback_data=DocumentPlace(code=FOREST.code))
    builder.button(text="Скасувати", callback_data=DocumentPlace(code=CANCEL))
    builder.adjust(2, 2, 2, 2, 3, 1, 1)
    return builder.as_markup()


def delete_keyboard(docs: list[DocumentInfo]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for doc in docs:
        label = f"🗑 {doc.title} · {PLACES[doc.place_code].name}"
        builder.button(text=label, callback_data=DeleteDocument(id=doc.id))
    builder.adjust(1)
    return builder.as_markup()
