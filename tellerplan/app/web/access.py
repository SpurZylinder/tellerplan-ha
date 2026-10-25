"""Zugang zur Oberfläche: Ingress ohne Login, Vollbild-App mit Anmeldung über Home Assistant.

Über Ingress meldet Home Assistant selbst an. Auf dem Port der Vollbild-App
(gleicher Port wie die API) braucht jede Seite eine Sitzung aus der Anmeldung
über Home Assistant; fehlt sie, geht es zur Anmeldeseite.
"""

import logging
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from db import get_session
from ha_auth import (
    ADDON_INTERNAL_URL,
    HomeAssistantUnavailable,
    LoginRejected,
    check_refresh_token,
)
from settings import Settings
from supervisor import supervisor_token
from web_sessions import WebSession, delete_session, find_session, mark_checked, needs_check

logger = logging.getLogger(__name__)

SESSION_COOKIE = "tellerplan_session"
# Standardport von Home Assistant, wenn `homeassistant_url` leer ist
HOMEASSISTANT_PORT = 8123


class LoginRequired(Exception):
    """Die Seite braucht eine Anmeldung über Home Assistant."""


def is_standalone(request: Request) -> bool:
    """True für Anfragen an die Vollbild-App, False für Ingress."""
    server = request.scope.get("server")
    settings: Settings = request.app.state.settings
    return server is not None and server[1] == settings.api_port


def client_id(request: Request) -> str:
    """Adresse der Vollbild-App, wie das iPhone sie aufruft, z. B. http://homeassistant.local:8099/."""
    return f"{request.url.scheme}://{request.url.netloc}/"


def browser_url(request: Request) -> str:
    """Home Assistant aus Sicht des iPhones; leer konfiguriert = gleicher Host, Port 8123."""
    configured = request.app.state.settings.homeassistant_url
    return configured or f"{request.url.scheme}://{request.url.hostname}:{HOMEASSISTANT_PORT}"


def server_url(request: Request) -> str:
    """Home Assistant aus Sicht von Tellerplan: im Add-on über das interne Netz."""
    return ADDON_INTERNAL_URL if supervisor_token() else browser_url(request)


def _still_valid(request: Request, session: Session, web_session: WebSession) -> bool:
    """Fragt bei Home Assistant nach; ist es nicht erreichbar, gilt die Sitzung weiter."""
    try:
        check_refresh_token(server_url(request), web_session.client_id, web_session.refresh_token)
    except LoginRejected:
        logger.info("Zugang in Home Assistant entzogen, Sitzung beendet")
        delete_session(session, web_session)
        session.commit()
        return False
    except HomeAssistantUnavailable:
        return True
    mark_checked(session, web_session)
    session.commit()
    return True


def require_login(request: Request, session: Annotated[Session, Depends(get_session)]) -> None:
    """Abhängigkeit für alle Seiten: auf dem Vollbild-Port nur mit gültiger Sitzung."""
    if not is_standalone(request):
        return
    web_session = find_session(session, request.cookies.get(SESSION_COOKIE))
    if web_session is None:
        raise LoginRequired
    if needs_check(web_session) and not _still_valid(request, session, web_session):
        raise LoginRequired
    request.state.web_session = web_session
