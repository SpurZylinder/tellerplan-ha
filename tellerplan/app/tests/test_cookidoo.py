"""Anbindung an Cookidoo: mit einer Attrappe der Bibliothek, ohne Netzwerk."""

import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cookidoo_api import CookidooAuthData, CookidooAuthException, CookidooRequestException
from fastapi.testclient import TestClient

import cookidoo as cookidoo_module
from cookidoo import CookidooAccount, CookidooError, NotConnectedError, week_starts
from settings import Settings

PASSWORD = "richtig"
MONDAY = date(2026, 11, 2)


class FakeCookidoo:
    """Verhält sich wie `cookidoo_api.Cookidoo`, so weit Tellerplan es nutzt."""

    calendar: dict[date, list[tuple[str, bool]]]
    fail_requests = False

    def __init__(self, session: object, cfg: Any, on_auth_data_update: Any = None) -> None:
        self.cfg = cfg
        self.on_auth_data_update = on_auth_data_update
        self.auth_data: CookidooAuthData | None = None

    def apply_auth_data(self, auth_data: CookidooAuthData) -> None:
        self.auth_data = auth_data

    async def login(self) -> None:
        if self.cfg.password != PASSWORD:
            raise CookidooAuthException("Anmeldung abgelehnt")
        self.auth_data = CookidooAuthData(access_token="a1", refresh_token="r1", expires_at=1.0)

    async def get_user_info(self) -> SimpleNamespace:
        return SimpleNamespace(username="Fabi")

    async def get_recipes_in_calendar_week(self, day: date) -> list[SimpleNamespace]:
        if self.fail_requests:
            raise CookidooRequestException("Zeitüberschreitung")
        # Die Bibliothek erneuert abgelaufene Tokens selbst und meldet sie zurück
        self.on_auth_data_update(
            CookidooAuthData(access_token="a2", refresh_token="r2", expires_at=2.0)
        )
        monday = day - timedelta(days=day.weekday())
        return [
            SimpleNamespace(
                id=planned.isoformat(),
                recipes=[
                    SimpleNamespace(
                        id=rid, name=f"Rezept {rid}", url=f"https://c/{rid}", is_custom=c
                    )
                    for rid, c in recipes
                ],
            )
            for planned, recipes in sorted(self.calendar.items())
            if monday <= planned < monday + timedelta(days=7) and recipes
        ]

    async def add_recipes_to_calendar(self, day: date, recipe_ids: list[str]) -> None:
        self.calendar.setdefault(day, []).extend((rid, False) for rid in recipe_ids)

    async def remove_recipe_from_calendar(self, day: date, recipe_id: str) -> None:
        self.calendar[day] = [entry for entry in self.calendar[day] if entry[0] != recipe_id]


async def _localization(country: str, language: str) -> list[SimpleNamespace]:
    if language == "xx-XX":
        return []
    return [SimpleNamespace(country_code=country, language=language, url="https://c")]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> type[FakeCookidoo]:
    FakeCookidoo.calendar = {}
    FakeCookidoo.fail_requests = False
    monkeypatch.setattr(cookidoo_module, "Cookidoo", FakeCookidoo)
    monkeypatch.setattr(cookidoo_module, "get_localization_options", _localization)
    return FakeCookidoo


@pytest.fixture
def account(tmp_path: Path, fake: type[FakeCookidoo]) -> CookidooAccount:
    return CookidooAccount(tmp_path / "cookidoo_token.json", "de-DE")


def test_week_starts_cover_the_range() -> None:
    assert week_starts(date(2026, 10, 31), date(2026, 11, 13)) == [
        date(2026, 10, 26),
        MONDAY,
        date(2026, 11, 9),
    ]


def test_connect_stores_tokens_but_never_the_password(account: CookidooAccount) -> None:
    assert account.username() is None

    assert account.connect("ich@example.org", PASSWORD) == "Fabi"

    stored = account.token_path.read_text(encoding="utf-8")
    assert account.username() == "Fabi"
    assert json.loads(stored)["tokens"]["refresh_token"] == "r1"
    assert PASSWORD not in stored
    assert "ich@example.org" not in stored


def test_rejected_login_stores_nothing(account: CookidooAccount) -> None:
    with pytest.raises(CookidooError, match="abgelehnt"):
        account.connect("ich@example.org", "falsch")

    assert not account.token_path.exists()


def test_read_calendar_spans_weeks_and_skips_custom_recipes(
    account: CookidooAccount, fake: type[FakeCookidoo]
) -> None:
    account.connect("ich@example.org", PASSWORD)
    fake.calendar = {
        MONDAY - timedelta(days=1): [("r1", False)],  # vor dem Zeitraum
        MONDAY: [("r2", False), ("eigen", True)],
        MONDAY + timedelta(days=8): [("r3", False)],
    }

    recipes = account.read_calendar(MONDAY, MONDAY + timedelta(days=13))

    assert [(r.day, r.recipe_id, r.name) for r in recipes] == [
        (MONDAY, "r2", "Rezept r2"),
        (MONDAY + timedelta(days=8), "r3", "Rezept r3"),
    ]


def test_renewed_tokens_are_saved(account: CookidooAccount) -> None:
    account.connect("ich@example.org", PASSWORD)

    account.read_calendar(MONDAY, MONDAY)

    stored = json.loads(account.token_path.read_text(encoding="utf-8"))
    assert stored == {
        "username": "Fabi",
        "tokens": {"access_token": "a2", "refresh_token": "r2", "expires_at": 2.0},
    }


def test_plan_and_unplan(account: CookidooAccount) -> None:
    account.connect("ich@example.org", PASSWORD)

    account.plan(MONDAY, ["r7", "r8"])
    account.unplan(MONDAY, "r7")

    assert [r.recipe_id for r in account.read_calendar(MONDAY, MONDAY)] == ["r8"]


def test_without_connection_nothing_is_called(account: CookidooAccount) -> None:
    with pytest.raises(NotConnectedError):
        account.read_calendar(MONDAY, MONDAY)


def test_unreachable_cookidoo_becomes_a_readable_error(
    account: CookidooAccount, fake: type[FakeCookidoo]
) -> None:
    account.connect("ich@example.org", PASSWORD)
    fake.fail_requests = True

    with pytest.raises(CookidooError, match="nicht erreichbar"):
        account.read_calendar(MONDAY, MONDAY)


def test_unknown_locale_is_reported(tmp_path: Path, fake: type[FakeCookidoo]) -> None:
    account = CookidooAccount(tmp_path / "token.json", "xx-XX")

    with pytest.raises(CookidooError, match="xx-XX"):
        account.connect("ich@example.org", PASSWORD)


def test_disconnect_forgets_tokens(account: CookidooAccount) -> None:
    account.connect("ich@example.org", PASSWORD)

    account.disconnect()

    assert account.username() is None


def test_token_file_lies_next_to_the_database(settings: Settings) -> None:
    assert settings.cookidoo_token_path.parent == settings.database_path.parent


def test_settings_page_connects_and_disconnects(
    ingress_client: TestClient, fake: type[FakeCookidoo]
) -> None:
    assert "Verbinden" in ingress_client.get("/settings").text

    response = ingress_client.post(
        "/settings/cookidoo", data={"email": "ich@example.org", "password": PASSWORD}
    )

    assert "Verbunden als <b>Fabi</b>" in response.text
    response = ingress_client.post("/settings/cookidoo/disconnect")
    assert "Verbunden als" not in response.text


def test_settings_page_shows_rejected_login(
    ingress_client: TestClient, fake: type[FakeCookidoo]
) -> None:
    response = ingress_client.post(
        "/settings/cookidoo", data={"email": "ich@example.org", "password": "falsch"}
    )

    assert response.status_code == 200
    assert "abgelehnt" in response.text
    assert 'value="ich@example.org"' in response.text
    assert "falsch" not in response.text
