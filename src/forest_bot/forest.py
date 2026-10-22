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


FOREST = Place("forest", Level.FOREST, "Весь ліс", (r"(?:всіх|усіх) мешканців (?:нашого )?лісу",))

PARTS = (
    Place("coniferous", Level.PART, "Хвойний ліс", (r"хвойн\w*\s+ліс\w*",)),
    Place("deciduous", Level.PART, "Листяний ліс", (r"листян\w*\s+ліс\w*",)),
    Place("river", Level.PART, "Біля річки", (r"біля річки",)),
)

MITTENS = (
    Place("pid_yalynoyu", Level.MITTEN, "Під ялиною", (r"під ялиною",)),
    Place("u_sosnakh", Level.MITTEN, "У соснах", (r"[ув] соснах",)),
    Place("bilia_murashnyka", Level.MITTEN, "Біля мурашника", (r"біля мурашника",)),
    Place("pid_dubom", Level.MITTEN, "Під дубом", (r"під дубом",)),
    Place("u_lishchyni", Level.MITTEN, "У ліщині", (r"[ув] ліщині",)),
    Place("pid_verboyu", Level.MITTEN, "Під вербою", (r"під вербою",)),
    Place("bilia_hrebli", Level.MITTEN, "Біля бобрової греблі", (r"біля бобрової греблі",)),
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
