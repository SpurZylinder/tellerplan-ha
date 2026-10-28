"""Rezepte anlegen und pflegen; Nährwerte pro Portion über `nutrition`.

Welches Lebensmittel eine Zeile rechnet: das bewusst gewählte Produkt der Zeile,
sonst das Standardprodukt ihrer Grundzutat (`resolved_food`). Grundzutaten
„ohne Nährwerte“ (Gewürze) zählen als vollständig mit 0 kcal.
"""

import enum
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import QueryableAttribute, Session, selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from modules.foods.models import Food
from modules.foods.service import get_food, short_name
from modules.nutrition.service import (
    Nutrients,
    StandardUnit,
    nutrients_for,
    to_grams,
    total_nutrients,
    uses_standard_unit,
)
from modules.recipes.models import BaseIngredient, Recipe, RecipeIngredient, RecipeReference


@dataclass(frozen=True)
class RecipeInput:
    title: str
    servings: float
    category: str | None = None
    source_url: str | None = None
    note: str | None = None
    instructions: str | None = None


@dataclass(frozen=True)
class IngredientInput:
    food_id: int | None
    quantity: float | None
    unit: str | None
    is_optional: bool = False


@dataclass(frozen=True)
class MatchStatus:
    """Wie viele Pflichtzutaten ein Lebensmittel und eine Grammzahl haben."""

    matched: int
    total: int

    @property
    def complete(self) -> bool:
        return self.matched == self.total


class IngredientIssue(enum.StrEnum):
    """Warum eine Zutat nicht in die Nährwerte eingeht."""

    NO_FOOD = "no_food"
    UNKNOWN_UNIT = "unknown_unit"


@dataclass(frozen=True)
class RecipeSummary:
    recipe: Recipe
    per_serving: Nutrients
    match: MatchStatus
    issues: dict[int, IngredientIssue]


def _ingredient_loads(ingredients: _AbstractLoad) -> list[_AbstractLoad]:
    """Lädt zu jeder Zeile Produkt und Grundzutat samt Standardprodukt und Einheiten."""
    return [
        ingredients.selectinload(RecipeIngredient.food).selectinload(Food.units),
        ingredients.selectinload(RecipeIngredient.base_ingredient)
        .selectinload(BaseIngredient.default_food)
        .selectinload(Food.units),
    ]


def _with_ingredients() -> list[_AbstractLoad]:
    return _ingredient_loads(selectinload(Recipe.ingredients))


def load_recipe_details(relationship: QueryableAttribute[Recipe]) -> list[_AbstractLoad]:
    """Ladeoptionen für Module, die Rezepte über eine Beziehung holen und summarize() nutzen."""
    return _ingredient_loads(selectinload(relationship).selectinload(Recipe.ingredients))


def create_recipe(session: Session, data: RecipeInput) -> Recipe:
    recipe = Recipe(**asdict(data))
    session.add(recipe)
    session.flush()
    return recipe


def update_recipe(session: Session, recipe: Recipe, data: RecipeInput) -> Recipe:
    for key, value in asdict(data).items():
        setattr(recipe, key, value)
    session.flush()
    return recipe


def delete_recipe(session: Session, recipe: Recipe) -> None:
    session.delete(recipe)
    session.flush()


def get_recipe(session: Session, recipe_id: int) -> Recipe | None:
    return session.get(Recipe, recipe_id, options=_with_ingredients())


def list_recipes(session: Session) -> list[Recipe]:
    statement = select(Recipe).options(*_with_ingredients()).order_by(Recipe.title)
    return list(session.scalars(statement))


def list_categories(session: Session) -> list[str]:
    statement = (
        select(Recipe.category)
        .where(Recipe.category.is_not(None))
        .distinct()
        .order_by(Recipe.category)
    )
    return list(session.scalars(statement))


def toggle_favorite(session: Session, recipe: Recipe) -> Recipe:
    recipe.is_favorite = not recipe.is_favorite
    session.flush()
    return recipe


def instruction_steps(recipe: Recipe) -> list[str]:
    """Kochschritte als Liste: jede nicht leere Zeile ist ein Schritt."""
    lines = (recipe.instructions or "").splitlines()
    return [line.strip() for line in lines if line.strip()]


def describe_ingredient(quantity: float | None, unit: str | None, food_name: str) -> str:
    """Zeilentext wie „200 g Skyr“."""
    parts = [
        f"{quantity:g}".replace(".", ",") if quantity is not None else "",
        unit or "",
        food_name,
    ]
    return " ".join(part for part in parts if part)


def add_ingredient(session: Session, recipe: Recipe, data: IngredientInput) -> RecipeIngredient:
    food = get_food(session, data.food_id) if data.food_id is not None else None
    unit = (data.unit or "").strip() or None
    grams = to_grams(food, data.quantity, unit) if food and data.quantity is not None else None
    ingredient = RecipeIngredient(
        position=len(recipe.ingredients) + 1,
        raw_text=describe_ingredient(data.quantity, unit, food.name if food else "?"),
        name=short_name(food) if food else None,
        quantity=data.quantity,
        unit=unit,
        food=food,
        grams=grams,
        is_optional=data.is_optional,
    )
    recipe.ingredients.append(ingredient)
    session.flush()
    return ingredient


def remove_ingredient(session: Session, recipe: Recipe, ingredient_id: int) -> None:
    recipe.ingredients[:] = [i for i in recipe.ingredients if i.id != ingredient_id]
    for position, ingredient in enumerate(recipe.ingredients, start=1):
        ingredient.position = position
    session.flush()


def is_as_needed(ingredient: RecipeIngredient) -> bool:
    """Zeile ohne Menge („Salz“, „Öl zum Braten“): nach Bedarf, zählt nicht mit."""
    return ingredient.quantity is None and ingredient.grams is None


def resolved_food(ingredient: RecipeIngredient) -> Food | None:
    """Bewusst gewähltes Produkt der Zeile, sonst das Standardprodukt der Grundzutat."""
    if ingredient.food is not None:
        return ingredient.food
    base = ingredient.base_ingredient
    return base.default_food if base is not None else None


def has_no_nutrients(ingredient: RecipeIngredient) -> bool:
    """Grundzutat „ohne Nährwerte“ (z. B. Gewürz) und kein eigenes Produkt gewählt."""
    base = ingredient.base_ingredient
    return ingredient.food is None and base is not None and base.no_nutrients


def effective_grams(ingredient: RecipeIngredient) -> float | None:
    """Grammzahl einer Zeile; neu berechnet, falls inzwischen eine Einheit gepflegt wurde."""
    food = resolved_food(ingredient)
    if food is None:
        return None
    if ingredient.quantity is None:
        return ingredient.grams
    return to_grams(food, ingredient.quantity, ingredient.unit)


def ingredient_issue(ingredient: RecipeIngredient) -> IngredientIssue | None:
    if has_no_nutrients(ingredient):
        return None
    if resolved_food(ingredient) is None:
        return IngredientIssue.NO_FOOD
    if not is_as_needed(ingredient) and effective_grams(ingredient) is None:
        return IngredientIssue.UNKNOWN_UNIT
    return None


def summarize(recipe: Recipe) -> RecipeSummary:
    """Nährwerte pro Portion und Matching-Grad; optionale Zutaten und „nach Bedarf“ zählen nicht."""
    required = [i for i in recipe.ingredients if not i.is_optional and not is_as_needed(i)]
    resolved = [
        (food, grams)
        for i in required
        if (food := resolved_food(i)) is not None and (grams := effective_grams(i)) is not None
    ]
    without_nutrients = sum(1 for i in required if has_no_nutrients(i))
    total = total_nutrients(resolved)
    per_serving = total.scaled(1 / recipe.servings) if recipe.servings else total
    issues = {i.id: issue for i in recipe.ingredients if (issue := ingredient_issue(i))}
    return RecipeSummary(
        recipe=recipe,
        per_serving=per_serving,
        match=MatchStatus(matched=len(resolved) + without_nutrients, total=len(required)),
        issues=issues,
    )


@dataclass(frozen=True)
class LineNutrition:
    """Eine Zeile in der Aufschlüsselung: was gerechnet wird und mit wie viel."""

    ingredient: RecipeIngredient
    label: str
    food: Food | None
    chosen: bool
    grams: float | None
    # Gerechnet mit einer Standard-Einheit (z. B. 1 EL = 15 g), weil das Produkt keine eigene hat
    standard_unit: StandardUnit | None
    nutrients: Nutrients | None


# Einheiten, die bei mehr als einem anders heißen („2 Prisen“)
UNIT_PLURALS = {
    "Prise": "Prisen",
    "Dose": "Dosen",
    "Scheibe": "Scheiben",
    "Kugel": "Kugeln",
    "Packung": "Packungen",
    "Flasche": "Flaschen",
    "Tasse": "Tassen",
    "Zweig": "Zweige",
    "Blatt": "Blätter",
}
# Zähleinheit, die der Zeilenparser ergänzt; im Text steht sie nicht („2 Zwiebeln“)
COUNT_UNIT = "Stück"


def _display_unit(quantity: float | None, unit: str | None) -> str | None:
    if unit == COUNT_UNIT:
        return None
    if unit and quantity is not None and quantity > 1:
        return UNIT_PLURALS.get(unit, unit)
    return unit


def ingredient_label(ingredient: RecipeIngredient) -> str:
    """Zeilentext fürs Rezept und zum Kochen: „200 ml Milch“ – ohne Produktnamen."""
    name = ingredient.name or ingredient.raw_text
    food = ingredient.food
    if food is not None and ingredient.base_ingredient is None and name == food.name:
        name = short_name(food)  # ältere Zeilen von Hand trugen den vollen Lebensmittelnamen
    unit = _display_unit(ingredient.quantity, ingredient.unit)
    return describe_ingredient(ingredient.quantity, unit, name)


def _standard_unit_of(ingredient: RecipeIngredient, food: Food | None) -> StandardUnit | None:
    if food is None or ingredient.quantity is None:
        return None
    return uses_standard_unit(food, ingredient.unit)


def line_breakdown(recipe: Recipe) -> list[LineNutrition]:
    """Je Zeile das gerechnete Produkt und seine Nährwerte (None, wenn nicht rechenbar)."""
    result = []
    for ingredient in recipe.ingredients:
        food = resolved_food(ingredient)
        grams = effective_grams(ingredient)
        nutrients = nutrients_for(food, grams) if food is not None and grams is not None else None
        result.append(
            LineNutrition(
                ingredient=ingredient,
                label=ingredient_label(ingredient),
                food=food,
                chosen=ingredient.food is not None and ingredient.base_ingredient is not None,
                grams=grams,
                standard_unit=_standard_unit_of(ingredient, food),
                nutrients=nutrients,
            )
        )
    return result


def get_ingredient(recipe: Recipe, ingredient_id: int) -> RecipeIngredient | None:
    return next((i for i in recipe.ingredients if i.id == ingredient_id), None)


def update_line(
    session: Session,
    ingredient: RecipeIngredient,
    name: str,
    quantity: float | None,
    unit: str | None,
    is_optional: bool,
) -> None:
    """Name, Menge und Einheit einer Zeile ändern; der Originaltext bleibt erhalten."""
    ingredient.name = name
    ingredient.quantity = quantity
    ingredient.unit = unit if quantity is not None else None
    ingredient.is_optional = is_optional
    food = resolved_food(ingredient)
    has_quantity = food is not None and quantity is not None
    ingredient.grams = to_grams(food, quantity, ingredient.unit) if has_quantity else None
    session.flush()


def recipe_summaries(session: Session) -> list[RecipeSummary]:
    return [summarize(recipe) for recipe in list_recipes(session)]


# Endungen der Mehrzahl (und das -e der Einzahl), die der Schlüssel am letzten Wort weglässt:
# „Tomaten“ = „Tomate“, „Zwiebeln“ = „Zwiebel“, „Lachsfilets“ = „Lachsfilet“
PLURAL_ENDINGS = ("en", "n", "e", "s")
# So viele Buchstaben bleiben mindestens stehen („Reis“, „Eier“ und „Mais“ bleiben ganz)
MIN_STEM_LENGTH = 4


def _stem(word: str) -> str:
    for ending in PLURAL_ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= MIN_STEM_LENGTH:
            return word[: -len(ending)]
    return word


def alias_key(name: str) -> str:
    """Vergleichsschlüssel eines Zutatennamens, unabhängig von Schreibweise und Mehrzahl.

    Groß/klein, ß/ss, Bindestrich/Leerzeichen und die Mehrzahl des letzten Wortes
    zählen nicht: „Rote  Zwiebeln“ = „rote Zwiebel“, „Cheddar-Käse“ = „Cheddar Käse“.
    Ein geänderter Schlüssel braucht eine Migration (siehe 0014).
    """
    words = name.casefold().replace("-", " ").split()
    if words:
        words[-1] = _stem(words[-1])
    return " ".join(words)


def find_recipe_by_source(session: Session, source: str, source_id: str) -> Recipe | None:
    statement = (
        select(Recipe)
        .where(Recipe.source == source, Recipe.source_id == source_id)
        .options(*_with_ingredients())
    )
    return session.scalar(statement)


def set_reference(session: Session, recipe: Recipe, values: dict[str, float | None]) -> None:
    """Vergleichswerte der Quelle pro Portion speichern – nur zur Anzeige, nie gerechnet."""
    recipe.reference = RecipeReference(
        kcal=values.get("kcal"),
        protein_g=values.get("protein_g"),
        fat_g=values.get("fat_g"),
        carbs_g=values.get("carbs_g"),
    )
    session.flush()
