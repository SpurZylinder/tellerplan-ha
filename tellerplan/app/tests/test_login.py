"""Vollbild-App: Anmeldung über Home Assistant, Sitzungen, Schutz der Ports."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import web.access as access
import web.pages.login as login
from ha_auth import ADDON_INTERNAL_URL, HomeAssistantUnavailable, LoginRejected
from main import create_app
from settings import Settings
from supervisor import TOKEN_ENV_VAR
from web_sessions import CHECK_INTERVAL, WebSession

APP_URL = "http://homeassistant.local:8099"
Exchanges = list[tuple[str, str, str, str]]


@pytest.fixture
def standalone(migrated: Settings) -> TestClient:
    """Wie das iPhone: Vollbild-App direkt auf dem Port 8099."""
    return TestClient(create_app(migrated), base_url=APP_URL, follow_redirects=False)


@pytest.fixture
def exchanged(monkeypatch: pytest.MonkeyPatch) -> Exchanges:
    calls: Exchanges = []

    def fake_exchange(server_url: str, client_id: str, code: str, verifier: str) -> str:
        calls.append((server_url, client_id, code, verifier))
        return "refresh-1"

    monkeypatch.setattr(login, "exchange_code", fake_exchange)
    return calls


def _sign_in(client: TestClient) -> None:
    start = client.get("/auth/login")
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    callback = client.get(f"/auth/callback?code=abc&state={state}")
    assert callback.status_code == 303


def _age_sessions(session: Session) -> None:
    for web_session in session.scalars(select(WebSession)):
        web_session.checked_at -= CHECK_INTERVAL + timedelta(minutes=1)
    session.commit()


def test_pages_need_login(standalone: TestClient) -> None:
    response = standalone.get("/")

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_htmx_requests_reload_to_login(standalone: TestClient) -> None:
    response = standalone.get("/foods/search?q=skyr", headers={"HX-Request": "true"})

    assert response.status_code == 401
    assert response.headers["HX-Redirect"] == "/auth/login"


def test_static_files_and_manifest_need_no_login(standalone: TestClient) -> None:
    assert standalone.get("/static/app.css").status_code == 200
    assert standalone.get("/static/manifest.webmanifest").status_code == 200
    assert standalone.get("/static/icon-180.png").status_code == 200


def test_login_redirects_to_home_assistant(standalone: TestClient) -> None:
    response = standalone.get("/auth/login")

    target = urlsplit(response.headers["location"])
    query = parse_qs(target.query)
    assert f"{target.scheme}://{target.netloc}{target.path}" == (
        "http://homeassistant.local:8123/auth/authorize"
    )
    assert query["client_id"] == [f"{APP_URL}/"]
    assert query["redirect_uri"] == [f"{APP_URL}/auth/callback"]
    assert query["code_challenge_method"] == ["S256"]
    assert "tellerplan_login" in response.headers["set-cookie"]


def test_configured_home_assistant_url_is_used(migrated: Settings) -> None:
    settings = migrated.model_copy(update={"homeassistant_url": "http://192.168.178.20:8123"})
    client = TestClient(create_app(settings), base_url=APP_URL, follow_redirects=False)

    location = client.get("/auth/login").headers["location"]

    assert location.startswith("http://192.168.178.20:8123/auth/authorize?")


@pytest.mark.usefixtures("exchanged")
def test_callback_with_foreign_state_is_rejected(standalone: TestClient) -> None:
    standalone.get("/auth/login")

    response = standalone.get("/auth/callback?code=abc&state=fremd")

    assert response.status_code == 400
    assert "Anmeldung abgelaufen" in response.text


def test_login_flow_opens_the_app(standalone: TestClient, exchanged: Exchanges) -> None:
    _sign_in(standalone)

    server_url, client_id, code, verifier = exchanged[0]
    assert server_url == "http://homeassistant.local:8123"
    assert (client_id, code) == (f"{APP_URL}/", "abc")
    assert len(verifier) > 40
    assert standalone.get("/").status_code == 200
    assert "Abmelden" in standalone.get("/settings").text


def test_addon_exchanges_code_over_internal_network(
    monkeypatch: pytest.MonkeyPatch, standalone: TestClient, exchanged: Exchanges
) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "supervisor-token")

    _sign_in(standalone)

    assert exchanged[0][0] == ADDON_INTERNAL_URL


@pytest.mark.usefixtures("exchanged")
def test_revoked_access_ends_the_session(
    monkeypatch: pytest.MonkeyPatch, standalone: TestClient, session: Session
) -> None:
    def rejected(*args: str) -> None:
        raise LoginRejected("entzogen")

    _sign_in(standalone)
    _age_sessions(session)
    monkeypatch.setattr(access, "check_refresh_token", rejected)

    assert standalone.get("/").status_code == 303
    session.expire_all()
    assert session.scalars(select(WebSession)).all() == []


@pytest.mark.usefixtures("exchanged")
def test_unreachable_home_assistant_keeps_the_session(
    monkeypatch: pytest.MonkeyPatch, standalone: TestClient, session: Session
) -> None:
    def unreachable(*args: str) -> None:
        raise HomeAssistantUnavailable("weg")

    _sign_in(standalone)
    _age_sessions(session)
    monkeypatch.setattr(access, "check_refresh_token", unreachable)

    assert standalone.get("/").status_code == 200


@pytest.mark.usefixtures("exchanged")
def test_logout_revokes_access(monkeypatch: pytest.MonkeyPatch, standalone: TestClient) -> None:
    revoked: list[str] = []
    monkeypatch.setattr(login, "revoke", lambda server_url, token: revoked.append(token))
    _sign_in(standalone)

    response = standalone.post("/auth/logout")

    assert "Abgemeldet" in response.text
    assert revoked == ["refresh-1"]
    assert standalone.get("/").status_code == 303


def test_api_on_standalone_port_still_needs_token(standalone: TestClient) -> None:
    assert standalone.get("/api/v1/health").status_code == 401


def test_ingress_needs_no_login(ingress_client: TestClient) -> None:
    assert ingress_client.get("/").status_code == 200
    login_page = ingress_client.get("/auth/login", follow_redirects=False)
    assert login_page.headers["location"] == "/"


def test_addon_ingress_port_only_accepts_home_assistant(
    monkeypatch: pytest.MonkeyPatch, migrated: Settings, ingress_client: TestClient
) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "supervisor-token")
    other_addon = TestClient(
        create_app(migrated),
        base_url=f"http://testserver:{migrated.ingress_port}",
        client=("172.30.33.5", 40000),
    )

    assert other_addon.get("/").status_code == 403
    assert ingress_client.get("/").status_code == 200


def test_local_ingress_port_is_open_without_supervisor(
    monkeypatch: pytest.MonkeyPatch, migrated: Settings
) -> None:
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    local = TestClient(create_app(migrated), base_url=f"http://localhost:{migrated.ingress_port}")

    assert local.get("/").status_code == 200
