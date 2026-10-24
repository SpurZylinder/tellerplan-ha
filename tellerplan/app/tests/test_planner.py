from datetime import date

import pytest
from sqlalchemy.orm import Session

from factories import make_food, make_recipe
from modules.planner.service import add_entry, delete_entry, plan_days, week_start

MONDAY = date(2026, 10, 19)


def test_week_start_is_monday() -> None:
    assert week_start(date(2026, 10, 24)) == MONDAY
    assert week_start(MONDAY) == MONDAY


def test_plan_days_include_empty_days(session: Session) -> None:
    days = plan_days(session, MONDAY, 14)

    assert len(days) == 14
    assert all(not day.dishes for day in days)


def test_planned_recipe_counts_all_standard_servings(session: Session) -> None:
    skyr = make_food(session, "Skyr", kcal=60, protein_g=11)
    recipe = make_recipe(session, servings=2, ingredients=[(skyr, 400, "g")])
    entry = add_entry(session, MONDAY, recipe)

    (day,) = plan_days(session, MONDAY, 1)

    assert day.dishes[0].entry.id == entry.id
    assert day.dishes[0].per_serving.kcal == pytest.approx(120)
    assert day.total.kcal == pytest.approx(240)
    assert day.complete


def test_plan_follows_later_recipe_changes(session: Session) -> None:
    skyr = make_food(session, "Skyr", kcal=100)
    recipe = make_recipe(session, servings=1, ingredients=[(skyr, 100, "g")])
    add_entry(session, MONDAY, recipe)

    recipe.servings = 2

    (day,) = plan_days(session, MONDAY, 1)
    assert day.dishes[0].per_serving.kcal == pytest.approx(50)
    assert day.total.kcal == pytest.approx(100)


def test_entries_outside_range_are_ignored(session: Session) -> None:
    add_entry(session, date(2026, 10, 26), make_recipe(session))

    assert all(not day.dishes for day in plan_days(session, MONDAY, 7))


def test_delete_entry(session: Session) -> None:
    entry = add_entry(session, MONDAY, make_recipe(session))

    delete_entry(session, entry)

    assert not plan_days(session, MONDAY, 1)[0].dishes
