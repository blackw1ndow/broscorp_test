"""Everything the bot says, in Ukrainian (R5). Messages are sent with HTML parse mode."""

from datetime import datetime
from html import escape as _html_escape

from forest_bot.config import KYIV_TZ
from forest_bot.db.repositories.documents import DocumentInfo
from forest_bot.forest import PLACES, Place, describe_place
from forest_bot.ingestion.service import MAX_OCR_PAGES, MAX_TEXT_CHARS
from forest_bot.qa.answer import Answer, Source


def escape(text: str) -> str:
    # Quotes need no escaping in Telegram HTML; animals write apostrophes a lot (п'ятниця)
    return _html_escape(text, quote=False)


TELEGRAM_LIMIT = 4096

START = (
    "Привіт! Я бот «Лісовий архів» 🌲\n\n"
    "Знаю поради для життя в лісі: стандартні документи архіву й ті, що надсилають звірі.\n\n"
    "• Напишіть питання звичайним текстом, наприклад: «Скільки внесок під дубом?»\n"
    "• Надішліть документ (PDF, DOCX або TXT) — я його запам'ятаю.\n\n"
    "Якщо порада залежить від рукавички, назвіть її в питанні. Команди — /help"
)

HELP = (
    "<b>Що я вмію</b>\n"
    "• Відповідаю на питання з документів архіву й завжди кажу, з якого документа порада.\n"
    "• Запам'ятовую документи PDF, DOCX і TXT до 20 МБ. Підпис до файла — це його опис: "
    "напишіть там, для якої рукавички чи частини лісу порада.\n"
    "• Новіший документ того самого типу для того самого місця замінює старий.\n\n"
    "<b>Рукавички:</b> Під ялиною, У соснах, Біля мурашника, Під дубом, У ліщині, "
    "Під вербою, Біля бобрової греблі, На узліссі.\n\n"
    "<b>Команди</b>\n"
    "/docs — усі документи, які я знаю\n"
    "/my_docs — ваші документи (їх можна видалити)\n"
    "/name — змінити ваше ім'я в джерелах\n"
    "/help — ця довідка"
)

COMMANDS = {
    "start": "Привітання",
    "help": "Що вміє бот",
    "docs": "Усі документи",
    "my_docs": "Мої документи",
    "name": "Змінити ім'я",
}

ASK_NAME_FIRST_DOCUMENT = (
    "Дякую за документ! Ви надсилаєте його вперше, тож скажіть, будь ласка, ваше справжнє "
    "ім'я — те, за яким звірі впізнають автора (наприклад, «Зайчик-побігайчик»)."
)
ASK_NAME = "Напишіть ваше справжнє ім'я — за ним звірі впізнають автора документа."
BAD_NAME = "Ім'я має бути від 2 до 64 символів, без команд. Спробуйте ще раз."


def name_saved(name: str) -> str:
    return f"Записав: {escape(name)}. Саме це ім'я бачитимуть звірі у джерелах ваших документів."


READING_DOCUMENT = "Читаю документ…"
UNSUPPORTED_FILE = (
    "Я розумію лише документи PDF, DOCX і TXT. Надішліть, будь ласка, файл в одному з цих форматів."
)
FILE_TOO_BIG = "Файл завеликий: Telegram дає ботам завантажувати файли лише до 20 МБ."
BROKEN_FILE = "Не вдалося відкрити цей файл — можливо, він пошкоджений. Спробуйте надіслати ще раз."
NO_TEXT = (
    "Не вдалося розпізнати текст у документі. Надішліть його, будь ласка, у текстовому вигляді "
    "(TXT, DOCX або PDF із текстом)."
)
TOO_LONG = (
    f"Документ задовгий для мене: я читаю до {MAX_OCR_PAGES} сторінок-сканів і до "
    f"{MAX_TEXT_CHARS:_} символів тексту. Розділіть його, будь ласка, на менші документи "
    "або надішліть скани у текстовому вигляді."
).replace("_", " ")
NOT_UNDERSTOOD = (
    "Я розумію лише текстові питання й документи PDF, DOCX, TXT. "
    "Голосові, фото, стікери та інше, на жаль, не читаю."
)
NOT_ABOUT_FOREST = (
    "Я допомагаю лише з лісовими порадами з архіву: гриби, внески, сусіди, небезпеки, сезони… "
    "Спитайте мене про життя в лісі."
)
NOT_FOUND = "В архіві такої поради немає. Я відповідаю лише з документів, тож не вигадуватиму."
ASK_MITTEN = "Порада залежить від рукавички. Про яку рукавичку йдеться?"
ASK_DOCUMENT_PLACE = "Для якого місця цей документ? Виберіть рукавичку, частину лісу або весь ліс."
DOCUMENT_CANCELLED = "Гаразд, документ не зберігаю."
STALE_BUTTON = "Ця кнопка вже не діє."
BUSY = "Зараз багато питань, спробуйте, будь ласка, за хвилинку."
ERROR = "Ой, щось пішло не так. Спробуйте, будь ласка, ще раз."
NO_DOCUMENTS = "Я ще не знаю жодного документа."
NO_OWN_DOCUMENTS = "Ви ще не надсилали документів. Надішліть PDF, DOCX або TXT — я запам'ятаю."
UNKNOWN_COMMAND = "Не знаю такої команди. Що я вмію — /help"


def waiting_dropped(count: int) -> str:
    return (
        f"Документи, що чекали на місце чи ваше ім'я, я не зберіг (їх було: {count}). "
        "Якщо вони потрібні — надішліть їх ще раз."
    )


def document_failed(file_name: str) -> str:
    return (
        f"Документ «{escape(file_name)}» не вдалося обробити. Надішліть його, будь ласка, ще раз."
    )


def unknown_mitten(name: str) -> str:
    return (
        f"Рукавички «{escape(name)}» на карті лісу немає. "
        "Виберіть, для якого місця цей документ: одна з 8 рукавичок, частина лісу або весь ліс."
    )


def needs_split(places: list[Place]) -> str:
    names = "\n".join(f"• {escape(describe_place(p.code))}" for p in places)
    return (
        "У документі поради для кількох місць:\n"
        f"{names}\n\n"
        "Один документ має бути для одного місця. Розділіть його, будь ласка, на окремі "
        "документи — по одному на місце — і надішліть кожен."
    )


def _uploaded(source: str, author: str | None, uploaded_at: datetime) -> str:
    if source == "archive":
        return "Лісовий архів"  # D20
    return f"{escape(author or 'невідомий звір')}, {uploaded_at.astimezone(KYIV_TZ):%d.%m.%Y}"


def document_line(document: DocumentInfo) -> str:
    return (
        f"«{escape(document.title)}» — "
        f"{_uploaded(document.source, document.author, document.uploaded_at)}"
    )


def source_line(source: Source) -> str:
    return (
        f"• «{escape(source.title)}» ({escape(describe_place(source.place_code))}) — "
        f"{_uploaded(source.source, source.author, source.uploaded_at)}"
    )


def answer(result: Answer) -> str:
    heading = "Джерело" if len(result.sources) == 1 else "Джерела"
    sources = "\n".join(source_line(s) for s in result.sources)
    return f"{escape(result.text)}\n\n<b>{heading}:</b>\n{sources}"


def document_saved(title: str, place_code: str, replaced: DocumentInfo | None) -> str:
    text = f"Запам'ятав документ «{escape(title)}».\nМісце: {escape(describe_place(place_code))}."
    if replaced is not None:
        text += f"\nВін замінив попередню версію: {document_line(replaced)}."
    else:
        text += "\nПопередньої версії не було — це новий документ."
    return text


def already_known(document: DocumentInfo) -> str:
    return f"Цей документ я вже знаю: {document_line(document)}."


def own_documents(docs: list[DocumentInfo], page: int = 0, pages: int = 1) -> str:
    header = "<b>Ваші документи</b>"
    if pages > 1:
        header += f" (сторінка {page + 1} з {pages})"
    lines = "\n".join(
        f"• «{escape(d.title)}» ({escape(describe_place(d.place_code))}), "
        f"{d.uploaded_at.astimezone(KYIV_TZ):%d.%m.%Y}"
        for d in docs
    )
    return f"{header}\n{lines}\n\nЩоб видалити документ, натисніть на нього:"


def document_deleted(title: str, restored: DocumentInfo | None) -> str:
    text = f"Документ «{escape(title)}» видалено."
    if restored is not None:
        text += f"\nЗнову діє попередня версія: {document_line(restored)}."
    return text


def all_documents(docs: list[DocumentInfo]) -> str:
    by_place: dict[str, list[DocumentInfo]] = {}
    for doc in docs:
        by_place.setdefault(doc.place_code, []).append(doc)
    sections = [f"<b>Документи архіву</b> ({len(docs)})"]
    for code, place in PLACES.items():
        if code in by_place:
            lines = "\n".join(f"• {document_line(d)}" for d in by_place[code])
            sections.append(f"<b>{escape(place.name)}</b>\n{lines}")
    return "\n\n".join(sections)


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Splits by lines so that every part fits into one Telegram message."""
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        while len(line) > limit:
            parts.append(line[:limit])
            line = line[limit:]
        current = line
    if current:
        parts.append(current)
    return parts
