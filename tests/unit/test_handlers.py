"""aiogram handlers with mocked services and Telegram objects."""

import io
from datetime import datetime

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from forest_bot.bot import texts
from forest_bot.bot.handlers import documents, fallback, names, questions
from forest_bot.bot.keyboards import CANCEL, Dialog, DocumentPlace, QuestionPlace
from forest_bot.config import KYIV_TZ
from forest_bot.forest import PLACES
from forest_bot.ingestion.service import (
    MAX_FILE_SIZE,
    NeedsPlace,
    NeedsSplit,
    PendingDocument,
    Saved,
)
from forest_bot.qa.answer import NOT_FOUND, Answer, Source
from forest_bot.qa.router import Route

USER_ID = 7


@pytest.fixture
def state() -> FSMContext:
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=USER_ID, user_id=USER_ID))


@pytest.fixture
def bot(mocker):
    bot = mocker.AsyncMock()
    bot.download.return_value = io.BytesIO(b"file bytes")
    return bot


@pytest.fixture(autouse=True)
def no_chat_action(mocker):
    # ChatActionSender would call Telegram in the background
    typing = mocker.patch("aiogram.utils.chat_action.ChatActionSender.typing")
    # A truthy __aexit__ would swallow exceptions from inside the block
    typing.return_value.__aexit__.return_value = False


def _message(mocker, text=None, document=None, caption=None):
    message = mocker.AsyncMock()
    message.text = text
    message.caption = caption
    message.document = document
    message.chat.id = USER_ID
    message.from_user.id = USER_ID
    return message


def _document(mocker, file_name="Членські внески.txt", size=1000):
    document = mocker.MagicMock()
    document.file_name = file_name
    document.file_size = size
    document.file_id = "file-1"
    return document


def _replies(message) -> list[str]:
    return [c.args[0] for c in message.answer.call_args_list]


def _pending() -> PendingDocument:
    return PendingDocument("a.txt", "sha", "Членські внески", "text", None, "Членські внески")


# --- documents -------------------------------------------------------------------------------


async def test_unsupported_format_is_rejected(mocker, state, bot):
    message = _message(mocker, document=_document(mocker, "фото.jpg"))
    ingestion = mocker.AsyncMock()
    await documents.on_document(message, state, bot, ingestion, user_name="Їжачок")
    assert _replies(message) == [texts.UNSUPPORTED_FILE]
    ingestion.receive.assert_not_called()


async def test_file_over_20_mb_is_rejected_before_download(mocker, state, bot):
    message = _message(mocker, document=_document(mocker, size=MAX_FILE_SIZE + 1))
    await documents.on_document(message, state, bot, mocker.AsyncMock(), user_name="Їжачок")
    assert _replies(message) == [texts.FILE_TOO_BIG]
    bot.download.assert_not_called()


async def test_first_document_asks_for_the_real_name(mocker, state, bot):
    message = _message(mocker, document=_document(mocker), caption="для Під дубом")
    ingestion = mocker.AsyncMock()
    await documents.on_document(message, state, bot, ingestion, user_name=None)

    assert _replies(message) == [texts.ASK_NAME_FIRST_DOCUMENT]
    assert await state.get_state() == Dialog.name_for_document.state
    assert await state.get_data() == {
        "file_id": "file-1",
        "file_name": "Членські внески.txt",
        "caption": "для Під дубом",
    }
    ingestion.receive.assert_not_called()


async def test_name_then_the_waiting_document_is_processed(mocker, state, bot):
    await state.set_state(Dialog.name_for_document)
    await state.set_data({"file_id": "file-1", "file_name": "a.txt", "caption": None})
    pool = mocker.MagicMock()
    set_name = mocker.patch.object(names.users, "set_display_name", mocker.AsyncMock())
    ingestion = mocker.AsyncMock()
    ingestion.receive.return_value = Saved("Членські внески", "pid_dubom", None)
    message = _message(mocker, text="  Зайчик-побігайчик ")

    await names.on_name(message, state, bot, pool, ingestion)

    assert set_name.call_args.args[1:] == (USER_ID, "Зайчик-побігайчик")
    ingestion.receive.assert_awaited_once_with("a.txt", b"file bytes", None, USER_ID)
    assert _replies(message)[-1] == texts.document_saved("Членські внески", "pid_dubom", None)
    assert await state.get_state() is None


async def test_bad_name_is_asked_again(mocker, state, bot):
    await state.set_state(Dialog.name)
    message = _message(mocker, text="Я")
    await names.on_name(message, state, bot, mocker.MagicMock(), mocker.AsyncMock())
    assert _replies(message) == [texts.BAD_NAME]
    assert await state.get_state() == Dialog.name.state


async def test_known_animal_document_is_saved(mocker, state, bot):
    ingestion = mocker.AsyncMock()
    ingestion.receive.return_value = Saved("Членські внески", "pid_dubom", None)
    message = _message(mocker, document=_document(mocker), caption="Під дубом")
    await documents.on_document(message, state, bot, ingestion, user_name="Їжачок")

    ingestion.receive.assert_awaited_once_with(
        "Членські внески.txt", b"file bytes", "Під дубом", USER_ID
    )
    assert _replies(message) == [
        texts.READING_DOCUMENT,
        texts.document_saved("Членські внески", "pid_dubom", None),
    ]


async def test_mixed_document_is_not_saved(mocker, state, bot):
    ingestion = mocker.AsyncMock()
    ingestion.receive.return_value = NeedsSplit([PLACES["coniferous"], PLACES["deciduous"]])
    message = _message(mocker, document=_document(mocker))
    await documents.on_document(message, state, bot, ingestion, user_name="Їжачок")
    assert "частина лісу: хвойний ліс" in _replies(message)[-1]
    assert await state.get_state() is None


async def test_unclear_place_shows_the_place_buttons(mocker, state, bot):
    ingestion = mocker.AsyncMock()
    ingestion.receive.return_value = NeedsPlace(_pending(), "Під горобиною")
    message = _message(mocker, document=_document(mocker))
    await documents.on_document(message, state, bot, ingestion, user_name="Їжачок")

    assert _replies(message)[-1] == texts.unknown_mitten("Під горобиною")
    markup = message.answer.call_args.kwargs["reply_markup"]
    assert sum(len(row) for row in markup.inline_keyboard) == 8 + 3 + 1 + 1
    assert await state.get_state() == Dialog.document_place.state
    assert await state.get_data() == {"pending": _pending().to_state()}


async def test_chosen_place_saves_the_pending_document(mocker, state, bot):
    await state.set_state(Dialog.document_place)
    await state.set_data({"pending": _pending().to_state()})
    ingestion = mocker.AsyncMock()
    ingestion.save.return_value = Saved("Членські внески", "u_sosnakh", None)
    callback = mocker.AsyncMock()
    callback.message = _message(mocker)

    await documents.on_document_place(
        callback, DocumentPlace(code="u_sosnakh"), state, bot, ingestion
    )

    ingestion.save.assert_awaited_once_with(_pending(), "u_sosnakh", USER_ID)
    assert await state.get_state() is None


async def test_typed_place_saves_the_pending_document(mocker, state, bot):
    await state.set_state(Dialog.document_place)
    await state.set_data({"pending": _pending().to_state()})
    ingestion = mocker.AsyncMock()
    ingestion.save.return_value = Saved("Членські внески", "pid_dubom", None)
    await documents.on_document_place_text(
        _message(mocker, text="під дубом"), state, bot, ingestion
    )
    ingestion.save.assert_awaited_once_with(_pending(), "pid_dubom", USER_ID)


async def test_cancel_drops_the_pending_document(mocker, state, bot):
    await state.set_state(Dialog.document_place)
    await state.set_data({"pending": _pending().to_state()})
    ingestion = mocker.AsyncMock()
    callback = mocker.AsyncMock()
    callback.message = _message(mocker)
    await documents.on_document_place(callback, DocumentPlace(code=CANCEL), state, bot, ingestion)
    assert _replies(callback.message) == [texts.DOCUMENT_CANCELLED]
    ingestion.save.assert_not_called()


# --- questions -------------------------------------------------------------------------------


def _qa(mocker, route: Route, answer: Answer = NOT_FOUND):
    qa = mocker.AsyncMock()
    qa.route.return_value = route
    qa.answer.return_value = answer
    return qa


async def test_question_without_the_mitten_asks_for_it_first(mocker, state, bot):
    # R10a: no general advice before the animal says which mitten
    route = Route(True, "Скільки внесок?", None, needs_place=True, doc_types=("членські внески",))
    qa = _qa(mocker, route)
    message = _message(mocker, text="Скільки внесок?")
    await questions.on_question(message, state, bot, qa)

    qa.answer.assert_not_called()
    assert _replies(message) == [texts.ASK_MITTEN]
    markup = message.answer.call_args.kwargs["reply_markup"]
    assert [b.text for row in markup.inline_keyboard for b in row][:2] == ["Під ялиною", "У соснах"]
    assert await state.get_data() == {
        "question": "Скільки внесок?",
        "doc_types": ("членські внески",),
    }
    qa.remember_clarification.assert_awaited_once_with(USER_ID, "Скільки внесок?", texts.ASK_MITTEN)


async def test_chosen_mitten_answers_the_waiting_question(mocker, state, bot):
    await state.set_state(Dialog.question_mitten)
    # Postgres storage gives the types back as a JSON list
    await state.set_data({"question": "Скільки внесок?", "doc_types": ["членські внески"]})
    qa = _qa(mocker, Route(True, "", None, False))
    callback = mocker.AsyncMock()
    callback.from_user.id = USER_ID
    callback.message = _message(mocker)

    await questions.on_question_mitten(callback, QuestionPlace(code="pid_dubom"), state, bot, qa)

    qa.answer.assert_awaited_once_with(
        USER_ID, "Під дубом", "Скільки внесок?", "pid_dubom", ("членські внески",)
    )
    assert _replies(callback.message) == [texts.NOT_FOUND]
    assert await state.get_state() is None


async def test_forged_mitten_code_is_ignored(mocker, state, bot):
    await state.set_state(Dialog.question_mitten)
    qa = _qa(mocker, Route(True, "", None, False))
    callback = mocker.AsyncMock()
    await questions.on_question_mitten(callback, QuestionPlace(code="nope"), state, bot, qa)
    callback.answer.assert_awaited_once_with(texts.STALE_BUTTON)
    qa.answer.assert_not_called()


async def test_question_with_a_place_is_answered_with_sources(mocker, state, bot):
    source = Source(1, "Членські внески", "pid_dubom", "user", "Кабан", datetime.now(KYIV_TZ))
    answer = Answer("4 жолуді на місяць.", [source])
    qa = _qa(mocker, Route(True, "Скільки внесок під дубом?", "pid_dubom", True), answer)
    message = _message(mocker, text="Скільки внесок під дубом?")
    await questions.on_question(message, state, bot, qa)

    qa.answer.assert_awaited_once_with(
        USER_ID, "Скільки внесок під дубом?", "Скільки внесок під дубом?", "pid_dubom", ()
    )
    assert _replies(message) == [texts.answer(answer)]


async def test_question_not_about_the_forest(mocker, state, bot):
    qa = _qa(mocker, Route(False, "Як приготувати борщ?", None, False))
    message = _message(mocker, text="Як приготувати борщ?")
    await questions.on_question(message, state, bot, qa)
    assert _replies(message) == [texts.NOT_ABOUT_FOREST]
    qa.answer.assert_not_called()


async def test_nothing_in_the_archive(mocker, state, bot):
    qa = _qa(mocker, Route(True, "Що робити при повені?", None, False))
    message = _message(mocker, text="Що робити при повені?")
    await questions.on_question(message, state, bot, qa)
    assert _replies(message) == [texts.NOT_FOUND]


async def test_voice_and_photos_get_an_explanation(mocker):
    message = _message(mocker)
    await fallback.on_anything_else(message)
    assert _replies(message) == [texts.NOT_UNDERSTOOD]
