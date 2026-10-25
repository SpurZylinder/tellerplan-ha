from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import modules.shopping.service as shopping_service
from factories import make_food, make_recipe
from main import create_app
from modules.foods.service import set_shopping_name
from modules.planner.service import add_entry
from modules.recipes.models import RecipeIngredient
from modules.shopping.service import (
    ShoppingItem,
    build_shopping_list,
    default_shopping_name,
    is_pantry,
    send_to_todo_list,
)
from settings import Settings
from supervisor import TOKEN_ENV_VAR, SupervisorError

MONDAY = date(2026, 10, 19)
PANTRY = ["salz", "mehl", "zucker"]


@pytest.mark.parametrize(
    ("bls_name", "expected"),
    [
        ("Broccoli roh", "Broccoli"),
        ("Karotte/Möhre, roh", "Karotte"),
        ("Hähnchen Brustfilet, roh", "Hähnchen Brustfilet"),
        ("Linse rot reif", "Linse rot"),
        ("Parmesan mind. 30 % Fett i. Tr.", "Parmesan"),
        ("Speisequark Magerstufe < 10 % Fett i. Tr.", "Speisequark Magerstufe"),
        ("Vollmilch 3,5 % Fett", "Vollmilch"),
        ("Weizenmehl Type 405", "Weizenmehl Type 405"),
        ("Tofu", "Tofu"),
    ],
)
def test_default_shopping_name_drops_qualifiers(bls_name: str, expected: str) -> None:
    assert default_shopping_name(bls_name) == expected


@pytest.mark.parametrize(
    ("name", "pantry"),
    [
        ("Speisesalz jodiert", True),
        ("Meersalz", True),
        ("Weizenmehl Type 405", True),
        ("Zucker weiß", True),
        ("Zuckerschote roh", False),
        ("Salzstangen", False),
        ("Broccoli roh", False),
    ],
)
def test_pantry_keywords_match_word_endings(name: str, pantry: bool) -> None:
    assert is_pantry([name], PANTRY) is pantry


def test_same_food_is_added_up_per_unit(session: Session) -> None:
    egg = make_food(session, "Hühnerei roh", units={"Stück": 58})
    broccoli = make_food(session, "Broccoli roh")
    first = make_recipe(session, "Rührei", ingredients=[(egg, 3, "Stück"), (broccoli, 300, "g")])
    second = make_recipe(session, "Pfanne", ingredients=[(egg, 2, "Stück"), (broccoli, 250, "g")])
    add_entry(session, MONDAY, first)
    add_entry(session, MONDAY + timedelta(days=3), second)

    shopping = build_shopping_list(session, MONDAY, 14, PANTRY)

    assert [(item.name, item.description) for item in shopping.items] == [
        ("Broccoli", "550 g"),
        ("Hühnerei", "5 Stück"),
    ]
    assert shopping.items[0].recipes == {"Rührei", "Pfanne"}


def test_mixed_units_are_listed_side_by_side(session: Session) -> None:
    chickpeas = make_food(session, "Kichererbse reif, Konserve", units={"Dose": 240})
    add_entry(session, MONDAY, make_recipe(session, "Salat", ingredients=[(chickpeas, 1, "Dose")]))
    add_entry(session, MONDAY, make_recipe(session, "Curry", ingredients=[(chickpeas, 200, "g")]))

    (item,) = build_shopping_list(session, MONDAY, 1, PANTRY).items

    assert item.description == "1 Dose + 200 g"


def test_pantry_items_are_set_aside(session: Session) -> None:
    salt = make_food(session, "Speisesalz jodiert")
    flour = make_food(session, "Weizenmehl Type 405")
    quark = make_food(session, "Speisequark Magerstufe")
    recipe = make_recipe(
        session, "Kuchen", ingredients=[(salt, 1, "g"), (flour, 200, "g"), (quark, 500, "g")]
    )
    add_entry(session, MONDAY, recipe)

    shopping = build_shopping_list(session, MONDAY, 1, PANTRY)

    assert [item.name for item in shopping.items] == ["Speisequark Magerstufe"]
    assert [item.name for item in shopping.pantry] == ["Speisesalz jodiert", "Weizenmehl Type 405"]


def test_shopping_name_wins_and_merges_foods(session: Session) -> None:
    fillet = make_food(session, "Hähnchen Brustfilet, roh")
    meat = make_food(session, "Hähnchen Fleisch, ohne Haut, roh")
    set_shopping_name(session, fillet, "Hähnchenbrust")
    set_shopping_name(session, meat, "Hähnchenbrust")
    recipe = make_recipe(session, "Pfanne", ingredients=[(fillet, 400, "g"), (meat, 200, "g")])
    add_entry(session, MONDAY, recipe)

    (item,) = build_shopping_list(session, MONDAY, 1, PANTRY).items

    assert (item.name, item.description) == ("Hähnchenbrust", "600 g")


def test_only_days_in_range_count(session: Session) -> None:
    skyr = make_food(session, "Skyr")
    add_entry(
        session,
        MONDAY - timedelta(days=1),
        make_recipe(session, "Gestern", ingredients=[(skyr, 1, "g")]),
    )
    add_entry(
        session,
        MONDAY + timedelta(days=14),
        make_recipe(session, "Zu spät", ingredients=[(skyr, 2, "g")]),
    )
    add_entry(
        session,
        MONDAY + timedelta(days=13),
        make_recipe(session, "Passt", ingredients=[(skyr, 4, "g")]),
    )

    (item,) = build_shopping_list(session, MONDAY, 14, PANTRY).items

    assert item.description == "4 g"
    assert item.recipes == {"Passt"}


def test_unmatched_and_optional_lines(session: Session) -> None:
    recipe = make_recipe(session, "Salat")
    recipe.ingredients.append(RecipeIngredient(position=1, raw_text="200 g Feta"))
    basil = make_food(session, "Basilikum roh")
    recipe.ingredients.append(
        RecipeIngredient(
            position=2, raw_text="Basilikum", food=basil, quantity=1, unit="Bund", is_optional=True
        )
    )
    session.flush()
    add_entry(session, MONDAY, recipe)

    items = build_shopping_list(session, MONDAY, 1, PANTRY).items

    assert [(item.name, item.description) for item in items] == [
        ("200 g Feta", ""),
        ("Basilikum", "1 Bund · optional"),
    ]


def test_send_to_todo_list_calls_add_item(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, dict[str, Any], str]] = []
    monkeypatch.setattr(shopping_service, "call_service", lambda *args: calls.append(args))
    items = [ShoppingItem("Broccoli", {"g": 550}), ShoppingItem("200 g Feta")]

    result = send_to_todo_list(items, "todo.einkauf", "token")

    assert result.sent == 2
    assert calls == [
        (
            "todo",
            "add_item",
            {"entity_id": "todo.einkauf", "item": "Broccoli", "description": "550 g"},
            "token",
        ),
        ("todo", "add_item", {"entity_id": "todo.einkauf", "item": "200 g Feta"}, "token"),
    ]


def test_send_collects_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: Any) -> None:
        raise SupervisorError("Entität unbekannt")

    monkeypatch.setattr(shopping_service, "call_service", reject)

    result = send_to_todo_list([ShoppingItem("Broccoli")], "todo.x", "token")

    assert result.sent == 0
    assert result.errors == ["Broccoli: Entität unbekannt"]


# --- Seiten ---------------------------------------------------------------


@pytest.fixture
def planned_today(ingress_client: TestClient, session: Session) -> None:
    """Ein Rezept für heute, mit Broccoli und Salz (Vorrat)."""
    broccoli = make_food(session, "Broccoli roh")
    salt = make_food(session, "Speisesalz jodiert")
    recipe = make_recipe(session, "Pfanne", ingredients=[(broccoli, 300, "g"), (salt, 2, "g")])
    add_entry(session, date.today(), recipe)
    session.commit()


def test_plan_has_shopping_button(ingress_client: TestClient) -> None:
    assert 'action="/plan/shopping"' in ingress_client.get("/plan").text


@pytest.mark.usefixtures("planned_today")
def test_shopping_page_lists_items_and_pantry(ingress_client: TestClient) -> None:
    text = ingress_client.get("/plan/shopping").text

    assert "Broccoli" in text
    assert "300 g" in text
    assert "1 × Vorrat, nicht auf der Liste" in text


@pytest.mark.usefixtures("planned_today")
def test_send_without_supervisor_only_shows_list(
    monkeypatch: pytest.MonkeyPatch, ingress_client: TestClient
) -> None:
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)

    response = ingress_client.post("/plan/shopping")

    assert "Lokal ohne Home Assistant: nichts gesendet." in response.text
    assert "Broccoli (300 g)" in response.text


@pytest.mark.usefixtures("planned_today")
def test_send_adds_items_to_bring_list(
    monkeypatch: pytest.MonkeyPatch, ingress_client: TestClient
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setenv(TOKEN_ENV_VAR, "supervisor-token")
    monkeypatch.setattr(shopping_service, "call_service", lambda *args: calls.append(args[2]))

    response = ingress_client.post("/plan/shopping")

    assert calls == [{"entity_id": "todo.einkauf", "item": "Broccoli", "description": "300 g"}]
    assert "1 Artikel an todo.einkauf gesendet." in response.text


def test_send_without_list_asks_for_settings(
    monkeypatch: pytest.MonkeyPatch, migrated: Settings, options_file: Path
) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "supervisor-token")
    settings = migrated.model_copy(update={"bring_list_entity": ""})
    client = TestClient(create_app(settings, options_file), base_url="http://testserver:8000")

    response = client.post("/plan/shopping")

    assert "Keine Bring-Liste festgelegt." in response.text


def test_shopping_name_can_be_set_on_food(ingress_client: TestClient, session: Session) -> None:
    food = make_food(session, "Hähnchen Brustfilet, roh")
    session.commit()

    detail = ingress_client.get(f"/foods/{food.id}").text
    assert 'placeholder="Hähnchen Brustfilet"' in detail

    ingress_client.post(
        f"/foods/{food.id}/shopping-name", data={"shopping_name": " Hähnchenbrust "}
    )

    assert 'value="Hähnchenbrust"' in ingress_client.get(f"/foods/{food.id}").text


def test_items_sort_umlauts_like_their_base_letter(session: Session) -> None:
    recipe = make_recipe(
        session,
        "Pfanne",
        ingredients=[
            (make_food(session, "Honig"), 1, "g"),
            (make_food(session, "Hähnchen"), 1, "g"),
        ],
    )
    add_entry(session, MONDAY, recipe)

    items = build_shopping_list(session, MONDAY, 1, PANTRY).items

    assert [item.name for item in items] == ["Hähnchen", "Honig"]
