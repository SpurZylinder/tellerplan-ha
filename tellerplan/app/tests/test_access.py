import pytest
from fastapi.testclient import TestClient

from main import create_app
from settings import Settings

AUTH = {"Authorization": "Bearer test-token"}


def test_ingress_serves_pages_without_login(ingress_client: TestClient) -> None:
    response = ingress_client.get("/")

    assert response.status_code == 200
    assert "Frühstück" in response.text


def test_ingress_serves_api_without_token(ingress_client: TestClient) -> None:
    assert ingress_client.get("/api/v1/health").json() == {"status": "ok", "database": "ok"}


INGRESS = {"X-Ingress-Path": "/api/hassio_ingress/abc"}


def test_ingress_path_prefixes_static_urls(ingress_client: TestClient) -> None:
    response = ingress_client.get("/", headers=INGRESS)

    assert "/api/hassio_ingress/abc/static/tokens.css" in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/static/tokens.css",
        "/static/app.css",
        "/static/vendor/htmx.min.js",
        "/",
        "/plan",
        "/recipes",
        "/settings",
        "/foods/search?q=skyr",
        "/api/v1/health",
    ],
)
def test_ingress_serves_everything_behind_prefix(ingress_client: TestClient, path: str) -> None:
    # Home Assistant schickt den Pfad ohne Präfix und das Präfix im Header.
    assert ingress_client.get(path, headers=INGRESS).status_code == 200


def test_ingress_redirects_keep_prefix(ingress_client: TestClient) -> None:
    response = ingress_client.post(
        "/recipes/new",
        data={"title": "Chili", "servings": "2"},
        headers=INGRESS,
        follow_redirects=False,
    )

    assert response.headers["location"].startswith("/api/hassio_ingress/abc/recipes/")


def test_api_port_requires_token(api_client: TestClient) -> None:
    assert api_client.get("/api/v1/health").status_code == 401
    assert (
        api_client.get("/api/v1/health", headers={"Authorization": "Bearer falsch"}).status_code
        == 401
    )
    assert api_client.get("/api/v1/health", headers=AUTH).status_code == 200


def test_api_token_does_not_open_pages(api_client: TestClient) -> None:
    # Seiten auf dem API-Port sind die Vollbild-App: Anmeldung über Home Assistant, kein Token.
    response = api_client.get("/", headers=AUTH, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_api_port_locked_without_configured_token(settings: Settings) -> None:
    unconfigured = settings.model_copy(update={"api_token": ""})
    client = TestClient(create_app(unconfigured), base_url=f"http://testserver:{settings.api_port}")

    assert client.get("/api/v1/health", headers={"Authorization": "Bearer "}).status_code == 503
