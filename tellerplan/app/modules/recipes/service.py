"""Rezepte anlegen und pflegen; Nährwerte pro Portion über `nutrition`."""

import enum
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import QueryableAttribute, Session, selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from modules.foods.models import Food
from modules.foods.service import get_food
from modules.nutrition.service import Nutrients, to_grams, total_nutrients
from modules.recipes.models import IngredientAlias, Recipe, RecipeIngredient, RecipeReference


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


def _with_ingredients() -> list[_AbstractLoad]:
    return [
        selectinload(Recipe.ingredients)
        .selectinload(RecipeIngredient.food)
        .selectinload(Food.units)
    ]


def load_recipe_details(relationship: QueryableAttribute[Recipe]) -> _AbstractLoad:
    """Ladeoption für Module, die Rezepte über eine Beziehung holen und summarize() nutzen."""
    return (
        selectinload(relationship)
        .selectinload(Recipe.ingredients)
        .selectinload(RecipeIngredient.food)
        .selectinload(Food.units)
    )


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
        name=food.name if food else None,
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


def effective_grams(ingredient: RecipeIngredient) -> float | None:
    """Grammzahl einer Zeile; neu berechnet, falls inzwischen eine Einheit gepflegt wurde."""
    if ingredient.food is None:
        return None
    if ingredient.quantity is None:
        return ingredient.grams
    return to_grams(ingredient.food, ingredient.quantity, ingredient.unit)


def ingredient_issue(ingredient: RecipeIngredient) -> IngredientIssue | None:
    if ingredient.food is None:
        return IngredientIssue.NO_FOOD
    if not is_as_needed(ingredient) and effective_grams(ingredient) is None:
        return IngredientIssue.UNKNOWN_UNIT
    return None


def summarize(recipe: Recipe) -> RecipeSummary:
    """Nährwerte pro Portion und Matching-Grad; optionale Zutaten und „nach Bedarf“ zählen nicht."""
    required = [i for i in recipe.ingredients if not i.is_optional and not is_as_needed(i)]
    resolved = [(i.food, grams) for i in required if (grams := effective_grams(i)) is not None]
    total = total_nutrients(resolved)
    per_serving = total.scaled(1 / recipe.servings) if recipe.servings else total
    issues = {i.id: issue for i in recipe.ingredients if (issue := ingredient_issue(i))}
    return RecipeSummary(
        recipe=recipe,
        per_serving=per_serving,
        match=MatchStatus(matched=len(resolved), total=len(required)),
        issues=issues,
    )


def recipe_summaries(session: Session) -> list[RecipeSummary]:
    return [summarize(recipe) for recipe in list_recipes(session)]


# --- Import und Zuordnung -------------------------------------------------


def alias_key(name: str) -> str:
    """Schlüssel eines Zutatennamens, z. B. „Rote  Paprika“ → „rote paprika“."""
    return " ".join(name.casefold().split())


def find_recipe_by_source(session: Session, source: str, source_id: str) -> Recipe | None:
    statement = (
        select(Recipe)
        .where(Recipe.source == source, Recipe.source_id == source_id)
        .options(*_with_ingredients())
    )
    return session.scalar(statement)


def alias_food(session: Session, key: str) -> Food | None:
    """Standardartikel für einen Zutatennamen, falls schon gelernt."""
    alias = session.scalar(select(IngredientAlias).where(IngredientAlias.key == key))
    return alias.food if alias else None


def _set_food(ingredient: RecipeIngredient, food: Food | None) -> None:
    ingredient.food = food
    has_quantity = food is not None and ingredient.quantity is not None
    ingredient.grams = (
        to_grams(food, ingredient.quantity, ingredient.unit) if has_quantity else None
    )


def add_parsed_ingredient(
    session: Session,
    recipe: Recipe,
    raw_text: str,
    name: str,
    quantity: float | None,
    unit: str | None,
) -> RecipeIngredient:
    """Fügt eine importierte Zeile an; ein gelernter Standardartikel wird gleich zugeordnet."""
    ingredient = RecipeIngredient(
        position=len(recipe.ingredients) + 1,
        raw_text=raw_text,
        name=name,
        quantity=quantity,
        unit=unit,
    )
    _set_food(ingredient, alias_food(session, alias_key(name)))
    recipe.ingredients.append(ingredient)
    session.flush()
    return ingredient


def set_reference(session: Session, recipe: Recipe, values: dict[str, float | None]) -> None:
    """Vergleichswerte der Quelle pro Portion speichern – nur zur Anzeige, nie gerechnet."""
    recipe.reference = RecipeReference(
        kcal=values.get("kcal"),
        protein_g=values.get("protein_g"),
        fat_g=values.get("fat_g"),
        carbs_g=values.get("carbs_g"),
    )
    session.flush()
