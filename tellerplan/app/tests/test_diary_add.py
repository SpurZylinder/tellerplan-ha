"""Eintragen: Vorfilter nach Mahlzeit und Rezept von gestern als Vorschlag."""

import re
from datetime import date, timedelta

from fastapi.testclient import TestClient

from factories import make_food, make_recipe
from modules.diary.service import log_recipe
from modules.recipes.models import Recipe

DAY = date(2026, 10, 28)
YESTERDAY = DAY - timedelta(days=1)


def _recipes(client: TestClient) -> dict[str, int]:
    """Ein Rezept je Kategorie; gestern gab es mittags Linsen-Dal und als Snack Skyr-Bowl."""
    with client.app.state.session_factory() as session:
        skyr = make_food(session)
        created: dict[str, Recipe] = {}
        for title, category in (
            ("Skyr-Bowl", "Snack"),
            ("Proteinriegel", "Snack"),
            ("Linsen-Dal", "Hauptgericht"),
            ("Ofengemüse", "Beilage"),
        ):
            recipe = make_recipe(session, title, ingredients=[(skyr, 200, "g")])
            recipe.category = category
            created[title] = recipe
        log_recipe(session, YESTERDAY, "Mittag", created["Linsen-Dal"], 1.5)
        log_recipe(session, YESTERDAY, "Snacks", created["Skyr-Bowl"], 1)
        session.commit()
        return {title: recipe.id for title, recipe in created.items()}


def _add_page(client: TestClient, meal: str, extra: str = "") -> str:
    response = client.get(f"/diary/add?day={DAY}&mode=recipe&meal={meal}{extra}")
    assert response.status_code == 200
    return response.text


def _checked_id(page: str) -> str | None:
    match = re.search(r'name="recipe_id" value="(\d+)" required checked', page)
    return match.group(1) if match else None


def test_snacks_show_only_snack_recipes_first(ingress_client: TestClient) -> None:
    _recipes(ingress_client)

    page = _add_page(ingress_client, "Snacks")

    assert "Proteinriegel" in page
    assert "Linsen-Dal" not in page
    assert "Ofengemüse" not in page
    assert "Alle Rezepte" in page


def test_all_recipes_lifts_the_filter(ingress_client: TestClient) -> None:
    _recipes(ingress_client)

    page = _add_page(ingress_client, "Snacks", "&all=1")

    assert "Linsen-Dal" in page
    assert "Ofengemüse" in page


def test_meal_without_categories_shows_everything(ingress_client: TestClient) -> None:
    _recipes(ingress_client)

    page = _add_page(ingress_client, "Frühstück")

    assert "Ofengemüse" in page
    assert "Alle Rezepte" not in page


def test_yesterdays_recipe_of_the_same_meal_is_preselected(ingress_client: TestClient) -> None:
    ids = _recipes(ingress_client)

    page = _add_page(ingress_client, "Mittag")

    assert _checked_id(page) == str(ids["Linsen-Dal"])
    assert "gestern 1,5 Portionen" in page
    assert 'name="servings" value="1.5"' in page
    assert "Skyr-Bowl" not in page  # Snack von gestern gehört nicht zum Mittag


def test_yesterdays_snack_is_suggested_only_for_snacks(ingress_client: TestClient) -> None:
    ids = _recipes(ingress_client)

    assert _checked_id(_add_page(ingress_client, "Snacks")) == str(ids["Skyr-Bowl"])
    # Abendessen bekommt keinen Vorschlag (nicht in suggest_yesterday_meals)
    dinner = _add_page(ingress_client, "Abendessen")
    assert _checked_id(dinner) is None
    assert "gestern" not in dinner


def test_recipe_from_plan_stays_visible_despite_filter(ingress_client: TestClient) -> None:
    ids = _recipes(ingress_client)

    page = _add_page(ingress_client, "Snacks", f"&recipe_id={ids['Linsen-Dal']}")

    assert _checked_id(page) == str(ids["Linsen-Dal"])
    assert "Ofengemüse" in page  # Filter aufgehoben, damit das Rezept auswählbar bleibt
