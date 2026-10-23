"""Receiving a document from an animal (flow 3.2): text, place, version, saving."""

import asyncio
import hashlib
import logging
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg

from forest_bot.config import KYIV_TZ
from forest_bot.db.repositories import documents
from forest_bot.db.repositories.documents import DocumentInfo
from forest_bot.embeddings import Embedder
from forest_bot.forest import PLACES, Level, Place, find_places, find_question_places
from forest_bot.ingestion.chunking import chunk_text
from forest_bot.ingestion.extract import SUPPORTED_EXTENSIONS, extract_text
from forest_bot.ingestion.placement import detect_place, document_type
from forest_bot.llm.client import LLMBadResponseError, LLMBusyError, LLMClient
from forest_bot.llm.prompts import PLACEMENT_SYSTEM, VERSION_SYSTEM

log = logging.getLogger(__name__)

# The most a bot can download through the Bot API (D19)
MAX_FILE_SIZE = 20 * 1024 * 1024

_INTRO_CHARS = 2000
_MAX_PLACE_LINES = 30
_MAX_TITLE_CHARS = 150
_MAX_HEADING_CHARS = 60


def is_supported(file_name: str) -> bool:
    return Path(file_name).suffix.lower() in SUPPORTED_EXTENSIONS


@dataclass(frozen=True)
class PendingDocument:
    """A read document waiting for its place; kept in the FSM while the animal chooses (R16)."""

    file_name: str
    sha256: str
    text: str
    extraction: str
    caption: str | None
    title: str

    def to_state(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_state(cls, data: dict[str, Any]) -> "PendingDocument":
        return cls(**data)


@dataclass(frozen=True)
class Broken:
    """The file could not be parsed at all."""


@dataclass(frozen=True)
class NoText:
    """No text even after OCR (D22)."""


@dataclass(frozen=True)
class NeedsSplit:
    places: list[Place]  # R20, D21


@dataclass(frozen=True)
class NeedsPlace:
    pending: PendingDocument
    unknown_mitten: str | None  # D16


@dataclass(frozen=True)
class AlreadyKnown:
    document: DocumentInfo


@dataclass(frozen=True)
class Saved:
    title: str
    place_code: str
    replaced: DocumentInfo | None  # D11


Outcome = Broken | NoText | NeedsSplit | NeedsPlace | AlreadyKnown | Saved


class IngestionService:
    def __init__(self, pool: asyncpg.Pool, embedder: Embedder, llm: LLMClient, model: str) -> None:
        self._pool = pool
        self._embedder = embedder
        self._llm = llm
        self._model = model

    async def receive(
        self, file_name: str, data: bytes, caption: str | None, author_id: int
    ) -> Outcome:
        read = await self.read(file_name, data, caption)
        if not isinstance(read, PendingDocument):
            return read
        located = await self.locate(read)
        if not isinstance(located, tuple):
            return located
        pending, place = located
        return await self.save(pending, place.code, author_id)

    async def read(
        self, file_name: str, data: bytes, caption: str | None
    ) -> PendingDocument | Broken | NoText:
        try:
            extracted = await asyncio.to_thread(extract_text, file_name, data)
        except Exception:
            log.exception("Cannot read %s", file_name)
            return Broken()
        if not extracted.text:
            return NoText()
        return PendingDocument(
            file_name=file_name,
            sha256=hashlib.sha256(data).hexdigest(),
            text=extracted.text,
            extraction=extracted.method.value,
            caption=caption.strip() if caption and caption.strip() else None,
            title=guess_title(extracted.text, file_name),
        )

    async def locate(
        self, pending: PendingDocument
    ) -> tuple[PendingDocument, Place] | NeedsSplit | NeedsPlace:
        """Rules first, then the LLM with the rules and the caption as hints (D17, D23)."""
        rules = detect_place(pending.title, pending.text)
        caption_places = find_question_places(pending.caption) if pending.caption else []
        headings = section_headings(pending.text)
        # Sections for two parts of the forest are a mixed document for sure (D21). Mittens in
        # headings are not: a document about paths may have a section per neighbour.
        heading_parts = list(
            dict.fromkeys(p for _, places in headings for p in places if p.level is Level.PART)
        )
        if len(heading_parts) > 1:
            return NeedsSplit(heading_parts)
        try:
            raw = await self._llm.complete_json(
                self._model,
                PLACEMENT_SYSTEM,
                _placement_prompt(pending, rules.place, caption_places, headings),
            )
        except (LLMBusyError, LLMBadResponseError):
            log.warning("LLM placement failed for %s, using the rules", pending.file_name)
            raw = None

        if raw is None:
            if len(caption_places) == 1:
                return pending, caption_places[0]
            if rules.place is not None:
                return pending, rules.place
            return NeedsPlace(pending, None)

        title = raw.get("title")
        if isinstance(title, str) and 0 < len(title.strip()) <= _MAX_TITLE_CHARS:
            pending = replace(pending, title=title.strip())
        places = _valid_places(raw.get("places"))
        log.info("Placement of %s: rules %s, LLM %s", pending.file_name, rules, places)
        if len(places) > 1:
            return NeedsSplit(places)
        if len(places) == 1:
            return pending, places[0]
        unknown = raw.get("unknown_mitten")
        return NeedsPlace(
            pending, unknown.strip() if isinstance(unknown, str) and unknown.strip() else None
        )

    async def save(
        self, pending: PendingDocument, place_code: str, author_id: int
    ) -> AlreadyKnown | Saved:
        place = PLACES[place_code]
        async with self._pool.acquire() as conn:
            duplicate = await documents.find_active_by_hash(conn, pending.sha256, place_code)
            if duplicate is not None:
                return AlreadyKnown(duplicate)
            doc_type = document_type(pending.title, place)
            previous = await documents.find_active(conn, doc_type, place_code)
            if previous is None:
                candidates = await documents.list_active(conn, place_code=place_code)
                previous = await self._previous_version(pending, candidates)
                if previous is not None:
                    doc_type = previous.doc_type

        chunks = chunk_text(pending.title, pending.text)
        embeddings = await self._embedder.embed(chunks)
        doc = documents.NewDocument(
            title=pending.title,
            doc_type=doc_type,
            place_code=place_code,
            source="user",
            author_id=author_id,
            file_name=pending.file_name,
            file_sha256=pending.sha256,
            extraction=pending.extraction,
            full_text=pending.text,
            # D13: the newer version is the one sent later
            uploaded_at=datetime.now(KYIV_TZ),
        )
        async with self._pool.acquire() as conn, conn.transaction():
            # Re-read under the transaction: someone may have replaced it in the meantime
            current = await documents.find_active(conn, doc_type, place_code)
            if current is not None:
                await documents.supersede(conn, current.id)
            await documents.insert_document(
                conn, doc, chunks, embeddings, replaces_id=current.id if current else None
            )
        log.info("Saved %r for %s, replaced %s", pending.title, place_code, current)
        return Saved(pending.title, place_code, current)

    async def _previous_version(
        self, pending: PendingDocument, candidates: list[DocumentInfo]
    ) -> DocumentInfo | None:
        """No exact type match: ask the LLM whether it is a new version of one of them (D24)."""
        if not candidates:
            return None
        listing = "\n".join(f"{i}. «{c.title}»" for i, c in enumerate(candidates, start=1))
        prompt = (
            f"Новий документ «{pending.title}»:\n{pending.text[:600]}\n\n"
            f"Чинні документи для цього місця:\n{listing}"
        )
        try:
            raw = await self._llm.complete_json(self._model, VERSION_SYSTEM, prompt, max_tokens=500)
        except (LLMBusyError, LLMBadResponseError):
            log.warning("LLM version check failed for %s; saving as a new document", pending.title)
            return None
        number = raw.get("replaces")
        if isinstance(number, int) and 1 <= number <= len(candidates):
            return candidates[number - 1]
        return None


def guess_title(text: str, file_name: str) -> str:
    """The first line if it looks like a heading, otherwise the file name."""
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if 3 <= len(first_line) <= _MAX_TITLE_CHARS and not first_line.endswith((".", ",", ":")):
        return first_line
    return Path(file_name).stem


def section_headings(text: str) -> list[tuple[str, list[Place]]]:
    """Short heading-like lines after the title that name a place: «Хвойний ліс», «Для листяного
    лісу:». None of the 78 archive documents has headings for two places."""
    result = []
    for line in text.splitlines()[1:]:
        line = line.strip()
        if 3 <= len(line) <= _MAX_HEADING_CHARS and not line.endswith((".", ",", ";", "!", "?")):
            places = find_places(line)
            if places:
                result.append((line, places))
    return result


def _valid_places(value: Any) -> list[Place]:
    if not isinstance(value, list):
        return []
    codes = list(dict.fromkeys(code for code in value if isinstance(code, str) and code in PLACES))
    return [PLACES[code] for code in codes]


def _placement_prompt(
    pending: PendingDocument,
    rules_place: Place | None,
    caption_places: list[Place],
    headings: list[tuple[str, list[Place]]],
) -> str:
    lines = [f"Файл: {pending.file_name}"]
    if pending.caption:
        lines.append(f"Підпис звіра до файла: {pending.caption}")
        if caption_places:
            lines.append(f"(у підписі названо: {', '.join(p.code for p in caption_places)})")
    if rules_place is not None:
        lines.append(f"Правила за вступом припускають: {rules_place.code}")
    if headings:
        lines.append("Заголовки розділів, що називають місця:")
        lines += [
            f"- {line} → {', '.join(p.code for p in places)}"
            for line, places in headings[:_MAX_PLACE_LINES]
        ]
    lines += ["", "Початок документа:", pending.text[:_INTRO_CHARS]]

    rest = pending.text[_INTRO_CHARS:]
    # Section headings further on usually name their place: enough to spot a mixed document
    place_lines = [line.strip() for line in rest.splitlines() if line.strip() and find_places(line)]
    if place_lines:
        lines += ["", "Далі в документі згадано місця в рядках:"]
        lines += [f"- {line[:200]}" for line in place_lines[:_MAX_PLACE_LINES]]
    elif rest.strip():
        lines += ["", f"(далі ще {len(rest)} символів тексту без назв місць)"]
    return "\n".join(lines)
