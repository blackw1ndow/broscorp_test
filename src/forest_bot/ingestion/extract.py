"""Text extraction from PDF, DOCX and TXT. Scanned PDF pages go through OCR (D22)."""

import io
import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import docx
import pypdfium2
import pytesseract
from PIL import Image, ImageFilter, ImageOps
from pypdf import PdfReader

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt")

# A page with less text than this is treated as a scan
_MIN_PAGE_TEXT = 20
_OCR_DPI = 300
# Scans in the archive have grey blotches on the background; the text is much darker
_OCR_THRESHOLD = 120
_OCR_MIN_CONFIDENCE = 60
_OCR_MIN_CONFIDENT_NEIGHBOURS = 3


class ExtractionMethod(StrEnum):
    TEXT = "text"
    OCR = "ocr"


@dataclass(frozen=True)
class ExtractedText:
    text: str
    method: ExtractionMethod


class UnsupportedFormatError(ValueError):
    pass


def extract_text(file_name: str, data: bytes) -> ExtractedText:
    extension = Path(file_name).suffix.lower()
    if extension == ".txt":
        return ExtractedText(_clean(_decode_txt(data)), ExtractionMethod.TEXT)
    if extension == ".docx":
        return ExtractedText(_clean(_docx_text(data)), ExtractionMethod.TEXT)
    if extension == ".pdf":
        return _pdf_text(data)
    raise UnsupportedFormatError(extension or file_name)


def _decode_txt(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Older Windows editors save Ukrainian text in cp1251
        return data.decode("cp1251")


def _docx_text(data: bytes) -> str:
    document = docx.Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(parts)


def _pdf_text(data: bytes) -> ExtractedText:
    reader = PdfReader(io.BytesIO(data))
    pages: list[str] = []
    ocr_pages: list[int] = []
    for index, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if len(text.strip()) < _MIN_PAGE_TEXT:
            ocr_pages.append(index)
        pages.append(text)

    if ocr_pages:
        pdf = pypdfium2.PdfDocument(data)
        try:
            for index in ocr_pages:
                pages[index] = ocr_image(pdf[index].render(scale=_OCR_DPI / 72).to_pil())
        finally:
            pdf.close()

    method = ExtractionMethod.OCR if ocr_pages else ExtractionMethod.TEXT
    return ExtractedText(_clean("\n\n".join(pages)), method)


def ocr_image(image: Image.Image) -> str:
    gray = ImageOps.autocontrast(image.convert("L"))
    binary = gray.point(lambda value: 255 if value > _OCR_THRESHOLD else 0)
    binary = binary.filter(ImageFilter.MedianFilter(3))
    data = pytesseract.image_to_data(
        binary, lang="ukr", config="--psm 3", output_type=pytesseract.Output.DICT
    )
    return _drop_noise_lines(_fix_misread_letters(_confident_text(data)))


def _confident_text(data: dict[str, list]) -> str:
    """Rebuilds the page without the junk Tesseract reads from background blotches.

    Junk comes as low-confidence words in lines of their own. A real word can also get a low
    score ("Кабан" in "Кабан носить хмиз"), so a low-confidence word survives when it looks
    like a word and its line has enough confident neighbours.
    """
    lines: dict[tuple[int, int, int], list[tuple[str, float]]] = {}
    for i, word in enumerate(data["text"]):
        if word.strip():
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append((word, float(data["conf"][i])))

    result: list[str] = []
    previous_paragraph = None
    for (block, paragraph, _), words in sorted(lines.items()):
        confident = sum(conf >= _OCR_MIN_CONFIDENCE for _, conf in words)
        kept = [
            word
            for word, conf in words
            if conf >= _OCR_MIN_CONFIDENCE
            or confident >= _OCR_MIN_CONFIDENT_NEIGHBOURS
            and _looks_like_word(word)
        ]
        if not kept:
            continue
        if previous_paragraph is not None and previous_paragraph != (block, paragraph):
            result.append("")
        result.append(" ".join(kept))
        previous_paragraph = (block, paragraph)
    return "\n".join(result)


def _looks_like_word(token: str) -> bool:
    letters = sum(ch.isalpha() for ch in token)
    return letters >= 3 and letters >= len(token) * 0.6


def _fix_misread_letters(text: str) -> str:
    # "1 рибина за З гілки": the digit 3 read as the Cyrillic letter З in the middle of a sentence
    text = re.sub(r"(?<=[^\s.!?] )З(?= )", "3", text)
    # "спокійно Й затишно": a capital conjunction in the middle of a sentence
    return re.sub(r"(?<=[^\s.!?] )Й(?= )", "й", text)


def _drop_noise_lines(text: str) -> str:
    """OCR turns dark blotches into lines like '— ~~ .'; real lines are mostly letters."""
    kept = []
    for line in text.splitlines():
        letters = sum(ch.isalpha() for ch in line)
        if not line.strip() or letters >= 3 and letters >= len(line.strip()) * 0.5:
            kept.append(line)
    return "\n".join(kept)


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("­", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # words hyphenated across lines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
