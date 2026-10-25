from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from factories import make_food
from modules.foods.models import FoodSource
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


def _bls(session: Session, *names: str) -> None:
    for index, name in enumerate(names):
        make_food(session, name, source=FoodSource.BLS, source_id=f"T{index:06d}")


def test_search_prefers_whole_word_and_main_word(session: Session) -> None:
    _bls(session, "Reisrand", "Curryreis", "Milchreis gekocht", "Reis poliert, roh", "Reis Mehl")

    names = [food.name for food in search_foods(session, "reis")]

    assert names[:2] == ["Reis poliert, roh", "Reis Mehl"]
    # Grundwort hinten: Curryreis ist ein Reis, ein Reisrand ist kein Reis
    assert names.index("Curryreis") < names.index("Reisrand")


def test_search_prefers_main_word_over_later_mentions(session: Session) -> None:
    _bls(
        session, "Salzkartoffeln (Kartoffeln mit Salz gekocht)", "Lachs in Öl", "Meersalz", "Rapsöl"
    )

    assert search_foods(session, "salz")[0].name == "Meersalz"
    assert search_foods(session, "öl")[0].name == "Rapsöl"


def test_search_prefers_raw_and_own_foods(session: Session) -> None:
    _bls(session, "Lachs gegrillt", "Lachs roh")
    make_food(session, "Lachs")

    assert [food.name for food in search_foods(session, "lachs")] == [
        "Lachs roh",
        "Lachs",
        "Lachs gegrillt",
    ]


def test_search_ignores_spaces_between_words(session: Session) -> None:
    _bls(session, "Hafer Flocken")

    assert [food.name for food in search_foods(session, "haferflocken")] == ["Hafer Flocken"]


def test_hyphenated_words_do_not_count_as_main_word(session: Session) -> None:
    _bls(session, "Quark-Plunder", "Joghurt-Dip", "Joghurt mild, mind. 3,5 % Fett")

    assert search_foods(session, "joghurt")[0].name == "Joghurt mild, mind. 3,5 % Fett"


def test_fuzzy_fallback_finds_other_spelling(session: Session) -> None:
    _bls(session, "Broccoli roh", "Aioli")

    assert search_foods(session, "brokkoli")[0].name == "Broccoli roh"


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


def test_brand_is_shown_instead_of_source(ingress_client: TestClient) -> None:
    response = ingress_client.post(
        "/foods/new",
        data={
            "name": "Laktosefreie Milch 1,5 %",
            "brand": "Berchtesgadener Land",
            "kcal": "47",
            "protein_g": "3,4",
            "fat_g": "1,5",
            "carbs_g": "4,9",
        },
        follow_redirects=False,
    )
    detail = ingress_client.get(response.headers["location"]).text

    assert "Berchtesgadener Land" in detail
    assert ">eigen<" not in detail
    assert "Berchtesgadener Land" in ingress_client.get("/foods/search?q=laktosefrei").text
