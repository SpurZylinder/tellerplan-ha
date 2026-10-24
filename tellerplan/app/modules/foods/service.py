"""Lebensmittel anlegen, ändern, suchen; Einheiten pflegen."""

from dataclasses import asdict, dataclass

from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from modules.foods.models import Food, FoodSource, FoodUnit

SEARCH_LIMIT = 30
SEARCH_CANDIDATES = 300


@dataclass(frozen=True)
class FoodInput:
    """Eingabedaten eines Lebensmittels, Nährwerte pro 100 g."""

    name: str
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    fiber_g: float | None = None
    sugar_g: float | None = None
    salt_g: float | None = None


def create_food(
    session: Session,
    data: FoodInput,
    source: FoodSource = FoodSource.CUSTOM,
    source_id: str | None = None,
) -> Food:
    food = Food(source=source, source_id=source_id, **asdict(data))
    session.add(food)
    session.flush()
    return food


def update_food(session: Session, food: Food, data: FoodInput) -> Food:
    for key, value in asdict(data).items():
        setattr(food, key, value)
    session.flush()
    return food


def get_food(session: Session, food_id: int) -> Food | None:
    return session.get(Food, food_id, options=[selectinload(Food.units)])


def find_by_source(session: Session, source: FoodSource, source_id: str) -> Food | None:
    return session.scalar(select(Food).where(Food.source == source, Food.source_id == source_id))


def list_foods(session: Session, limit: int = SEARCH_LIMIT) -> list[Food]:
    """Zuletzt angelegte Lebensmittel zuerst."""
    return list(session.scalars(select(Food).order_by(Food.id.desc()).limit(limit)))


def search_foods(session: Session, query: str, limit: int = SEARCH_LIMIT) -> list[Food]:
    """Alle Suchwörter müssen im Namen vorkommen; sortiert nach Ähnlichkeit."""
    terms = query.casefold().split()
    if not terms:
        return list_foods(session, limit)

    statement = select(Food)
    for term in terms:
        statement = statement.where(func.casefold(Food.name).contains(term, autoescape=True))
    candidates = session.scalars(statement.limit(SEARCH_CANDIDATES)).all()

    needle = " ".join(terms)
    ranked = sorted(
        candidates,
        key=lambda food: (-fuzz.WRatio(needle, food.name.casefold()), len(food.name)),
    )
    return ranked[:limit]


def set_unit(session: Session, food: Food, name: str, grams: float) -> FoodUnit:
    """Legt eine Einheit an oder ändert ihre Grammzahl."""
    clean_name = name.strip()
    for unit in food.units:
        if unit.name.casefold() == clean_name.casefold():
            unit.grams = grams
            session.flush()
            return unit
    unit = FoodUnit(name=clean_name, grams=grams)
    food.units.append(unit)
    session.flush()
    return unit


def delete_unit(session: Session, food: Food, unit_id: int) -> None:
    food.units[:] = [unit for unit in food.units if unit.id != unit_id]
    session.flush()
