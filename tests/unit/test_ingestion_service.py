import pytest

from forest_bot.ingestion.service import (
    Broken,
    IngestionService,
    NeedsPlace,
    NeedsSplit,
    NoText,
    PendingDocument,
    guess_title,
    section_headings,
)
from forest_bot.llm.client import LLMBusyError


def _pending(text: str, title: str = "Членські внески", caption: str | None = None):
    return PendingDocument(
        file_name="внески.txt",
        sha256="abc",
        text=text,
        extraction="text",
        caption=caption,
        title=title,
    )


@pytest.fixture
def llm(mocker):
    return mocker.AsyncMock()


@pytest.fixture
def service(mocker, llm):
    return IngestionService(mocker.MagicMock(), mocker.AsyncMock(), llm, "fast")


async def test_read_txt(service):
    result = await service.read("внески.txt", "Членські внески\n\nПо 4 жолуді.".encode(), "  ")
    assert isinstance(result, PendingDocument)
    assert result.title == "Членські внески"
    assert result.caption is None
    assert len(result.sha256) == 64


async def test_read_empty_document(service):
    assert isinstance(await service.read("порожньо.txt", b"   ", None), NoText)


async def test_read_broken_document(service):
    assert isinstance(await service.read("зламаний.docx", b"not a zip", None), Broken)


async def test_one_place_from_the_llm(service, llm):
    llm.complete_json.return_value = {"title": "Членські внески", "places": ["pid_dubom"]}
    pending, place = await service.locate(_pending("Мешканці рукавички «Під дубом»! Внесок — 4."))
    assert place.code == "pid_dubom"
    assert pending.title == "Членські внески"


async def test_several_places_ask_to_split(service, llm):
    # D21: the intro is for the whole forest, the sections are for two parts
    llm.complete_json.return_value = {"places": ["coniferous", "deciduous", "coniferous"]}
    result = await service.locate(_pending("Осінній путівник. Для всіх мешканців лісу..."))
    assert isinstance(result, NeedsSplit)
    assert [p.code for p in result.places] == ["coniferous", "deciduous"]


async def test_unknown_mitten_asks_for_the_place(service, llm):
    # D16
    llm.complete_json.return_value = {"places": [], "unknown_mitten": "Під горобиною"}
    result = await service.locate(_pending("Мешканці рукавички «Під горобиною»!"))
    assert isinstance(result, NeedsPlace)
    assert result.unknown_mitten == "Під горобиною"


async def test_unclear_place_asks_for_the_place(service, llm):
    # R16
    llm.complete_json.return_value = {"places": ["somewhere"], "unknown_mitten": None}
    result = await service.locate(_pending("Просто порада без адресата."))
    assert isinstance(result, NeedsPlace)
    assert result.unknown_mitten is None


async def test_rules_and_caption_are_hints_for_the_llm(service, llm):
    llm.complete_json.return_value = {"places": ["pid_dubom"]}
    await service.locate(_pending("Внесок — 4 жолуді.", caption="це для рукавички під дубом"))
    prompt = llm.complete_json.call_args.args[2]
    assert "Підпис звіра до файла: це для рукавички під дубом" in prompt
    assert "(у підписі названо: pid_dubom)" in prompt


async def test_sections_further_in_a_long_document_reach_the_llm(service, llm):
    llm.complete_json.return_value = {"places": ["forest"]}
    text = "Путівник для всіх мешканців лісу.\n" + "Слово. " * 400 + "\nПоради для листяного лісу"
    await service.locate(_pending(text, title="Путівник"))
    prompt = llm.complete_json.call_args.args[2]
    assert "Правила за вступом припускають: forest" in prompt
    assert "- Поради для листяного лісу" in prompt


async def test_llm_unavailable_falls_back_to_the_rules(service, llm):
    llm.complete_json.side_effect = LLMBusyError("429")
    pending, place = await service.locate(_pending("Ця порада для мешканців хвойного лісу."))
    assert place.code == "coniferous"


async def test_llm_unavailable_falls_back_to_the_caption(service, llm):
    llm.complete_json.side_effect = LLMBusyError("429")
    _, place = await service.locate(_pending("Внесок — 4 жолуді.", caption="Під дубом"))
    assert place.code == "pid_dubom"


async def test_llm_unavailable_and_no_hints_asks_for_the_place(service, llm):
    llm.complete_json.side_effect = LLMBusyError("429")
    assert isinstance(await service.locate(_pending("Внесок — 4 жолуді.")), NeedsPlace)


def test_pending_document_survives_the_fsm():
    pending = _pending("текст", caption="підпис")
    assert PendingDocument.from_state(pending.to_state()) == pending


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Членські внески\n\nПо 4 жолуді.", "Членські внески"),
        ("\n\n  Статут ОСМД  \nТекст", "Статут ОСМД"),
        ("Внесок — 4 жолуді на місяць.\nДругий рядок", "мій файл"),
        ("ОК\nТекст", "мій файл"),
    ],
)
def test_guess_title(text, expected):
    assert guess_title(text, "мій файл.txt") == expected


MIXED_GUIDE = (
    "Осінній путівник\n\nЦі поради для всіх мешканців лісу.\n\n"
    "Хвойний ліс\nГриби шукайте на 2–3 день після дощу.\n\n"
    "Для листяного лісу:\nЖолуді збирайте у жовтні."
)


async def test_sections_for_two_parts_are_split_without_the_llm(service, llm):
    # D21: the model sees a forest-wide intro and may miss the sections
    result = await service.locate(_pending(MIXED_GUIDE, title="Осінній путівник"))
    assert isinstance(result, NeedsSplit)
    assert [p.code for p in result.places] == ["coniferous", "deciduous"]
    llm.complete_json.assert_not_called()


async def test_neighbour_mittens_in_headings_go_to_the_llm(service, llm):
    llm.complete_json.return_value = {"places": ["pid_dubom"]}
    text = (
        "Стежки до сусідів\n\nМешканці рукавички «Під дубом»!\n\n"
        "До Під вербою\nСтежкою вздовж струмка.\n\nДо У ліщині\nПовз старий пень."
    )
    _, place = await service.locate(_pending(text, title="Стежки до сусідів"))
    assert place.code == "pid_dubom"
    prompt = llm.complete_json.call_args.args[2]
    assert "- До Під вербою → pid_verboyu" in prompt


def test_section_headings():
    assert [(line, [p.code for p in places]) for line, places in section_headings(MIXED_GUIDE)] == [
        ("Хвойний ліс", ["coniferous"]),
        ("Для листяного лісу:", ["deciduous"]),
    ]
