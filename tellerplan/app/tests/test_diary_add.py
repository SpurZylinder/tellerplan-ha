"""Eintragen: Vorfilter nach Mahlzeit und Rezept von gestern als Vorschlag."""

import re
from datetime import date, timedelta

from fastapi.testclient import TestClient

from factories import make_food, make_recipe
from modules.diary.service import get_entry, log_food, log_recipe
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


def test_unit_select_offers_only_convertible_units(ingress_client: TestClient) -> None:
    with ingress_client.app.state.session_factory() as session:
        onion = make_food(session, "Zwiebel", units={"Stück": 80, "EL": 12})
        session.commit()
        onion_id = onion.id

    page = ingress_client.get(f"/diary/amount?food_id={onion_id}").text

    assert "<select" in page
    assert 'value="Stück"' in page
    assert "EL (12 g)" in page
    assert "TL (5 g)" in page
    assert "EL (15 g)" not in page
    assert 'value="Stück"' not in ingress_client.get("/diary/amount").text


def test_entry_on_today_can_be_changed(ingress_client: TestClient) -> None:
    with ingress_client.app.state.session_factory() as session:
        roll = make_food(session, "Brötchen", kcal=250, units={"Stück": 60})
        entry = log_food(session, DAY, "Frühstück", roll, 1, "Stück")
        session.commit()
        entry_id = entry.id

    page = ingress_client.get(f"/?day={DAY}").text
    assert f'action="/diary/entries/{entry_id}"' in page

    response = ingress_client.post(
        f"/diary/entries/{entry_id}", data={"quantity": "80", "unit": "g"}, follow_redirects=False
    )
    assert response.status_code == 303

    with ingress_client.app.state.session_factory() as session:
        changed = get_entry(session, entry_id)
        assert changed is not None
        assert (changed.quantity, changed.unit, changed.kcal) == (80, "g", 200)


def test_changing_an_entry_reports_invalid_amount(ingress_client: TestClient) -> None:
    with ingress_client.app.state.session_factory() as session:
        recipe = make_recipe(session, ingredients=[(make_food(session), 200, "g")])
        entry = log_recipe(session, DAY, "Mittag", recipe, 1)
        session.commit()
        entry_id = entry.id

    response = ingress_client.post(f"/diary/entries/{entry_id}", data={"servings": "0"})

    assert response.status_code == 200
    assert "größer als 0" in response.text


def _quantity(page: str) -> str:
    match = re.search(r'name="quantity" value="([^"]*)"', page)
    assert match is not None
    return match.group(1)


def _selected_unit(page: str) -> str:
    match = re.search(r'<option value="([^"]+)" selected>', page)
    assert match is not None
    return match.group(1)


def test_last_amount_is_suggested(ingress_client: TestClient) -> None:
    with ingress_client.app.state.session_factory() as session:
        egg = make_food(session, "Hühnerei roh", units={"Stück": 58})
        log_food(session, YESTERDAY, "Frühstück", egg, 2, "Stück")
        session.commit()
        egg_id = egg.id

    page = ingress_client.get(f"/diary/amount?food_id={egg_id}").text

    assert (_quantity(page), _selected_unit(page)) == ("2", "Stück")
    assert 'name="prefilled" value="2|Stück"' in page


def test_typed_amount_is_kept_when_food_changes(ingress_client: TestClient) -> None:
    with ingress_client.app.state.session_factory() as session:
        egg = make_food(session, "Hühnerei roh", units={"Stück": 58})
        log_food(session, YESTERDAY, "Frühstück", egg, 2, "Stück")
        session.commit()
        egg_id = egg.id

    typed = ingress_client.get(f"/diary/amount?food_id={egg_id}&quantity=150&unit=g").text
    untouched = ingress_client.get(
        f"/diary/amount?food_id={egg_id}&quantity=3&unit=EL&prefilled=3|EL"
    ).text

    assert (_quantity(typed), _selected_unit(typed)) == ("150", "g")
    assert (_quantity(untouched), _selected_unit(untouched)) == ("2", "Stück")


def test_food_search_lifts_frequently_eaten(ingress_client: TestClient) -> None:
    with ingress_client.app.state.session_factory() as session:
        make_food(session, "Hühnerei Eigelb roh")
        egg = make_food(session, "Hühnerei roh")
        for days_ago in (1, 2):
            log_food(session, DAY - timedelta(days=days_ago), "Frühstück", egg, 1, "g")
        session.commit()

    page = ingress_client.get(f"/diary/foods?day={DAY}&meal=Frühstück&q=ei").text

    assert page.index("Hühnerei roh") < page.index("Hühnerei Eigelb roh")


def test_recipes_eaten_often_come_first(ingress_client: TestClient) -> None:
    ids = _recipes(ingress_client)
    with ingress_client.app.state.session_factory() as session:
        recipe = session.get(Recipe, ids["Proteinriegel"])
        assert recipe is not None
        for days_ago in (4, 5):  # Linsen-Dal gab es gestern einmal
            log_recipe(session, DAY - timedelta(days=days_ago), "Snacks", recipe, 1)
        session.commit()

    page = _add_page(ingress_client, "Frühstück")

    assert page.index("Proteinriegel") < page.index("Linsen-Dal")
