"""Platzhalter von der Rezeptseite füllen: Steuerung, Plan nach dem Abgleich, Import-Seite."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import clock
from factories import FAKE_TODAY, FakeCalendar, make_recipe, recipe_page
from modules.planner.models import PlanEntry
from modules.planner.service import add_entry
from modules.recipes.models import Recipe
from modules.recipes.service import create_placeholder, list_placeholders
from web import cookidoo_fill
from web.cookidoo_fill import fill_placeholders
from web.pages import imports as imports_page
from web.pages import plan as plan_page

DAY = date(2026, 11, 4)


class ConnectedPages(FakeCalendar):
    def username(self) -> str | None:
        return "Fabi"


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    pauses: list[float] = []
    monkeypatch.setattr(cookidoo_fill.time, "sleep", pauses.append)
    return pauses


def _placeholder(session: Session, rid: str, title: str) -> Recipe:
    return create_placeholder(
        session, rid, title, f"https://cookidoo.de/recipes/recipe/de-DE/{rid}"
    )


def _page(title: str, servings: int = 4) -> str:
    return recipe_page(
        title,
        ["200 g rote Linsen", "1 Zwiebel"],
        recipe_yield=f"{servings} Portionen",
        nutrition={"calories": "430 kcal"},
    )


# --- Steuerung -------------------------------------------------------------------------


def test_placeholder_gets_lines_servings_reference_and_its_plan_entries(session: Session) -> None:
    recipe = _placeholder(session, "r1", "Linsen-Dal")
    planned = add_entry(session, DAY, recipe)
    pages = FakeCalendar()
    pages.pages["r1"] = _page("Linsen-Dal", servings=4)

    result = fill_placeholders(session, pages, [recipe])

    assert (result.filled, result.adopted, result.skipped) == (1, 1, [])
    assert [line.raw_text for line in recipe.ingredients] == ["200 g rote Linsen", "1 Zwiebel"]
    assert (recipe.servings, planned.servings) == (4, 4)
    assert recipe.reference is not None and recipe.reference.kcal == 430
    assert not recipe.is_placeholder
    assert "Gesamtzeit 30 min" in (recipe.note or "")


def test_only_placeholders_are_fetched(session: Session) -> None:
    pages = FakeCalendar()

    result = fill_placeholders(session, pages, [make_recipe(session)])

    assert (result.filled, result.skipped, pages.page_requests) == (0, [], [])


def test_missing_page_and_wrong_title_are_skipped_others_go_on(session: Session) -> None:
    missing = _placeholder(session, "r1", "Gibt es nicht mehr")
    renamed = _placeholder(session, "r2", "Linsen-Dal")
    good = _placeholder(session, "r3", "Kürbissuppe")
    pages = FakeCalendar()
    pages.pages |= {"r2": _page("Kichererbsen-Curry"), "r3": _page("Kürbissuppe")}

    result = fill_placeholders(session, pages, [missing, renamed, good])

    assert result.filled == 1
    assert [(item.title, item.reason) for item in result.skipped] == [
        ("Gibt es nicht mehr", "Rezeptseite nicht gefunden (404)."),
        ("Linsen-Dal", "Titel passt nicht, die Rezeptseite heißt „Kichererbsen-Curry“."),
    ]
    assert (missing.is_placeholder, renamed.is_placeholder, good.is_placeholder) == (
        True,
        True,
        False,
    )


def test_unreachable_cookidoo_stops_after_the_first_request(session: Session) -> None:
    recipes = [_placeholder(session, f"r{n}", f"Rezept {n}") for n in range(1, 4)]
    pages = FakeCalendar()
    pages.unreachable = True

    result = fill_placeholders(session, pages, recipes)

    assert pages.page_requests == ["r1"]
    assert [item.title for item in result.skipped] == ["Rezept 1", "Rezept 2", "Rezept 3"]
    assert all(recipe.is_placeholder for recipe in recipes)


def test_requests_are_throttled_and_limited(
    session: Session, monkeypatch: pytest.MonkeyPatch, no_waiting: list[float]
) -> None:
    monkeypatch.setattr(cookidoo_fill, "MAX_PAGES_PER_RUN", 2)
    recipes = [_placeholder(session, f"r{n}", f"Rezept {n}") for n in range(1, 4)]
    pages = FakeCalendar()
    pages.pages |= {f"r{n}": _page(f"Rezept {n}") for n in range(1, 4)}

    result = fill_placeholders(session, pages, recipes)

    assert pages.page_requests == ["r1", "r2"]
    assert no_waiting == [cookidoo_fill.PAGE_DELAY_SECONDS]
    assert result.filled == 2
    assert [item.title for item in result.skipped] == ["Rezept 3"]


# --- Abgleich im Plan ------------------------------------------------------------------


@pytest.fixture
def calendar(monkeypatch: pytest.MonkeyPatch) -> ConnectedPages:
    fake = ConnectedPages((2, "r1"))
    monkeypatch.setattr(clock, "today", lambda: FAKE_TODAY)
    monkeypatch.setattr(plan_page, "cookidoo_account", lambda settings: fake)
    monkeypatch.setattr(imports_page, "cookidoo_account", lambda settings: fake)
    return fake


def _apply(client: TestClient) -> str:
    page = client.get("/plan/cookidoo").text
    fingerprint = page.split('name="fingerprint" value="')[1].split('"')[0]
    return client.post("/plan/cookidoo", data={"fingerprint": fingerprint}).text


def _planned(client: TestClient) -> list[tuple[str, float, int]]:
    with client.app.state.session_factory() as session:
        return [
            (entry.recipe.title, entry.servings, len(entry.recipe.ingredients))
            for entry in session.scalars(select(PlanEntry))
        ]


def test_sync_loads_unknown_recipe_right_away(
    ingress_client: TestClient, calendar: ConnectedPages
) -> None:
    calendar.pages["r1"] = _page("Rezept r1", servings=4)

    assert "Neue Rezepte" in ingress_client.get("/plan/cookidoo").text
    page = _apply(ingress_client)

    assert "1 neues Rezept aus Cookidoo geladen." in page
    assert "vorerst Platzhalter" not in page
    assert _planned(ingress_client) == [("Rezept r1", 4, 2)]
    assert "Alles abgeglichen" in ingress_client.get("/plan/cookidoo").text


def test_sync_keeps_placeholder_when_page_fails(
    ingress_client: TestClient, calendar: ConnectedPages
) -> None:
    page = _apply(ingress_client)

    assert "Mit Cookidoo abgeglichen: 1 Änderung." in page
    assert "1 Rezept bleibt vorerst Platzhalter." in page
    assert _planned(ingress_client) == [("Rezept r1", 1, 0)]


# --- Import-Seite ----------------------------------------------------------------------


def test_import_page_offers_and_fills_placeholders(
    ingress_client: TestClient, calendar: ConnectedPages
) -> None:
    with ingress_client.app.state.session_factory() as session:
        _placeholder(session, "r7", "Linsen-Dal")
        _placeholder(session, "r8", "Weg")
        session.commit()
    calendar.pages["r7"] = _page("Linsen-Dal")

    assert "2 Rezepte ohne Zutaten: Linsen-Dal, Weg." in ingress_client.get("/settings/import").text
    page = ingress_client.post("/settings/import/placeholders").text

    assert "1 Platzhalter mit Zutaten und Portionen aus Cookidoo gefüllt" in page
    assert 'Weg <span class="meta">– Rezeptseite nicht gefunden (404).</span>' in page
    with ingress_client.app.state.session_factory() as session:
        assert [recipe.title for recipe in list_placeholders(session)] == ["Weg"]


def test_import_page_without_connection_has_no_fill_button(
    ingress_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Disconnected(FakeCalendar):
        def username(self) -> str | None:
            return None

    monkeypatch.setattr(imports_page, "cookidoo_account", lambda settings: Disconnected())
    with ingress_client.app.state.session_factory() as session:
        _placeholder(session, "r7", "Linsen-Dal")
        session.commit()

    assert "Platzhalter füllen" not in ingress_client.get("/settings/import").text
