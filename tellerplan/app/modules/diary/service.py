"""Tagebuch: eintragen, löschen, Tagesübersicht. Nur diese Einträge zählen für den Tag."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.orm import InstrumentedAttribute, Session

from modules.diary.models import DiaryEntry
from modules.foods.models import Food
from modules.nutrition.service import Nutrients, nutrients_for, to_grams
from modules.planner.models import PlanEntry
from modules.planner.service import PlannedDish, plan_days
from modules.recipes.models import Recipe
from modules.recipes.service import summarize

# Ein Tag mit dem Lebensmittel in derselben Mahlzeit zählt so viel wie zwei in einer anderen
SAME_MEAL_WEIGHT = 2


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
        kcal=entry.kcal,
        protein_g=entry.protein_g,
        fat_g=entry.fat_g,
        carbs_g=entry.carbs_g,
        fiber_g=entry.fiber_g,
        sugar_g=entry.sugar_g,
        salt_g=entry.salt_g,
    )


def _snapshot(entry: DiaryEntry, nutrients: Nutrients) -> None:
    entry.kcal = nutrients.kcal
    entry.protein_g = nutrients.protein_g
    entry.fat_g = nutrients.fat_g
    entry.carbs_g = nutrients.carbs_g
    entry.fiber_g = nutrients.fiber_g
    entry.sugar_g = nutrients.sugar_g
    entry.salt_g = nutrients.salt_g


@dataclass(frozen=True)
class Viewer:
    """Wessen Tagebuch gelesen wird.

    Jeder sieht nur seine eigenen Einträge. Einträge von vor 0.5.12 haben noch keinen
    Besitzer; die sieht nur ein Verwalter (`sees_unowned`), bis er sie zuordnet.
    """

    user_id: str
    sees_unowned: bool = False


def _visible(viewer: Viewer) -> ColumnElement[bool]:
    own = DiaryEntry.user_id == viewer.user_id
    return or_(own, DiaryEntry.user_id.is_(None)) if viewer.sees_unowned else own


def log_recipe(
    session: Session,
    user_id: str,
    day: date,
    meal: str,
    recipe: Recipe,
    servings: float,
    plan_entry: PlanEntry | None = None,
) -> DiaryEntry:
    """Trägt gegessene Portionen eines Rezepts für einen Benutzer ein."""
    summary = summarize(recipe)
    entry = DiaryEntry(
        user_id=user_id,
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
    session: Session,
    user_id: str,
    day: date,
    meal: str,
    food: Food,
    quantity: float,
    unit: str | None,
) -> DiaryEntry:
    """Trägt eine Menge eines Lebensmittels ein, z. B. 150 g Skyr oder 1 Stück Banane."""
    grams = to_grams(food, quantity, unit)
    if grams is None:
        raise UnknownUnitError(f"Für „{food.name}“ ist die Einheit „{unit}“ nicht hinterlegt.")
    entry = DiaryEntry(
        user_id=user_id,
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


def change_servings(session: Session, entry: DiaryEntry, servings: float) -> None:
    """Ändert die gegessenen Portionen eines Rezepteintrags.

    Der Snapshot wird im Verhältnis skaliert, nicht neu aus dem Rezept gerechnet:
    spätere Rezeptänderungen bleiben so ohne Einfluss auf den Eintrag.
    """
    old = entry.servings or 1
    _snapshot(entry, entry_nutrients(entry).scaled(servings / old))
    entry.servings = servings
    session.flush()


def change_amount(
    session: Session, entry: DiaryEntry, food: Food | None, quantity: float, unit: str | None
) -> None:
    """Ändert Menge und Einheit eines Lebensmitteleintrags, z. B. 1 Stück → 80 g.

    Ohne Lebensmittel (inzwischen gelöscht) bleibt die Einheit; nur die Menge ändert sich.
    """
    if food is None:
        unit = entry.unit
        grams = (entry.grams or 0) * quantity / entry.quantity if entry.quantity else None
    else:
        grams = to_grams(food, quantity, unit)
    if grams is None:
        name = food.name if food else entry.label
        raise UnknownUnitError(f"Für „{name}“ ist die Einheit „{unit}“ nicht hinterlegt.")
    if entry.grams:
        _snapshot(entry, entry_nutrients(entry).scaled(grams / entry.grams))
    elif food is not None:
        _snapshot(entry, nutrients_for(food, grams))
    entry.quantity = quantity
    entry.unit = (unit or "g").strip()
    entry.grams = grams
    session.flush()


def get_entry(session: Session, entry_id: int, viewer: Viewer) -> DiaryEntry | None:
    """Ein Eintrag, den der Benutzer sehen darf; fremde gibt es für ihn nicht."""
    statement = select(DiaryEntry).where(DiaryEntry.id == entry_id, _visible(viewer))
    return session.scalar(statement)


def delete_entry(session: Session, entry: DiaryEntry) -> None:
    session.delete(entry)
    session.flush()


def _entries_on(session: Session, day: date, viewer: Viewer) -> list[DiaryEntry]:
    statement = (
        select(DiaryEntry).where(DiaryEntry.day == day, _visible(viewer)).order_by(DiaryEntry.id)
    )
    return list(session.scalars(statement))


def day_log(session: Session, day: date, meal_names: Sequence[str], viewer: Viewer) -> DayLog:
    """Alle Mahlzeiten eines Tages mit Einträgen und Summen.

    Einträge zu Mahlzeiten, die es in den Einstellungen nicht mehr gibt,
    erscheinen am Ende unter ihrem alten Namen.
    """
    entries = _entries_on(session, day, viewer)
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


def recipes_eaten(session: Session, day: date, meal: str, viewer: Viewer) -> list[DiaryEntry]:
    """Rezepteinträge einer Mahlzeit an einem Tag, je Rezept der erste (z. B. „wie gestern“)."""
    statement = (
        select(DiaryEntry)
        .where(
            DiaryEntry.day == day,
            DiaryEntry.meal == meal,
            DiaryEntry.recipe_id.is_not(None),
            _visible(viewer),
        )
        .order_by(DiaryEntry.id)
    )
    first_per_recipe: dict[int | None, DiaryEntry] = {}
    for entry in session.scalars(statement):
        first_per_recipe.setdefault(entry.recipe_id, entry)
    return list(first_per_recipe.values())


def planned_for_day(session: Session, day: date, viewer: Viewer) -> list[PlannedForDay]:
    """Für den Tag geplante Rezepte, markiert, ob *dieser Benutzer* sie schon eingetragen hat.

    Der Plan ist gemeinsam, das Tagebuch nicht: Hat jemand anderes gegessen, steht das
    Rezept hier weiter zum Eintragen bereit.
    """
    (plan_day,) = plan_days(session, day, 1)
    logged_ids = {entry.plan_entry_id for entry in _entries_on(session, day, viewer)}
    return [
        PlannedForDay(dish=dish, logged=dish.entry.id in logged_ids) for dish in plan_day.dishes
    ]


def _frequency(
    session: Session,
    column: InstrumentedAttribute[int | None],
    since: date,
    until: date,
    meal: str | None,
    viewer: Viewer,
) -> dict[int, int]:
    """Gewicht je ID: Tage mit Eintrag im Zeitraum, Tage in derselben Mahlzeit doppelt.

    Gezählt werden Tage, nicht Einträge: drei Eier an einem Tag zählen einmal.
    """
    statement = (
        select(column, DiaryEntry.day, DiaryEntry.meal)
        .where(
            column.is_not(None),
            DiaryEntry.day >= since,
            DiaryEntry.day <= until,
            _visible(viewer),
        )
        .distinct()
    )
    weights: dict[int, dict[date, int]] = {}
    for item_id, day, entry_meal in session.execute(statement):
        weight = SAME_MEAL_WEIGHT if entry_meal == meal else 1
        days = weights.setdefault(item_id, {})
        days[day] = max(days.get(day, 0), weight)
    return {item_id: sum(days.values()) for item_id, days in weights.items()}


def food_frequency(
    session: Session, since: date, until: date, meal: str | None, viewer: Viewer
) -> dict[int, int]:
    """Wie oft der Benutzer Lebensmittel im Zeitraum gegessen hat (ID → Gewicht)."""
    return _frequency(session, DiaryEntry.food_id, since, until, meal, viewer)


def recipe_frequency(
    session: Session, since: date, until: date, meal: str | None, viewer: Viewer
) -> dict[int, int]:
    """Wie oft der Benutzer Rezepte im Zeitraum gegessen hat (ID → Gewicht)."""
    return _frequency(session, DiaryEntry.recipe_id, since, until, meal, viewer)


def last_amount(session: Session, food_id: int, viewer: Viewer) -> tuple[float, str] | None:
    """Menge und Einheit, mit der der Benutzer das Lebensmittel zuletzt eingetragen hat."""
    statement = (
        select(DiaryEntry.quantity, DiaryEntry.unit)
        .where(DiaryEntry.food_id == food_id, DiaryEntry.quantity.is_not(None), _visible(viewer))
        .order_by(DiaryEntry.day.desc(), DiaryEntry.id.desc())
        .limit(1)
    )
    row = session.execute(statement).first()
    if row is None or row.quantity is None:
        return None
    return row.quantity, row.unit or "g"


def count_unowned(session: Session) -> int:
    """Einträge von vor 0.5.12, die noch keinem Benutzer gehören."""
    statement = select(func.count()).select_from(DiaryEntry).where(DiaryEntry.user_id.is_(None))
    return session.scalar(statement) or 0


def assign_unowned(session: Session, user_id: str) -> int:
    """Gibt alle Einträge ohne Besitzer einem Benutzer; liefert ihre Anzahl."""
    result = session.execute(
        update(DiaryEntry).where(DiaryEntry.user_id.is_(None)).values(user_id=user_id)
    )
    session.flush()
    return result.rowcount or 0
