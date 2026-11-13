"""Zugriff auf die Supervisor-API von Home Assistant.

Im Add-on gibt der Supervisor beim Start einen Schlüssel in `SUPERVISOR_TOKEN` mit;
welche Zugänge er öffnet, steht in `config.yaml` (`hassio_api`, `homeassistant_api`).
Lokal fehlt der Schlüssel, dann gibt es keine Supervisor-Aufrufe.
"""

import json
import logging
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

SUPERVISOR_URL = "http://supervisor"
TOKEN_ENV_VAR = "SUPERVISOR_TOKEN"
TIMEOUT_SECONDS = 10

logger = logging.getLogger(__name__)


class SupervisorError(RuntimeError):
    """Der Supervisor hat eine Anfrage abgelehnt oder war nicht erreichbar."""


def supervisor_token() -> str | None:
    """Schlüssel für die Supervisor-API; None außerhalb des Add-ons."""
    return os.environ.get(TOKEN_ENV_VAR) or None


def get_own_options(token: str) -> dict[str, Any]:
    """Aktuelle Optionen dieses Add-ons, wie sie Home Assistant im Reiter „Konfiguration“ zeigt.

    Sie können neuer sein als `options.json`: Eine Änderung in Home Assistant landet erst
    beim nächsten Start in der Datei.
    """
    body = _request("GET", "/addons/self/info", None, token)
    data = body.get("data") if isinstance(body, dict) else None
    options = data.get("options") if isinstance(data, dict) else None
    if not isinstance(options, dict):
        raise SupervisorError("Supervisor liefert keine Optionen")
    return options


def set_own_options(options: dict[str, Any], token: str) -> None:
    """Speichert die Optionen dieses Add-ons, wie „Speichern“ im Reiter „Konfiguration“."""
    _post("/addons/self/options", {"options": options}, token)


def call_service(
    domain: str,
    service: str,
    data: dict[str, Any],
    token: str,
    timeout: float = TIMEOUT_SECONDS,
) -> None:
    """Führt eine Home-Assistant-Aktion aus, z. B. `todo.add_item` (braucht `homeassistant_api`)."""
    _post(f"/core/api/services/{domain}/{service}", data, token, timeout)


def get_core_state(entity_id: str, token: str, timeout: float = TIMEOUT_SECONDS) -> dict[str, Any]:
    """Zustand einer Entität in Home Assistant, z. B. `todo.furth` (braucht `homeassistant_api`)."""
    body = _request("GET", f"/core/api/states/{quote(entity_id)}", None, token, timeout)
    if not isinstance(body, dict):
        raise SupervisorError("Home Assistant liefert keinen Zustand")
    return body


def get_auth_users(token: str, timeout: float = TIMEOUT_SECONDS) -> list[dict[str, Any]]:
    """Benutzer von Home Assistant laut Supervisor (`GET /auth/list`); Erkundung für 0.6.0."""
    body = _request("GET", "/auth/list", None, token, timeout)
    data = body.get("data") if isinstance(body, dict) else None
    users = data.get("users") if isinstance(data, dict) else None
    if not isinstance(users, list):
        raise SupervisorError("Supervisor liefert keine Benutzerliste")
    return [user for user in users if isinstance(user, dict)]


def call_service_with_response(
    domain: str,
    service: str,
    data: dict[str, Any],
    token: str,
    timeout: float = TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Aktion mit Antwort, z. B. `todo.get_items`; liefert `service_response`."""
    path = f"/core/api/services/{domain}/{service}?return_response"
    body = _request("POST", path, data, token, timeout)
    response = body.get("service_response") if isinstance(body, dict) else None
    if not isinstance(response, dict):
        raise SupervisorError("Home Assistant liefert keine Antwort der Aktion")
    return response


def _post(path: str, payload: dict[str, Any], token: str, timeout: float = TIMEOUT_SECONDS) -> None:
    body = _request("POST", path, payload, token, timeout)
    if isinstance(body, dict) and body.get("result") == "error":
        message = body.get("message") or "Supervisor meldet einen Fehler"
        logger.warning("Supervisor meldet Fehler für %s: %s", path, message)
        raise SupervisorError(str(message))


def _request(
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    token: str,
    timeout: float = TIMEOUT_SECONDS,
) -> Any:
    """Anfrage an den Supervisor; liefert die Antwort als JSON (leer → None)."""
    request = Request(
        f"{SUPERVISOR_URL}{path}",
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as error:
        message = _error_message(error)
        logger.warning("Supervisor lehnt %s ab (%s): %s", path, error.code, message)
        raise SupervisorError(message) from error
    except URLError as error:
        logger.warning("Supervisor nicht erreichbar für %s: %s", path, error.reason)
        raise SupervisorError(f"Supervisor nicht erreichbar: {error.reason}") from error
    try:
        return json.loads(raw) if raw else None
    except ValueError as error:
        raise SupervisorError("Supervisor liefert keine lesbare Antwort") from error


def _error_message(error: HTTPError) -> str:
    """Meldung aus der Supervisor-Antwort, z. B. bei Werten außerhalb des Schemas."""
    try:
        body = json.loads(error.read())
    except OSError, ValueError:
        body = {}
    message = body.get("message") if isinstance(body, dict) else None
    return message or f"Supervisor antwortet mit Status {error.code}"
