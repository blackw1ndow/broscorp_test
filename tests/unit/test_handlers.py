"""aiogram handlers with mocked services and Telegram objects."""

import io
from datetime import datetime

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from forest_bot.bot import texts
from forest_bot.bot.handlers import commands, documents, fallback, names, questions
from forest_bot.bot.keyboards import (
    CANCEL,
    DeleteDocument,
    Dialog,
    DocumentPlace,
    OwnDocumentsPage,
    QuestionPlace,
)
from forest_bot.config import KYIV_TZ
from forest_bot.db.repositories import waiting
from forest_bot.db.repositories.documents import DocumentInfo
from forest_bot.forest import PLACES
from forest_bot.ingestion.service import (
    MAX_FILE_SIZE,
    NeedsPlace,
    NeedsSplit,
    PendingDocument,
    Saved,
    TooLong,
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


def _message(mocker, text=None, document=None, caption=None, message_id=1):
    message = mocker.AsyncMock()
    message.message_id = message_id
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


def _pending(title: str = "Членські внески") -> PendingDocument:
    return PendingDocument("a.txt", f"sha-{title}", title, "text", None, title)


class FakeWaiting:
    """In-memory stand-in for the waiting_documents repository."""

    def __init__(self) -> None:
        self.rows: dict[int, tuple[int, str, dict]] = {}
        self._next_id = 0

    async def add(self, conn, user_id, waits_for, data):
        self._next_id += 1
        self.rows[self._next_id] = (user_id, waits_for, data)
        return self._next_id

    async def take(self, conn, user_id, waits_for, waiting_id):
        row = self.rows.get(waiting_id)
        if row is None or row[:2] != (user_id, waits_for):
            return None
        del self.rows[waiting_id]
        return row[2]

    async def take_all(self, conn, user_id, waits_for):
        ids = [i for i, row in self.rows.items() if row[:2] == (user_id, waits_for)]
        return [self.rows.pop(i)[2] for i in sorted(ids)]

    async def drop_all(self, conn, user_id):
        ids = [i for i, row in self.rows.items() if row[0] == user_id]
        for i in ids:
            del self.rows[i]
        return len(ids)


@pytest.fixture
def waiting_docs(mocker) -> FakeWaiting:
    fake = FakeWaiting()
    for name in ("add", "take", "take_all", "drop_all"):
        mocker.patch.object(waiting, name, getattr(fake, name))
    return fake


@pytest.fixture
def pool(mocker):
    return mocker.MagicMock()


def _button(message, text: str):
    """The callback data of the button with this text in the message's last keyboard."""
    markup = message.answer.call_args.kwargs["reply_markup"]
    data = next(b.callback_data for row in markup.inline_keyboard for b in row if b.text == text)
    return data


def _callback(mocker, message):
    callback = mocker.AsyncMock()
    callback.from_user.id = USER_ID
    callback.message = message
    return callback


# --- documents -------------------------------------------------------------------------------


async def test_unsupported_format_is_rejected(mocker, state, bot, pool):
    message = _message(mocker, document=_document(mocker, "фото.jpg"))
    ingestion = mocker.AsyncMock()
    await documents.on_document(message, state, bot, ingestion, pool, user_name="Їжачок")
    assert _replies(message) == [texts.UNSUPPORTED_FILE]
    ingestion.receive.assert_not_called()


async def test_file_over_20_mb_is_rejected_before_download(mocker, state, bot, pool):
    message = _message(mocker, document=_document(mocker, size=MAX_FILE_SIZE + 1))
    await documents.on_document(message, state, bot, mocker.AsyncMock(), pool, user_name="Їжачок")
    assert _replies(message) == [texts.FILE_TOO_BIG]
    bot.download.assert_not_called()


async def test_first_document_asks_for_the_real_name(mocker, state, bot, pool, waiting_docs):
    message = _message(mocker, document=_document(mocker), caption="для Під дубом")
    ingestion = mocker.AsyncMock()
    await documents.on_document(message, state, bot, ingestion, pool, user_name=None)

    assert _replies(message) == [texts.ASK_NAME_FIRST_DOCUMENT]
    assert await state.get_state() == Dialog.name_for_document.state
    assert list(waiting_docs.rows.values()) == [
        (
            USER_ID,
            waiting.NAME,
            {"file_id": "file-1", "file_name": "Членські внески.txt", "caption": "для Під дубом"},
        )
    ]
    ingestion.receive.assert_not_called()


async def test_name_then_the_waiting_document_is_processed(mocker, state, bot, pool, waiting_docs):
    await state.set_state(Dialog.name_for_document)
    await waiting_docs.add(
        None, USER_ID, waiting.NAME, {"file_id": "file-1", "file_name": "a.txt", "caption": None}
    )
    set_name = mocker.patch.object(names.users, "set_display_name", mocker.AsyncMock())
    ingestion = mocker.AsyncMock()
    ingestion.receive.return_value = Saved("Членські внески", "pid_dubom", None)
    message = _message(mocker, text="  Зайчик-побігайчик ")

    await names.on_name(message, state, bot, pool, ingestion)

    assert set_name.call_args.args[1:] == (USER_ID, "Зайчик-побігайчик")
    ingestion.receive.assert_awaited_once_with("a.txt", b"file bytes", None, USER_ID)
    assert _replies(message)[-1] == texts.document_saved("Членські внески", "pid_dubom", None)
    assert await state.get_state() is None
    assert waiting_docs.rows == {}


async def test_bad_name_is_asked_again(mocker, state, bot, pool):
    await state.set_state(Dialog.name)
    message = _message(mocker, text="Я")
    await names.on_name(message, state, bot, pool, mocker.AsyncMock())
    assert _replies(message) == [texts.BAD_NAME]
    assert await state.get_state() == Dialog.name.state


async def test_known_animal_document_is_saved(mocker, state, bot, pool):
    ingestion = mocker.AsyncMock()
    ingestion.receive.return_value = Saved("Членські внески", "pid_dubom", None)
    message = _message(mocker, document=_document(mocker), caption="Під дубом")
    await documents.on_document(message, state, bot, ingestion, pool, user_name="Їжачок")

    ingestion.receive.assert_awaited_once_with(
        "Членські внески.txt", b"file bytes", "Під дубом", USER_ID
    )
    assert _replies(message) == [
        texts.READING_DOCUMENT,
        texts.document_saved("Членські внески", "pid_dubom", None),
    ]


async def test_mixed_document_is_not_saved(mocker, state, bot, pool):
    ingestion = mocker.AsyncMock()
    ingestion.receive.return_value = NeedsSplit([PLACES["coniferous"], PLACES["deciduous"]])
    message = _message(mocker, document=_document(mocker))
    await documents.on_document(message, state, bot, ingestion, pool, user_name="Їжачок")
    assert "частина лісу: хвойний ліс" in _replies(message)[-1]
    assert await state.get_state() is None


async def test_too_long_document_is_refused(mocker, state, bot, pool):
    ingestion = mocker.AsyncMock()
    ingestion.receive.return_value = TooLong()
    message = _message(mocker, document=_document(mocker))
    await documents.on_document(message, state, bot, ingestion, pool, user_name="Їжачок")
    assert _replies(message)[-1] == texts.TOO_LONG


async def test_unclear_place_shows_the_place_buttons(mocker, state, bot, pool, waiting_docs):
    ingestion = mocker.AsyncMock()
    ingestion.receive.return_value = NeedsPlace(_pending(), "Під горобиною")
    message = _message(mocker, document=_document(mocker))
    await documents.on_document(message, state, bot, ingestion, pool, user_name="Їжачок")

    assert _replies(message)[-1] == texts.unknown_mitten("Під горобиною")
    markup = message.answer.call_args.kwargs["reply_markup"]
    assert sum(len(row) for row in markup.inline_keyboard) == 8 + 3 + 1 + 1
    assert list(waiting_docs.rows.values()) == [(USER_ID, waiting.PLACE, _pending().to_state())]
    # D27: no dialog state, so the next text is still a question
    assert await state.get_state() is None


async def test_each_waiting_document_keeps_its_own_place_buttons(
    mocker, state, bot, pool, waiting_docs
):
    # D26: two documents in a row both wait; the first one's buttons still save the first one
    ingestion = mocker.AsyncMock()
    ingestion.receive.side_effect = [
        NeedsPlace(_pending("Членські внески"), None),
        NeedsPlace(_pending("Стежки до сусідів"), None),
    ]
    first = _message(mocker, document=_document(mocker))
    second = _message(mocker, document=_document(mocker))
    await documents.on_document(first, state, bot, ingestion, pool, user_name="Їжачок")
    await documents.on_document(second, state, bot, ingestion, pool, user_name="Їжачок")
    ingestion.save.return_value = Saved("Членські внески", "pid_dubom", None)

    pressed = DocumentPlace.unpack(_button(first, "Під дубом"))
    await documents.on_document_place(_callback(mocker, first), pressed, bot, ingestion, pool)

    ingestion.save.assert_awaited_once_with(_pending("Членські внески"), "pid_dubom", USER_ID)


async def test_album_from_a_new_animal_is_read_whole_after_the_name(
    mocker, state, bot, pool, waiting_docs
):
    # D26: every file of the album waits for the name, not only the last one
    mocker.patch.object(names.users, "set_display_name", mocker.AsyncMock())
    ingestion = mocker.AsyncMock()
    for file_name in ("Внески.txt", "Стежки.txt"):
        message = _message(mocker, document=_document(mocker, file_name))
        await documents.on_document(message, state, bot, ingestion, pool, user_name=None)
    ingestion.receive.return_value = Saved("Членські внески", "pid_dubom", None)

    await names.on_name(_message(mocker, text="Зайчик-побігайчик"), state, bot, pool, ingestion)

    assert [c.args[0] for c in ingestion.receive.call_args_list] == ["Внески.txt", "Стежки.txt"]


async def test_place_button_pressed_twice_saves_once(mocker, state, bot, pool, waiting_docs):
    waiting_id = await waiting_docs.add(None, USER_ID, waiting.PLACE, _pending().to_state())
    ingestion = mocker.AsyncMock()
    ingestion.save.return_value = Saved("Членські внески", "pid_dubom", None)
    callback = _callback(mocker, _message(mocker))
    pressed = DocumentPlace(id=waiting_id, code="pid_dubom")

    await documents.on_document_place(callback, pressed, bot, ingestion, pool)
    await documents.on_document_place(callback, pressed, bot, ingestion, pool)

    ingestion.save.assert_awaited_once()
    callback.answer.assert_awaited_with(texts.STALE_BUTTON)


async def test_name_command_does_not_drop_a_waiting_document(
    mocker, state, bot, pool, waiting_docs
):
    # Review #8 / D28: /name changes only what the next text means
    waiting_id = await waiting_docs.add(None, USER_ID, waiting.PLACE, _pending().to_state())
    command = mocker.MagicMock(args=None)
    await names.on_name_command(
        _message(mocker, text="/name"), command, state, bot, pool, mocker.AsyncMock()
    )
    ingestion = mocker.AsyncMock()
    ingestion.save.return_value = Saved("Членські внески", "pid_dubom", None)

    pressed = DocumentPlace(id=waiting_id, code="pid_dubom")
    await documents.on_document_place(
        _callback(mocker, _message(mocker)), pressed, bot, ingestion, pool
    )

    ingestion.save.assert_awaited_once_with(_pending(), "pid_dubom", USER_ID)


async def test_cancel_drops_the_pending_document(mocker, bot, pool, waiting_docs):
    waiting_id = await waiting_docs.add(None, USER_ID, waiting.PLACE, _pending().to_state())
    ingestion = mocker.AsyncMock()
    callback = _callback(mocker, _message(mocker))
    await documents.on_document_place(
        callback, DocumentPlace(id=waiting_id, code=CANCEL), bot, ingestion, pool
    )
    assert _replies(callback.message) == [texts.DOCUMENT_CANCELLED]
    ingestion.save.assert_not_called()
    assert waiting_docs.rows == {}


# --- commands --------------------------------------------------------------------------------


async def test_start_drops_the_waiting_documents_and_says_how_many(
    mocker, state, pool, waiting_docs
):
    # D28: /start begins again; documents that were waiting are not saved
    await waiting_docs.add(None, USER_ID, waiting.NAME, {"file_id": "f1"})
    await waiting_docs.add(None, USER_ID, waiting.PLACE, _pending().to_state())
    await state.set_state(Dialog.name_for_document)
    message = _message(mocker, text="/start")

    await commands.on_start(message, state, pool)

    assert _replies(message) == [texts.START, texts.waiting_dropped(2)]
    assert waiting_docs.rows == {}
    assert await state.get_state() is None


async def test_start_without_waiting_documents_only_greets(mocker, state, pool, waiting_docs):
    message = _message(mocker, text="/start")
    await commands.on_start(message, state, pool)
    assert _replies(message) == [texts.START]


def _own_docs(count: int) -> list[DocumentInfo]:
    # The longest titles the bot keeps (150 characters)
    return [
        DocumentInfo(
            i, f"{i:03} " + "Д" * 146, "тип", "pid_dubom", "user", "Їжачок", datetime.now(KYIV_TZ)
        )
        for i in range(1, count + 1)
    ]


def _buttons(markup) -> list[str]:
    return [b.text for row in markup.inline_keyboard for b in row]


async def test_many_own_documents_are_shown_page_by_page(mocker, pool):
    # Review #3: one message with every document breaks Telegram's 4096 chars / 100 buttons
    mocker.patch.object(commands.documents, "list_active", return_value=_own_docs(25))
    message = _message(mocker, text="/my_docs")

    await commands.on_my_docs(message, pool)

    [call] = message.answer.call_args_list
    text, markup = call.args[0], call.kwargs["reply_markup"]
    assert len(text) <= texts.TELEGRAM_LIMIT
    assert "001 " in text and "010 " in text and "011 " not in text
    assert sum(b.startswith("🗑") for b in _buttons(markup)) == 10
    assert "▶" in _buttons(markup)

    pressed = OwnDocumentsPage.unpack(_button(message, "▶"))
    callback = _callback(mocker, _message(mocker))
    await commands.on_own_documents_page(callback, pressed, pool)

    shown = callback.message.edit_text.call_args.args[0]
    assert "011 " in shown and "020 " in shown and "001 " not in shown


async def test_deleting_keeps_the_list_on_its_page(mocker, pool):
    remaining = _own_docs(25)
    deleted = remaining.pop(14)  # from the second page
    mocker.patch.object(commands.documents, "delete_own", return_value=(deleted, None))
    mocker.patch.object(commands.documents, "list_active", return_value=remaining)
    # `async with conn.transaction()` needs a context manager, not a coroutine
    pool.acquire.return_value.__aenter__.return_value.transaction = mocker.MagicMock()
    callback = _callback(mocker, _message(mocker))

    await commands.on_delete(callback, DeleteDocument(id=deleted.id, page=1), pool)

    shown = callback.message.edit_text.call_args.args[0]
    assert "011 " in shown and "021 " in shown and "001 " not in shown


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
        "asked_in": 1,
    }
    qa.remember_clarification.assert_awaited_once_with(USER_ID, "Скільки внесок?", texts.ASK_MITTEN)


async def test_chosen_mitten_answers_the_waiting_question(mocker, state, bot):
    await state.set_state(Dialog.question_mitten)
    # Postgres storage gives the types back as a JSON list
    await state.set_data(
        {"question": "Скільки внесок?", "doc_types": ["членські внески"], "asked_in": 5}
    )
    qa = _qa(mocker, Route(True, "", None, False))
    callback = _callback(mocker, _message(mocker))

    await questions.on_question_mitten(
        callback, QuestionPlace(code="pid_dubom", asked_in=5), state, bot, qa
    )

    qa.answer.assert_awaited_once_with(
        USER_ID, "Під дубом", "Скільки внесок?", "pid_dubom", ("членські внески",)
    )
    assert _replies(callback.message) == [texts.NOT_FOUND]
    assert await state.get_state() is None


async def test_forged_mitten_code_is_ignored(mocker, state, bot):
    await state.set_state(Dialog.question_mitten)
    qa = _qa(mocker, Route(True, "", None, False))
    callback = mocker.AsyncMock()
    await questions.on_question_mitten(
        callback, QuestionPlace(code="nope", asked_in=1), state, bot, qa
    )
    callback.answer.assert_awaited_once_with(texts.STALE_BUTTON)
    qa.answer.assert_not_called()


async def test_mitten_buttons_of_an_earlier_question_no_longer_work(mocker, state, bot):
    # D26: only the last question waits; the earlier prompt must not answer the newer question
    route = Route(True, "Скільки внесок?", None, needs_place=True)
    qa = _qa(mocker, route)
    earlier = _message(mocker, text="Скільки внесок?", message_id=10)
    later = _message(mocker, text="Коли утеплювати?", message_id=11)
    await questions.on_question(earlier, state, bot, qa)
    qa.route.return_value = Route(True, "Коли утеплювати?", None, needs_place=True)
    await questions.on_question(later, state, bot, qa)

    callback = _callback(mocker, earlier)
    pressed = QuestionPlace.unpack(_button(earlier, "Під дубом"))
    await questions.on_question_mitten(callback, pressed, state, bot, qa)

    callback.answer.assert_awaited_once_with(texts.STALE_BUTTON)
    qa.answer.assert_not_called()

    pressed = QuestionPlace.unpack(_button(later, "Під дубом"))
    await questions.on_question_mitten(_callback(mocker, later), pressed, state, bot, qa)
    assert qa.answer.call_args.args[2] == "Коли утеплювати?"


async def test_waiting_question_survives_the_name_command(mocker, state, bot, pool):
    # D26: documents and the name do not cancel the waiting question
    qa = _qa(mocker, Route(True, "Скільки внесок?", None, needs_place=True))
    question = _message(mocker, text="Скільки внесок?", message_id=10)
    await questions.on_question(question, state, bot, qa)
    await names.on_name_command(
        _message(mocker, text="/name"), mocker.MagicMock(args=None), state, bot, pool, qa
    )

    pressed = QuestionPlace.unpack(_button(question, "Під дубом"))
    await questions.on_question_mitten(_callback(mocker, question), pressed, state, bot, qa)

    assert qa.answer.call_args.args[2:4] == ("Скільки внесок?", "pid_dubom")
    # The animal is still asked for the name
    assert await state.get_state() == Dialog.name.state


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
