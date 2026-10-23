from datetime import date, datetime

from forest_bot.bot import texts
from forest_bot.config import ARCHIVE_UPLOADED_AT, KYIV_TZ
from forest_bot.db.repositories.chunks import Fragment
from forest_bot.qa.answer import NOT_FOUND, build_answer_prompt, format_date, parse_answer

UPLOADED = datetime(2026, 10, 21, 15, 30, tzinfo=KYIV_TZ)


def _fragment(chunk_id, document_id, title, place, source="archive", author=None):
    uploaded = ARCHIVE_UPLOADED_AT if source == "archive" else UPLOADED
    return Fragment(
        chunk_id=chunk_id,
        content=f"{title}\n\nтекст {chunk_id}",
        document_id=document_id,
        title=title,
        place_code=place,
        source=source,
        author=author,
        uploaded_at=uploaded,
        distance=0.1,
    )


FRAGMENTS = [
    _fragment(1, 10, "Броди і коли бобри відкривають греблю", "river"),
    _fragment(2, 20, "Стежки до сусідів", "bilia_hrebli", "user", "Бобер-будівничий"),
    _fragment(3, 20, "Стежки до сусідів", "bilia_hrebli", "user", "Бобер-будівничий"),
]


def test_prompt_labels_every_fragment_with_its_place():
    prompt = build_answer_prompt(
        "Як перейти річку біля бобрової греблі?", "bilia_hrebli", FRAGMENTS, date(2026, 10, 23)
    )
    assert prompt.startswith("Сьогодні 23 жовтня 2026.")
    assert "рукавичку «Біля бобрової греблі» (належить до: біля річки)" in prompt
    assert "--- 1 [частина лісу: біля річки]" in prompt
    assert "--- 2 [рукавичка «Біля бобрової греблі»]" in prompt


def test_prompt_for_a_mitten_in_no_part():
    prompt = build_answer_prompt("Гриби?", "na_uzlissi", [], date(2026, 1, 1))
    assert "«На узліссі» (не належить до жодної частини лісу)" in prompt


def test_format_date():
    assert format_date(date(2026, 3, 8)) == "8 березня 2026"


def test_sources_are_the_used_documents_once_each():
    answer = parse_answer({"answer": "Тільки по греблі.", "used": [2, 3, 1]}, FRAGMENTS)
    assert answer.found
    assert [s.document_id for s in answer.sources] == [20, 10]


def test_invalid_fragment_numbers_are_ignored():
    answer = parse_answer({"answer": "Так.", "used": ["2", 0, 7, "x", None]}, FRAGMENTS)
    assert [s.document_id for s in answer.sources] == [20]


def test_no_used_fragments_means_not_found():
    # D3: an answer that cites nothing is not from the archive
    assert parse_answer({"answer": "Борщ варять із буряка.", "used": []}, FRAGMENTS) == NOT_FOUND
    assert parse_answer({"answer": "", "used": [1]}, FRAGMENTS) == NOT_FOUND
    assert parse_answer({"text": "?"}, FRAGMENTS) == NOT_FOUND


def test_answer_text_names_document_author_and_date():
    answer = parse_answer(
        {"answer": "Тільки по греблі, вбрід — ніколи.", "used": [2, 1]}, FRAGMENTS
    )
    text = texts.answer(answer)
    assert text.startswith("Тільки по греблі, вбрід — ніколи.\n\n<b>Джерела:</b>")
    # R14: a document from an animal shows who sent it and when
    assert (
        "• «Стежки до сусідів» (рукавичка «Біля бобрової греблі») — Бобер-будівничий, 21.10.2026"
        in text
    )
    # D20: archive documents show the archive instead of an author
    assert (
        "• «Броди і коли бобри відкривають греблю» (частина лісу: біля річки) — Лісовий архів"
        in (text)
    )


def test_answer_text_is_escaped():
    answer = parse_answer({"answer": "<b>Увага</b> & обережно", "used": [1]}, FRAGMENTS)
    assert texts.answer(answer).startswith("&lt;b&gt;Увага&lt;/b&gt; &amp; обережно")


def test_double_escaped_line_breaks_are_fixed():
    answer = parse_answer({"answer": "— перше\n— друге", "used": [1]}, FRAGMENTS)
    assert answer.text == "— перше\n— друге"


def test_fragment_numbers_are_removed_from_the_text():
    answer = parse_answer(
        {"answer": "Не ходити вбрід (фрагмент 5). Лише по греблі (фрагменти 1, 2).", "used": [1]},
        FRAGMENTS,
    )
    assert answer.text == "Не ходити вбрід. Лише по греблі."
