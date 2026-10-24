"""Tagebuch: eintragen, löschen, Tagesübersicht. Nur diese Einträge zählen für den Tag."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.diary.models import DiaryEntry
from modules.foods.models import Food
from modules.nutrition.service import Nutrients, nutrients_for, to_grams
from modules.planner.models import PlanEntry
from modules.planner.service import PlannedDish, plan_days
from modules.recipes.models import Recipe
from modules.recipes.service import summarize


class UnknownUnitError(ValueError):
    """Die Einheit lässt sich für dieses Lebensmittel nicht in Gramm umrechnen."""


@dataclass(frozen=True)
class DiaryMeal:
    name: str
    entries: list[DiaryEntry]
    total: Nutrients


@dataclass(frozen=True)
class DayLog:
    day: date
    meals: list[DiaryMeal]
    total: Nutrients
    complete: bool


@dataclass(frozen=True)
class PlannedForDay:
    dish: PlannedDish
    logged: bool


def entry_nutrients(entry: DiaryEntry) -> Nutrients:
    """Nährwerte aus dem Snapshot des Eintrags."""
    return Nutrients(
        kcal=entry.kcal, protein_g=entry.protein_g, fat_g=entry.fat_g, carbs_g=entry.carbs_g
    )


def _snapshot(entry: DiaryEntry, nutrients: Nutrients) -> None:
    entry.kcal = nutrients.kcal
    entry.protein_g = nutrients.protein_g
    entry.fat_g = nutrients.fat_g
    entry.carbs_g = nutrients.carbs_g


def log_recipe(
    session: Session,
    day: date,
    meal: str,
    recipe: Recipe,
    servings: float,
    plan_entry: PlanEntry | None = None,
) -> DiaryEntry:
    """Trägt gegessene Portionen eines Rezepts ein."""
    summary = summarize(recipe)
    entry = DiaryEntry(
        day=day,
        meal=meal,
        recipe_id=recipe.id,
        plan_entry_id=plan_entry.id if plan_entry else None,
        servings=servings,
        label=recipe.title,
        is_complete=summary.match.complete,
    )
    _snapshot(entry, summary.per_serving.scaled(servings))
    session.add(entry)
    session.flush()
    return entry


def log_food(
    session: Session, day: date, meal: str, food: Food, quantity: float, unit: str | None
) -> DiaryEntry:
    """Trägt eine Menge eines Lebensmittels ein, z. B. 150 g Skyr oder 1 Stück Banane."""
    grams = to_grams(food, quantity, unit)
    if grams is None:
        raise UnknownUnitError(f"Für „{food.name}“ ist die Einheit „{unit}“ nicht hinterlegt.")
    entry = DiaryEntry(
        day=day,
        meal=meal,
        food_id=food.id,
        quantity=quantity,
        unit=(unit or "g").strip(),
        grams=grams,
        label=food.name,
    )
    _snapshot(entry, nutrients_for(food, grams))
    session.add(entry)
    session.flush()
    return entry


def get_entry(session: Session, entry_id: int) -> DiaryEntry | None:
    return session.get(DiaryEntry, entry_id)


def delete_entry(session: Session, entry: DiaryEntry) -> None:
    session.delete(entry)
    session.flush()


def _entries_on(session: Session, day: date) -> list[DiaryEntry]:
    statement = select(DiaryEntry).where(DiaryEntry.day == day).order_by(DiaryEntry.id)
    return list(session.scalars(statement))


def day_log(session: Session, day: date, meal_names: Sequence[str]) -> DayLog:
    """Alle Mahlzeiten eines Tages mit Einträgen und Summen.

    Einträge zu Mahlzeiten, die es in den Einstellungen nicht mehr gibt,
    erscheinen am Ende unter ihrem alten Namen.
    """
    entries = _entries_on(session, day)
    names = list(meal_names) + sorted({e.meal for e in entries} - set(meal_names))
    meals = []
    for name in names:
        meal_entries = [entry for entry in entries if entry.meal == name]
        total = sum((entry_nutrients(entry) for entry in meal_entries), Nutrients())
        meals.append(DiaryMeal(name=name, entries=meal_entries, total=total))
    return DayLog(
        day=day,
        meals=meals,
        total=sum((meal.total for meal in meals), Nutrients()),
        complete=all(entry.is_complete for entry in entries),
    )


def planned_for_day(session: Session, day: date) -> list[PlannedForDay]:
    """Für den Tag geplante Rezepte, markiert, ob sie schon eingetragen wurden."""
    (plan_day,) = plan_days(session, day, 1)
    logged_ids = {entry.plan_entry_id for entry in _entries_on(session, day)}
    return [
        PlannedForDay(dish=dish, logged=dish.entry.id in logged_ids) for dish in plan_day.dishes
    ]
