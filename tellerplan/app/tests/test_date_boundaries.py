"""Datumsgrenzen in den Seiten (Befund C-G): „heute“ wechselt um Mitternacht nach der Uhr der App.

Die Uhr (`clock.now`) wird fest gestellt, eine Minute vor und nach Mitternacht.
So prüfen die Tests die Zeitzone von Home Assistant statt der Systemzeit des Rechners.
"""

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import clock
from factories import make_food, make_recipe
from modules.planner.service import add_entry

BEFORE_MIDNIGHT = datetime(2026, 11, 13, 23, 59)
AFTER_MIDNIGHT = datetime(2026, 11, 14, 0, 1)
FRIDAY = date(2026, 11, 13)


def _set_clock(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    monkeypatch.setattr(clock, "now", lambda: moment)


def test_plan_moves_today_at_midnight(
    monkeypatch: pytest.MonkeyPatch, ingress_client: TestClient
) -> None:
    _set_clock(monkeypatch, BEFORE_MIDNIGHT)
    before = ingress_client.get("/plan").text
    _set_clock(monkeypatch, AFTER_MIDNIGHT)
    after = ingress_client.get("/plan").text

    assert 'id="day-2026-11-13" data-today' in before
    assert 'id="day-2026-11-10"' in before  # drei Tage zurück
    assert 'id="day-2026-11-27"' in before  # heute + 14
    assert 'id="day-2026-11-28"' not in before
    assert 'id="day-2026-11-14" data-today' in after
    assert 'id="day-2026-11-13" data-today' not in after
    assert 'id="day-2026-11-28"' in after
    assert 'id="day-2026-11-10"' not in after


def test_today_page_starts_empty_after_midnight(
    monkeypatch: pytest.MonkeyPatch, ingress_client: TestClient, session: Session
) -> None:
    food = make_food(session, "Skyr", kcal=60)
    session.commit()
    _set_clock(monkeypatch, BEFORE_MIDNIGHT)
    ingress_client.post(
        "/diary/food",
        data={
            "day": FRIDAY.isoformat(),
            "meal": "Snacks",
            "food_id": str(food.id),
            "quantity": "100",
            "unit": "g",
        },
    )
    before = ingress_client.get("/").text

    _set_clock(monkeypatch, AFTER_MIDNIGHT)
    after = ingress_client.get("/").text
    friday = ingress_client.get(f"/?day={FRIDAY.isoformat()}").text

    assert "Skyr" in before
    assert "Skyr" not in after
    assert "Skyr" in friday


def test_shopping_list_drops_yesterday_at_midnight(
    monkeypatch: pytest.MonkeyPatch, ingress_client: TestClient, session: Session
) -> None:
    leek = make_food(session, "Lauch roh")
    add_entry(session, FRIDAY, make_recipe(session, "Suppe", ingredients=[(leek, 200, "g")]))
    session.commit()

    _set_clock(monkeypatch, BEFORE_MIDNIGHT)
    before = ingress_client.get("/plan/shopping").text
    _set_clock(monkeypatch, AFTER_MIDNIGHT)
    after = ingress_client.get("/plan/shopping").text

    assert "Lauch" in before
    assert "Lauch" not in after
