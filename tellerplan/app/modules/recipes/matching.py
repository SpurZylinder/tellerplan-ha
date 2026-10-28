"""Grundzutaten und Zuordnung: Zutatenname → Grundzutat → Standardprodukt.

- Ein Zutatenname („frische milch“) wird einmal einer Grundzutat zugeordnet
  (`IngredientAlias`); alle Zeilen mit diesem Namen folgen, auch künftige Importe.
- Die Grundzutat („Milch“) hält das Standardprodukt und die Produkte zur Auswahl.
- Eine Rezeptzeile kann bewusst ein anderes Produkt wählen; dann gilt dieses,
  und ein späterer Wechsel des Standards ändert sie nicht.
"""

from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from modules.foods.models import Food
from modules.nutrition.service import to_grams
from modules.recipes.models import BaseIngredient, IngredientAlias, Recipe, RecipeIngredient
from modules.recipes.service import alias_key, ingredient_issue, resolved_food


@dataclass(frozen=True)
class OpenGroup:
    """Alle Zeilen mit demselben Zutatennamen ohne Grundzutat, über alle Rezepte."""

    key: str
    name: str
    lines: int
    recipes: list[str]
    examples: list[str]


@dataclass(frozen=True)
class BaseUsage:
    """Eine Grundzutat mit ihrer Verwendung in Rezepten."""

    base: BaseIngredient
    lines: int
    names: list[str]


@dataclass(frozen=True)
class UnitGap:
    """Zeilen, deren Einheit für das gerechnete Lebensmittel noch keine Grammzahl hat."""

    food: Food
    unit: str
    lines: int
    recipes: list[str]


# Beschreibende Wörter vor dem Namen, die beim Vorschlagen wegfallen („frischer Koriander“).
# Nur für Vorschläge: „getrocknete Tomaten“ sind nicht automatisch Tomaten.
DESCRIPTIVE_WORDS = {
    "etwas", "frisch", "frische", "frischer", "frisches", "getrocknet", "getrocknete",
    "getrockneter", "gehackt", "gehackte", "geschält", "geschälte", "gemahlen", "gemahlener",
    "gemahlene", "grob", "grobes", "grober", "fein", "feines", "feiner", "tk",
}  # fmt: skip
# Mindestlänge eines Grundworts, das am Ende eines zusammengesetzten Namens erkannt wird
MIN_HEAD_WORD_LENGTH = 3
# Ähnlichkeit (0–100) für Tippfehler und Schreibvarianten, z. B. „Brokoli“ ↔ „Brokkoli“
SIMILAR_SPELLING = 85
SUGGESTION_LIMIT = 3


# --- Grundzutaten ---------------------------------------------------------


def _bases_with_products() -> list[_AbstractLoad]:
    return [
        selectinload(BaseIngredient.default_food),
        selectinload(BaseIngredient.products).selectinload(Food.units),
    ]


def get_base(session: Session, base_id: int) -> BaseIngredient | None:
    return session.get(BaseIngredient, base_id, options=_bases_with_products())


def find_base(session: Session, name: str) -> BaseIngredient | None:
    return session.scalar(select(BaseIngredient).where(BaseIngredient.key == alias_key(name)))


def base_names(session: Session) -> list[str]:
    """Alle Grundzutaten nach Name, z. B. für eine Auswahlliste."""
    return list(session.scalars(select(BaseIngredient.name).order_by(BaseIngredient.name)))


def create_base(session: Session, name: str, no_nutrients: bool = False) -> BaseIngredient:
    """Legt eine Grundzutat an; gibt es sie unter diesem Namen schon, wird sie verwendet."""
    existing = find_base(session, name)
    if existing is not None:
        return existing
    base = BaseIngredient(
        name=" ".join(name.split()), key=alias_key(name), no_nutrients=no_nutrients
    )
    session.add(base)
    session.flush()
    return base


def add_product(session: Session, base: BaseIngredient, food: Food) -> None:
    if food not in base.products:
        base.products.append(food)
    session.flush()


def set_default_product(session: Session, base: BaseIngredient, food: Food | None) -> None:
    """Neues Standardprodukt; gilt sofort für alle Zeilen ohne eigene Produktwahl."""
    if food is not None:
        add_product(session, base, food)
    base.default_food = food
    session.flush()


def remove_product(session: Session, base: BaseIngredient, food: Food) -> None:
    if food in base.products:
        base.products.remove(food)
    if base.default_food is not None and base.default_food.id == food.id:
        base.default_food = None
    session.flush()


def set_no_nutrients(session: Session, base: BaseIngredient, value: bool) -> None:
    base.no_nutrients = value
    session.flush()


class BaseNameTakenError(ValueError):
    """Unter diesem Namen gibt es schon eine andere Grundzutat."""


def rename_base(session: Session, base: BaseIngredient, name: str) -> None:
    existing = find_base(session, name)
    if existing is not None and existing.id != base.id:
        raise BaseNameTakenError(
            f"„{existing.name}“ gibt es schon – zusammenführen statt umbenennen."
        )
    base.name = " ".join(name.split())
    base.key = alias_key(name)
    session.flush()


def merge_bases(session: Session, source: BaseIngredient, target: BaseIngredient) -> int:
    """Lässt `source` in `target` aufgehen: Zeilen, Namen und Produkte wandern mit.

    Danach gilt das Standardprodukt von `target` (hat es keins, das von `source`).
    Gibt die Zahl der umgehängten Rezeptzeilen zurück.
    """
    if source.id == target.id:
        return 0
    moved = session.execute(
        update(RecipeIngredient)
        .where(RecipeIngredient.base_ingredient_id == source.id)
        .values(base_ingredient_id=target.id)
    ).rowcount
    session.execute(
        update(IngredientAlias)
        .where(IngredientAlias.base_ingredient_id == source.id)
        .values(base_ingredient_id=target.id)
    )
    for food in source.products:
        add_product(session, target, food)
    if target.default_food is None and source.default_food is not None:
        set_default_product(session, target, source.default_food)
    session.delete(source)
    session.flush()
    session.expire_all()
    return moved


def _without_descriptions(key: str) -> str:
    words = key.split()
    while len(words) > 1 and words[0] in DESCRIPTIVE_WORDS:
        words = words[1:]
    return " ".join(words)


def _head_word_match(key: str, other: str) -> bool:
    """Ein Wort des einen Namens endet mit dem einwortigen anderen („Räuchertofu“ → Tofu).

    Jedes Wort wird wie ein Schlüssel verglichen, also auch in der Mitte ohne Mehrzahl
    („Risottoreis Arborio“ → Risottoreis).
    """
    if " " in other or len(other) < MIN_HEAD_WORD_LENGTH:
        return False
    return key != other and any(alias_key(word).endswith(other) for word in key.split())


def _suggestion_rank(key: str, base_key: str) -> int | None:
    """Wie gut eine Grundzutat zu einem Namen passt; kleiner ist besser, None = gar nicht."""
    plain, base_plain = _without_descriptions(key), _without_descriptions(base_key)
    if plain == base_plain:
        return 0
    if _head_word_match(plain, base_plain):
        return 1
    if _head_word_match(base_plain, plain):
        return 2
    if fuzz.ratio(plain, base_plain) >= SIMILAR_SPELLING:
        return 3
    return None


def similar_bases(
    bases: list[BaseIngredient], name: str, exclude: BaseIngredient | None = None
) -> list[BaseIngredient]:
    """Bis zu drei Grundzutaten, die zu einem Namen passen könnten – beste zuerst.

    Erkannt werden beschreibende Wörter („frischer Koriander“ → Koriander),
    zusammengesetzte Namen in beide Richtungen („Räuchertofu“ → Tofu,
    „Quark“ → Magerquark) und Schreibvarianten.
    """
    key = alias_key(name)
    ranked = [
        (rank, -len(base.key), base.name, base)
        for base in bases
        if base is not exclude and (rank := _suggestion_rank(key, base.key)) is not None
    ]
    return [entry[-1] for entry in sorted(ranked, key=lambda entry: entry[:3])][:SUGGESTION_LIMIT]


def all_bases(session: Session) -> list[BaseIngredient]:
    return list(session.scalars(select(BaseIngredient).order_by(BaseIngredient.name)))


# --- Namen und Zeilen -----------------------------------------------------


def base_for_name(session: Session, name: str) -> BaseIngredient | None:
    """Grundzutat, der ein Zutatenname schon zugeordnet ist."""
    alias = session.scalar(select(IngredientAlias).where(IngredientAlias.key == alias_key(name)))
    return alias.base_ingredient if alias else None


def _all_lines(session: Session) -> list[RecipeIngredient]:
    statement = select(RecipeIngredient).options(
        selectinload(RecipeIngredient.recipe),
        selectinload(RecipeIngredient.food).selectinload(Food.units),
        selectinload(RecipeIngredient.base_ingredient)
        .selectinload(BaseIngredient.default_food)
        .selectinload(Food.units),
    )
    return list(session.scalars(statement))


def _line_key(ingredient: RecipeIngredient) -> str:
    return alias_key(ingredient.name or ingredient.raw_text)


def link_name(session: Session, name: str, base: BaseIngredient) -> int:
    """Ordnet einen Zutatennamen einer Grundzutat zu, auch für künftige Importe.

    Betroffen sind Zeilen dieses Namens ohne Grundzutat und solche, die bisher über
    den Namen an einer anderen Grundzutat hingen. Gibt die Zahl der Zeilen zurück.
    """
    key = alias_key(name)
    alias = session.scalar(select(IngredientAlias).where(IngredientAlias.key == key))
    previous_id = alias.base_ingredient_id if alias else None
    if alias is None:
        session.add(IngredientAlias(key=key, base_ingredient=base))
    else:
        alias.base_ingredient = base
    changed = 0
    for ingredient in _all_lines(session):
        if ingredient.food is not None and ingredient.base_ingredient is None:
            continue  # Zeile aus einem Rezept von Hand, direkt mit Lebensmittel
        if _line_key(ingredient) == key and ingredient.base_ingredient_id in (None, previous_id):
            ingredient.base_ingredient = base
            changed += 1
    session.flush()
    return changed


def add_parsed_ingredient(
    session: Session,
    recipe: Recipe,
    raw_text: str,
    name: str,
    quantity: float | None,
    unit: str | None,
) -> RecipeIngredient:
    """Fügt eine importierte Zeile an; ein schon zugeordneter Name bringt seine Grundzutat mit."""
    ingredient = RecipeIngredient(
        position=len(recipe.ingredients) + 1,
        raw_text=raw_text,
        name=name,
        quantity=quantity,
        unit=unit,
        base_ingredient=base_for_name(session, name),
    )
    recipe.ingredients.append(ingredient)
    session.flush()
    return ingredient


def choose_product(session: Session, ingredient: RecipeIngredient, food: Food | None) -> None:
    """Produkt nur für diese Zeile; None = wieder dem Standard der Grundzutat folgen."""
    ingredient.food = food
    if food is not None and ingredient.base_ingredient is not None:
        add_product(session, ingredient.base_ingredient, food)
    has_quantity = food is not None and ingredient.quantity is not None
    ingredient.grams = (
        to_grams(food, ingredient.quantity, ingredient.unit) if has_quantity else None
    )
    session.flush()


def set_line_base(
    session: Session, ingredient: RecipeIngredient, base: BaseIngredient | None
) -> None:
    """Grundzutat nur für diese Zeile ändern (der gelernte Name bleibt)."""
    ingredient.base_ingredient = base
    session.flush()


# --- Übersichten für die Zuordnungsseite ----------------------------------


def open_groups(session: Session) -> list[OpenGroup]:
    """Zutatennamen ohne Grundzutat, häufigste zuerst."""
    groups: dict[str, list[RecipeIngredient]] = {}
    for ingredient in _all_lines(session):
        if ingredient.base_ingredient is None and ingredient.food is None:
            groups.setdefault(_line_key(ingredient), []).append(ingredient)
    result = []
    for key, lines in groups.items():
        names = [line.name or line.raw_text for line in lines]
        result.append(
            OpenGroup(
                key=key,
                name=max(set(names), key=names.count),
                lines=len(lines),
                recipes=sorted({line.recipe.title for line in lines}),
                examples=sorted({line.raw_text for line in lines})[:3],
            )
        )
    return sorted(result, key=lambda group: (-group.lines, group.key))


def base_usages(session: Session) -> list[BaseUsage]:
    """Alle Grundzutaten mit Zeilenzahl und zugeordneten Namen, meistgenutzte zuerst."""
    lines = session.execute(
        select(RecipeIngredient.base_ingredient_id, func.count())
        .where(RecipeIngredient.base_ingredient_id.is_not(None))
        .group_by(RecipeIngredient.base_ingredient_id)
    ).all()
    counts = dict(lines)
    names: dict[int, list[str]] = {}
    for alias in session.scalars(select(IngredientAlias)):
        names.setdefault(alias.base_ingredient_id, []).append(alias.key)
    bases = session.scalars(select(BaseIngredient).options(*_bases_with_products())).all()
    usages = [
        BaseUsage(base=base, lines=counts.get(base.id, 0), names=sorted(names.get(base.id, [])))
        for base in bases
    ]
    return sorted(usages, key=lambda usage: (-usage.lines, usage.base.name.casefold()))


def unit_gaps(session: Session) -> list[UnitGap]:
    """Fehlende Grammzahlen je gerechnetem Lebensmittel und Einheit, häufigste zuerst."""
    gaps: dict[tuple[int, str], tuple[Food, list[RecipeIngredient]]] = {}
    for ingredient in _all_lines(session):
        food = resolved_food(ingredient)
        if food is not None and ingredient_issue(ingredient) is not None:
            unit = ingredient.unit or "g"
            gaps.setdefault((food.id, unit), (food, []))[1].append(ingredient)
    result = [
        UnitGap(
            food=food,
            unit=unit,
            lines=len(lines),
            recipes=sorted({line.recipe.title for line in lines}),
        )
        for (_, unit), (food, lines) in gaps.items()
    ]
    return sorted(result, key=lambda gap: (-gap.lines, gap.food.name))
