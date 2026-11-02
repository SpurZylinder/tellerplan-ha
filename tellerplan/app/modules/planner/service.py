"""Wochenplan: Rezepte an Tage hängen, Tage mit Vorschau liefern.

Ein Planeintrag hat eigene Portionen; ohne Angabe die Standardportionen des
Rezepts. Was davon gegessen wird, hält erst das Tagebuch fest.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.nutrition.service import Nutrients
from modules.planner.models import CookidooRemoval, PlanEntry
from modules.recipes.models import COOKIDOO_SOURCE, Recipe
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
    """Verschiebt ein Rezept auf einen anderen Tag, z. B. wenn es nicht gekocht wurde.

    `cookidoo_day` bleibt stehen: Daran erkennt der Abgleich, dass Tellerplan verschoben hat.
    """
    entry.day = day
    session.flush()
    return entry


def mark_shopping_sent(session: Session, entries: Iterable[PlanEntry], at: datetime) -> None:
    """Merkt sich, dass die Zutaten dieser Einträge auf der Einkaufsliste stehen."""
    for entry in entries:
        entry.shopping_sent_at = at
    session.flush()


def delete_entry(session: Session, entry: PlanEntry) -> None:
    """Löscht einen Planeintrag; abgeglichene hinterlassen eine Notiz für Cookidoo."""
    recipe = entry.recipe
    if entry.cookidoo_day is not None and recipe.source == COOKIDOO_SOURCE and recipe.source_id:
        session.add(CookidooRemoval(day=entry.cookidoo_day, cookidoo_id=recipe.source_id))
    session.delete(entry)
    session.flush()


def delete_entries_of_recipe(session: Session, recipe: Recipe) -> None:
    """Alle Planeinträge eines Rezepts löschen, bevor das Rezept selbst gelöscht wird.

    Läuft über `delete_entry` statt über `ON DELETE CASCADE`, damit abgeglichene
    Einträge ihre Notiz hinterlassen und nicht beim nächsten Abgleich zurückkommen.
    """
    for entry in session.scalars(select(PlanEntry).where(PlanEntry.recipe_id == recipe.id)):
        delete_entry(session, entry)


def removals(session: Session) -> list[CookidooRemoval]:
    """Offene Notizen „in Cookidoo entfernen“, älteste zuerst."""
    return list(session.scalars(select(CookidooRemoval).order_by(CookidooRemoval.id)))


def entries_between(session: Session, first: date, last: date) -> list[PlanEntry]:
    """Planeinträge von `first` bis einschließlich `last`, mit Rezept und Zutaten."""
    statement = (
        select(PlanEntry)
        .where(PlanEntry.day >= first, PlanEntry.day <= last)
        .options(*load_recipe_details(PlanEntry.recipe))
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
