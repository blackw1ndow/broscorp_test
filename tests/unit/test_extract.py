import pytest

from forest_bot.ingestion import extract
from forest_bot.ingestion.extract import ExtractionMethod, UnsupportedFormatError, extract_text
from tests.conftest import ARCHIVE_DIR


def _archive(name: str) -> bytes:
    return (ARCHIVE_DIR / name).read_bytes()


def test_txt_utf8_with_bom():
    result = extract_text("a.txt", "﻿Порада: гриби після дощу".encode())
    assert result.text == "Порада: гриби після дощу"
    assert result.method is ExtractionMethod.TEXT


def test_txt_cp1251():
    result = extract_text("a.TXT", "Їжак знає гриби".encode("cp1251"))
    assert result.text == "Їжак знає гриби"


def test_docx_from_archive():
    result = extract_text("x.docx", _archive("Осінній путівник лісу.docx"))
    assert "Перша порада — про гриби" in result.text
    assert result.method is ExtractionMethod.TEXT


def test_text_pdf_from_archive(mocker):
    ocr = mocker.patch.object(extract, "ocr_image")
    result = extract_text("x.pdf", _archive("Карта лісу.pdf"))
    assert "Під вербою — і листяний ліс, і біля річки" in " ".join(result.text.split())
    assert result.method is ExtractionMethod.TEXT
    ocr.assert_not_called()


def test_scanned_pdf_goes_through_ocr(mocker):
    ocr = mocker.patch.object(extract, "ocr_image", return_value="Внесок — 2 соснові шишки")
    result = extract_text("x.pdf", _archive("Членські внески рукавички У соснах.pdf"))
    assert result.text == "Внесок — 2 соснові шишки"
    assert result.method is ExtractionMethod.OCR
    ocr.assert_called_once()


def _tesseract_words(*words):
    """image_to_data output: (word, confidence, block, paragraph, line)."""
    return {
        "text": [w[0] for w in words],
        "conf": [w[1] for w in words],
        "block_num": [w[2] for w in words],
        "par_num": [w[3] for w in words],
        "line_num": [w[4] for w in words],
    }


def test_ocr_keeps_confident_words_and_paragraphs(mocker):
    tesseract = mocker.patch.object(
        extract.pytesseract,
        "image_to_data",
        return_value=_tesseract_words(
            ("Членські", 96, 1, 1, 1),
            ("внески", 95, 1, 1, 1),
            ("~~", 12, 1, 1, 1),  # a blotch
            ("Внесок", 91, 2, 1, 1),
            ("—", 88, 2, 1, 1),
            ("2", 90, 2, 1, 1),
            ("шишки", 93, 2, 1, 1),
        ),
    )
    from PIL import Image

    text = extract.ocr_image(Image.new("RGB", (100, 100), "white"))

    assert text == "Членські внески\n\nВнесок — 2 шишки"
    assert tesseract.call_args.kwargs["lang"] == "ukr"


def test_ocr_keeps_unsure_word_among_confident_neighbours(mocker):
    mocker.patch.object(
        extract.pytesseract,
        "image_to_data",
        return_value=_tesseract_words(
            ("Кабан", 15, 1, 1, 1),  # a real word with a low score
            ("носить", 92, 1, 1, 1),
            ("хмиз", 90, 1, 1, 1),
            ("по", 91, 1, 1, 1),
            ("понеділках.", 89, 1, 1, 1),
            ("рранаюо", 0, 2, 1, 1),  # a blotch in a line of its own
            ("ча", 25, 2, 1, 1),
        ),
    )
    from PIL import Image

    text = extract.ocr_image(Image.new("RGB", (100, 100), "white"))

    assert text == "Кабан носить хмиз по понеділках."


@pytest.mark.parametrize(
    ("ocr", "expected"),
    [
        ("Видра може платити рибою: 1 рибина за З гілки.", "1 рибина за 3 гілки."),
        ("нашій рукавичці спокійно Й затишно.", "спокійно й затишно."),
        ("Заміна. З берега не брати.", "Заміна. З берега не брати."),
    ],
)
def test_misread_letters_are_fixed(ocr, expected):
    assert expected in extract._fix_misread_letters(ocr)


def test_ocr_noise_lines_are_dropped():
    text = "Заголовок\n— ~~ .\nНормальний рядок тексту\n_-="
    assert extract._drop_noise_lines(text) == "Заголовок\nНормальний рядок тексту"


@pytest.mark.parametrize("name", ["photo.jpg", "voice.ogg", "old.doc", "noext"])
def test_unsupported_formats(name):
    with pytest.raises(UnsupportedFormatError):
        extract_text(name, b"data")
