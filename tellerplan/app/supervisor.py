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


def set_own_options(options: dict[str, Any], token: str) -> None:
    """Speichert die Optionen dieses Add-ons, wie „Speichern“ im Reiter „Konfiguration“."""
    _post("/addons/self/options", {"options": options}, token)


def call_service(domain: str, service: str, data: dict[str, Any], token: str) -> None:
    """Führt eine Home-Assistant-Aktion aus, z. B. `todo.add_item` (braucht `homeassistant_api`)."""
    _post(f"/core/api/services/{domain}/{service}", data, token)


def _post(path: str, payload: dict[str, Any], token: str) -> None:
    request = Request(
        f"{SUPERVISOR_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS):
            return
    except HTTPError as error:
        message = _error_message(error)
        logger.warning("Supervisor lehnt %s ab (%s): %s", path, error.code, message)
        raise SupervisorError(message) from error
    except URLError as error:
        logger.warning("Supervisor nicht erreichbar für %s: %s", path, error.reason)
        raise SupervisorError(f"Supervisor nicht erreichbar: {error.reason}") from error


def _error_message(error: HTTPError) -> str:
    """Meldung aus der Supervisor-Antwort, z. B. bei Werten außerhalb des Schemas."""
    try:
        body = json.loads(error.read())
    except OSError, ValueError:
        body = {}
    message = body.get("message") if isinstance(body, dict) else None
    return message or f"Supervisor antwortet mit Status {error.code}"
