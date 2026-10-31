from datetime import date

import pytest
from sqlalchemy.orm import Session

from factories import make_food, make_recipe
from modules.diary.service import (
    UnknownUnitError,
    change_amount,
    change_servings,
    day_log,
    delete_entry,
    log_food,
    log_recipe,
    planned_for_day,
)
from modules.planner.service import add_entry

DAY = date(2026, 10, 24)
MEALS = ["Frühstück", "Mittag", "Abendessen", "Snacks"]


def test_log_food_converts_units(session: Session) -> None:
    banana = make_food(session, "Banane", kcal=93, protein_g=1.1, units={"Stück": 120})

    entry = log_food(session, DAY, "Snacks", banana, 1, "Stück")

    assert entry.grams == 120
    assert entry.kcal == pytest.approx(111.6)
    assert entry.label == "Banane"


def test_log_food_rejects_unknown_unit(session: Session) -> None:
    skyr = make_food(session, "Skyr")

    with pytest.raises(UnknownUnitError):
        log_food(session, DAY, "Frühstück", skyr, 1, "Becher")


def test_log_recipe_uses_eaten_servings(session: Session) -> None:
    skyr = make_food(session, "Skyr", kcal=60, protein_g=11)
    recipe = make_recipe(session, servings=4, ingredients=[(skyr, 800, "g")])

    entry = log_recipe(session, DAY, "Mittag", recipe, servings=1.5)

    assert entry.kcal == pytest.approx(120 * 1.5)
    assert entry.protein_g == pytest.approx(22 * 1.5)
    assert entry.is_complete


def test_snapshot_survives_recipe_changes(session: Session) -> None:
    skyr = make_food(session, "Skyr", kcal=100)
    recipe = make_recipe(session, servings=1, ingredients=[(skyr, 100, "g")])
    log_recipe(session, DAY, "Mittag", recipe, servings=1)

    skyr.kcal = 500
    recipe.servings = 10

    assert day_log(session, DAY, MEALS).total.kcal == pytest.approx(100)


def test_day_log_groups_by_meal_and_sums(session: Session) -> None:
    skyr = make_food(session, "Skyr", kcal=60)
    log_food(session, DAY, "Frühstück", skyr, 200, "g")
    log_food(session, DAY, "Snacks", skyr, 100, "g")
    log_food(session, date(2026, 10, 25), "Snacks", skyr, 1000, "g")

    log = day_log(session, DAY, MEALS)

    assert [meal.name for meal in log.meals] == MEALS
    assert log.meals[0].total.kcal == pytest.approx(120)
    assert log.meals[1].entries == []
    assert log.total.kcal == pytest.approx(180)


def test_day_log_keeps_entries_of_renamed_meals(session: Session) -> None:
    log_food(session, DAY, "Brunch", make_food(session), 100, "g")

    log = day_log(session, DAY, MEALS)

    assert log.meals[-1].name == "Brunch"
    assert len(log.meals[-1].entries) == 1


def test_incomplete_recipe_marks_day(session: Session) -> None:
    recipe = make_recipe(session, ingredients=[(None, 1, "Prise")])
    log_recipe(session, DAY, "Mittag", recipe, servings=1)

    assert not day_log(session, DAY, MEALS).complete


def test_planned_for_day_marks_logged_dishes(session: Session) -> None:
    recipe = make_recipe(session, title="Bolognese")
    other = make_recipe(session, title="Salat")
    planned = add_entry(session, DAY, recipe)
    add_entry(session, DAY, other)

    log_recipe(session, DAY, "Mittag", recipe, servings=1, plan_entry=planned)

    status = {item.dish.entry.recipe.title: item.logged for item in planned_for_day(session, DAY)}
    assert status == {"Bolognese": True, "Salat": False}


def test_delete_entry(session: Session) -> None:
    entry = log_food(session, DAY, "Snacks", make_food(session), 100, "g")

    delete_entry(session, entry)

    assert day_log(session, DAY, MEALS).total.kcal == 0


def test_change_servings_scales_snapshot(session: Session) -> None:
    skyr = make_food(session, "Skyr", kcal=100)
    recipe = make_recipe(session, servings=1, ingredients=[(skyr, 100, "g")])
    entry = log_recipe(session, DAY, "Mittag", recipe, servings=1)
    skyr.kcal = 500  # spätere Änderung darf nicht einfließen

    change_servings(session, entry, 1.5)

    assert entry.servings == 1.5
    assert entry.kcal == pytest.approx(150)


def test_change_amount_switches_unit(session: Session) -> None:
    roll = make_food(session, "Brötchen", kcal=250, units={"Stück": 60})
    entry = log_food(session, DAY, "Frühstück", roll, 1, "Stück")

    change_amount(session, entry, roll, 80, "g")

    assert (entry.quantity, entry.unit, entry.grams) == (80, "g", 80)
    assert entry.kcal == pytest.approx(200)


def test_change_amount_rejects_unknown_unit(session: Session) -> None:
    skyr = make_food(session, "Skyr")
    entry = log_food(session, DAY, "Frühstück", skyr, 150, "g")

    with pytest.raises(UnknownUnitError):
        change_amount(session, entry, skyr, 1, "Stück")
    assert entry.grams == 150


def test_change_amount_without_food_keeps_unit(session: Session) -> None:
    banana = make_food(session, "Banane", kcal=100, units={"Stück": 120})
    entry = log_food(session, DAY, "Snacks", banana, 1, "Stück")

    change_amount(session, entry, None, 2, "g")

    assert (entry.unit, entry.grams) == ("Stück", 240)
    assert entry.kcal == pytest.approx(240)
