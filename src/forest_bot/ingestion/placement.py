"""Rule-based detection of the place a document is written for (R7, D23).

Every archive document says who it is for: either in the title ("Статут ОСМД Під дубом")
or in the first sentences ("Ця порада для мешканців хвойного лісу"). These rules place all
78 archive documents without an LLM; documents from animals also go through the LLM.
"""

import re
from dataclasses import dataclass, field

from forest_bot.forest import Place, find_places, normalize

_INTRO_CHARS = 800


@dataclass(frozen=True)
class RulePlacement:
    place: Place | None
    # Filled when the text names several places at once: the document may need splitting (D21)
    conflicting: list[Place] = field(default_factory=list)

    @property
    def is_resolved(self) -> bool:
        return self.place is not None


def detect_place(title: str, text: str) -> RulePlacement:
    title_places = find_places(title)
    if len(title_places) == 1:
        return RulePlacement(title_places[0])
    if title_places:
        return RulePlacement(None, title_places)

    for sentence in _intro_sentences(title, text):
        places = find_places(sentence)
        if len(places) == 1:
            return RulePlacement(places[0])
        if places:
            return RulePlacement(None, places)
    return RulePlacement(None)


def _intro_sentences(title: str, text: str) -> list[str]:
    body = re.sub(r"\s+", " ", text).strip()
    if normalize(body).startswith(normalize(title)):
        body = body[len(title) :]
    return [s for s in re.split(r"(?<=[.!?])\s+", body[:_INTRO_CHARS]) if s.strip()]


_TRAILING_PREPOSITION = re.compile(r"\s+(?:в|у|для|біля|на|з|із|від)$")
_TRAILING_MITTEN = re.compile(r"(?:\s+(?:поруч із|поруч з|від|в|у))?\s+рукавич\w*$")


def document_type(title: str, place: Place) -> str:
    """Title without the place: two documents of one type for one place are versions (D24).

    "Членські внески рукавички «Під дубом»" -> "членські внески"
    "Як утеплити рукавичку в хвойному лісі" -> "як утеплити"
    """
    result = normalize(title)
    for pattern in place.patterns:
        result = re.sub(pattern, " ", result)
    result = re.sub(r"[^\w\s'-]", " ", result)
    result = re.sub(r"\s+", " ", result).strip()
    result = _TRAILING_PREPOSITION.sub("", result)
    result = _TRAILING_MITTEN.sub("", result)
    result = _TRAILING_PREPOSITION.sub("", result)
    return result or normalize(title)
