from sqlalchemy.orm import Session

from factories import make_food
from modules.foods.service import delete_unit, search_foods, set_unit


def test_search_requires_all_terms_and_ignores_case(session: Session) -> None:
    make_food(session, "Skyr natur")
    make_food(session, "Skyr Vanille")
    make_food(session, "Magerquark")

    names = [food.name for food in search_foods(session, "skyr NATUR")]

    assert names == ["Skyr natur"]


def test_search_folds_umlauts(session: Session) -> None:
    make_food(session, "Rapsöl")
    make_food(session, "Äpfel")

    assert [f.name for f in search_foods(session, "äpfel")] == ["Äpfel"]
    assert [f.name for f in search_foods(session, "ÖL")] == ["Rapsöl"]


def test_search_ranks_closer_names_first(session: Session) -> None:
    make_food(session, "Hühnerei, gekocht, mit Schale")
    make_food(session, "Ei")

    assert search_foods(session, "ei")[0].name == "Ei"


def test_empty_search_lists_newest_first(session: Session) -> None:
    make_food(session, "Erstes")
    make_food(session, "Zweites")

    assert [f.name for f in search_foods(session, "  ")] == ["Zweites", "Erstes"]


def test_set_unit_updates_existing_unit(session: Session) -> None:
    food = make_food(session, "Ei")
    set_unit(session, food, "Stück", 55)
    set_unit(session, food, "stück", 60)

    assert [(u.name, u.grams) for u in food.units] == [("Stück", 60)]


def test_delete_unit(session: Session) -> None:
    food = make_food(session, "Öl", units={"EL": 10, "TL": 4})
    tablespoon = next(u for u in food.units if u.name == "EL")

    delete_unit(session, food, tablespoon.id)

    assert [u.name for u in food.units] == ["TL"]
