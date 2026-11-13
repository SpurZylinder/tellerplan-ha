"""Anbindung an Cookidoo: mit einer Attrappe der Bibliothek, ohne Netzwerk."""

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cookidoo_api import CookidooAuthData, CookidooAuthException, CookidooRequestException
from fastapi.testclient import TestClient

import clock
import cookidoo as cookidoo_module
import files as files_module
from cookidoo import (
    CookidooAccount,
    CookidooError,
    NotConnectedError,
    RecipePageMissingError,
    is_recipe_id,
    week_starts,
)
from settings import Settings

PASSWORD = "richtig"
MONDAY = date(2026, 11, 2)


class FakeCookidoo:
    """Verhält sich wie `cookidoo_api.Cookidoo`, so weit Tellerplan es nutzt."""

    calendar: dict[date, list[tuple[str, bool]]]
    # Abweichender Name und Link je ID, z. B. für manipulierte Antworten
    details: dict[str, tuple[str, str]]
    fail_requests = False
    # Datum, das Cookidoo statt des echten Tags liefert, z. B. für kaputte Antworten
    day_id: str | None = None

    def __init__(self, session: object, cfg: Any, on_auth_data_update: Any = None) -> None:
        self.cfg = cfg
        self.localization = cfg.localization
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
                id=self.day_id or planned.isoformat(),
                recipes=[
                    SimpleNamespace(
                        id=rid,
                        name=self.details.get(rid, (f"Rezept {rid}", ""))[0],
                        url=self.details.get(rid, ("", f"https://c/{rid}"))[1],
                        is_custom=c,
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
    FakeCookidoo.details = {}
    FakeCookidoo.fail_requests = False
    FakeCookidoo.day_id = None
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


def test_check_lists_the_next_days(
    ingress_client: TestClient, fake: type[FakeCookidoo], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(clock, "today", lambda: MONDAY)
    ingress_client.post(
        "/settings/cookidoo", data={"email": "ich@example.org", "password": PASSWORD}
    )
    fake.calendar = {
        MONDAY + timedelta(days=1): [("r2", False)],
        MONDAY + timedelta(days=14): [("r9", False)],  # nach den 14 Tagen
    }

    page = ingress_client.post("/settings/cookidoo/check").text

    assert "Di 03.11." in page
    assert "Rezept r2" in page
    assert "Rezept r9" not in page
    assert fake.calendar[MONDAY + timedelta(days=1)] == [("r2", False)]  # nichts geändert


def test_check_with_empty_calendar_confirms_connection(
    ingress_client: TestClient, fake: type[FakeCookidoo]
) -> None:
    ingress_client.post(
        "/settings/cookidoo", data={"email": "ich@example.org", "password": PASSWORD}
    )

    page = ingress_client.post("/settings/cookidoo/check").text

    assert "Verbindung in Ordnung" in page


def test_check_shows_errors(ingress_client: TestClient, fake: type[FakeCookidoo]) -> None:
    ingress_client.post(
        "/settings/cookidoo", data={"email": "ich@example.org", "password": PASSWORD}
    )
    fake.fail_requests = True

    page = ingress_client.post("/settings/cookidoo/check").text

    assert "nicht erreichbar" in page


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(document.cookie)",
        "http://c/r5",  # ohne https
        "https://boese.example/r5",  # fremde Seite
        "",
    ],
)
def test_untrusted_links_are_rebuilt_from_the_id(
    account: CookidooAccount, fake: type[FakeCookidoo], url: str
) -> None:
    account.connect("ich@example.org", PASSWORD)
    fake.calendar = {MONDAY: [("r5", False)]}
    fake.details = {"r5": ("Linsen-Dal", url)}

    (recipe,) = account.read_calendar(MONDAY, MONDAY)

    assert recipe.url == "https://c/recipes/recipe/de-DE/r5"


def test_cookidoo_link_of_the_country_is_kept(
    account: CookidooAccount, fake: type[FakeCookidoo]
) -> None:
    account.connect("ich@example.org", PASSWORD)
    fake.calendar = {MONDAY: [("r5", False)]}
    fake.details = {"r5": ("Linsen-Dal", "https://c/recipes/recipe/de-DE/r5?x=1")}

    (recipe,) = account.read_calendar(MONDAY, MONDAY)

    assert recipe.url == "https://c/recipes/recipe/de-DE/r5?x=1"


@pytest.mark.parametrize("recipe_id", ["../etc", "r12a", "<script>", "R1", ""])
def test_unexpected_ids_are_skipped(
    account: CookidooAccount, fake: type[FakeCookidoo], recipe_id: str
) -> None:
    account.connect("ich@example.org", PASSWORD)
    fake.calendar = {MONDAY: [(recipe_id, False), ("r6", False)]}

    assert [r.recipe_id for r in account.read_calendar(MONDAY, MONDAY)] == ["r6"]


def test_names_are_trimmed_and_shortened(
    account: CookidooAccount, fake: type[FakeCookidoo]
) -> None:
    account.connect("ich@example.org", PASSWORD)
    fake.calendar = {MONDAY: [("r5", False), ("r6", False)]}
    fake.details = {"r5": ("  " + "x" * 400, ""), "r6": ("   ", "")}

    names = [r.name for r in account.read_calendar(MONDAY, MONDAY)]

    assert names == ["x" * 300, "r6"]


# --- Rezeptseiten ------------------------------------------------------------------------


class FakeResponse:
    """Antwort von `aiohttp`, so weit `recipe_page` sie nutzt."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.content = SimpleNamespace(read=self._read)
        self._body = body

    async def _read(self, limit: int) -> bytes:
        return self._body[:limit]

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeSession:
    """`aiohttp.ClientSession` ohne Netzwerk; merkt sich die Anfragen."""

    status = 200
    body = b"<html>Linsen-Dal</html>"
    requests: list[tuple[str, dict[str, Any]]] = []

    def __init__(self, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        FakeSession.requests.append((url, kwargs))
        return FakeResponse(self.status, self.body)


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch, fake: type[FakeCookidoo]) -> type[FakeSession]:
    FakeSession.status, FakeSession.requests = 200, []
    FakeSession.body = b"<html>Linsen-Dal</html>"
    monkeypatch.setattr(cookidoo_module, "ClientSession", FakeSession)
    return FakeSession


def test_recipe_page_is_built_from_the_id_without_redirects(
    account: CookidooAccount, web: type[FakeSession]
) -> None:
    assert account.recipe_page("r821223") == "<html>Linsen-Dal</html>"

    [(url, options)] = web.requests
    assert url == "https://c/recipes/recipe/de-DE/r821223"
    assert options["allow_redirects"] is False


@pytest.mark.parametrize("recipe_id", ["821223", "r1/../x", "https://evil", "r" + "1" * 20])
def test_recipe_page_rejects_other_ids(
    account: CookidooAccount, web: type[FakeSession], recipe_id: str
) -> None:
    with pytest.raises(CookidooError, match="keine Cookidoo-Rezept-ID"):
        account.recipe_page(recipe_id)
    assert web.requests == []


@pytest.mark.parametrize("status", [301, 404, 500])
def test_recipe_page_other_status_means_missing(
    account: CookidooAccount, web: type[FakeSession], status: int
) -> None:
    web.status = status

    with pytest.raises(RecipePageMissingError, match=str(status)):
        account.recipe_page("r1")


def test_recipe_page_size_is_limited(
    account: CookidooAccount, web: type[FakeSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cookidoo_module, "MAX_PAGE_BYTES", 10)
    web.body = b"x" * 11

    with pytest.raises(RecipePageMissingError, match="unerwartet groß"):
        account.recipe_page("r1")


def test_recipe_page_network_error_is_a_cookidoo_error(
    account: CookidooAccount, monkeypatch: pytest.MonkeyPatch, fake: type[FakeCookidoo]
) -> None:
    class Broken(FakeSession):
        def get(self, url: str, **kwargs: Any) -> FakeResponse:
            raise TimeoutError

    monkeypatch.setattr(cookidoo_module, "ClientSession", Broken)

    with pytest.raises(CookidooError, match="nicht erreichbar") as caught:
        account.recipe_page("r1")
    assert not isinstance(caught.value, RecipePageMissingError)


@pytest.mark.parametrize("value", ["r1", "r821223"])
def test_recipe_ids_are_accepted(value: str) -> None:
    assert is_recipe_id(value)


@pytest.mark.parametrize(
    "value", ["", "r", "r1\n", " r1", "R1", "r1/../x", "../r1", "r" + "1" * 13]
)
def test_other_values_are_no_recipe_ids(value: str) -> None:
    assert not is_recipe_id(value)


@pytest.mark.parametrize("bad", [["r1\n"], ["r1", "../planning"]])
def test_plan_rejects_invalid_ids_before_calling_cookidoo(
    account: CookidooAccount, fake: type[FakeCookidoo], bad: list[str]
) -> None:
    account.connect("ich@example.org", PASSWORD)

    with pytest.raises(CookidooError, match="keine Cookidoo-Rezept-ID"):
        account.plan(MONDAY, bad)
    with pytest.raises(CookidooError, match="keine Cookidoo-Rezept-ID"):
        account.unplan(MONDAY, bad[-1])

    assert fake.calendar == {}


def test_unexpected_day_in_calendar_is_an_error_not_an_empty_day(
    account: CookidooAccount, fake: type[FakeCookidoo]
) -> None:
    account.connect("ich@example.org", PASSWORD)
    fake.calendar = {MONDAY: [("r1", False)]}
    fake.day_id = "kein Datum"

    with pytest.raises(CookidooError, match="unerwartete Antwort"):
        account.read_calendar(MONDAY, MONDAY)


def test_failed_token_write_keeps_the_old_file(
    account: CookidooAccount, monkeypatch: pytest.MonkeyPatch
) -> None:
    account.connect("ich@example.org", PASSWORD)
    before = account.token_path.read_text(encoding="utf-8")

    def broken_replace(source: object, target: object) -> None:
        raise OSError("Datenträger voll")

    monkeypatch.setattr(files_module.os, "replace", broken_replace)

    renewed = CookidooAuthData(access_token="a9", refresh_token="r9", expires_at=9.0)
    with pytest.raises(OSError, match="Datenträger voll"):
        account._write("Fabi", renewed)

    assert account.token_path.read_text(encoding="utf-8") == before
    assert not account.token_path.with_name(f"{account.token_path.name}.tmp").exists()


def test_token_write_replaces_a_leftover_temporary_file(account: CookidooAccount) -> None:
    leftover = account.token_path.with_name(f"{account.token_path.name}.tmp")
    leftover.write_text("Rest", encoding="utf-8")

    account.connect("ich@example.org", PASSWORD)

    assert account.username() == "Fabi"
    assert not leftover.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Dateirechte nur unter POSIX")
def test_token_file_is_only_readable_by_the_owner(account: CookidooAccount) -> None:
    old_umask = os.umask(0)
    try:
        account.connect("ich@example.org", PASSWORD)
    finally:
        os.umask(old_umask)

    assert account.token_path.stat().st_mode & 0o777 == 0o600
