import pytest
from sqlalchemy.orm import Session

from factories import make_food
from modules.nutrition.service import (
    Nutrients,
    StandardUnit,
    nutrients_for,
    to_grams,
    total_nutrients,
    unit_choices,
    uses_standard_unit,
)


def test_to_grams_handles_mass_units(session: Session) -> None:
    food = make_food(session)

    assert to_grams(food, 250, "g") == 250
    assert to_grams(food, 0.5, "kg") == 500
    assert to_grams(food, 80, None) == 80


def test_to_grams_uses_food_units_case_insensitive(session: Session) -> None:
    food = make_food(session, "Ei", units={"Stück": 58})

    assert to_grams(food, 2, "stück") == 116


def test_to_grams_returns_none_for_unknown_unit(session: Session) -> None:
    assert to_grams(make_food(session), 1, "Handvoll") is None


def test_standard_units_apply_without_own_unit(session: Session) -> None:
    food = make_food(session)

    assert to_grams(food, 2, "EL") == 30
    assert to_grams(food, 1, "tl") == 5
    assert uses_standard_unit(food, "EL") == StandardUnit("EL", 15)
    assert uses_standard_unit(food, "g") is None


def test_own_unit_beats_standard_unit(session: Session) -> None:
    oil = make_food(session, "Rapsöl", units={"EL": 10})

    assert to_grams(oil, 2, "EL") == 20
    assert uses_standard_unit(oil, "EL") is None
    assert uses_standard_unit(oil, "TL") == StandardUnit("TL", 5)


def test_unit_choices_offer_own_units_and_standard_units(session: Session) -> None:
    onion = make_food(session, "Zwiebel", units={"EL": 12, "Stück": 80})

    assert unit_choices(onion) == [
        StandardUnit("g", 1),
        StandardUnit("EL", 12),
        StandardUnit("Stück", 80),
        StandardUnit("TL", 5),
    ]


def test_unit_choices_without_food_offer_only_grams() -> None:
    assert unit_choices(None) == [StandardUnit("g", 1)]


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


def test_containers_count_as_one_package(session: Session) -> None:
    coconut = make_food(session, "ja! Kokosmilch fettreduziert 400g", units={"Packung": 400})
    tomatoes = make_food(session, "Tomaten geschält", units={"Packung": 480, "Dose": 240})
    plain = make_food(session, "Kichererbse reif")

    assert to_grams(coconut, 1, "Dose") == 400
    assert to_grams(coconut, 0.5, "Glas") == 200
    assert to_grams(tomatoes, 1, "Dose") == 240  # eigene Angabe geht vor
    assert to_grams(plain, 1, "Dose") is None  # ohne Packungsgröße weiter fragen
    assert to_grams(coconut, 1, "Prise") is None


def test_fiber_sugar_and_salt_are_calculated(session: Session) -> None:
    oats = make_food(session, "Haferflocken", kcal=370)
    oats.fiber_g, oats.sugar_g, oats.salt_g = 10.0, 1.0, 0.02

    nutrients = nutrients_for(oats, 50)

    assert (nutrients.fiber_g, nutrients.sugar_g, nutrients.salt_g) == (5.0, 0.5, 0.01)


def test_missing_value_makes_the_total_unknown_not_zero(session: Session) -> None:
    # K15: Kennt eine Zutat keinen Zucker, ist die Summe unbekannt statt zu niedrig
    oats = make_food(session, "Haferflocken")
    oats.sugar_g = 1.0
    own = make_food(session, "Eigenes Müsli")  # ohne Zucker-Angabe

    total = total_nutrients([(oats, 100), (own, 100)])

    assert total.sugar_g is None
    assert total_nutrients([(oats, 100)]).sugar_g == 1.0
    assert (Nutrients(sugar_g=None) + Nutrients(sugar_g=2.0)).sugar_g is None
    assert Nutrients(sugar_g=None).scaled(2).sugar_g is None
