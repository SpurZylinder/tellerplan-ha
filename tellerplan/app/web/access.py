"""Zugang zur Oberfläche: wer angemeldet ist und was er darf.

Über Ingress meldet Home Assistant selbst an und schickt den Benutzer in Kopfzeilen
mit (`X-Remote-User-*`; glaubwürdig, weil der Ingress-Port im Add-on nur den Proxy
hereinlässt). Auf dem Port der Vollbild-App (gleicher Port wie die API) braucht jede
Seite eine Sitzung aus der Anmeldung über Home Assistant; fehlt sie, geht es zur
Anmeldeseite. Die Sitzung weiß, wer angemeldet ist.

Ob jemand hereindarf und ob er Verwalter ist, entscheidet Home Assistant: aktive,
echte Benutzer (keine Systemkonten), wahlweise nur die in `allowed_users`; Verwalter
sind die Admins von Home Assistant. Im Add-on kommt das aus der Benutzerliste
(`ha_users.directory`), lokal ohne Supervisor gilt ein lokaler Verwalter.
"""

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

import clock
from db import get_session
from ha_auth import (
    ADDON_INTERNAL_URL,
    HomeAssistantUnavailable,
    LoginRejected,
)
from ha_users import HaAccount, directory, session_user
from modules.users.service import touch_user
from settings import Settings
from supervisor import supervisor_token
from web_sessions import WebSession, delete_session, find_session, mark_checked, needs_check

logger = logging.getLogger(__name__)

SESSION_COOKIE = "tellerplan_session"
# Standardport von Home Assistant, wenn `homeassistant_url` leer ist
HOMEASSISTANT_PORT = 8123


# Kopfzeilen, mit denen Home Assistant über Ingress den Benutzer nennt
USER_ID_HEADER = "x-remote-user-id"
USER_NAME_HEADER = "x-remote-user-name"
USER_DISPLAY_NAME_HEADER = "x-remote-user-display-name"


class LoginRequired(Exception):
    """Die Seite braucht eine Anmeldung über Home Assistant."""


class NoAccess(Exception):
    """Der Benutzer darf Tellerplan bzw. diese Seite nicht nutzen; die Meldung sagt, warum."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CurrentUser:
    """Wer die Anfrage stellt. Verwalter = Admin in Home Assistant."""

    id: str
    name: str
    is_admin: bool


# Lokal ohne Supervisor (Entwicklung): ein Verwalter, damit alles erreichbar ist
LOCAL_USER = CurrentUser("local", "Lokal", is_admin=True)


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
    """Fragt bei Home Assistant nach; ist es nicht erreichbar, gilt die Sitzung weiter.

    Name und Admin-Recht der Sitzung werden dabei aktualisiert (lokal ohne Supervisor
    sind sie die einzige Quelle für die Rolle).
    """
    try:
        user = session_user(server_url(request), web_session.client_id, web_session.refresh_token)
    except LoginRejected:
        logger.info("Zugang in Home Assistant entzogen, Sitzung beendet")
        delete_session(session, web_session)
        session.commit()
        return False
    except HomeAssistantUnavailable:
        return True
    if user.id != web_session.user_id:
        logger.warning("Vollbild-App: Sitzung gehört einem anderen Benutzer, beendet")
        delete_session(session, web_session)
        session.commit()
        return False
    web_session.user_name = user.name
    web_session.is_admin = user.is_admin
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
    if web_session.user_id is None:
        # Sitzung von vor 0.5.11: ohne Benutzer, also neu anmelden
        delete_session(session, web_session)
        session.commit()
        raise LoginRequired
    request.state.web_session = web_session


def require_user(request: Request, session: Annotated[Session, Depends(get_session)]) -> None:
    """Abhängigkeit für alle Seiten: ermittelt den Benutzer und prüft, ob er hereindarf.

    Setzt `request.state.user`; wirft `NoAccess`, wenn nicht.
    """
    user = _identify(request)
    token = supervisor_token()
    if token is not None:
        user = _checked_with_home_assistant(request, token, user)
    touch_user(session, user.id, user.name, clock.now())
    session.commit()
    request.state.user = user


def require_admin(request: Request) -> None:
    """Abhängigkeit für Seiten nur für Verwalter (Admins in Home Assistant)."""
    user: CurrentUser | None = getattr(request.state, "user", None)
    if user is None or not user.is_admin:
        raise NoAccess("Das dürfen nur Verwalter (Admins in Home Assistant).")


def current_user(request: Request) -> CurrentUser:
    """Der Benutzer dieser Anfrage; nur nach `require_user` aufrufen."""
    user: CurrentUser = request.state.user
    return user


def _identify(request: Request) -> CurrentUser:
    """Wer fragt: aus der Sitzung (Vollbild-App) oder den Kopfzeilen (Ingress)."""
    if is_standalone(request):
        web_session: WebSession = request.state.web_session
        return CurrentUser(str(web_session.user_id), web_session.user_name, web_session.is_admin)
    if supervisor_token() is None:
        return LOCAL_USER
    user_id = request.headers.get(USER_ID_HEADER)
    if not user_id:
        raise NoAccess("Home Assistant hat nicht mitgeschickt, wer angemeldet ist.")
    name = request.headers.get(USER_DISPLAY_NAME_HEADER) or request.headers.get(
        USER_NAME_HEADER, ""
    )
    return CurrentUser(user_id, name, is_admin=False)


def _checked_with_home_assistant(request: Request, token: str, user: CurrentUser) -> CurrentUser:
    """Rolle und Freigabe aus der Benutzerliste von Home Assistant."""
    try:
        account = directory.find(token, user.id)
    except HomeAssistantUnavailable as error:
        logger.warning("Benutzerliste nicht verfügbar: %s", error)
        raise NoAccess("Home Assistant ist gerade nicht erreichbar.") from error
    if account is None or account.system_generated or not account.is_active:
        raise NoAccess("Dieses Konto ist in Home Assistant nicht (mehr) aktiv.")
    if not _allowed(request.app.state.settings.allowed_users, account):
        raise NoAccess("Dieses Konto ist für Tellerplan nicht freigegeben.")
    return CurrentUser(account.id, account.name or user.name, account.is_admin)


def _allowed(allowed_users: list[str], account: HaAccount) -> bool:
    """Leer = alle; sonst nur die genannten Benutzernamen (ohne Groß/klein)."""
    if not allowed_users:
        return True
    names = {name.strip().casefold() for name in allowed_users if name.strip()}
    return account.username.casefold() in names
