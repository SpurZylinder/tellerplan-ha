"""Rezepte anlegen und pflegen; Nährwerte pro Portion über `nutrition`."""

import enum
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import QueryableAttribute, Session, selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from modules.foods.models import Food
from modules.foods.service import get_food
from modules.nutrition.service import Nutrients, to_grams, total_nutrients
from modules.recipes.models import Recipe, RecipeIngredient


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
    if effective_grams(ingredient) is None:
        return IngredientIssue.UNKNOWN_UNIT
    return None


def summarize(recipe: Recipe) -> RecipeSummary:
    """Nährwerte pro Portion und Matching-Grad; optionale Zutaten zählen nicht."""
    required = [i for i in recipe.ingredients if not i.is_optional]
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
