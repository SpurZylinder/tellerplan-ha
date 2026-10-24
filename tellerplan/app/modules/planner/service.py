"""Wochenplan: Einträge anlegen, Portionen ändern, Tage mit Vorschau liefern."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.nutrition.service import Nutrients
from modules.planner.models import PlanEntry
from modules.recipes.models import Recipe
from modules.recipes.service import load_recipe_details, summarize

DAYS_PER_WEEK = 7


@dataclass(frozen=True)
class PlannedDish:
    entry: PlanEntry
    nutrients: Nutrients
    complete: bool


@dataclass(frozen=True)
class PlanMeal:
    name: str
    dishes: list[PlannedDish]


@dataclass(frozen=True)
class PlanDay:
    day: date
    meals: list[PlanMeal]
    total: Nutrients
    complete: bool


def week_start(day: date) -> date:
    """Montag der Woche, in der `day` liegt."""
    return day - timedelta(days=day.weekday())


def add_entry(session: Session, day: date, meal: str, recipe: Recipe, servings: float) -> PlanEntry:
    entry = PlanEntry(day=day, meal=meal, recipe=recipe, servings=servings)
    session.add(entry)
    session.flush()
    return entry


def get_entry(session: Session, entry_id: int) -> PlanEntry | None:
    return session.get(PlanEntry, entry_id)


def set_servings(session: Session, entry: PlanEntry, servings: float) -> PlanEntry:
    entry.servings = servings
    session.flush()
    return entry


def delete_entry(session: Session, entry: PlanEntry) -> None:
    session.delete(entry)
    session.flush()


def _entries_between(session: Session, first: date, last: date) -> list[PlanEntry]:
    statement = (
        select(PlanEntry)
        .where(PlanEntry.day >= first, PlanEntry.day <= last)
        .options(load_recipe_details(PlanEntry.recipe))
        .order_by(PlanEntry.day, PlanEntry.id)
    )
    return list(session.scalars(statement))


def _dish(entry: PlanEntry) -> PlannedDish:
    summary = summarize(entry.recipe)
    return PlannedDish(
        entry=entry,
        nutrients=summary.per_serving.scaled(entry.servings),
        complete=summary.match.complete,
    )


def plan_days(session: Session, first: date, days: int, meal_names: Sequence[str]) -> list[PlanDay]:
    """Tage ab `first` mit allen Mahlzeiten (auch leeren) und Tagessummen."""
    last = first + timedelta(days=days - 1)
    dishes = [_dish(entry) for entry in _entries_between(session, first, last)]

    result = []
    for offset in range(days):
        day = first + timedelta(days=offset)
        day_dishes = [dish for dish in dishes if dish.entry.day == day]
        meals = [
            PlanMeal(name=name, dishes=[d for d in day_dishes if d.entry.meal == name])
            for name in meal_names
        ]
        total = sum((dish.nutrients for dish in day_dishes), Nutrients())
        complete = all(dish.complete for dish in day_dishes)
        result.append(PlanDay(day=day, meals=meals, total=total, complete=complete))
    return result
