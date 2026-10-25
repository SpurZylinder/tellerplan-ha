"""Anmelden und Abmelden der Vollbild-App über Home Assistant.

Diese Seiten brauchen selbst keine Sitzung. Über Ingress gibt es nichts zu tun,
dort meldet Home Assistant an; die Seiten leiten dann nur weiter.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from db import get_session
from ha_auth import (
    HomeAssistantUnavailable,
    LoginRejected,
    authorize_url,
    exchange_code,
    new_pkce,
    new_state,
    revoke,
)
from web.access import SESSION_COOKIE, browser_url, client_id, is_standalone, server_url
from web.forms import redirect_to
from web.templating import path_for, render
from web_sessions import create_session, delete_session, find_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth")
SessionDep = Annotated[Session, Depends(get_session)]

LOGIN_COOKIE = "tellerplan_login"
LOGIN_COOKIE_MAX_AGE = 10 * 60
# Die Sitzung prüft Tellerplan selbst bei Home Assistant; das Cookie darf lange leben.
SESSION_COOKIE_MAX_AGE = 400 * 24 * 60 * 60


def _redirect_uri(request: Request) -> str:
    return f"{client_id(request)}auth/callback"


def _message(request: Request, title: str, text: str, status_code: int = 200) -> HTMLResponse:
    response = render(request, "auth/message.html", title=title, text=text)
    response.status_code = status_code
    return response


@router.get("/login", response_model=None)
def login_start(request: Request) -> Response:
    """Leitet zur Anmeldeseite von Home Assistant weiter."""
    if not is_standalone(request):
        return redirect_to(request, "today_page")
    state = new_state()
    verifier, challenge = new_pkce()
    target = authorize_url(
        browser_url(request), client_id(request), _redirect_uri(request), state, challenge
    )
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        LOGIN_COOKIE,
        f"{state}.{verifier}",
        max_age=LOGIN_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path=path_for(request, "login_callback"),
    )
    return response


@router.get("/callback", response_model=None)
def login_callback(
    request: Request, session: SessionDep, code: str = "", state: str = ""
) -> Response:
    """Rückleitung von Home Assistant: Code einlösen, Sitzung anlegen."""
    if not is_standalone(request):
        return redirect_to(request, "today_page")
    expected_state, _, verifier = request.cookies.get(LOGIN_COOKIE, "").partition(".")
    if not code or not expected_state or state != expected_state:
        return _message(
            request,
            "Anmeldung abgelaufen",
            "Die Anmeldung passt nicht zu diesem Gerät oder hat zu lange gedauert.",
            status_code=400,
        )
    try:
        refresh_token = exchange_code(server_url(request), client_id(request), code, verifier)
    except (LoginRejected, HomeAssistantUnavailable) as error:
        logger.warning("Anmeldung über Home Assistant fehlgeschlagen: %s", error)
        return _message(request, "Anmeldung fehlgeschlagen", str(error), status_code=502)

    token = create_session(session, refresh_token, client_id(request))
    session.commit()
    logger.info("Vollbild-App angemeldet über %s", client_id(request))
    response = redirect_to(request, "today_page")
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    response.delete_cookie(LOGIN_COOKIE, path=path_for(request, "login_callback"))
    return response


@router.post("/logout", response_model=None)
def logout(request: Request, session: SessionDep) -> Response:
    """Beendet die Sitzung und entzieht den Zugang auch in Home Assistant."""
    web_session = find_session(session, request.cookies.get(SESSION_COOKIE))
    if web_session is not None:
        revoke(server_url(request), web_session.refresh_token)
        delete_session(session, web_session)
        session.commit()
    response = _message(
        request, "Abgemeldet", "Tellerplan ist auf diesem Gerät abgemeldet.", status_code=200
    )
    response.delete_cookie(SESSION_COOKIE)
    return response
