import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import clock
import web.pages.shopping as shopping_page
from conftest import INGRESS_HEADERS
from factories import make_food, make_recipe
from main import create_app
from modules.foods.models import FoodSource
from modules.foods.service import default_short_name, set_shopping_name
from modules.planner.service import PLAN_DAYS_AHEAD, add_entry
from modules.recipes.matching import create_base, set_default_product
from modules.recipes.models import RecipeIngredient
from modules.shopping.service import (
    ListItem,
    SendError,
    ShoppingItem,
    build_shopping_list,
    is_pantry,
    merge_description,
    send_shopping_list,
)
from security import INGRESS_PROXY_IP
from settings import Settings
from supervisor import TOKEN_ENV_VAR, SupervisorError

MONDAY = date(2026, 10, 19)
PANTRY = ["salz", "mehl", "zucker"]


class FakeList:
    """Einkaufsliste wie Bring: offene Einträge lesen, anlegen, ergänzen; Namen können scheitern."""

    def __init__(self, failing: dict[str, str] | None = None, unreadable: bool = False) -> None:
        self.items: list[ListItem] = []
        self.failing = failing or {}
        self.unreadable = unreadable
        self.calls: list[tuple[str, str, str]] = []

    def open_items(self) -> list[ListItem]:
        if self.unreadable:
            raise SendError("Supervisor nicht erreichbar")
        return list(self.items)

    def add(self, name: str, description: str) -> None:
        self._maybe_fail(name)
        self.calls.append(("add", name, description))
        self.items.append(ListItem(f"u{len(self.items)}", name, description))

    def update(self, item: str, description: str) -> None:
        index = next(i for i, e in enumerate(self.items) if item in (e.uid, e.name))
        self._maybe_fail(self.items[index].name)
        self.calls.append(("update", item, description))
        old = self.items[index]
        self.items[index] = ListItem(old.uid, old.name, description)

    def descriptions(self) -> dict[str, str]:
        return {item.name: item.description for item in self.items}

    def _maybe_fail(self, name: str) -> None:
        if name in self.failing:
            raise SendError(self.failing[name])


RECORDED_ITEMS = json.loads(
    (Path(__file__).parent / "data" / "bring_get_items.json").read_text(encoding="utf-8")
)


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
def test_default_short_name_drops_qualifiers(bls_name: str, expected: str) -> None:
    assert default_short_name(bls_name) == expected


@pytest.mark.parametrize(
    ("name", "pantry"),
    [
        ("Speisesalz jodiert", True),
        ("Meersalz", True),
        ("Weizenmehl Type 405", True),
        ("Zucker weiß", True),
        ("Zuckerschote roh", False),
        ("Thunfisch in Öl, Konserve", False),
        ("Artischocke in Öl, Konserve, abgetropft", False),
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

    shopping = build_shopping_list(session, MONDAY, MONDAY + timedelta(days=13), PANTRY)

    assert [(item.name, item.description) for item in shopping.items] == [
        ("Broccoli", "550 g"),
        ("Hühnerei", "5 Stück"),
    ]
    assert shopping.items[0].recipes == {"Rührei", "Pfanne"}


def test_planned_servings_scale_amounts(session: Session) -> None:
    broccoli = make_food(session, "Broccoli roh")
    recipe = make_recipe(session, "Pfanne", servings=2, ingredients=[(broccoli, 300, "g")])
    add_entry(session, MONDAY, recipe, servings=3)

    (item,) = build_shopping_list(session, MONDAY, MONDAY, PANTRY).items

    assert item.description == "450 g"


def test_mixed_units_are_listed_side_by_side(session: Session) -> None:
    chickpeas = make_food(session, "Kichererbse reif, Konserve", units={"Dose": 240})
    add_entry(session, MONDAY, make_recipe(session, "Salat", ingredients=[(chickpeas, 1, "Dose")]))
    add_entry(session, MONDAY, make_recipe(session, "Curry", ingredients=[(chickpeas, 200, "g")]))

    (item,) = build_shopping_list(session, MONDAY, MONDAY, PANTRY).items

    assert item.description == "1 Dose + 200 g"


def test_pantry_items_are_set_aside(session: Session) -> None:
    salt = make_food(session, "Speisesalz jodiert")
    flour = make_food(session, "Weizenmehl Type 405")
    quark = make_food(session, "Speisequark Magerstufe")
    recipe = make_recipe(
        session, "Kuchen", ingredients=[(salt, 1, "g"), (flour, 200, "g"), (quark, 500, "g")]
    )
    add_entry(session, MONDAY, recipe)

    shopping = build_shopping_list(session, MONDAY, MONDAY, PANTRY)

    assert [item.name for item in shopping.items] == ["Speisequark Magerstufe"]
    assert [item.name for item in shopping.pantry] == ["Speisesalz jodiert", "Weizenmehl Type 405"]


def test_shopping_name_wins_and_merges_foods(session: Session) -> None:
    fillet = make_food(session, "Hähnchen Brustfilet, roh")
    meat = make_food(session, "Hähnchen Fleisch, ohne Haut, roh")
    set_shopping_name(session, fillet, "Hähnchenbrust")
    set_shopping_name(session, meat, "Hähnchenbrust")
    recipe = make_recipe(session, "Pfanne", ingredients=[(fillet, 400, "g"), (meat, 200, "g")])
    add_entry(session, MONDAY, recipe)

    (item,) = build_shopping_list(session, MONDAY, MONDAY, PANTRY).items

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

    (item,) = build_shopping_list(session, MONDAY, MONDAY + timedelta(days=13), PANTRY).items

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

    items = build_shopping_list(session, MONDAY, MONDAY, PANTRY).items

    assert [(item.name, item.description) for item in items] == [
        ("200 g Feta", ""),
        ("Basilikum", "1 Bund · optional"),
    ]


def test_send_adds_new_items_and_extends_existing_ones(session: Session) -> None:
    # K19b: vorhandene Einträge werden ergänzt, nicht doppelt angelegt
    target = FakeList()
    target.items = [ListItem("u-b", "Broccoli", "200 g")]
    _plan(session, MONDAY, "Pfanne", "Broccoli roh")
    _plan(session, MONDAY, "Curry", "Kichererbse")
    shopping = build_shopping_list(session, MONDAY, MONDAY, PANTRY)

    result = send_shopping_list(session, shopping, target, "todo.x")

    assert target.descriptions() == {"Broccoli": "500 g", "Kichererbse": "300 g"}
    assert ("update", "u-b", "500 g") in target.calls
    assert (result.added, result.updated, result.recipes_sent) == (1, 1, 2)


def test_same_item_in_two_recipes_is_one_entry(session: Session) -> None:
    target = FakeList()
    _plan(session, MONDAY, "Pfanne", "Broccoli roh")
    _plan(session, MONDAY, "Auflauf", "Broccoli roh")
    shopping = build_shopping_list(session, MONDAY, MONDAY, PANTRY)

    send_shopping_list(session, shopping, target, "todo.x")

    assert target.descriptions() == {"Broccoli": "600 g"}
    assert [call[0] for call in target.calls] == ["add", "update"]


def test_names_are_matched_tolerantly(session: Session) -> None:
    # Wie beim Zuordnen: Groß/klein, Bindestrich und Mehrzahl zählen nicht
    target = FakeList()
    target.items = [ListItem("u1", "broccolis", "100 g")]
    _plan(session, MONDAY, "Pfanne", "Broccoli roh")

    send_shopping_list(session, build_shopping_list(session, MONDAY, MONDAY, PANTRY), target, "x")

    assert target.descriptions() == {"broccolis": "400 g"}


def test_unreadable_list_sends_nothing(session: Session) -> None:
    target = FakeList(unreadable=True)
    _plan(session, MONDAY, "Pfanne", "Broccoli roh")
    shopping = build_shopping_list(session, MONDAY, MONDAY, PANTRY)

    result = send_shopping_list(session, shopping, target, "todo.x")

    assert target.calls == []
    assert result.errors == ["Liste nicht lesbar: Supervisor nicht erreichbar"]
    assert result.recipes_open == 1
    assert [i.name for i in build_shopping_list(session, MONDAY, MONDAY, PANTRY).items] == [
        "Broccoli"
    ]


def test_failed_recipe_stays_open_others_are_marked(session: Session) -> None:
    # Je Rezept abhaken: ein Fehler betrifft nur sein Rezept
    target = FakeList({"Kichererbse": "abgelehnt"})
    _plan(session, MONDAY, "Pfanne", "Broccoli roh")
    _plan(session, MONDAY, "Curry", "Kichererbse")
    checkpoints: list[int] = []
    shopping = build_shopping_list(session, MONDAY, MONDAY, PANTRY)

    result = send_shopping_list(
        session, shopping, target, "todo.x", checkpoint=lambda: checkpoints.append(1)
    )
    again = build_shopping_list(session, MONDAY, MONDAY, PANTRY)

    assert (result.recipes_sent, result.recipes_open) == (1, 1)
    assert result.errors == ["Kichererbse: abgelehnt"]
    assert checkpoints == [1]
    assert [item.name for item in again.items] == ["Kichererbse"]


@pytest.mark.parametrize(
    ("existing", "amounts", "products", "expected"),
    [
        # Angaben aus der aufgezeichneten Bring-Liste
        (
            "200 g · ja! Blattspinat 1kg",
            {"g": 300},
            {"ja! Blattspinat 1kg"},
            "500 g · ja! Blattspinat 1kg",
        ),
        ("8 Stängel + 1 TL", {"Stängel": 2}, set(), "10 Stängel + 1 TL"),
        ("", {"Blatt": 5}, set(), "5 Blatt"),
        ("2,5 Prise", {"Prise": 1}, set(), "3,5 Prise"),
        (
            "130 g · Berchtesgadener Land Bio Milch 1,5% 1l",
            {"g": 200},
            set(),
            "330 g · Berchtesgadener Land Bio Milch 1,5% 1l",
        ),
        ("1,5 kg", {"g": 500}, set(), "2 kg"),
        (
            "200 g · ja! Tomatenmark",
            {"g": 100},
            {"Mutti Tomatenmark"},
            "300 g · Mutti Tomatenmark, ja! Tomatenmark",
        ),
        # Von Hand in Bring geändert: anhängen statt rechnen
        ("für Pesto", {"g": 100}, set(), "für Pesto + 100 g"),
    ],
)
def test_merge_description(
    existing: str, amounts: dict[str, float], products: set[str], expected: str
) -> None:
    item = ShoppingItem("Artikel", amounts=amounts, products=products)

    assert merge_description(existing, item) == expected


def test_home_assistant_list_reads_recorded_items(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        shopping_page, "call_service_with_response", lambda *args, **kwargs: RECORDED_ITEMS
    )

    items = shopping_page.HomeAssistantTodoList("todo.furth", "token").open_items()

    assert items[1] == ListItem(
        "114e1328-91e7-40dd-96e4-f71849b96d5b", "Blattspinat", "200 g · ja! Blattspinat 1kg"
    )
    assert items[0].description == ""
    assert len(items) == 6


def test_home_assistant_list_adds_and_updates_with_short_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        shopping_page, "call_service", lambda *args, **kwargs: calls.append((*args, kwargs))
    )
    todo = shopping_page.HomeAssistantTodoList("todo.einkauf", "token")

    todo.add("Broccoli", "550 g")
    todo.add("Feta", "")
    todo.update("uid-1", "700 g")

    timeout = {"timeout": shopping_page.ITEM_TIMEOUT_SECONDS}
    assert calls == [
        (
            "todo",
            "add_item",
            {"entity_id": "todo.einkauf", "item": "Broccoli", "description": "550 g"},
            "token",
            timeout,
        ),
        ("todo", "add_item", {"entity_id": "todo.einkauf", "item": "Feta"}, "token", timeout),
        (
            "todo",
            "update_item",
            {"entity_id": "todo.einkauf", "item": "uid-1", "description": "700 g"},
            "token",
            timeout,
        ),
    ]


def test_home_assistant_list_turns_supervisor_errors_into_send_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(*args: Any, **kwargs: Any) -> None:
        raise SupervisorError("Entität unbekannt")

    monkeypatch.setattr(shopping_page, "call_service", reject)
    monkeypatch.setattr(shopping_page, "call_service_with_response", reject)
    todo = shopping_page.HomeAssistantTodoList("todo.x", "token")

    with pytest.raises(SendError, match="Entität unbekannt"):
        todo.add("Broccoli", "")
    with pytest.raises(SendError, match="Entität unbekannt"):
        todo.open_items()


# --- Seiten ---------------------------------------------------------------


class FakeHomeAssistant:
    """Supervisor-Aufrufe der Seite: `todo.add_item`, `todo.update_item`, `todo.get_items`."""

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []
        self.calls: list[dict[str, Any]] = []

    def call_service(
        self, domain: str, service: str, data: dict[str, Any], *args: Any, **kwargs: Any
    ) -> None:
        self.calls.append({"service": service, **data})
        if service == "add_item":
            uid = f"u{len(self.items)}"
            self.items.append(
                {"summary": data["item"], "uid": uid, "description": data.get("description", "")}
            )
        elif service == "update_item":
            item = next(i for i in self.items if data["item"] in (i["uid"], i["summary"]))
            item["description"] = data["description"]

    def call_service_with_response(
        self, domain: str, service: str, data: dict[str, Any], *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        return {data["entity_id"]: {"items": [dict(item) for item in self.items]}}


@pytest.fixture
def home_assistant(monkeypatch: pytest.MonkeyPatch) -> FakeHomeAssistant:
    fake = FakeHomeAssistant()
    monkeypatch.setenv(TOKEN_ENV_VAR, "supervisor-token")
    monkeypatch.setattr(shopping_page, "call_service", fake.call_service)
    monkeypatch.setattr(
        shopping_page, "call_service_with_response", fake.call_service_with_response
    )
    return fake


@pytest.fixture(autouse=True)
def send_in_foreground(monkeypatch: pytest.MonkeyPatch) -> None:
    """Das Senden läuft sonst in einem eigenen Thread; im Test sofort und im selben Thread."""
    monkeypatch.setattr(shopping_page, "_start_thread", lambda work: work())


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
    home_assistant: FakeHomeAssistant, ingress_client: TestClient
) -> None:
    response = ingress_client.post("/plan/shopping")

    assert home_assistant.items == [{"summary": "Broccoli", "uid": "u0", "description": "300 g"}]
    assert "1 Rezept an todo.einkauf gesendet: 1 Artikel neu, 0 ergänzt." in response.text


def test_send_without_list_asks_for_settings(
    monkeypatch: pytest.MonkeyPatch, migrated: Settings, options_file: Path
) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "supervisor-token")
    settings = migrated.model_copy(update={"bring_list_entity": ""})
    client = TestClient(
        create_app(settings, options_file),
        base_url=f"http://testserver:{settings.ingress_port}",
        client=(INGRESS_PROXY_IP, 50000),
        headers=INGRESS_HEADERS,
    )

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

    items = build_shopping_list(session, MONDAY, MONDAY, PANTRY).items

    assert [item.name for item in items] == ["Hähnchen", "Honig"]


def test_unmatched_line_with_pantry_word_is_set_aside(session: Session) -> None:
    recipe = make_recipe(session, "Suppe")
    recipe.ingredients.append(RecipeIngredient(position=1, raw_text="1 TL Salz"))
    session.flush()
    add_entry(session, MONDAY, recipe)

    shopping = build_shopping_list(session, MONDAY, MONDAY, PANTRY)

    assert [item.name for item in shopping.pantry] == ["1 TL Salz"]


# --- Erneutes Senden -----------------------------------------------------


def _plan(session: Session, day: date, title: str, food_name: str) -> None:
    food = make_food(session, food_name)
    add_entry(session, day, make_recipe(session, title, ingredients=[(food, 300, "g")]))


def test_sent_entries_are_not_sent_again(session: Session) -> None:
    target = FakeList()
    _plan(session, MONDAY, "Pfanne", "Broccoli roh")

    first = build_shopping_list(session, MONDAY, MONDAY + timedelta(days=13), PANTRY)
    send_shopping_list(session, first, target, "todo.einkauf")
    _plan(session, MONDAY + timedelta(days=2), "Curry", "Kichererbse")
    second = build_shopping_list(session, MONDAY, MONDAY + timedelta(days=13), PANTRY)

    assert [name for _, name, _ in target.calls] == ["Broccoli"]
    assert [item.name for item in second.items] == ["Kichererbse"]
    assert [entry.recipe.title for entry in second.already_sent] == ["Pfanne"]


def test_resend_includes_sent_entries(session: Session) -> None:
    _plan(session, MONDAY, "Pfanne", "Broccoli roh")
    shopping = build_shopping_list(session, MONDAY, MONDAY, PANTRY)
    send_shopping_list(session, shopping, FakeList(), "todo.x")

    again = build_shopping_list(session, MONDAY, MONDAY, PANTRY, include_sent=True)

    assert [item.name for item in again.items] == ["Broccoli"]
    assert again.already_sent == []


def test_failed_send_marks_nothing(session: Session) -> None:
    _plan(session, MONDAY, "Pfanne", "Broccoli roh")
    shopping = build_shopping_list(session, MONDAY, MONDAY, PANTRY)

    send_shopping_list(session, shopping, FakeList({"Broccoli": "weg"}), "todo.x")

    assert [item.name for item in build_shopping_list(session, MONDAY, MONDAY, PANTRY).items] == [
        "Broccoli"
    ]


@pytest.mark.usefixtures("planned_today")
def test_second_press_sends_nothing_new(
    home_assistant: FakeHomeAssistant, ingress_client: TestClient
) -> None:
    ingress_client.post("/plan/shopping")
    second = ingress_client.post("/plan/shopping")
    resent = ingress_client.post("/plan/shopping", data={"resend": "true"})

    assert "Keine neuen Rezepte im Plan, nichts gesendet." in second.text
    assert "Bereits gesendet" in second.text
    assert "1 Rezept an todo.einkauf gesendet: 0 Artikel neu, 1 ergänzt." in resent.text
    assert home_assistant.items == [{"summary": "Broccoli", "uid": "u0", "description": "600 g"}]


def test_send_result_is_logged(session: Session, caplog: pytest.LogCaptureFixture) -> None:
    target = FakeList({"Broccoli": "Entität unbekannt"})
    _plan(session, MONDAY, "Pfanne", "Broccoli roh")

    with caplog.at_level("INFO"):
        send_shopping_list(
            session, build_shopping_list(session, MONDAY, MONDAY, PANTRY), target, "todo.x"
        )

    assert "0 Rezepte an todo.x gesendet (0 Artikel neu, 0 ergänzt), 1 offen" in caplog.text
    assert "Broccoli: Entität unbekannt" in caplog.text


def test_imported_unmatched_lines_use_parsed_name_and_amount(session: Session) -> None:
    recipe = make_recipe(session, "Auflauf")
    recipe.ingredients.append(
        RecipeIngredient(
            position=1,
            raw_text="350 g Brokkoliröschen",
            name="Brokkoliröschen",
            quantity=350,
            unit="g",
        )
    )
    recipe.ingredients.append(RecipeIngredient(position=2, raw_text="½ TL Salz", name="Salz"))
    session.flush()
    add_entry(session, MONDAY, recipe)

    shopping = build_shopping_list(session, MONDAY, MONDAY, PANTRY)

    assert [(item.name, item.description) for item in shopping.items] == [
        ("Brokkoliröschen", "350 g")
    ]
    assert [item.name for item in shopping.pantry] == ["Salz"]


def test_shopping_page_covers_the_same_days_as_the_plan(
    monkeypatch: pytest.MonkeyPatch, ingress_client: TestClient, session: Session
) -> None:
    # K11: Plan und Einkaufsliste reichen beide bis heute + PLAN_DAYS_AHEAD
    monkeypatch.setattr(clock, "today", lambda: MONDAY)
    last = MONDAY + timedelta(days=PLAN_DAYS_AHEAD)
    add_entry(
        session,
        last,
        make_recipe(
            session, "Letzter Tag", ingredients=[(make_food(session, "Lauch roh"), 100, "g")]
        ),
    )
    add_entry(
        session,
        last + timedelta(days=1),
        make_recipe(session, "Danach", ingredients=[(make_food(session, "Kohl roh"), 100, "g")]),
    )
    session.commit()

    text = ingress_client.get("/plan/shopping").text

    assert "Lauch" in text
    assert "Kohl" not in text
    assert f"day-{last.isoformat()}" in ingress_client.get("/plan").text


def test_unit_spellings_are_added_up(session: Session) -> None:
    # K10: „EL“/„el“ und „g“/„kg“ sind dieselbe Einheit, eigene Einheiten ohne Groß/klein
    oil = make_food(session, "Rapsöl", units={"EL": 10})
    potatoes = make_food(session, "Kartoffel roh")
    garlic = make_food(session, "Knoblauch roh", units={"Zehe": 4})
    add_entry(
        session,
        MONDAY,
        make_recipe(
            session, "A", ingredients=[(oil, 2, "EL"), (potatoes, 500, "g"), (garlic, 1, "Zehe")]
        ),
    )
    add_entry(
        session,
        MONDAY,
        make_recipe(
            session, "B", ingredients=[(oil, 1, "el"), (potatoes, 1, "kg"), (garlic, 2, "zehe")]
        ),
    )

    items = {
        item.name: item.description
        for item in build_shopping_list(session, MONDAY, MONDAY, PANTRY).items
    }

    assert items == {"Rapsöl": "3 EL", "Kartoffel": "1,5 kg", "Knoblauch": "3 Zehe"}


def test_base_ingredient_names_the_item_and_product_goes_to_details(session: Session) -> None:
    # K20: „Tomatenmark“ statt „ja! Tomatenmark“, damit Bring den Artikel einsortiert
    product = make_food(session, "ja! Tomatenmark", source=FoodSource.REWE, source_id="rewe-1")
    base = create_base(session, "Tomatenmark")
    set_default_product(session, base, product)
    recipe = make_recipe(session, "Soße", ingredients=[(product, 200, "g")])
    recipe.ingredients[0].base_ingredient = base
    add_entry(session, MONDAY, recipe)
    session.flush()

    (item,) = build_shopping_list(session, MONDAY, MONDAY, PANTRY).items

    assert item.name == "Tomatenmark"
    assert item.description == "200 g · ja! Tomatenmark"


def test_own_food_is_not_listed_as_product(session: Session) -> None:
    own = make_food(session, "Hähnchenbrust")
    add_entry(session, MONDAY, make_recipe(session, "Pfanne", ingredients=[(own, 300, "g")]))

    (item,) = build_shopping_list(session, MONDAY, MONDAY, PANTRY).items

    assert item.description == "300 g"


@pytest.mark.usefixtures("planned_today", "home_assistant")
def test_running_send_is_not_started_twice(
    monkeypatch: pytest.MonkeyPatch, ingress_client: TestClient
) -> None:
    # K19a: Ein Klick während des Sendens startet nichts Neues
    started: list[object] = []
    monkeypatch.setattr(shopping_page, "_start_thread", started.append)

    ingress_client.post("/plan/shopping")
    page = ingress_client.post("/plan/shopping")

    assert len(started) == 1
    assert "Wird an todo.einkauf gesendet" in page.text
    assert 'hx-get="/plan/shopping/status"' in page.text


@pytest.mark.usefixtures("planned_today")
def test_status_shows_progress_and_reloads_when_done(
    monkeypatch: pytest.MonkeyPatch, home_assistant: FakeHomeAssistant, ingress_client: TestClient
) -> None:
    # K18: Die Seite antwortet sofort und fragt den Stand ab
    started: list[Any] = []
    monkeypatch.setattr(shopping_page, "_start_thread", started.append)
    ingress_client.post("/plan/shopping")

    running = ingress_client.get("/plan/shopping/status")
    started[0]()  # das Senden läuft durch
    done = ingress_client.get("/plan/shopping/status")
    page = ingress_client.get("/plan/shopping").text

    assert "Wird an todo.einkauf gesendet" in running.text
    assert done.headers["HX-Refresh"] == "true"
    assert "1 Rezept an todo.einkauf gesendet" in page
    assert "1 Rezept an" not in ingress_client.get("/plan/shopping").text  # Meldung nur einmal
    assert len(home_assistant.items) == 1


@pytest.mark.usefixtures("planned_today", "home_assistant")
def test_unexpected_error_in_background_is_reported(
    monkeypatch: pytest.MonkeyPatch, ingress_client: TestClient
) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("kaputt")

    monkeypatch.setattr(shopping_page, "call_service", broken)

    page = ingress_client.post("/plan/shopping").text

    assert "unerwartet abgebrochen" in page


def test_check_reads_features_and_open_items(
    monkeypatch: pytest.MonkeyPatch, ingress_client: TestClient
) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "supervisor-token")
    monkeypatch.setattr(
        shopping_page,
        "get_core_state",
        lambda entity_id, token: {"attributes": {"supported_features": 71}},
    )
    monkeypatch.setattr(
        shopping_page,
        "call_service_with_response",
        lambda *args: {
            "todo.einkauf": {"items": [{"summary": "Tomatenmark", "description": "200 g"}]}
        },
    )

    text = ingress_client.post("/plan/shopping/check").text

    assert "Funktionen: Anlegen, Löschen, Ändern, Beschreibung (71)" in text
    assert "Tomatenmark" in text
    assert "service_response" in text


def test_check_shows_supervisor_errors(
    monkeypatch: pytest.MonkeyPatch, ingress_client: TestClient
) -> None:
    def reject(*args: Any) -> None:
        raise SupervisorError("Entität unbekannt")

    monkeypatch.setenv(TOKEN_ENV_VAR, "supervisor-token")
    monkeypatch.setattr(shopping_page, "get_core_state", reject)

    assert "Entität unbekannt" in ingress_client.post("/plan/shopping/check").text


@pytest.mark.parametrize(
    ("product_name", "expected"),
    [
        ("Cherry Romatomaten 250g", "Cherry Romatomaten"),
        ("ja! Kokosmilch fettreduziert 400 g", "ja! Kokosmilch fettreduziert"),
        ("Bio Milch 1,5% 1l", "Bio Milch 1,5%"),
        ("ja! Eier", "ja! Eier"),
    ],
)
def test_product_without_base_ingredient_drops_package_size(
    session: Session, product_name: str, expected: str
) -> None:
    product = make_food(session, product_name, source=FoodSource.REWE, source_id=product_name)
    add_entry(session, MONDAY, make_recipe(session, "Salat", ingredients=[(product, 1, "Stück")]))

    (item,) = build_shopping_list(session, MONDAY, MONDAY, PANTRY).items

    assert item.name == expected


def test_entry_without_details_is_left_alone(session: Session) -> None:
    # Von Hand „Oliven“ ohne Angaben: vielleicht andere Oliven, also eigener Eintrag
    target = FakeList()
    target.items = [ListItem("u-o", "Oliven", "")]
    olives = make_food(session, "Oliven grün", units={"EL": 10})
    olives.shopping_name = "Oliven"
    add_entry(session, MONDAY, make_recipe(session, "Salat", ingredients=[(olives, 4, "EL")]))
    add_entry(session, MONDAY, make_recipe(session, "Pizza", ingredients=[(olives, 2, "EL")]))
    shopping = build_shopping_list(session, MONDAY, MONDAY, PANTRY)

    send_shopping_list(session, shopping, target, "todo.x")

    assert [(item.name, item.description) for item in target.items] == [
        ("Oliven", ""),
        ("Oliven", "6 EL"),
    ]
