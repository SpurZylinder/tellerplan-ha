"""Abgleich im Plan: Knopf, Vorschau, Übernehmen, Meldungen."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import clock
from cookidoo import CookidooError
from factories import FAKE_TODAY, FakeCalendar
from modules.planner.models import PlanEntry
from web.pages import plan as plan_page

TODAY = FAKE_TODAY


class ConnectedCalendar(FakeCalendar):
    """Attrappe mit Anzeigename, wie ein verbundenes `CookidooAccount`."""

    connected = True
    fail_reading = False

    def username(self) -> str | None:
        return "Fabi" if self.connected else None

    def read_calendar(self, first: date, last: date) -> list:  # type: ignore[override]
        if self.fail_reading:
            raise CookidooError("Cookidoo ist gerade nicht erreichbar.")
        return super().read_calendar(first, last)


@pytest.fixture
def calendar(monkeypatch: pytest.MonkeyPatch) -> ConnectedCalendar:
    fake = ConnectedCalendar((1, "r1"))
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    monkeypatch.setattr(plan_page, "cookidoo_account", lambda settings: fake)
    return fake


def _entries(client: TestClient) -> list[tuple[date, date | None]]:
    with client.app.state.session_factory() as session:
        return [(e.day, e.cookidoo_day) for e in session.scalars(select(PlanEntry))]


def test_button_only_when_connected(
    ingress_client: TestClient, calendar: ConnectedCalendar
) -> None:
    assert "⇄ Cookidoo" in ingress_client.get("/plan").text

    calendar.connected = False

    assert "⇄ Cookidoo" not in ingress_client.get("/plan").text


def test_preview_lists_changes_and_writes_nothing(
    ingress_client: TestClient, calendar: ConnectedCalendar
) -> None:
    page = ingress_client.get("/plan/cookidoo").text

    assert "Neue Platzhalter" in page
    assert "Rezept r1: neu am Di 03.11." in page
    assert 'name="fingerprint"' in page
    assert _entries(ingress_client) == []
    assert calendar.calls == []


def test_apply_takes_over_and_reports(
    ingress_client: TestClient, calendar: ConnectedCalendar
) -> None:
    page = ingress_client.get("/plan/cookidoo").text
    fingerprint = page.split('name="fingerprint" value="')[1].split('"')[0]

    response = ingress_client.post("/plan/cookidoo", data={"fingerprint": fingerprint})

    assert "Mit Cookidoo abgeglichen: 1 Änderung." in response.text
    assert _entries(ingress_client) == [(date(2026, 11, 3), date(2026, 11, 3))]
    assert "Platzhalter" in response.text
    assert "In Cookidoo öffnen" in response.text
    assert "Alles abgeglichen" in ingress_client.get("/plan/cookidoo").text


def test_changed_meanwhile_shows_new_preview(
    ingress_client: TestClient, calendar: ConnectedCalendar
) -> None:
    response = ingress_client.post("/plan/cookidoo", data={"fingerprint": "veraltet"})

    assert "hat sich seit der Vorschau etwas geändert" in response.text
    assert _entries(ingress_client) == []


def test_unreachable_cookidoo_points_to_settings(
    ingress_client: TestClient, calendar: ConnectedCalendar
) -> None:
    calendar.fail_reading = True

    page = ingress_client.get("/plan/cookidoo").text

    assert "nicht erreichbar" in page
    assert "Einstellungen → Cookidoo" in page
