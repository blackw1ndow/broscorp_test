"""Question routing: is it about the forest, which place it is about, and whether the bot has to
ask for the mitten first (R8, R10a, D8, D12)."""

import logging
from dataclasses import dataclass
from typing import Any

from forest_bot.db.repositories.messages import HistoryMessage
from forest_bot.forest import PLACES, find_question_places
from forest_bot.llm.client import LLMClient
from forest_bot.llm.prompts import ROUTER_SYSTEM

log = logging.getLogger(__name__)

_LEVEL_LABELS = {
    "forest": "для всього лісу (одні для всіх)",
    "part": "для частин лісу (у кожної частини свої)",
    "mitten": "для рукавичок (у кожної рукавички свої)",
}


@dataclass(frozen=True)
class Route:
    is_forest_question: bool
    question: str  # rewritten to make sense without the conversation
    place: str | None
    needs_place: bool
    # Document types from the catalog where the answer probably is: vector search alone misses
    # "Календар сезонів" for «Чи можна зараз збирати гриби?»
    doc_types: tuple[str, ...] = ()

    @property
    def must_ask_place(self) -> bool:
        return self.place is None and self.needs_place


def named_place(text: str) -> str | None:
    """The one place the text names, if it names exactly one."""
    places = find_question_places(text)
    return places[0].code if len(places) == 1 else None


def build_router_prompt(
    text: str, history: list[HistoryMessage], doc_types: dict[str, list[str]]
) -> str:
    lines = ["Типи документів в архіві:"]
    for level, label in _LEVEL_LABELS.items():
        if doc_types.get(level):
            lines.append(f"- {label}: {'; '.join(doc_types[level])}")
    if history:
        lines += ["", "Попередня розмова:"]
        for message in history:
            who = "Звір" if message.role == "user" else "Бот"
            lines.append(f"{who}: {message.content[:300]}")
    lines += ["", f"Нове повідомлення звіра: {text}"]
    return "\n".join(lines)


def parse_route(raw: dict[str, Any], text: str, known_types: set[str] | None = None) -> Route:
    question = raw.get("standalone_question")
    if not isinstance(question, str) or not question.strip():
        question = text
    # A place named in the message itself beats the model's guess
    place = named_place(text)
    if place is None:
        llm_place = raw.get("place")
        place = llm_place if isinstance(llm_place, str) and llm_place in PLACES else None
    if place is None:
        place = named_place(question)
    doc_types = raw.get("doc_types")
    if not isinstance(doc_types, list):
        doc_types = []
    return Route(
        is_forest_question=raw.get("is_forest_question") is not False,
        question=question.strip(),
        place=place,
        needs_place=bool(raw.get("needs_place")),
        doc_types=tuple(
            dict.fromkeys(t for t in doc_types if isinstance(t, str) and t in (known_types or ()))
        )[:3],
    )


async def route_question(
    llm: LLMClient,
    model: str,
    text: str,
    history: list[HistoryMessage],
    doc_types: dict[str, list[str]],
) -> Route:
    raw = await llm.complete_json(
        model, ROUTER_SYSTEM, build_router_prompt(text, history, doc_types), max_tokens=800
    )
    known_types = {t for types in doc_types.values() for t in types}
    route = parse_route(raw, text, known_types)
    log.info("Route %r -> %s", text, route)
    return route
