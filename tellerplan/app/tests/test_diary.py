from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from factories import make_food, make_recipe
from modules.diary.service import (
    UnknownUnitError,
    Viewer,
    change_amount,
    change_servings,
    day_log,
    delete_entry,
    food_frequency,
    last_amount,
    log_food,
    log_recipe,
    planned_for_day,
    recipe_frequency,
)
from modules.planner.service import add_entry

# Alle Einträge gehören dem Testbenutzer; gelesen wird sein Tagebuch
USER = "u1"
VIEWER = Viewer(USER)

DAY = date(2026, 10, 24)
MEALS = ["Frühstück", "Mittag", "Abendessen", "Snacks"]


def test_log_food_converts_units(session: Session) -> None:
    banana = make_food(session, "Banane", kcal=93, protein_g=1.1, units={"Stück": 120})

    entry = log_food(session, USER, DAY, "Snacks", banana, 1, "Stück")

    assert entry.grams == 120
    assert entry.kcal == pytest.approx(111.6)
    assert entry.label == "Banane"


def test_log_food_rejects_unknown_unit(session: Session) -> None:
    skyr = make_food(session, "Skyr")

    with pytest.raises(UnknownUnitError):
        log_food(session, USER, DAY, "Frühstück", skyr, 1, "Becher")


def test_log_recipe_uses_eaten_servings(session: Session) -> None:
    skyr = make_food(session, "Skyr", kcal=60, protein_g=11)
    recipe = make_recipe(session, servings=4, ingredients=[(skyr, 800, "g")])

    entry = log_recipe(session, USER, DAY, "Mittag", recipe, servings=1.5)

    assert entry.kcal == pytest.approx(120 * 1.5)
    assert entry.protein_g == pytest.approx(22 * 1.5)
    assert entry.is_complete


def test_snapshot_survives_recipe_changes(session: Session) -> None:
    skyr = make_food(session, "Skyr", kcal=100)
    recipe = make_recipe(session, servings=1, ingredients=[(skyr, 100, "g")])
    log_recipe(session, USER, DAY, "Mittag", recipe, servings=1)

    skyr.kcal = 500
    recipe.servings = 10

    assert day_log(session, DAY, MEALS, VIEWER).total.kcal == pytest.approx(100)


def test_day_log_groups_by_meal_and_sums(session: Session) -> None:
    skyr = make_food(session, "Skyr", kcal=60)
    log_food(session, USER, DAY, "Frühstück", skyr, 200, "g")
    log_food(session, USER, DAY, "Snacks", skyr, 100, "g")
    log_food(session, USER, date(2026, 10, 25), "Snacks", skyr, 1000, "g")

    log = day_log(session, DAY, MEALS, VIEWER)

    assert [meal.name for meal in log.meals] == MEALS
    assert log.meals[0].total.kcal == pytest.approx(120)
    assert log.meals[1].entries == []
    assert log.total.kcal == pytest.approx(180)


def test_day_log_keeps_entries_of_renamed_meals(session: Session) -> None:
    log_food(session, USER, DAY, "Brunch", make_food(session), 100, "g")

    log = day_log(session, DAY, MEALS, VIEWER)

    assert log.meals[-1].name == "Brunch"
    assert len(log.meals[-1].entries) == 1


def test_incomplete_recipe_marks_day(session: Session) -> None:
    recipe = make_recipe(session, ingredients=[(None, 1, "Prise")])
    log_recipe(session, USER, DAY, "Mittag", recipe, servings=1)

    assert not day_log(session, DAY, MEALS, VIEWER).complete


def test_planned_for_day_marks_logged_dishes(session: Session) -> None:
    recipe = make_recipe(session, title="Bolognese")
    other = make_recipe(session, title="Salat")
    planned = add_entry(session, DAY, recipe)
    add_entry(session, DAY, other)

    log_recipe(session, USER, DAY, "Mittag", recipe, servings=1, plan_entry=planned)

    status = {
        item.dish.entry.recipe.title: item.logged for item in planned_for_day(session, DAY, VIEWER)
    }
    assert status == {"Bolognese": True, "Salat": False}


def test_delete_entry(session: Session) -> None:
    entry = log_food(session, USER, DAY, "Snacks", make_food(session), 100, "g")

    delete_entry(session, entry)

    assert day_log(session, DAY, MEALS, VIEWER).total.kcal == 0


def test_change_servings_scales_snapshot(session: Session) -> None:
    skyr = make_food(session, "Skyr", kcal=100)
    recipe = make_recipe(session, servings=1, ingredients=[(skyr, 100, "g")])
    entry = log_recipe(session, USER, DAY, "Mittag", recipe, servings=1)
    skyr.kcal = 500  # spätere Änderung darf nicht einfließen

    change_servings(session, entry, 1.5)

    assert entry.servings == 1.5
    assert entry.kcal == pytest.approx(150)


def test_change_amount_switches_unit(session: Session) -> None:
    roll = make_food(session, "Brötchen", kcal=250, units={"Stück": 60})
    entry = log_food(session, USER, DAY, "Frühstück", roll, 1, "Stück")

    change_amount(session, entry, roll, 80, "g")

    assert (entry.quantity, entry.unit, entry.grams) == (80, "g", 80)
    assert entry.kcal == pytest.approx(200)


def test_change_amount_rejects_unknown_unit(session: Session) -> None:
    skyr = make_food(session, "Skyr")
    entry = log_food(session, USER, DAY, "Frühstück", skyr, 150, "g")

    with pytest.raises(UnknownUnitError):
        change_amount(session, entry, skyr, 1, "Stück")
    assert entry.grams == 150


def test_change_amount_without_food_keeps_unit(session: Session) -> None:
    banana = make_food(session, "Banane", kcal=100, units={"Stück": 120})
    entry = log_food(session, USER, DAY, "Snacks", banana, 1, "Stück")

    change_amount(session, entry, None, 2, "g")

    assert (entry.unit, entry.grams) == ("Stück", 240)
    assert entry.kcal == pytest.approx(240)


def test_food_frequency_counts_days_and_weights_same_meal(session: Session) -> None:
    egg = make_food(session, "Hühnerei roh", units={"Stück": 58})
    since = DAY - timedelta(days=90)
    log_food(session, USER, DAY, "Frühstück", egg, 1, "Stück")
    log_food(session, USER, DAY, "Frühstück", egg, 1, "Stück")  # gleicher Tag zählt einmal
    log_food(session, USER, DAY - timedelta(days=1), "Mittag", egg, 1, "Stück")
    log_food(session, USER, DAY - timedelta(days=100), "Frühstück", egg, 1, "Stück")  # zu alt

    assert food_frequency(session, since, DAY, "Frühstück", VIEWER) == {egg.id: 2 + 1}
    assert food_frequency(session, since, DAY, "Mittag", VIEWER) == {egg.id: 1 + 2}


def test_recipe_frequency(session: Session) -> None:
    recipe = make_recipe(session, ingredients=[(make_food(session), 100, "g")])
    log_recipe(session, USER, DAY, "Mittag", recipe, 1)

    assert recipe_frequency(session, DAY, DAY, "Mittag", VIEWER) == {recipe.id: 2}
    assert recipe_frequency(session, DAY, DAY, "Abendessen", VIEWER) == {recipe.id: 1}


def test_last_amount_takes_latest_day(session: Session) -> None:
    egg = make_food(session, "Hühnerei roh", units={"Stück": 58})
    log_food(session, USER, DAY, "Frühstück", egg, 2, "Stück")
    log_food(session, USER, DAY - timedelta(days=3), "Frühstück", egg, 100, "g")

    assert last_amount(session, egg.id, VIEWER) == (2, "Stück")
    assert last_amount(session, make_food(session, "Neu").id, VIEWER) is None


def test_snapshot_keeps_fiber_sugar_and_salt(session: Session) -> None:
    # K15: Der Snapshot hält alle sieben Nährwerte
    bread = make_food(session, "Vollkornbrot", kcal=200)
    bread.fiber_g, bread.sugar_g, bread.salt_g = 8.0, 2.0, 1.2

    entry = log_food(session, USER, DAY, "Frühstück", bread, 50, "g")
    bread.sugar_g = 50.0  # spätere Änderung am Lebensmittel

    assert (entry.fiber_g, entry.sugar_g, entry.salt_g) == (4.0, 1.0, 0.6)
    total = day_log(session, DAY, MEALS, VIEWER).total
    assert (total.fiber_g, total.sugar_g, total.salt_g) == (4.0, 1.0, 0.6)


def test_food_without_values_is_stored_as_unknown(session: Session) -> None:
    entry = log_food(session, USER, DAY, "Snacks", make_food(session), 100, "g")

    assert entry.sugar_g is None
