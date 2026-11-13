"""Benutzer und Rollen (0.6.0, B2b): wer hereindarf und was Verwalter und Benutzer dürfen."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import ha_users
from conftest import ADMIN_ID, MEMBER_ID, FakeDirectory
from ha_auth import HomeAssistantUnavailable
from ha_users import AccountDirectory, HaAccount
from main import create_app
from modules.users.models import AppUser
from security import INGRESS_PROXY_IP, _drop_remote_user_headers
from settings import Settings
from supervisor import TOKEN_ENV_VAR

# Seiten, die nur Verwalter erreichen; die Methode zählt (GET oder POST)
ADMIN_ONLY = [
    ("post", "/settings"),
    ("post", "/settings/users"),
    ("post", "/settings/cookidoo/disconnect"),
    ("get", "/settings/import"),
    ("post", "/settings/import/placeholders"),
    ("post", "/plan/shopping/check"),
    ("post", "/recipes/1/delete"),
    ("get", "/foods/1/delete"),
    ("post", "/bases/1/merge"),
]
# Seiten, die jeder freigegebene Benutzer erreicht
FOR_EVERYONE = ["/", "/plan", "/plan/shopping", "/recipes", "/foods", "/settings", "/matching"]


@pytest.fixture(autouse=True)
def in_addon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "supervisor-token")


def _client(
    settings: Settings, options_file: Path, user_id: str | None, raise_errors: bool = True
) -> TestClient:
    headers = {"x-remote-user-id": user_id, "x-remote-user-name": "x"} if user_id else {}
    return TestClient(
        create_app(settings, options_file),
        base_url=f"http://testserver:{settings.ingress_port}",
        client=(INGRESS_PROXY_IP, 50000),
        headers=headers,
        follow_redirects=False,
        raise_server_exceptions=raise_errors,
    )


@pytest.fixture
def member(migrated: Settings, options_file: Path) -> Iterator[TestClient]:
    client = _client(migrated, options_file, MEMBER_ID)
    yield client
    client.app.state.engine.dispose()


@pytest.fixture
def admin(migrated: Settings, options_file: Path) -> Iterator[TestClient]:
    # Verwalter-Seiten wie „Benutzer prüfen“ treffen die Netzsperre der Tests (Fehler 500);
    # hier zählt nur, dass sie nicht mit 403 abgewiesen werden
    client = _client(migrated, options_file, ADMIN_ID, raise_errors=False)
    yield client
    client.app.state.engine.dispose()


@pytest.mark.parametrize("path", FOR_EVERYONE)
def test_member_reaches_shared_pages(member: TestClient, path: str) -> None:
    assert member.get(path).status_code == 200


@pytest.mark.parametrize(("method", "path"), ADMIN_ONLY)
def test_member_is_refused_admin_pages(member: TestClient, method: str, path: str) -> None:
    response = getattr(member, method)(path)

    assert response.status_code == 403
    assert "nur Verwalter" in response.text
    assert 'class="tabbar"' not in response.text


@pytest.mark.parametrize(("method", "path"), ADMIN_ONLY)
def test_admin_is_not_refused(admin: TestClient, method: str, path: str) -> None:
    assert getattr(admin, method)(path).status_code != 403


def test_member_sees_no_admin_controls(member: TestClient) -> None:
    settings = member.get("/settings").text

    assert "settings_save" not in settings and 'action="/settings"' not in settings
    assert "Tagesziele legen bisher die Verwalter" in settings
    assert "Cookidoo" not in settings
    assert "Benutzer prüfen" not in settings
    assert "Importieren" not in settings
    assert "Angemeldet als Fabian · Benutzer" in settings


def test_admin_sees_admin_controls(admin: TestClient) -> None:
    settings = admin.get("/settings").text

    assert 'action="/settings"' in settings
    assert "Benutzer prüfen" in settings
    assert "Importieren" in settings
    assert "Angemeldet als SpurZylinder · Verwalter" in settings


@pytest.mark.parametrize(
    ("user_id", "reason"),
    [
        (None, "nicht mitgeschickt"),
        ("unbekannt", "nicht (mehr) aktiv"),
        ("sys", "nicht (mehr) aktiv"),  # Systemkonto
        ("gone", "nicht (mehr) aktiv"),  # deaktiviert
    ],
)
def test_who_may_not_enter(
    migrated: Settings, options_file: Path, user_id: str | None, reason: str
) -> None:
    client = _client(migrated, options_file, user_id)

    response = client.get("/plan")

    assert response.status_code == 403
    assert reason in response.text


def test_allowed_users_limit_access(migrated: Settings, options_file: Path) -> None:
    settings = migrated.model_copy(update={"allowed_users": ["SpurZylinder"]})

    assert _client(settings, options_file, ADMIN_ID).get("/plan").status_code == 200
    refused = _client(settings, options_file, MEMBER_ID).get("/plan")
    assert refused.status_code == 403
    assert "nicht freigegeben" in refused.text


def test_unreachable_home_assistant_means_no_access(
    accounts: FakeDirectory, member: TestClient
) -> None:
    accounts.unavailable = True

    response = member.get("/plan")

    assert response.status_code == 403
    assert "nicht erreichbar" in response.text


def test_htmx_request_without_access_gets_only_the_status(member: TestClient) -> None:
    response = member.post("/settings", headers={"HX-Request": "true"})

    assert response.status_code == 403
    assert "<html" not in response.text


def test_users_are_remembered(admin: TestClient, member: TestClient, session: Session) -> None:
    admin.get("/")
    member.get("/")

    names = {user.id: user.name for user in session.scalars(select(AppUser))}
    assert names == {ADMIN_ID: "SpurZylinder", MEMBER_ID: "Fabian"}


def test_local_without_supervisor_is_admin(
    monkeypatch: pytest.MonkeyPatch, migrated: Settings, options_file: Path
) -> None:
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)

    response = _client(migrated, options_file, None).get("/settings")

    assert "Angemeldet als Lokal · Verwalter" in response.text


def test_remote_user_headers_are_dropped_on_the_app_port() -> None:
    scope = {
        "headers": [
            (b"x-remote-user-id", b"admin-id"),
            (b"X-Remote-User-Name", b"spurzylinder"),
            (b"host", b"homeassistant.local:8099"),
        ]
    }

    _drop_remote_user_headers(scope)

    assert scope["headers"] == [(b"host", b"homeassistant.local:8099")]


def test_account_directory_caches_and_survives_short_outages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    state = {"down": False}
    account = HaAccount("a1", "fabi", "Fabi", True, True, False)

    def fake_list(token: str) -> list[HaAccount]:
        calls.append(token)
        if state["down"]:
            raise HomeAssistantUnavailable("weg")
        return [account]

    monkeypatch.setattr(ha_users, "list_accounts", fake_list)
    directory = AccountDirectory(ttl=0, stale_ttl=3600)

    assert directory.find("t", "a1") == account
    state["down"] = True
    assert directory.find("t", "a1") == account  # alter Stand hilft über den Ausfall
    assert directory.find("t", "fremd") is None
    assert len(calls) == 3

    expired = AccountDirectory(ttl=0, stale_ttl=0)
    with pytest.raises(HomeAssistantUnavailable):
        expired.find("t", "a1")


def test_accounts_from_recorded_user_list() -> None:
    # Aufbau wie die Antwort von config/auth/list auf dem Pi (2026-11-13)
    raw = [
        {
            "id": "s",
            "username": None,
            "name": "Supervisor",
            "is_active": True,
            "system_generated": True,
            "group_ids": ["system-admin"],
        },
        {
            "id": "f",
            "username": "fabian",
            "name": "Fabian",
            "is_active": True,
            "system_generated": False,
            "group_ids": ["system-users"],
        },
    ]

    supervisor, fabian = (ha_users._account(user) for user in raw)

    assert supervisor.system_generated and supervisor.is_admin
    assert fabian == HaAccount("f", "fabian", "Fabian", False, True, False)
