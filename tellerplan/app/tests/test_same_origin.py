"""Schreibende Anfragen nur von der eigenen Seite (Befund C-H, Schutz vor CSRF)."""

import pytest
from fastapi.testclient import TestClient

from supervisor import TOKEN_ENV_VAR

# Eine harmlose schreibende Anfrage: ohne Supervisor leitet sie nur auf die Einkaufsliste
WRITE_PATH = "/plan/shopping"


@pytest.fixture(autouse=True)
def no_supervisor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)


def _post(client: TestClient, **headers: str) -> int:
    return client.post(WRITE_PATH, headers=headers, follow_redirects=False).status_code


def test_own_origin_is_allowed(ingress_client: TestClient) -> None:
    assert _post(ingress_client, origin="http://testserver:8000") == 303


def test_ingress_origin_of_home_assistant_is_allowed(ingress_client: TestClient) -> None:
    # Über Ingress ruft der Browser Home Assistant auf; der Proxy nennt den Host
    headers = {
        "origin": "http://homeassistant.local:8123",
        "x-forwarded-host": "homeassistant.local:8123",
    }

    assert _post(ingress_client, **headers) == 303


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": "https://boese.example"},
        {"referer": "https://boese.example/seite"},
        {"origin": "null"},
        {"origin": "http://homeassistant.local:8123"},  # ohne passenden X-Forwarded-Host
    ],
)
def test_foreign_origin_is_rejected(
    ingress_client: TestClient, headers: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    response = ingress_client.post(WRITE_PATH, headers=headers, follow_redirects=False)

    assert response.status_code == 403
    assert "fremden Seite" in response.text


def test_rejection_is_logged_with_expected_host(
    ingress_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING"):
        _post(ingress_client, origin="https://boese.example")

    assert "von boese.example, erwartet testserver:8000" in caplog.text


def test_requests_without_origin_are_allowed(ingress_client: TestClient) -> None:
    # Kein Browser (z. B. ein Skript): nichts zu prüfen
    assert _post(ingress_client) == 303


def test_reading_is_not_checked(ingress_client: TestClient) -> None:
    response = ingress_client.get(WRITE_PATH, headers={"origin": "https://boese.example"})

    assert response.status_code == 200


def test_api_is_not_checked(api_client: TestClient) -> None:
    # Die API nutzt einen Token im Kopf, keine Cookies
    response = api_client.post(
        "/api/v1/recipes",
        headers={"origin": "https://boese.example", "authorization": "Bearer test-token"},
    )

    assert response.status_code != 403
