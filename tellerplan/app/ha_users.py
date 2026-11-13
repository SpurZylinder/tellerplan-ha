"""Benutzer von Home Assistant erkennen – Erkundung für 0.6.0 (B1), nur lesend.

Vier Wege werden auf dem Pi ausprobiert, bevor Benutzer und Rollen gebaut werden:

1. Kopfzeilen über Ingress (`X-Remote-User-*`): wer gerade die Seite öffnet.
2. Benutzerliste der Supervisor-API (`GET /auth/list`).
3. Benutzerliste der Websocket-API von Home Assistant (`config/auth/list`) mit dem
   Token des Add-ons über den Supervisor-Proxy; daraus ginge hervor, wer Admin ist.
4. Vollbild-App: `auth/current_user` mit dem Zugang aus der eigenen Anmeldung.

Jeder Weg liefert eine `Probe` mit kurzer Zusammenfassung und gekürzter Rohantwort zum
Kopieren. Fehler werden angezeigt, nie geworfen: Die Seite soll alle vier Ergebnisse zeigen.
"""

import asyncio
import json
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout, WSMsgType

from ha_auth import HomeAssistantUnavailable, LoginRejected, access_token
from supervisor import SupervisorError, get_auth_users

# Kopfzeilen, die Home Assistant über Ingress mitschickt (nur vom Ingress-Proxy glaubwürdig)
REMOTE_USER_HEADERS = ("x-remote-user-id", "x-remote-user-name", "x-remote-user-display-name")
# Websocket von Home Assistant über den Supervisor-Proxy, angemeldet mit SUPERVISOR_TOKEN
CORE_WEBSOCKET_URL = "ws://supervisor/core/websocket"
TIMEOUT_SECONDS = 10
# So viele Zeichen der Rohantwort zeigt die Seite zum Kopieren
RAW_LIMIT = 3000
# Gruppe der Admins in Home Assistant
ADMIN_GROUP = "system-admin"


@dataclass(frozen=True)
class Probe:
    """Ergebnis eines Wegs: hat er funktioniert, was kam heraus, Rohantwort zum Kopieren."""

    label: str
    ok: bool
    summary: str
    raw: str = ""


class _WebsocketError(RuntimeError):
    pass


def _raw(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)[:RAW_LIMIT]


def remote_user_headers(headers: Mapping[str, str]) -> Probe:
    """Weg 1: Benutzer aus den Kopfzeilen der aktuellen Anfrage (über Ingress)."""
    found = {name: headers[name] for name in REMOTE_USER_HEADERS if name in headers}
    if not found:
        return Probe("Kopfzeilen über Ingress", False, "Keine X-Remote-User-Kopfzeilen erhalten.")
    summary = ", ".join(
        f"{name.removeprefix('x-remote-user-')}: {value}" for name, value in found.items()
    )
    return Probe("Kopfzeilen über Ingress", True, summary, _raw(found))


def _describe_users(users: list[dict[str, Any]]) -> str:
    """Kurzfassung einer Benutzerliste: Name (Benutzername) und ob Admin, soweit erkennbar."""
    parts = []
    for user in users:
        name = user.get("name") or user.get("username") or user.get("id") or "?"
        groups = user.get("group_ids") or []
        role = " · Admin" if ADMIN_GROUP in groups else ""
        if user.get("is_owner"):
            role += " · Eigentümer"
        if user.get("system_generated"):
            role += " · System"
        parts.append(f"{name}{role}")
    return f"{len(users)} Benutzer: " + "; ".join(parts) if parts else "Keine Benutzer geliefert."


def supervisor_users(token: str) -> Probe:
    """Weg 2: Benutzerliste der Supervisor-API."""
    label = "Supervisor-API /auth/list"
    try:
        users = get_auth_users(token)
    except SupervisorError as error:
        return Probe(label, False, f"Fehler: {error}")
    return Probe(label, True, _describe_users(users), _raw(users))


async def _websocket_command(url: str, token: str, command: dict[str, Any]) -> Any:
    """Meldet sich am Websocket von Home Assistant an und führt einen Befehl aus."""
    timeout = ClientTimeout(total=TIMEOUT_SECONDS)
    async with ClientSession(timeout=timeout) as session, session.ws_connect(url) as socket:
        greeting = await socket.receive_json()
        if greeting.get("type") != "auth_required":
            raise _WebsocketError(f"Unerwartete Begrüßung: {greeting.get('type')}")
        await socket.send_json({"type": "auth", "access_token": token})
        auth = await socket.receive_json()
        if auth.get("type") != "auth_ok":
            raise _WebsocketError(f"Anmeldung abgelehnt: {auth.get('message') or auth.get('type')}")
        await socket.send_json({"id": 1, **command})
        while True:
            message = await socket.receive()
            if message.type != WSMsgType.TEXT:
                raise _WebsocketError("Verbindung ohne Antwort beendet")
            reply = json.loads(message.data)
            if reply.get("id") == 1 and reply.get("type") == "result":
                if not reply.get("success"):
                    error = reply.get("error") or {}
                    raise _WebsocketError(error.get("message") or "Befehl abgelehnt")
                return reply.get("result")


def _run_websocket(url: str, token: str, command: dict[str, Any]) -> Any:
    return asyncio.run(_websocket_command(url, token, command))


def core_users(token: str) -> Probe:
    """Weg 3: Benutzerliste über den Websocket von Home Assistant (Supervisor-Proxy)."""
    label = "Websocket config/auth/list"
    try:
        users = _run_websocket(CORE_WEBSOCKET_URL, token, {"type": "config/auth/list"})
    except (_WebsocketError, ClientError, TimeoutError, ValueError) as error:
        return Probe(label, False, f"Fehler: {type(error).__name__}: {error}")
    if not isinstance(users, list):
        return Probe(label, False, "Antwort ist keine Liste", _raw(users))
    return Probe(label, True, _describe_users(users), _raw(users))


def oauth_current_user(server_url: str, client_id: str, refresh_token: str) -> Probe:
    """Weg 4: der angemeldete Benutzer der Vollbild-App über `auth/current_user`."""
    label = "Vollbild-App auth/current_user"
    try:
        token = access_token(server_url, client_id, refresh_token)
        websocket = server_url.replace("http", "ws", 1) + "/api/websocket"
        user = _run_websocket(websocket, token, {"type": "auth/current_user"})
    except (HomeAssistantUnavailable, LoginRejected) as error:
        return Probe(label, False, f"Fehler: {error}")
    except (_WebsocketError, ClientError, TimeoutError, ValueError) as error:
        return Probe(label, False, f"Fehler: {type(error).__name__}: {error}")
    if not isinstance(user, dict):
        return Probe(label, False, "Antwort ist kein Benutzer", _raw(user))
    role = "Admin" if user.get("is_admin") else "kein Admin"
    summary = f"{user.get('name', '?')} (id {user.get('id', '?')}), {role}"
    return Probe(label, True, summary, _raw(user))


@dataclass(frozen=True)
class HaUser:
    """Ein Benutzer von Home Assistant, wie ihn `auth/current_user` liefert."""

    id: str
    name: str
    is_admin: bool


def session_user(server_url: str, client_id: str, refresh_token: str) -> HaUser:
    """Wer hinter einer Sitzung der Vollbild-App steht.

    Wirft `LoginRejected`, wenn Home Assistant den Zugang entzogen hat, und
    `HomeAssistantUnavailable`, wenn es nicht erreichbar ist oder nicht verständlich antwortet.
    """
    token = access_token(server_url, client_id, refresh_token)
    websocket = server_url.replace("http", "ws", 1) + "/api/websocket"
    try:
        user = _run_websocket(websocket, token, {"type": "auth/current_user"})
    except (_WebsocketError, ClientError, TimeoutError, ValueError) as error:
        raise HomeAssistantUnavailable(f"Benutzer nicht abfragbar: {error}") from error
    if not isinstance(user, dict) or not user.get("id"):
        raise HomeAssistantUnavailable("Home Assistant liefert keinen Benutzer.")
    return HaUser(str(user["id"]), str(user.get("name") or ""), bool(user.get("is_admin")))


@dataclass(frozen=True)
class HaAccount:
    """Ein Konto in Home Assistant, wie es `config/auth/list` liefert."""

    id: str
    username: str
    name: str
    is_admin: bool
    is_active: bool
    system_generated: bool


def _account(raw: dict[str, Any]) -> HaAccount:
    return HaAccount(
        id=str(raw.get("id") or ""),
        username=str(raw.get("username") or ""),
        name=str(raw.get("name") or raw.get("username") or ""),
        is_admin=ADMIN_GROUP in (raw.get("group_ids") or []),
        is_active=bool(raw.get("is_active", True)),
        system_generated=bool(raw.get("system_generated")),
    )


def list_accounts(token: str) -> list[HaAccount]:
    """Alle Konten von Home Assistant; `HomeAssistantUnavailable`, wenn das nicht klappt."""
    try:
        users = _run_websocket(CORE_WEBSOCKET_URL, token, {"type": "config/auth/list"})
    except (_WebsocketError, ClientError, TimeoutError, ValueError) as error:
        raise HomeAssistantUnavailable(f"Benutzerliste nicht abrufbar: {error}") from error
    if not isinstance(users, list):
        raise HomeAssistantUnavailable("Home Assistant liefert keine Benutzerliste.")
    return [_account(user) for user in users if isinstance(user, dict) and user.get("id")]


class AccountDirectory:
    """Konten aus Home Assistant, kurz zwischengespeichert.

    Rollen ändern sich selten; die Liste wird höchstens alle `ttl` Sekunden neu geholt.
    Ist Home Assistant kurz nicht erreichbar (z. B. Neustart), gilt der letzte Stand noch
    `stale_ttl` Sekunden, damit niemand ausgesperrt wird. Danach gilt: kein Zugriff.
    """

    def __init__(self, ttl: float = 60.0, stale_ttl: float = 3600.0) -> None:
        self.ttl = ttl
        self.stale_ttl = stale_ttl
        self._accounts: dict[str, HaAccount] = {}
        self._loaded_at: float | None = None
        self._lock = threading.Lock()

    def find(self, token: str, user_id: str) -> HaAccount | None:
        """Konto zur Benutzer-ID; None, wenn es das Konto nicht gibt."""
        return self._current(token).get(user_id)

    def clear(self) -> None:
        with self._lock:
            self._accounts = {}
            self._loaded_at = None

    def _current(self, token: str) -> dict[str, HaAccount]:
        with self._lock:
            now = time.monotonic()
            age = None if self._loaded_at is None else now - self._loaded_at
            if age is not None and age < self.ttl:
                return self._accounts
            try:
                accounts = list_accounts(token)
            except HomeAssistantUnavailable:
                if age is not None and age < self.stale_ttl:
                    return self._accounts
                raise
            self._accounts = {account.id: account for account in accounts}
            self._loaded_at = now
            return self._accounts


# Ein Verzeichnis für die ganze App (die Konten sind für alle Anfragen dieselben)
directory = AccountDirectory()
