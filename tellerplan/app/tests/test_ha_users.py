"""Erkundung B1: Benutzer von Home Assistant erkennen, ohne echtes Home Assistant."""

import asyncio
import json
from typing import Any

import pytest
from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer
from fastapi.testclient import TestClient

import ha_users
from ha_auth import LoginRejected
from supervisor import TOKEN_ENV_VAR, SupervisorError

USERS = [
    {
        "id": "a1",
        "username": "fabi",
        "name": "Fabi",
        "is_owner": True,
        "group_ids": ["system-admin"],
    },
    {
        "id": "b2",
        "username": "kind",
        "name": "Kind",
        "is_owner": False,
        "group_ids": ["system-users"],
    },
]


def _home_assistant(token: str, results: dict[str, Any]) -> web.Application:
    """Websocket wie bei Home Assistant: auth_required → auth → auth_ok → Befehl → result."""

    async def handler(request: web.Request) -> web.WebSocketResponse:
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        await socket.send_json({"type": "auth_required"})
        auth = await socket.receive_json()
        if auth.get("access_token") != token:
            await socket.send_json({"type": "auth_invalid", "message": "Falscher Token"})
            await socket.close()
            return socket
        await socket.send_json({"type": "auth_ok"})
        async for message in socket:
            if message.type != WSMsgType.TEXT:
                break
            command = json.loads(message.data)
            await socket.send_json({"id": 99, "type": "event"})  # fremde Nachricht dazwischen
            if command["type"] in results:
                reply = {"id": command["id"], "type": "result", "success": True}
                await socket.send_json({**reply, "result": results[command["type"]]})
            else:
                await socket.send_json(
                    {
                        "id": command["id"],
                        "type": "result",
                        "success": False,
                        "error": {"message": "Unauthorized"},
                    }
                )
        return socket

    app = web.Application()
    app.router.add_get("/api/websocket", handler)
    return app


def _ask(token: str, results: dict[str, Any], sent_token: str, command: str) -> Any:
    async def run() -> Any:
        server = TestServer(_home_assistant(token, results))
        await server.start_server()
        try:
            url = str(server.make_url("/api/websocket")).replace("http", "ws", 1)
            return await ha_users._websocket_command(url, sent_token, {"type": command})
        finally:
            await server.close()

    return asyncio.run(run())


def test_websocket_command_follows_the_protocol() -> None:
    result = _ask("geheim", {"config/auth/list": USERS}, "geheim", "config/auth/list")

    assert result == USERS


def test_websocket_rejects_wrong_token() -> None:
    with pytest.raises(ha_users._WebsocketError, match="Falscher Token"):
        _ask("geheim", {}, "falsch", "config/auth/list")


def test_websocket_reports_refused_command() -> None:
    with pytest.raises(ha_users._WebsocketError, match="Unauthorized"):
        _ask("geheim", {}, "geheim", "config/auth/list")


def test_remote_user_headers() -> None:
    probe = ha_users.remote_user_headers(
        {"x-remote-user-id": "a1", "x-remote-user-name": "fabi", "host": "x"}
    )

    assert probe.ok
    assert probe.summary == "id: a1, name: fabi"
    assert not ha_users.remote_user_headers({}).ok


def test_user_lists_show_admins() -> None:
    summary = ha_users._describe_users(USERS)

    assert summary == "2 Benutzer: Fabi · Admin · Eigentümer; Kind"


def test_core_users_reports_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any) -> Any:
        raise ha_users._WebsocketError("Unauthorized")

    monkeypatch.setattr(ha_users, "_run_websocket", refuse)

    probe = ha_users.core_users("token")

    assert not probe.ok
    assert "Unauthorized" in probe.summary


def test_oauth_current_user(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(ha_users, "access_token", lambda server, client, refresh: "zugang")

    def fake_run(url: str, token: str, command: dict[str, Any]) -> Any:
        calls.append((url, token))
        return {"id": "b2", "name": "Kind", "is_admin": False}

    monkeypatch.setattr(ha_users, "_run_websocket", fake_run)

    probe = ha_users.oauth_current_user("http://homeassistant:8123", "client", "refresh")

    assert probe.summary == "Kind (id b2), kein Admin"
    assert calls == [("ws://homeassistant:8123/api/websocket", "zugang")]


def test_oauth_current_user_with_revoked_login(monkeypatch: pytest.MonkeyPatch) -> None:
    def rejected(*args: Any) -> str:
        raise LoginRejected("Home Assistant hat die Anmeldung abgelehnt.")

    monkeypatch.setattr(ha_users, "access_token", rejected)

    assert not ha_users.oauth_current_user("http://ha", "c", "r").ok


def test_settings_page_shows_all_probes(
    monkeypatch: pytest.MonkeyPatch, ingress_client: TestClient
) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "supervisor-token")
    monkeypatch.setattr(ha_users, "get_auth_users", lambda token: USERS)

    def refuse(*args: Any) -> Any:
        raise SupervisorError("Forbidden")

    monkeypatch.setattr(ha_users, "_run_websocket", lambda *args: USERS)
    headers = {"x-remote-user-id": "a1", "x-remote-user-name": "fabi"}

    text = ingress_client.post("/settings/users", headers=headers).text

    assert "✓ Kopfzeilen über Ingress" in text
    assert "id: a1, name: fabi" in text
    assert "✓ Supervisor-API /auth/list" in text
    assert "✓ Websocket config/auth/list" in text
    assert "Fabi · Admin · Eigentümer; Kind" in text

    monkeypatch.setattr(ha_users, "get_auth_users", refuse)
    assert "✗ Supervisor-API /auth/list" in ingress_client.post("/settings/users").text


def test_access_token_from_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import ha_auth

    sent: list[dict[str, str]] = []

    def fake_post(url: str, form: dict[str, str]) -> dict[str, object]:
        sent.append(form)
        return {"access_token": "zugang", "token_type": "Bearer"}

    monkeypatch.setattr(ha_auth, "_post", fake_post)

    assert ha_auth.access_token("http://ha", "client", "refresh") == "zugang"
    assert sent == [
        {"grant_type": "refresh_token", "refresh_token": "refresh", "client_id": "client"}
    ]

    monkeypatch.setattr(ha_auth, "_post", lambda url, form: {})
    with pytest.raises(LoginRejected):
        ha_auth.access_token("http://ha", "client", "refresh")
