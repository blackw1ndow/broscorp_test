import pytest

from forest_bot.forest import MITTEN_PARTS, MITTENS, PLACES, Level, applicable_places, find_places


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("forest", ["forest"]),
        ("coniferous", ["forest", "coniferous"]),
        ("pid_dubom", ["forest", "deciduous", "pid_dubom"]),
        # "Під вербою" is both in the deciduous forest and by the river
        ("pid_verboyu", ["forest", "deciduous", "river", "pid_verboyu"]),
        # "На узліссі" belongs to no part: only forest-wide advice and its own
        ("na_uzlissi", ["forest", "na_uzlissi"]),
    ],
)
def test_applicable_places(code, expected):
    assert applicable_places(code) == expected


def test_every_mitten_is_on_the_map():
    assert set(MITTEN_PARTS) == {m.code for m in MITTENS}
    for parts in MITTEN_PARTS.values():
        assert all(PLACES[p].level is Level.PART for p in parts)


def test_map_matches_the_customer_answer():
    by_name = {PLACES[code].name: parts for code, parts in MITTEN_PARTS.items()}
    assert (
        by_name["Під ялиною"] == by_name["У соснах"] == by_name["Біля мурашника"] == ("coniferous",)
    )
    assert by_name["Під дубом"] == by_name["У ліщині"] == ("deciduous",)
    assert by_name["Біля бобрової греблі"] == ("river",)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Мешканці рукавички «У соснах»!", ["u_sosnakh"]),
        ("порада для мешканців хвойного лісу", ["coniferous"]),
        ("Для тих, хто живе біля річки", ["river"]),
        ("Ця пам'ятка для всіх мешканців лісу", ["forest"]),
        ("Для хвойного лісу і для листяного лісу", ["coniferous", "deciduous"]),
        ("Як не заблукати серед однакових сосен", []),
    ],
)
def test_find_places(text, expected):
    assert [p.code for p in find_places(text)] == expected
