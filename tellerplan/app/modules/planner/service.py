"""Wochenplan: Rezepte an Tage hängen, Tage mit Vorschau liefern.

Ein Planeintrag hat eigene Portionen; ohne Angabe die Standardportionen des
Rezepts. Was davon gegessen wird, hält erst das Tagebuch fest.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.nutrition.service import Nutrients
from modules.planner.models import PlanEntry
from modules.recipes.models import Recipe
from modules.recipes.service import load_recipe_details, summarize


@dataclass(frozen=True)
class PlannedDish:
    entry: PlanEntry
    per_serving: Nutrients
    total: Nutrients
    complete: bool


@dataclass(frozen=True)
class PlanDay:
    day: date
    dishes: list[PlannedDish]
    total: Nutrients
    complete: bool


def add_entry(
    session: Session, day: date, recipe: Recipe, servings: float | None = None
) -> PlanEntry:
    """Plant ein Rezept ein; ohne `servings` mit seinen Standardportionen."""
    entry = PlanEntry(day=day, recipe=recipe, servings=servings or recipe.servings)
    session.add(entry)
    session.flush()
    return entry


def get_entry(session: Session, entry_id: int) -> PlanEntry | None:
    return session.get(PlanEntry, entry_id)


def move_entry(session: Session, entry: PlanEntry, day: date) -> PlanEntry:
    """Verschiebt ein Rezept auf einen anderen Tag, z. B. wenn es nicht gekocht wurde."""
    entry.day = day
    session.flush()
    return entry


def delete_entry(session: Session, entry: PlanEntry) -> None:
    session.delete(entry)
    session.flush()


def entries_between(session: Session, first: date, last: date) -> list[PlanEntry]:
    """Planeinträge von `first` bis einschließlich `last`, mit Rezept und Zutaten."""
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
        per_serving=summary.per_serving,
        total=summary.per_serving.scaled(entry.servings),
        complete=summary.match.complete,
    )


def plan_days(session: Session, first: date, days: int) -> list[PlanDay]:
    """Tage ab `first` (auch leere) mit ihren Rezepten und Tagessummen."""
    last = first + timedelta(days=days - 1)
    dishes = [_dish(entry) for entry in entries_between(session, first, last)]

    result = []
    for offset in range(days):
        day = first + timedelta(days=offset)
        day_dishes = [dish for dish in dishes if dish.entry.day == day]
        result.append(
            PlanDay(
                day=day,
                dishes=day_dishes,
                total=sum((dish.total for dish in day_dishes), Nutrients()),
                complete=all(dish.complete for dish in day_dishes),
            )
        )
    return result
