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


def test_ingress_path_prefixes_static_urls(ingress_client: TestClient) -> None:
    response = ingress_client.get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"})

    assert "/api/hassio_ingress/abc/static/tokens.css" in response.text


def test_api_port_requires_token(api_client: TestClient) -> None:
    assert api_client.get("/api/v1/health").status_code == 401
    assert (
        api_client.get("/api/v1/health", headers={"Authorization": "Bearer falsch"}).status_code
        == 401
    )
    assert api_client.get("/api/v1/health", headers=AUTH).status_code == 200


def test_api_port_hides_pages(api_client: TestClient) -> None:
    assert api_client.get("/", headers=AUTH).status_code == 404


def test_api_port_locked_without_configured_token(settings: Settings) -> None:
    unconfigured = settings.model_copy(update={"api_token": ""})
    client = TestClient(create_app(unconfigured), base_url=f"http://testserver:{settings.api_port}")

    assert client.get("/api/v1/health", headers={"Authorization": "Bearer "}).status_code == 503
