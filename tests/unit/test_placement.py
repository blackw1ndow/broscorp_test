from pathlib import Path

import pytest

from forest_bot.forest import MITTENS, PLACES
from forest_bot.ingestion import extract
from forest_bot.ingestion.placement import detect_place, document_type
from tests.conftest import ARCHIVE_DIR

# Documents that are not for one mitten; their place is read from the first sentences
NOT_MITTEN_DOCUMENTS = {
    "Календар сезонів": "forest",
    "Карта лісу": "forest",
    "Осінній путівник лісу": "forest",
    "Правила толоки": "forest",
    "Що робити при пожежі": "forest",
    "Як кричати, коли бачиш мисливців": "forest",
    "Їстівне й отруйне": "forest",
    "Грибний путівник хвойного лісу": "coniferous",
    "Небезпеки хвойного лісу": "coniferous",
    "Що їсти в хвойному лісі": "coniferous",
    "Як не заблукати серед однакових сосен": "coniferous",
    "Як утеплити рукавичку в хвойному лісі": "coniferous",
    "Грибний путівник листяного лісу": "deciduous",
    "Небезпеки листяного лісу": "deciduous",
    "Коли падають жолуді й горіхи": "deciduous",
    "Що їсти в листяному лісі": "deciduous",
    "Як утеплити рукавичку в листяному лісі": "deciduous",
    "Броди і коли бобри відкривають греблю": "river",
    "Грибний путівник біля річки": "river",
    "Небезпеки біля річки": "river",
    "Що їсти біля річки": "river",
    "Як утеплити рукавичку біля річки": "river",
}

ARCHIVE_FILES = sorted(ARCHIVE_DIR.iterdir())


def _expected_place(stem: str) -> str:
    if stem in NOT_MITTEN_DOCUMENTS:
        return NOT_MITTEN_DOCUMENTS[stem]
    [mitten] = [m for m in MITTENS if m.name in stem]
    return mitten.code


@pytest.fixture(autouse=True)
def no_ocr(monkeypatch):
    # Scans have the place in the title, so the rules don't need their text
    monkeypatch.setattr(extract, "ocr_image", lambda image: "")


def test_archive_has_78_documents():
    assert len(ARCHIVE_FILES) == 78


@pytest.mark.parametrize("path", ARCHIVE_FILES, ids=lambda p: p.stem)
def test_every_archive_document_is_placed(path: Path):
    text = extract.extract_text(path.name, path.read_bytes()).text
    placement = detect_place(path.stem, text)
    assert placement.place is not None, placement.conflicting
    assert placement.place.code == _expected_place(path.stem)


def test_archive_document_types_are_unique_per_place():
    seen = {}
    for path in ARCHIVE_FILES:
        place = PLACES[_expected_place(path.stem)]
        key = (document_type(path.stem, place), place.code)
        assert key not in seen, f"{path.stem} clashes with {seen[key]}"
        seen[key] = path.stem


def test_several_places_in_one_document_are_reported():
    placement = detect_place(
        "Осінній путівник", "Осінній путівник\nПоради для хвойного лісу і для листяного лісу."
    )
    assert placement.place is None
    assert [p.code for p in placement.conflicting] == ["coniferous", "deciduous"]


def test_unknown_place():
    assert detect_place("Нотатки", "Просто якийсь текст без адресата.").place is None


@pytest.mark.parametrize(
    ("title", "place", "expected"),
    [
        ("Членські внески рукавички «Під дубом»", "pid_dubom", "членські внески"),
        ("Членські внески", "pid_dubom", "членські внески"),
        ("Небезпеки поруч із рукавичкою Біля бобрової греблі", "bilia_hrebli", "небезпеки"),
        ("Правила співжиття в рукавичці Під ялиною", "pid_yalynoyu", "правила співжиття"),
        ("Стежки до сусідів від рукавички У соснах", "u_sosnakh", "стежки до сусідів"),
        ("Як утеплити рукавичку в хвойному лісі", "coniferous", "як утеплити"),
        ("Як утеплити рукавичку біля річки", "river", "як утеплити"),
        ("Грибний путівник листяного лісу", "deciduous", "грибний путівник"),
        ("Календар сезонів", "forest", "календар сезонів"),
    ],
)
def test_document_type(title, place, expected):
    assert document_type(title, PLACES[place]) == expected
