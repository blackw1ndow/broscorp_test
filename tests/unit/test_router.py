import pytest

from forest_bot.db.repositories.messages import HistoryMessage
from forest_bot.forest import find_question_places
from forest_bot.qa.router import build_router_prompt, parse_route, route_question


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The customer's own examples (R8)
        ("Які гриби біля сосон?", ["u_sosnakh"]),
        ("Скільки внесок під дубом?", ["pid_dubom"]),
        ("Як перейти річку біля бобрової греблі?", ["bilia_hrebli"]),
        ("Коли йти по гриби на узліссі?", ["na_uzlissi"]),
        ("А під ялинкою?", ["pid_yalynoyu"]),
        ("Що їсти в хвойному лісі?", ["coniferous"]),
        # A mitten with its own part of the forest is just the mitten
        ("Гриби під вербою біля річки", ["pid_verboyu"]),
        ("Скільки внесок?", []),
        ("Що робити при пожежі?", []),
    ],
)
def test_find_question_places(text, expected):
    assert [p.code for p in find_question_places(text)] == expected


def test_two_mittens_are_not_collapsed():
    assert [p.code for p in find_question_places("Внески під дубом і в соснах")] == [
        "u_sosnakh",
        "pid_dubom",
    ]


def test_place_in_the_message_beats_the_model():
    route = parse_route(
        {"is_forest_question": True, "place": "u_sosnakh", "needs_place": True},
        "Скільки внесок під дубом?",
    )
    assert route.place == "pid_dubom"
    assert not route.must_ask_place


def test_unknown_place_code_from_the_model_is_dropped():
    route = parse_route({"place": "pid_horobynoyu", "needs_place": True}, "Скільки внесок?")
    assert route.place is None
    assert route.must_ask_place


def test_place_from_the_rewritten_follow_up():
    route = parse_route(
        {"standalone_question": "Скільки внесок під ялиною?", "place": None},
        "а там?",
    )
    assert route.question == "Скільки внесок під ялиною?"
    assert route.place == "pid_yalynoyu"


def test_place_not_needed_answers_right_away():
    route = parse_route(
        {"is_forest_question": True, "place": None, "needs_place": False},
        "Що робити при пожежі?",
    )
    assert route.place is None
    assert not route.must_ask_place
    assert route.question == "Що робити при пожежі?"


def test_small_talk():
    assert not parse_route({"is_forest_question": False}, "Як приготувати борщ?").is_forest_question


def test_broken_model_reply_falls_back_to_the_text():
    route = parse_route({}, "Коли падають жолуді?")
    assert route.question == "Коли падають жолуді?"
    assert route.is_forest_question


def test_router_prompt_has_doc_types_and_history():
    prompt = build_router_prompt(
        "а під ялиною?",
        [HistoryMessage("user", "Скільки внесок під дубом?"), HistoryMessage("assistant", "4")],
        {"forest": ["календар сезонів"], "mitten": ["членські внески", "чергування"]},
    )
    # Types are quoted: they come from document titles and are data, not instructions
    assert "для рукавичок (у кожної рукавички свої): «членські внески»; «чергування»" in prompt
    assert "Звір: Скільки внесок під дубом?" in prompt
    assert "Бот: 4" in prompt
    assert prompt.endswith("Нове повідомлення звіра: а під ялиною?")


async def test_route_question_calls_the_fast_model(mocker):
    llm = mocker.AsyncMock()
    llm.complete_json.return_value = {"is_forest_question": True, "needs_place": True}
    route = await route_question(llm, "fast", "Скільки внесок?", [], {})
    assert llm.complete_json.call_args.args[0] == "fast"
    assert route.must_ask_place


def test_doc_types_are_kept_only_from_the_catalog():
    route = parse_route(
        {
            "doc_types": [
                "календар сезонів",
                "рецепти",
                5,
                "календар сезонів",
                "що їсти",
                "небезпеки",
            ]
        },
        "Чи можна зараз збирати гриби?",
        {"календар сезонів", "що їсти", "небезпеки", "грибний путівник"},
    )
    assert route.doc_types == ("календар сезонів", "що їсти", "небезпеки")


async def test_route_question_validates_doc_types_against_the_catalog(mocker):
    llm = mocker.AsyncMock()
    llm.complete_json.return_value = {"doc_types": ["календар сезонів", "вигадка"]}
    route = await route_question(llm, "fast", "Коли гриби?", [], {"forest": ["календар сезонів"]})
    assert route.doc_types == ("календар сезонів",)


def test_doc_types_echoed_with_the_quotes_are_still_recognised():
    route = parse_route(
        {"doc_types": ["«календар сезонів»", " що їсти "]},
        "Чи можна зараз збирати гриби?",
        {"календар сезонів", "що їсти"},
    )
    assert route.doc_types == ("календар сезонів", "що їсти")
