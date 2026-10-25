"""Anmeldung über Home Assistant (OAuth 2 mit PKCE) für die Vollbild-App.

Tellerplan sieht nie ein Passwort: Home Assistant meldet an und gibt einen
`refresh_token` heraus. Mit ihm prüft Tellerplan später, ob der Zugang noch gilt;
wird er in Home Assistant entzogen, endet auch die Tellerplan-Sitzung.
Ablauf: https://contributors.home-assistant.io/core/internals/auth-api/
"""

import base64
import hashlib
import json
import logging
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# So erreicht ein Add-on Home Assistant Core im internen Netz.
ADDON_INTERNAL_URL = "http://homeassistant:8123"
TIMEOUT_SECONDS = 10
# Home Assistant antwortet mit 400, wenn ein Code oder Refresh-Token nicht (mehr) gilt.
INVALID_GRANT_STATUS = 400


class HomeAssistantUnavailable(RuntimeError):
    """Home Assistant war nicht erreichbar; über den Zugang lässt sich nichts sagen."""


class LoginRejected(RuntimeError):
    """Home Assistant hat Code oder Refresh-Token abgelehnt."""


def new_state() -> str:
    """Zufallswert gegen untergeschobene Rückleitungen."""
    return secrets.token_urlsafe(32)


def new_pkce() -> tuple[str, str]:
    """PKCE-Paar (verifier, challenge) nach S256."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(
    browser_url: str, client_id: str, redirect_uri: str, state: str, challenge: str
) -> str:
    """Adresse der Anmeldeseite von Home Assistant."""
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{browser_url}/auth/authorize?{query}"


def exchange_code(server_url: str, client_id: str, code: str, verifier: str) -> str:
    """Löst den Code aus der Rückleitung ein und gibt den Refresh-Token zurück."""
    body = _post_token(
        server_url,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    refresh_token = body.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise LoginRejected("Home Assistant hat keinen Refresh-Token geliefert.")
    return refresh_token


def check_refresh_token(server_url: str, client_id: str, refresh_token: str) -> None:
    """Prüft, ob der Zugang noch gilt; wirft LoginRejected, wenn nicht."""
    _post_token(
        server_url,
        {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id},
    )


def revoke(server_url: str, refresh_token: str) -> None:
    """Entzieht den Zugang in Home Assistant (Abmelden); Fehler werden nur protokolliert."""
    try:
        _post(f"{server_url}/auth/revoke", {"token": refresh_token})
    except (HomeAssistantUnavailable, LoginRejected) as error:
        logger.warning("Abmelden bei Home Assistant fehlgeschlagen: %s", error)


def _post_token(server_url: str, form: dict[str, str]) -> dict[str, object]:
    return _post(f"{server_url}/auth/token", form)


def _post(url: str, form: dict[str, str]) -> dict[str, object]:
    request = Request(
        url,
        data=urlencode(form).encode(),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read()
    except HTTPError as error:
        if error.code == INVALID_GRANT_STATUS:
            raise LoginRejected("Home Assistant hat die Anmeldung abgelehnt.") from error
        logger.warning("Home Assistant antwortet auf %s mit %s", url, error.code)
        raise HomeAssistantUnavailable(f"Home Assistant antwortet mit {error.code}") from error
    except (URLError, TimeoutError) as error:
        logger.warning("Home Assistant nicht erreichbar unter %s: %s", url, error)
        raise HomeAssistantUnavailable("Home Assistant ist nicht erreichbar.") from error
    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        body = {}
    return body if isinstance(body, dict) else {}
