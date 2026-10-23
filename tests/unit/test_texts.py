from datetime import datetime

from forest_bot.bot import texts
from forest_bot.config import ARCHIVE_UPLOADED_AT, KYIV_TZ
from forest_bot.db.repositories.documents import DocumentInfo


def _doc(id, title, place, source="archive", author=None):
    uploaded = (
        ARCHIVE_UPLOADED_AT if source == "archive" else datetime(2026, 10, 22, tzinfo=KYIV_TZ)
    )
    return DocumentInfo(id, title, title.lower(), place, source, author, uploaded)


def test_split_message_keeps_lines_whole():
    text = "\n".join(f"рядок {i:03}" for i in range(100))
    parts = texts.split_message(text, limit=100)
    assert all(len(p) <= 100 for p in parts)
    assert "\n".join(parts) == text


def test_split_message_cuts_a_huge_line():
    parts = texts.split_message("x" * 250, limit=100)
    assert [len(p) for p in parts] == [100, 100, 50]


def test_short_message_is_one_part():
    assert texts.split_message("Привіт") == ["Привіт"]


def test_all_documents_are_grouped_by_place_in_map_order():
    text = texts.all_documents(
        [
            _doc(1, "Членські внески", "pid_dubom", "user", "Кабан"),
            _doc(2, "Календар сезонів", "forest"),
        ]
    )
    assert text.index("<b>Весь ліс</b>") < text.index("<b>Під дубом</b>")
    assert "• «Календар сезонів» — Лісовий архів" in text
    assert "• «Членські внески» — Кабан, 22.10.2026" in text


def test_saved_document_says_what_it_replaced():
    replaced = _doc(1, "Членські внески рукавички Під дубом", "pid_dubom")
    text = texts.document_saved("Членські внески", "pid_dubom", replaced)
    assert "Місце: рукавичка «Під дубом»." in text
    assert "замінив попередню версію: «Членські внески рукавички Під дубом» — Лісовий архів" in text


def test_deleted_document_says_what_is_active_again():
    restored = _doc(1, "Членські внески рукавички Під дубом", "pid_dubom")
    text = texts.document_deleted("Членські внески", restored)
    assert "Знову діє попередня версія: «Членські внески рукавички Під дубом»" in text


def test_names_are_escaped():
    assert texts.name_saved("<Їжак>").startswith("Записав: &lt;Їжак&gt;.")


def test_too_long_names_the_limits_readably():
    assert "до 20 сторінок-сканів і до 200 000 символів" in texts.TOO_LONG
    assert "Розділіть його, будь ласка, на менші документи" in texts.TOO_LONG
