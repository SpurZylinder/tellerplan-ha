from datetime import date

import pytest
from sqlalchemy.orm import Session

from factories import make_food, make_recipe
from modules.planner.service import add_entry, plan_days, set_servings, week_start

MEALS = ["Frühstück", "Mittag", "Abendessen", "Snacks"]


def test_week_start_is_monday() -> None:
    assert week_start(date(2026, 10, 24)) == date(2026, 10, 19)
    assert week_start(date(2026, 10, 19)) == date(2026, 10, 19)


def test_plan_days_include_empty_meals(session: Session) -> None:
    days = plan_days(session, date(2026, 10, 19), 7, MEALS)

    assert len(days) == 7
    assert [meal.name for meal in days[0].meals] == MEALS
    assert all(not meal.dishes for day in days for meal in day.meals)


def test_planned_servings_scale_nutrients(session: Session) -> None:
    skyr = make_food(session, "Skyr", kcal=60, protein_g=11)
    recipe = make_recipe(session, servings=2, ingredients=[(skyr, 400, "g")])
    monday = date(2026, 10, 19)
    entry = add_entry(session, monday, "Frühstück", recipe, servings=1.5)

    (day,) = plan_days(session, monday, 1, MEALS)

    assert day.meals[0].dishes[0].entry.id == entry.id
    assert day.total.kcal == pytest.approx(120 * 1.5)
    assert day.complete


def test_set_servings_changes_day_total(session: Session) -> None:
    skyr = make_food(session, "Skyr", kcal=100)
    recipe = make_recipe(session, servings=1, ingredients=[(skyr, 100, "g")])
    monday = date(2026, 10, 19)
    entry = add_entry(session, monday, "Mittag", recipe, servings=1)

    set_servings(session, entry, 3)

    (day,) = plan_days(session, monday, 1, MEALS)
    assert day.total.kcal == pytest.approx(300)


def test_entries_outside_range_are_ignored(session: Session) -> None:
    recipe = make_recipe(session)
    add_entry(session, date(2026, 10, 26), "Mittag", recipe, servings=1)

    days = plan_days(session, date(2026, 10, 19), 7, MEALS)

    assert all(not meal.dishes for day in days for meal in day.meals)
