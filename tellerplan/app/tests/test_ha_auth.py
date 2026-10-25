"""Client für die Anmeldung über Home Assistant, ohne echtes Home Assistant."""

import base64
import hashlib
import io
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs
from urllib.request import Request

import pytest

import ha_auth
from ha_auth import (
    HomeAssistantUnavailable,
    LoginRejected,
    check_refresh_token,
    exchange_code,
    new_pkce,
    revoke,
)

HA = "http://homeassistant:8123"
CLIENT = "http://homeassistant.local:8099/"


class _Response:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = json.dumps(body).encode()

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def _answer(monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]) -> list[Request]:
    requests: list[Request] = []

    def fake_urlopen(request: Request, timeout: float) -> _Response:
        requests.append(request)
        return _Response(body)

    monkeypatch.setattr(ha_auth, "urlopen", fake_urlopen)
    return requests


def _fail(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def fake_urlopen(request: Request, timeout: float) -> Any:
        raise error

    monkeypatch.setattr(ha_auth, "urlopen", fake_urlopen)


def _form(request: Request) -> dict[str, list[str]]:
    assert isinstance(request.data, bytes)
    return parse_qs(request.data.decode())


def test_pkce_challenge_is_s256_of_verifier() -> None:
    verifier, challenge = new_pkce()

    digest = hashlib.sha256(verifier.encode()).digest()
    assert challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def test_exchange_code_returns_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = _answer(monkeypatch, {"access_token": "a", "refresh_token": "r", "expires_in": 1800})

    assert exchange_code(HA, CLIENT, "code-1", "verifier-1") == "r"
    assert requests[0].full_url == f"{HA}/auth/token"
    assert _form(requests[0]) == {
        "grant_type": ["authorization_code"],
        "code": ["code-1"],
        "client_id": [CLIENT],
        "code_verifier": ["verifier-1"],
    }


def test_exchange_without_refresh_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _answer(monkeypatch, {"access_token": "a"})

    with pytest.raises(LoginRejected):
        exchange_code(HA, CLIENT, "code-1", "verifier-1")


def test_invalid_grant_means_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _fail(monkeypatch, HTTPError(HA, 400, "Bad Request", None, io.BytesIO(b"{}")))

    with pytest.raises(LoginRejected):
        check_refresh_token(HA, CLIENT, "r")


@pytest.mark.parametrize(
    "error",
    [
        HTTPError(HA, 502, "Bad Gateway", None, io.BytesIO(b"")),
        URLError("Name or service not known"),
        TimeoutError("timed out"),
    ],
)
def test_other_failures_mean_unavailable(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    _fail(monkeypatch, error)

    with pytest.raises(HomeAssistantUnavailable):
        check_refresh_token(HA, CLIENT, "r")


def test_revoke_posts_token_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = _answer(monkeypatch, {})
    revoke(HA, "r")
    assert requests[0].full_url == f"{HA}/auth/revoke"
    assert _form(requests[0]) == {"token": ["r"]}

    _fail(monkeypatch, URLError("weg"))
    revoke(HA, "r")  # Fehler werden nur protokolliert
