"""The forest map (R17, R18): places, which parts of the forest each mitten belongs to,
and which documents apply to a place."""

import re
from dataclasses import dataclass
from enum import StrEnum


class Level(StrEnum):
    FOREST = "forest"
    PART = "part"
    MITTEN = "mitten"


@dataclass(frozen=True)
class Place:
    code: str
    level: Level
    name: str  # as the animals write it: "Під дубом", "Хвойний ліс"
    patterns: tuple[str, ...]  # regexes over normalized (lowercase) text
    # Extra ways animals name the place in questions ("які гриби біля сосон?", R8)
    aliases: tuple[str, ...] = ()


FOREST = Place("forest", Level.FOREST, "Весь ліс", (r"(?:всіх|усіх) мешканців (?:нашого )?лісу",))

PARTS = (
    Place("coniferous", Level.PART, "Хвойний ліс", (r"хвойн\w*\s+ліс\w*",)),
    Place("deciduous", Level.PART, "Листяний ліс", (r"листян\w*\s+ліс\w*",)),
    Place("river", Level.PART, "Біля річки", (r"біля річки",), (r"(?:коло|над) річкою",)),
)

MITTENS = (
    Place("pid_yalynoyu", Level.MITTEN, "Під ялиною", (r"під ялиною",), (r"під ялинк\w*",)),
    Place("u_sosnakh", Level.MITTEN, "У соснах", (r"[ув] соснах",), (r"(?:біля|коло) сос[ое]н",)),
    Place(
        "bilia_murashnyka",
        Level.MITTEN,
        "Біля мурашника",
        (r"біля мурашника",),
        (r"коло мурашника",),
    ),
    Place("pid_dubom", Level.MITTEN, "Під дубом", (r"під дубом",), (r"під дубами",)),
    Place("u_lishchyni", Level.MITTEN, "У ліщині", (r"[ув] ліщині",), (r"[ув] ліщиннику",)),
    Place("pid_verboyu", Level.MITTEN, "Під вербою", (r"під вербою",), (r"під вербами",)),
    Place(
        "bilia_hrebli",
        Level.MITTEN,
        "Біля бобрової греблі",
        (r"біля бобрової греблі",),
        (r"(?:біля|коло) греблі",),
    ),
    Place("na_uzlissi", Level.MITTEN, "На узліссі", (r"на узліссі",)),
)

PLACES: dict[str, Place] = {p.code: p for p in (FOREST, *PARTS, *MITTENS)}

# Карта лісу. "На узліссі" belongs to no part: only forest-wide advice applies there.
MITTEN_PARTS: dict[str, tuple[str, ...]] = {
    "pid_yalynoyu": ("coniferous",),
    "u_sosnakh": ("coniferous",),
    "bilia_murashnyka": ("coniferous",),
    "pid_dubom": ("deciduous",),
    "u_lishchyni": ("deciduous",),
    "pid_verboyu": ("deciduous", "river"),
    "bilia_hrebli": ("river",),
    "na_uzlissi": (),
}


def applicable_places(code: str) -> list[str]:
    """Places whose advice applies to `code`, from the most general to the most specific (R19)."""
    place = PLACES[code]
    if place.level is Level.FOREST:
        return [FOREST.code]
    if place.level is Level.PART:
        return [FOREST.code, code]
    return [FOREST.code, *MITTEN_PARTS[code], code]


_QUOTES = str.maketrans({"«": " ", "»": " ", '"': " ", "“": " ", "”": " ", "’": "'", "ʼ": "'"})


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_QUOTES).lower()).strip()


def find_places(text: str, candidates: tuple[Place, ...] | None = None) -> list[Place]:
    """All places mentioned in `text`, in a stable order (forest, parts, mittens)."""
    normalized = normalize(text)
    pool = candidates if candidates is not None else tuple(PLACES.values())
    return [p for p in pool if any(re.search(pat, normalized) for pat in p.patterns)]


def find_question_places(text: str) -> list[Place]:
    """Places named in a question: the document patterns plus the aliases animals use.

    A mitten together with its own part of the forest ("під вербою біля річки") is the mitten.
    """
    normalized = normalize(text)
    found = [
        p
        for p in PLACES.values()
        if any(re.search(pat, normalized) for pat in (*p.patterns, *p.aliases))
    ]
    mittens = [p for p in found if p.level is Level.MITTEN]
    if len(mittens) == 1:
        own = {FOREST.code, *MITTEN_PARTS[mittens[0].code]}
        if all(p.code in own for p in found if p.level is not Level.MITTEN):
            return mittens
    return found


def describe_place(code: str) -> str:
    """How a place is labelled for the LLM and in the bot's messages."""
    place = PLACES[code]
    if place.level is Level.FOREST:
        return "весь ліс"
    if place.level is Level.PART:
        return f"частина лісу: {place.name.lower()}"
    return f"рукавичка «{place.name}»"
