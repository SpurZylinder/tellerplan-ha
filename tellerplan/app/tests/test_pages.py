"""Abläufe über die Weboberfläche: Formulare absenden und Ergebnis prüfen."""

import html
from datetime import date

import pytest
from fastapi.testclient import TestClient

from modules.planner.service import week_start


def _last_id(url: str) -> str:
    return url.rsplit("/", 1)[1]


def _create_food(client: TestClient, name: str = "Skyr", kcal: str = "60") -> str:
    response = client.post(
        "/foods/new",
        data={"name": name, "kcal": kcal, "protein_g": "11", "fat_g": "0,2", "carbs_g": "4"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.headers["location"]


def _create_recipe(client: TestClient, title: str = "Skyr-Bowl", servings: str = "2") -> str:
    response = client.post(
        "/recipes/new", data={"title": title, "servings": servings}, follow_redirects=False
    )
    assert response.status_code == 303
    return response.headers["location"]


@pytest.mark.parametrize("path", ["/", "/recipes", "/plan", "/plan?weeks=2", "/foods"])
def test_main_pages_render_with_tab_bar(ingress_client: TestClient, path: str) -> None:
    response = ingress_client.get(path)

    assert response.status_code == 200
    assert 'class="tabbar"' in response.text
    assert 'aria-current="page"' in response.text


def test_food_form_accepts_german_decimals(ingress_client: TestClient) -> None:
    detail = ingress_client.get(_create_food(ingress_client, kcal="62,5"))

    assert "62,5" in detail.text


def test_food_form_reports_missing_values(ingress_client: TestClient) -> None:
    response = ingress_client.post("/foods/new", data={"name": "Skyr", "kcal": "abc"})

    assert response.status_code == 200
    assert "kcal ist keine Zahl." in response.text


def test_recipe_with_ingredient_shows_per_serving_values(ingress_client: TestClient) -> None:
    food_id = _last_id(_create_food(ingress_client))
    recipe_url = _create_recipe(ingress_client, servings="2")

    ingress_client.post(
        f"{recipe_url}/ingredients", data={"food_id": food_id, "quantity": "500", "unit": "g"}
    )
    detail = ingress_client.get(recipe_url)

    assert "500 g Skyr" in detail.text
    assert "150 kcal" in detail.text  # 500 g × 60 kcal / 100 g / 2 Portionen


def test_ingredient_without_food_is_rejected(ingress_client: TestClient) -> None:
    recipe_url = _create_recipe(ingress_client)

    response = ingress_client.post(f"{recipe_url}/ingredients", data={"quantity": "1"})

    assert "Bitte ein Lebensmittel auswählen." in response.text


def test_favorite_toggle_returns_star(ingress_client: TestClient) -> None:
    recipe_url = _create_recipe(ingress_client)

    response = ingress_client.post(f"{recipe_url}/favorite")

    assert 'aria-pressed="true"' in response.text


def _plan(client: TestClient, recipe_id: str, day: date, weeks: str = "1") -> str:
    response = client.post(
        "/plan/add",
        data={"day": day.isoformat(), "recipe_id": recipe_id, "weeks": weeks},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.headers["location"]


def test_plan_entry_lifecycle(ingress_client: TestClient) -> None:
    recipe_id = _last_id(_create_recipe(ingress_client, title="Linsen-Bolognese", servings="4"))
    today = date.today()

    location = _plan(ingress_client, recipe_id, today, weeks="2")
    assert f"start={week_start(today).isoformat()}" in location
    assert "weeks=2" in location

    page = ingress_client.get(location)
    assert "Linsen-Bolognese" in page.text
    assert "4 Portionen" in page.text

    entry_id = page.text.split("/plan/entries/")[1].split("/")[0]
    deleted = ingress_client.post(
        f"/plan/entries/{entry_id}/delete", data={"weeks": "2"}, follow_redirects=False
    )
    assert "weeks=2" in deleted.headers["location"]
    assert "Linsen-Bolognese" not in ingress_client.get("/plan").text
    assert "Linsen-Bolognese" in ingress_client.get("/recipes").text


def test_plan_requires_recipe(ingress_client: TestClient) -> None:
    response = ingress_client.post("/plan/add", data={"day": date.today().isoformat()})

    assert "Bitte ein Rezept auswählen." in response.text


def test_today_shows_gauge_with_remaining_kcal(ingress_client: TestClient) -> None:
    page = ingress_client.get("/")

    assert 'class="gauge"' in page.text
    assert "2.000" in page.text  # Rest = Limit, noch nichts gegessen
    assert "kcal übrig" in page.text


def test_log_food_updates_gauge(ingress_client: TestClient) -> None:
    food_id = _last_id(_create_food(ingress_client, name="Skyr", kcal="60"))

    response = ingress_client.post(
        "/diary/food",
        data={
            "day": date.today().isoformat(),
            "meal": "Frühstück",
            "food_id": food_id,
            "quantity": "250",
            "unit": "g",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    page = ingress_client.get("/")
    assert "Skyr" in page.text
    assert "1.850" in page.text  # 2.000 − 150 kcal
    assert 'stroke-dasharray="7.5 100"' in page.text


def test_log_food_reports_unknown_unit(ingress_client: TestClient) -> None:
    food_id = _last_id(_create_food(ingress_client, name="Skyr"))

    response = ingress_client.post(
        "/diary/food",
        data={
            "day": date.today().isoformat(),
            "meal": "Frühstück",
            "food_id": food_id,
            "quantity": "1",
            "unit": "Becher",
        },
    )

    assert "Einheit „Becher“ nicht hinterlegt" in response.text


def test_log_planned_recipe_marks_it(ingress_client: TestClient) -> None:
    recipe_id = _last_id(_create_recipe(ingress_client, title="Rührei"))
    today = date.today()
    _plan(ingress_client, recipe_id, today)

    page = ingress_client.get("/")
    assert "Rührei" in page.text
    link = html.unescape(page.text.split('<a class="btn small" href="')[1].split('"')[0])
    plan_entry_id = link.split("plan_entry_id=")[1].split("&")[0]

    add_page = ingress_client.get(link)
    assert '<option value="Abendessen" selected>' in add_page.text

    ingress_client.post(
        "/diary/recipe",
        data={
            "day": today.isoformat(),
            "meal": "Frühstück",
            "recipe_id": recipe_id,
            "servings": "1,5",
            "plan_entry_id": plan_entry_id,
        },
    )

    page = ingress_client.get("/")
    assert "✓ eingetragen" in page.text
    assert "1,5 Portionen" in page.text


def test_log_requires_meal(ingress_client: TestClient) -> None:
    recipe_id = _last_id(_create_recipe(ingress_client))

    response = ingress_client.post(
        "/diary/recipe",
        data={"day": date.today().isoformat(), "recipe_id": recipe_id, "servings": "1"},
    )

    assert "Bitte eine Mahlzeit wählen." in response.text


def test_over_limit_is_shown(ingress_client: TestClient) -> None:
    food_id = _last_id(_create_food(ingress_client, name="Öl", kcal="900"))
    ingress_client.post(
        "/diary/food",
        data={
            "day": date.today().isoformat(),
            "meal": "Abendessen",
            "food_id": food_id,
            "quantity": "250",
            "unit": "g",
        },
    )

    page = ingress_client.get("/")
    assert "kcal über dem Limit" in page.text
    assert "250" in page.text  # 2.250 − 2.000


def test_diary_add_page_renders_both_modes(ingress_client: TestClient) -> None:
    for mode in ("recipe", "food"):
        response = ingress_client.get(f"/diary/add?mode={mode}&meal=Mittag")
        assert response.status_code == 200
        assert '<option value="Mittag" selected>' in response.text


def test_links_carry_ingress_prefix(ingress_client: TestClient) -> None:
    response = ingress_client.get("/recipes", headers={"X-Ingress-Path": "/api/hassio_ingress/x"})

    assert 'href="/api/hassio_ingress/x/plan"' in response.text


def test_recipes_api_lists_summaries(api_client: TestClient, ingress_client: TestClient) -> None:
    _create_recipe(ingress_client, title="Skyr-Bowl")

    response = api_client.get("/api/v1/recipes", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json()[0]["title"] == "Skyr-Bowl"
