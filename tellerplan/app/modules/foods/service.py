"""Lebensmittel anlegen, ändern, suchen; Einheiten pflegen."""

import re
import uuid
from dataclasses import asdict, dataclass

from rapidfuzz import fuzz, process
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from db import search_key, search_words
from modules.foods.models import Food, FoodSource, FoodUnit

SEARCH_LIMIT = 30
SEARCH_CANDIDATES = 1000
# Unscharfe Suche nur, wenn nichts direkt passt; Schwelle für rapidfuzz (0–100)
FUZZY_CUTOFF = 75
RAW_WORD = "roh"
# Wörter vor dem eigentlichen Lebensmittel in Markennamen („Bio Milch“)
LEADING_LABELS = {"bio"}
# Fürs Ranking gelten Bindestrich-Wörter als ein Wort („Quark-Plunder“ ist kein „Quark“)
RANK_WORD_PATTERN = re.compile(r"[\w-]+")

# Trefferstufen eines Suchworts in einem Namen
EXACT_WORD, WORD_START, WORD_END, INSIDE = 3, 2, 1, 0


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
    brand: str | None = None


def create_food(
    session: Session,
    data: FoodInput,
    source: FoodSource = FoodSource.CUSTOM,
    source_id: str | None = None,
) -> Food:
    # Eigene Lebensmittel bekommen eine übertragbare Kennung (BLS: Code, OFF: Barcode),
    # damit Grundzutaten und Standards zwischen Datenbanken austauschbar sind.
    if source == FoodSource.CUSTOM and source_id is None:
        source_id = uuid.uuid4().hex
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


def _match_level(term: str, words: list[str]) -> int:
    if term in words:
        return EXACT_WORD
    if any(word.startswith(term) for word in words):
        return WORD_START
    if any(word.endswith(term) for word in words):
        return WORD_END
    return INSIDE


def _main_word_level(term: str, main_word: str) -> int:
    """Treffer im Hauptwort (erstes Wort) nach deutscher Wortbildung.

    Das Grundwort steht hinten: „Speisesalz“ ist ein Salz, „Salzkartoffeln“ sind
    Kartoffeln. Endet das Hauptwort mit dem Suchbegriff, zählt das daher mehr, als
    wenn es damit beginnt.
    """
    if main_word == term:
        return EXACT_WORD
    if main_word.endswith(term):
        return WORD_START
    if main_word.startswith(term):
        return WORD_END
    return INSIDE


def _main_word(food: Food, words: list[str]) -> str:
    """Erstes Wort des Namens; bei Markenprodukten das erste nach Hersteller und „Bio“.

    „Frankenland Frischmilch 1,5 %“ (Hersteller Frankenland) → „frischmilch“,
    „Berchtesgadener Land Bio Milch“ → „milch“.
    """
    skip = set(RANK_WORD_PATTERN.findall((food.brand or "").casefold())) | LEADING_LABELS
    rest = list(words)
    while len(rest) > 1 and rest[0] in skip:
        rest.pop(0)
    return rest[0] if rest else ""


def _rank(food: Food, terms: list[str]) -> tuple[int, int, bool, bool, int]:
    """Sortierschlüssel: Hauptwort, Trefferqualität, roh, eigene zuerst, kurze Namen.

    Das Hauptwort kommt zuerst, damit „Salz“ nicht „Salzkartoffeln (… mit Salz gekocht)“
    vor „Speisesalz“ liefert, nur weil „Salz“ weiter hinten als eigenes Wort steht.
    """
    words = RANK_WORD_PATTERN.findall(food.name.casefold())
    main_word = _main_word(food, words)
    return (
        -_main_word_level(terms[0], main_word),
        -sum(_match_level(term, words) for term in terms),
        RAW_WORD not in words,
        food.source != FoodSource.CUSTOM,
        len(food.name),
    )


def _fuzzy_candidates(session: Session, needle: str, limit: int) -> list[Food]:
    """Ähnliche Schreibweisen, z. B. „brokkoli“ → „Broccoli roh“."""
    names = dict(session.execute(select(Food.id, Food.name)).all())
    matches = process.extract(
        needle,
        {food_id: search_key(name) for food_id, name in names.items()},
        scorer=fuzz.partial_ratio,
        score_cutoff=FUZZY_CUTOFF,
        limit=SEARCH_CANDIDATES,
    )
    scores = {food_id: score for _, score, food_id in matches}
    foods = session.scalars(select(Food).where(Food.id.in_(scores))).all()

    def closeness(food: Food) -> tuple[float, bool, int]:
        raw = RAW_WORD in RANK_WORD_PATTERN.findall(food.name.casefold())
        return (-scores[food.id], not raw, len(food.name))

    return sorted(foods, key=closeness)[:limit]


def search_foods(session: Session, query: str, limit: int = SEARCH_LIMIT) -> list[Food]:
    """Alle Suchwörter müssen im Namen vorkommen (Leerzeichen egal); beste Treffer zuerst."""
    terms = search_words(query)
    if not terms:
        return list_foods(session, limit)

    statement = select(Food)
    for term in terms:
        statement = statement.where(func.search_key(Food.name).contains(term, autoescape=True))
    candidates = session.scalars(statement.limit(SEARCH_CANDIDATES)).all()
    if not candidates:
        return _fuzzy_candidates(session, "".join(terms), limit)
    return sorted(candidates, key=lambda food: _rank(food, terms))[:limit]


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


def set_shopping_name(session: Session, food: Food, name: str | None) -> Food:
    """Setzt den Einkaufsnamen; leer entfernt ihn wieder."""
    food.shopping_name = (name or "").strip() or None
    session.flush()
    return food


def delete_unit(session: Session, food: Food, unit_id: int) -> None:
    food.units[:] = [unit for unit in food.units if unit.id != unit_id]
    session.flush()


# Zustandswörter am Ende von BLS-Namen, die beim Kochen und Einkaufen nicht helfen („Broccoli roh“)
STATE_WORDS = ("roh", "reif")
# Ab hier folgen in BLS-Namen Gehaltsangaben: „Parmesan mind. 30 % Fett“, „Vollmilch 3,5 %“;
# andere Zahlen bleiben („Weizenmehl Type 405“)
DETAILS_START = re.compile(r"\s(?:mind\.|max\.|ca\.|<|>|\d+(?:,\d+)?\s?%)")


def default_short_name(food_name: str) -> str:
    """Kurzname aus dem Lebensmittelnamen: „Karotte/Möhre, roh“ → „Karotte“."""
    name = food_name.split(", ", 1)[0].split("/", 1)[0]
    words = DETAILS_START.split(name, maxsplit=1)[0].split()
    while len(words) > 1 and words[-1].casefold() in STATE_WORDS:
        words.pop()
    return " ".join(words)


def short_name(food: Food) -> str:
    """Kurzname fürs Kochen und Einkaufen: gepflegter Kurzname, sonst aus dem Namen abgeleitet."""
    return food.shopping_name or default_short_name(food.name)
