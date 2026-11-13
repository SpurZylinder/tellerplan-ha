"""Tagebuch je Benutzer (0.6.0, B3): Jeder sieht nur seine Einträge."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import clock
from conftest import ADMIN_ID, MEMBER_ID
from factories import make_food, make_recipe
from main import create_app
from modules.diary.models import DiaryEntry
from modules.diary.service import Viewer, assign_unowned, count_unowned, day_log, log_food
from modules.planner.service import add_entry
from security import INGRESS_PROXY_IP
from settings import Settings
from supervisor import TOKEN_ENV_VAR

DAY = date(2026, 11, 13)
MEALS = ["Frühstück", "Mittag", "Abendessen", "Snacks"]


@pytest.fixture(autouse=True)
def in_addon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "supervisor-token")
    monkeypatch.setattr(clock, "today", lambda: DAY)


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


def _log(client: TestClient, food_id: int) -> None:
    response = client.post(
        "/diary/food",
        data={
            "day": DAY.isoformat(),
            "meal": "Snacks",
            "food_id": str(food_id),
            "quantity": "100",
            "unit": "g",
        },
    )
    assert response.status_code == 303


def test_each_user_sees_only_own_entries(
    clients: tuple[TestClient, TestClient], session: Session
) -> None:
    admin, member = clients
    skyr = make_food(session, "Skyr")
    banana = make_food(session, "Banane")
    session.commit()

    _log(admin, skyr.id)
    _log(member, banana.id)

    admin_page, member_page = admin.get("/").text, member.get("/").text
    assert "Skyr" in admin_page and "Banane" not in admin_page
    assert "Banane" in member_page and "Skyr" not in member_page
    owners = {entry.label: entry.user_id for entry in session.scalars(select(DiaryEntry))}
    assert owners == {"Skyr": ADMIN_ID, "Banane": MEMBER_ID}


def test_foreign_entry_cannot_be_changed_or_deleted(
    clients: tuple[TestClient, TestClient], session: Session
) -> None:
    admin, member = clients
    skyr = make_food(session, "Skyr")
    session.commit()
    _log(admin, skyr.id)
    entry_id = session.scalars(select(DiaryEntry.id)).one()

    assert member.post(f"/diary/entries/{entry_id}/delete").status_code == 404
    assert member.post(f"/diary/entries/{entry_id}", data={"quantity": "5"}).status_code == 404
    assert session.get(DiaryEntry, entry_id) is not None


def test_plan_is_shared_but_logged_per_user(
    clients: tuple[TestClient, TestClient], session: Session
) -> None:
    admin, member = clients
    recipe = make_recipe(session, "Linsen-Dal")
    plan_entry = add_entry(session, DAY, recipe)
    session.commit()

    member.post(
        "/diary/recipe",
        data={
            "day": DAY.isoformat(),
            "meal": "Abendessen",
            "recipe_id": str(recipe.id),
            "servings": "1",
            "plan_entry_id": str(plan_entry.id),
        },
    )

    assert "✓ eingetragen" in member.get("/").text
    admin_page = admin.get("/").text
    assert "Linsen-Dal" in admin_page  # der Plan ist gemeinsam
    assert "✓ eingetragen" not in admin_page  # gegessen hat nur Fabian


def test_old_entries_are_seen_by_admins_until_assigned(
    clients: tuple[TestClient, TestClient], session: Session
) -> None:
    admin, member = clients
    old = log_food(session, "x", DAY, "Snacks", make_food(session, "Altbrot"), 50, "g")
    old.user_id = None  # Eintrag von vor 0.5.12
    session.commit()

    assert "Altbrot" in admin.get("/").text
    assert "Altbrot" not in member.get("/").text
    member.get("/")  # Fabian ist damit bekannt
    settings = admin.get("/settings").text
    assert "1 Einträge stammen aus der Zeit vor den getrennten Tagebüchern" in settings
    assert f'value="{MEMBER_ID}">Fabian' in settings

    response = admin.post("/settings/diary-owner", data={"user_id": MEMBER_ID})

    assert "1 Einträge gehören jetzt Fabian." in response.text
    assert "Altbrot" in member.get("/").text
    assert "Altbrot" not in admin.get("/").text


def test_members_cannot_assign_old_entries(clients: tuple[TestClient, TestClient]) -> None:
    _, member = clients

    assert member.post("/settings/diary-owner", data={"user_id": MEMBER_ID}).status_code == 403


def test_assignment_needs_a_known_user(clients: tuple[TestClient, TestClient]) -> None:
    admin, _ = clients

    response = admin.post("/settings/diary-owner", data={"user_id": "fremd"})

    assert "Bitte einen Benutzer wählen." in response.text


def test_service_counts_and_assigns_unowned(session: Session) -> None:
    food = make_food(session, "Skyr")
    own = log_food(session, "u1", DAY, "Snacks", food, 100, "g")
    old = log_food(session, "u1", DAY, "Snacks", food, 50, "g")
    old.user_id = None
    session.flush()

    assert count_unowned(session) == 1
    assert assign_unowned(session, "u2") == 1
    assert count_unowned(session) == 0
    assert [e.id for m in day_log(session, DAY, MEALS, Viewer("u1")).meals for e in m.entries] == [
        own.id
    ]
