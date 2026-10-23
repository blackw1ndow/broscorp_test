"""The answer prompt and its parsing. Sources come from the database, not from the model
(R13, R14, D4, D20): the model only says which fragments it used."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from forest_bot.db.repositories.chunks import Fragment
from forest_bot.forest import MITTEN_PARTS, PLACES, Level, describe_place

_MONTHS = (
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
)  # fmt: skip


@dataclass(frozen=True)
class Source:
    document_id: int
    title: str
    place_code: str
    source: str  # 'archive' | 'user'
    author: str | None
    uploaded_at: datetime


@dataclass(frozen=True)
class Answer:
    text: str  # empty when the archive has no such advice (D3)
    sources: list[Source]

    @property
    def found(self) -> bool:
        return bool(self.text and self.sources)


NOT_FOUND = Answer("", [])


def format_date(day: date) -> str:
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def _place_context(place_code: str | None) -> str:
    if place_code is None:
        return "Звір не назвав місце."
    place = PLACES[place_code]
    if place.level is Level.MITTEN:
        parts = [PLACES[p].name.lower() for p in MITTEN_PARTS[place_code]]
        where = (
            f"належить до: {' і '.join(parts)}" if parts else "не належить до жодної частини лісу"
        )
        return f"Звір питає про рукавичку «{place.name}» ({where})."
    return f"Звір питає про: {describe_place(place_code)}."


def build_answer_prompt(
    question: str, place_code: str | None, fragments: list[Fragment], today: date
) -> str:
    lines = [f"Сьогодні {format_date(today)}.", _place_context(place_code), "", "Фрагменти:"]
    for number, fragment in enumerate(fragments, start=1):
        lines += [f"--- {number} [{describe_place(fragment.place_code)}]", fragment.content]
    lines += ["", f"Питання: {question}"]
    return "\n".join(lines)


def parse_answer(raw: dict[str, Any], fragments: list[Fragment]) -> Answer:
    text = raw.get("answer")
    used = raw.get("used")
    if not isinstance(text, str) or not text.strip() or not isinstance(used, list):
        return NOT_FOUND

    sources: dict[int, Source] = {}
    for number in used:
        # The model sometimes writes numbers as strings; numbers outside the list are ignored
        try:
            index = int(number) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(fragments):
            continue
        fragment = fragments[index]
        sources.setdefault(
            fragment.document_id,
            Source(
                document_id=fragment.document_id,
                title=fragment.title,
                place_code=fragment.place_code,
                source=fragment.source,
                author=fragment.author,
                uploaded_at=fragment.uploaded_at,
            ),
        )
    if not sources:
        # An answer that cites nothing is not from the archive (D3)
        return NOT_FOUND
    return Answer(_clean_answer(text), list(sources.values()))


def _clean_answer(text: str) -> str:
    # The model sometimes double-escapes line breaks inside the JSON string
    text = text.replace("\\n", "\n")
    # ...and cites fragments despite the prompt: the sources are listed by the bot
    text = re.sub(r"\s*\((?:фрагмент|фрагменти)\s+[\d,\sі]+\)", "", text)
    return text.strip()
