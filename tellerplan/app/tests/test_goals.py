"""Ziele je Benutzer (0.6.0, B4): eigene Ziele ab einem Tag, sonst die Vorgabe."""

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import clock
from conftest import ADMIN_ID, MEMBER_ID
from main import create_app
from modules.users.goals import Goals, goals_for, set_goals
from modules.users.models import Goal
from security import INGRESS_PROXY_IP
from settings import Settings
from supervisor import TOKEN_ENV_VAR

DAY = date(2026, 11, 13)
DEFAULTS = Goals(kcal=2000, protein_g=150, fat_g=70, carbs_g=200)
MINE = {"kcal": "1800", "protein_g": "160", "fat_g": "60", "carbs_g": "180"}


class Today:
    """Verstellbares „heute“ für die Tests."""

    day = DAY


@pytest.fixture(autouse=True)
def in_addon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "supervisor-token")
    Today.day = DAY
    monkeypatch.setattr(clock, "today", lambda: Today.day)


def _client(settings: Settings, options_file: Path, user_id: str) -> TestClient:
    return TestClient(
        create_app(settings, options_file),
        base_url=f"http://testserver:{settings.ingress_port}",
        client=(INGRESS_PROXY_IP, 50000),
        headers={"x-remote-user-id": user_id, "x-remote-user-name": "x"},
        follow_redirects=False,
    )


@pytest.fixture
def clients(migrated: Settings, options_file: Path) -> Iterator[tuple[TestClient, TestClient]]:
    admin = _client(migrated, options_file, ADMIN_ID)
    member = _client(migrated, options_file, MEMBER_ID)
    yield admin, member
    admin.app.state.engine.dispose()
    member.app.state.engine.dispose()


def test_without_own_goals_the_defaults_apply(session: Session) -> None:
    result = goals_for(session, "u1", DAY, DEFAULTS)

    assert result.goals == DEFAULTS and not result.own


def test_goal_applies_from_its_day_and_past_days_keep_theirs(session: Session) -> None:
    first = Goals(1800, 160, 60, 180)
    later = Goals(1700, 170, 55, 160)
    set_goals(session, "u1", DAY, first)
    set_goals(session, "u1", DAY + timedelta(days=10), later)

    assert goals_for(session, "u1", DAY - timedelta(days=1), DEFAULTS).goals == DEFAULTS
    assert goals_for(session, "u1", DAY, DEFAULTS).goals == first
    assert goals_for(session, "u1", DAY + timedelta(days=9), DEFAULTS).goals == first
    assert goals_for(session, "u1", DAY + timedelta(days=30), DEFAULTS).goals == later
    assert goals_for(session, "u2", DAY, DEFAULTS).goals == DEFAULTS


def test_second_change_on_the_same_day_replaces_the_first(session: Session) -> None:
    set_goals(session, "u1", DAY, Goals(1800, 160, 60, 180))
    set_goals(session, "u1", DAY, Goals(1900, 160, 60, 180))

    assert session.scalars(select(Goal.kcal)).all() == [1900]


def test_member_saves_own_goals(clients: tuple[TestClient, TestClient], session: Session) -> None:
    admin, member = clients

    response = member.post("/settings/goals", data=MINE)

    assert response.status_code == 303
    assert response.headers["location"].endswith("/settings?goals_saved=1#ziele")
    page = member.get("/settings?goals_saved=1").text
    assert "Gespeichert. Gilt ab heute." in page
    assert 'name="kcal" value="1800"' in page and "Deine eigenen Ziele." in page
    assert "/ 160 g" in member.get("/").text
    # Der Verwalter hat weiter die Vorgabe
    assert 'name="kcal" value="2000"' in admin.get("/settings").text
    assert "/ 150 g" in admin.get("/").text
    assert session.scalars(select(Goal.user_id)).all() == [MEMBER_ID]


def test_past_days_keep_the_goals_of_their_time(clients: tuple[TestClient, TestClient]) -> None:
    _, member = clients
    member.post("/settings/goals", data=MINE)

    Today.day = DAY + timedelta(days=5)
    member.post("/settings/goals", data={**MINE, "protein_g": "175"})

    assert "/ 175 g" in member.get("/").text
    assert "/ 160 g" in member.get(f"/?day={DAY.isoformat()}").text
    assert "/ 150 g" in member.get(f"/?day={(DAY - timedelta(days=1)).isoformat()}").text


@pytest.mark.parametrize(
    ("field", "text", "message"),
    [
        ("kcal", "100", "Tageslimit muss zwischen 500 und 10000 kcal liegen."),
        ("protein_g", "12,5", "Eiweiß muss eine ganze Zahl sein."),
        ("fat_g", "", "Fett fehlt."),
    ],
)
def test_invalid_own_goal_is_reported(
    clients: tuple[TestClient, TestClient], session: Session, field: str, text: str, message: str
) -> None:
    _, member = clients

    response = member.post("/settings/goals", data={**MINE, field: text})

    assert response.status_code == 200
    assert message in response.text
    assert session.scalars(select(Goal)).all() == []
