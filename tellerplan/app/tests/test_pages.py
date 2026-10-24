"""Abläufe über die Weboberfläche: Formulare absenden und Ergebnis prüfen."""

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


def test_plan_entry_lifecycle(ingress_client: TestClient) -> None:
    recipe_id = _create_recipe(ingress_client, title="Linsen-Bolognese", servings="4").rsplit(
        "/", 1
    )[1]
    today = date.today()

    created = ingress_client.post(
        "/plan/add",
        data={"day": today.isoformat(), "meal": "Mittag", "recipe_id": recipe_id, "servings": ""},
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert f"start={week_start(today).isoformat()}" in created.headers["location"]

    page = ingress_client.get(f"/plan?start={today.isoformat()}")
    assert "Linsen-Bolognese" in page.text
    assert '<span class="servings-value" title="Portionen">4</span>' in page.text

    entry_id = page.text.split("/plan/entries/")[1].split("/")[0]
    ingress_client.post(f"/plan/entries/{entry_id}/servings", data={"change": "-0.5"})
    page = ingress_client.get(f"/plan?start={today.isoformat()}")
    assert '<span class="servings-value" title="Portionen">3,5</span>' in page.text

    ingress_client.post(f"/plan/entries/{entry_id}/delete")
    assert "Linsen-Bolognese" not in ingress_client.get("/plan").text
    assert "Linsen-Bolognese" in ingress_client.get("/recipes").text


def test_plan_rejects_unknown_meal(ingress_client: TestClient) -> None:
    recipe_id = _last_id(_create_recipe(ingress_client))

    response = ingress_client.post(
        "/plan/add",
        data={"day": date.today().isoformat(), "meal": "Mitternacht", "recipe_id": recipe_id},
    )

    assert "Unbekannte Mahlzeit." in response.text


def test_today_shows_planned_dish(ingress_client: TestClient) -> None:
    recipe_id = _last_id(_create_recipe(ingress_client, title="Rührei"))
    ingress_client.post(
        "/plan/add",
        data={"day": date.today().isoformat(), "meal": "Frühstück", "recipe_id": recipe_id},
    )

    assert "Rührei" in ingress_client.get("/").text


def test_links_carry_ingress_prefix(ingress_client: TestClient) -> None:
    response = ingress_client.get("/recipes", headers={"X-Ingress-Path": "/api/hassio_ingress/x"})

    assert 'href="/api/hassio_ingress/x/plan"' in response.text


def test_recipes_api_lists_summaries(api_client: TestClient, ingress_client: TestClient) -> None:
    _create_recipe(ingress_client, title="Skyr-Bowl")

    response = api_client.get("/api/v1/recipes", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json()[0]["title"] == "Skyr-Bowl"
