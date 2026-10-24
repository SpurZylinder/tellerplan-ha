import pytest
from sqlalchemy.orm import Session

from factories import make_food
from modules.nutrition.service import Nutrients, nutrients_for, to_grams, total_nutrients


def test_to_grams_handles_mass_units(session: Session) -> None:
    food = make_food(session)

    assert to_grams(food, 250, "g") == 250
    assert to_grams(food, 0.5, "kg") == 500
    assert to_grams(food, 80, None) == 80


def test_to_grams_uses_food_units_case_insensitive(session: Session) -> None:
    food = make_food(session, "Ei", units={"Stück": 58})

    assert to_grams(food, 2, "stück") == 116


def test_to_grams_returns_none_for_unknown_unit(session: Session) -> None:
    assert to_grams(make_food(session), 1, "EL") is None


def test_nutrients_for_scales_per_100_g(session: Session) -> None:
    food = make_food(session, kcal=60, protein_g=11, fat_g=0.2, carbs_g=4)

    result = nutrients_for(food, 250)

    assert result.kcal == pytest.approx(150)
    assert result.protein_g == pytest.approx(27.5)


def test_total_nutrients_sums_items(session: Session) -> None:
    skyr = make_food(session, "Skyr", kcal=60, protein_g=11)
    oats = make_food(session, "Haferflocken", kcal=370, protein_g=13.5)

    total = total_nutrients([(skyr, 200), (oats, 50)])

    assert total.kcal == pytest.approx(120 + 185)
    assert total.protein_g == pytest.approx(22 + 6.75)


def test_nutrients_add_and_scale() -> None:
    combined = Nutrients(kcal=100, protein_g=10) + Nutrients(kcal=50, protein_g=5)

    assert combined.scaled(0.5) == Nutrients(kcal=75, protein_g=7.5)
