"""Abläufe über die Weboberfläche: Formulare absenden und Ergebnis prüfen."""

import html
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient


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


def _plan(client: TestClient, recipe_id: str, day: date) -> str:
    response = client.post(
        "/plan/add",
        data={"day": day.isoformat(), "recipe_id": recipe_id},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.headers["location"]


def _entry_ids(page: str) -> list[str]:
    return [part.split("/")[0] for part in page.split('action="/plan/entries/')[1:]]


def test_plan_shows_week_back_and_titles_only(ingress_client: TestClient) -> None:
    recipe_id = _last_id(_create_recipe(ingress_client, title="Linsen-Bolognese", servings="4"))
    today = date.today()

    location = _plan(ingress_client, recipe_id, today)
    assert location.endswith(f"#day-{today.isoformat()}")

    page = ingress_client.get("/plan").text
    assert f'id="day-{(today - timedelta(days=3)).isoformat()}"' in page
    assert f'id="day-{(today + timedelta(days=14)).isoformat()}"' in page
    assert f'id="day-{today.isoformat()}" data-today' in page
    assert "<summary>Linsen-Bolognese</summary>" in page
    assert "kcal" not in page


def test_plan_move_and_delete(ingress_client: TestClient) -> None:
    recipe_id = _last_id(_create_recipe(ingress_client, title="Rührei"))
    yesterday = date.today() - timedelta(days=1)
    _plan(ingress_client, recipe_id, yesterday)

    page = ingress_client.get("/plan").text
    assert "Auf heute" in page
    entry_id = _entry_ids(page)[0]

    moved = ingress_client.post(
        f"/plan/entries/{entry_id}/move",
        data={"day": date.today().isoformat()},
        follow_redirects=False,
    )
    assert moved.headers["location"].endswith(f"#day-{date.today().isoformat()}")
    assert "Auf heute" not in ingress_client.get("/plan").text

    ingress_client.post(f"/plan/entries/{entry_id}/delete")
    assert "Rührei" not in ingress_client.get("/plan").text
    assert "Rührei" in ingress_client.get("/recipes").text


def test_plan_layout_toggle_is_remembered(ingress_client: TestClient) -> None:
    assert 'class="plan plan-columns"' in ingress_client.get("/plan").text

    switched = ingress_client.get("/plan?layout=list")
    assert 'class="plan plan-list"' in switched.text
    assert "plan_layout=list" in switched.headers["set-cookie"]

    assert 'class="plan plan-list"' in ingress_client.get("/plan").text


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
