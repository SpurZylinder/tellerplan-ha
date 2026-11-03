"""Kleine Helfer, um Testdaten anzulegen."""

import json
from datetime import date, timedelta

from sqlalchemy.orm import Session

from cookidoo import CalendarRecipe, CookidooError, RecipePageMissingError
from modules.foods.models import Food, FoodSource
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
    source: FoodSource = FoodSource.CUSTOM,
    source_id: str | None = None,
) -> Food:
    food = create_food(session, FoodInput(name, kcal, protein_g, fat_g, carbs_g), source, source_id)
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


# Bezugstag der Kalender-Attrappe (ein Montag)
FAKE_TODAY = date(2026, 11, 2)


class FakeCalendar:
    """„Meine Woche“ ohne Netzwerk: Einträge als (Tage ab `FAKE_TODAY`, Cookidoo-ID); `fail`
    lässt Aufrufe an bestimmten Tagen scheitern."""

    def __init__(self, *entries: tuple[int, str]) -> None:
        self.entries = [(FAKE_TODAY + timedelta(days=offset), rid) for offset, rid in entries]
        self.fail: set[tuple[str, date]] = set()
        self.calls: list[tuple[str, date, str]] = []
        # Rezeptseiten je ID; fehlende antworten wie Cookidoo mit 404
        self.pages: dict[str, str] = {}
        self.page_requests: list[str] = []
        self.unreachable = False

    def read_calendar(self, first: date, last: date) -> list[CalendarRecipe]:
        return [
            CalendarRecipe(day, rid, f"Rezept {rid}", f"https://cookidoo.de/{rid}")
            for day, rid in sorted(self.entries)
            if first <= day <= last
        ]

    def plan(self, day: date, recipe_ids: list[str]) -> None:
        self._maybe_fail("plan", day)
        for rid in recipe_ids:
            self.calls.append(("plan", day, rid))
            self.entries.append((day, rid))

    def unplan(self, day: date, recipe_id: str) -> None:
        self._maybe_fail("unplan", day)
        self.calls.append(("unplan", day, recipe_id))
        self.entries.remove((day, recipe_id))

    def recipe_page(self, recipe_id: str) -> str:
        self.page_requests.append(recipe_id)
        if self.unreachable:
            raise CookidooError("Die Rezeptseite ist gerade nicht erreichbar.")
        if recipe_id not in self.pages:
            raise RecipePageMissingError("Rezeptseite nicht gefunden (404).")
        return self.pages[recipe_id]

    def _maybe_fail(self, action: str, day: date) -> None:
        if (action, day) in self.fail:
            raise CookidooError("Cookidoo ist gerade nicht erreichbar.")


def recipe_page(
    name: str,
    ingredients: list[str],
    recipe_yield: object = "4 Portionen",
    nutrition: dict[str, str] | None = None,
    total_time: str = "PT30M",
) -> str:
    """Rezeptseite wie bei Cookidoo: HTML mit JSON-LD (schema.org/Recipe), stark gekürzt."""
    data = {
        "@context": "http://schema.org/",
        "@type": "Recipe",
        "name": name,
        "totalTime": total_time,
        "recipeYield": recipe_yield,
        "recipeIngredient": ingredients,
        "nutrition": {"@type": "NutritionInformation", **(nutrition or {})},
    }
    return (
        '<html><head><script type="application/ld+json">{"@type": "WebSite"}</script>'
        f'<script type="application/ld+json">{json.dumps(data)}</script></head>'
        "<body>…</body></html>"
    )
