import pytest
from sqlalchemy.orm import Session

from factories import make_food, make_recipe
from modules.foods.service import set_unit
from modules.recipes.service import (
    IngredientInput,
    IngredientIssue,
    add_ingredient,
    describe_ingredient,
    instruction_steps,
    remove_ingredient,
    summarize,
    toggle_favorite,
)


def test_per_serving_nutrients_divide_by_servings(session: Session) -> None:
    skyr = make_food(session, "Skyr", kcal=60, protein_g=11)
    oats = make_food(session, "Haferflocken", kcal=370, protein_g=13.5)
    recipe = make_recipe(session, servings=2, ingredients=[(skyr, 500, "g"), (oats, 100, "g")])

    summary = summarize(recipe)

    assert summary.per_serving.kcal == pytest.approx((300 + 370) / 2)
    assert summary.per_serving.protein_g == pytest.approx((55 + 13.5) / 2)
    assert summary.match.complete


def test_open_ingredients_are_reported_and_not_counted(session: Session) -> None:
    egg = make_food(session, "Ei", kcal=140, protein_g=12.5)
    recipe = make_recipe(session, servings=1, ingredients=[(egg, 2, "Stück"), (None, 1, "Prise")])

    summary = summarize(recipe)

    assert summary.per_serving.kcal == 0
    assert (summary.match.matched, summary.match.total) == (0, 2)
    assert set(summary.issues.values()) == {IngredientIssue.UNKNOWN_UNIT, IngredientIssue.NO_FOOD}


def test_unit_added_later_completes_recipe(session: Session) -> None:
    egg = make_food(session, "Ei", kcal=140, protein_g=12.5)
    recipe = make_recipe(session, servings=1, ingredients=[(egg, 2, "Stück")])

    set_unit(session, egg, "Stück", 50)

    summary = summarize(recipe)
    assert summary.match.complete
    assert summary.per_serving.kcal == pytest.approx(140)


def test_optional_ingredients_do_not_count(session: Session) -> None:
    skyr = make_food(session, "Skyr", kcal=60)
    honey = make_food(session, "Honig", kcal=300)
    recipe = make_recipe(session, servings=1, ingredients=[(skyr, 100, "g")])
    add_ingredient(session, recipe, IngredientInput(honey.id, 20, "g", is_optional=True))

    summary = summarize(recipe)

    assert summary.per_serving.kcal == pytest.approx(60)
    assert summary.match.total == 1


def test_remove_ingredient_renumbers_positions(session: Session) -> None:
    food = make_food(session)
    recipe = make_recipe(session, ingredients=[(food, 1, "g"), (food, 2, "g"), (food, 3, "g")])

    remove_ingredient(session, recipe, recipe.ingredients[0].id)

    assert [(i.position, i.quantity) for i in recipe.ingredients] == [(1, 2), (2, 3)]


def test_describe_ingredient_uses_german_decimal() -> None:
    assert describe_ingredient(1.5, "EL", "Olivenöl") == "1,5 EL Olivenöl"
    assert describe_ingredient(None, None, "Salz") == "Salz"


def test_toggle_favorite(session: Session) -> None:
    recipe = make_recipe(session)

    assert toggle_favorite(session, recipe).is_favorite
    assert not toggle_favorite(session, recipe).is_favorite


def test_instruction_steps_split_lines_and_skip_blanks(session: Session) -> None:
    recipe = make_recipe(session)
    recipe.instructions = "Zwiebel würfeln.\n\n  Anbraten.  \nAblöschen."

    assert instruction_steps(recipe) == ["Zwiebel würfeln.", "Anbraten.", "Ablöschen."]
