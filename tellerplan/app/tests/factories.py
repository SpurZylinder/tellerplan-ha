"""Kleine Helfer, um Testdaten anzulegen."""

from sqlalchemy.orm import Session

from modules.foods.models import Food
from modules.foods.service import FoodInput, create_food, set_unit
from modules.recipes.models import Recipe
from modules.recipes.service import IngredientInput, RecipeInput, add_ingredient, create_recipe


def make_food(
    session: Session,
    name: str = "Skyr",
    kcal: float = 60,
    protein_g: float = 11,
    fat_g: float = 0.2,
    carbs_g: float = 4,
    units: dict[str, float] | None = None,
) -> Food:
    food = create_food(session, FoodInput(name, kcal, protein_g, fat_g, carbs_g))
    for unit, grams in (units or {}).items():
        set_unit(session, food, unit, grams)
    return food


def make_recipe(
    session: Session,
    title: str = "Skyr-Bowl",
    servings: float = 2,
    ingredients: list[tuple[Food | None, float | None, str | None]] | None = None,
) -> Recipe:
    recipe = create_recipe(session, RecipeInput(title=title, servings=servings))
    for food, quantity, unit in ingredients or []:
        food_id = food.id if food else None
        add_ingredient(session, recipe, IngredientInput(food_id, quantity, unit))
    return recipe
