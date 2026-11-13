"""Aufrufe an die Supervisor-API, ohne echten Supervisor."""

import io
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

import supervisor
from supervisor import SupervisorError, get_own_options, set_own_options, supervisor_token


class _Response:
    def __init__(self, body: bytes = b"") -> None:
        self.body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_set_own_options_posts_options_with_token(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[Request] = []

    def fake_urlopen(request: Request, timeout: float) -> _Response:
        requests.append(request)
        return _Response()

    monkeypatch.setattr(supervisor, "urlopen", fake_urlopen)

    set_own_options({"daily_kcal_limit": 1800}, "geheim")

    request = requests[0]
    assert request.full_url == "http://supervisor/addons/self/options"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer geheim"
    assert json.loads(request.data) == {"options": {"daily_kcal_limit": 1800}}


def test_rejection_carries_supervisor_message(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"result": "error", "message": "Wert zu groß"}).encode()

    def reject(request: Request, timeout: float) -> Any:
        raise HTTPError(request.full_url, 400, "Bad Request", None, io.BytesIO(body))

    monkeypatch.setattr(supervisor, "urlopen", reject)

    with pytest.raises(SupervisorError, match="Wert zu groß"):
        set_own_options({}, "geheim")


def test_unreachable_supervisor_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable(request: Request, timeout: float) -> Any:
        raise URLError("Name or service not known")

    monkeypatch.setattr(supervisor, "urlopen", unreachable)

    with pytest.raises(SupervisorError, match="nicht erreichbar"):
        set_own_options({}, "geheim")


def test_token_is_missing_outside_the_addon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(supervisor.TOKEN_ENV_VAR, raising=False)

    assert supervisor_token() is None


def test_get_own_options_reads_addon_info(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[Request] = []
    body = json.dumps({"result": "ok", "data": {"options": {"daily_kcal_limit": 1900}}})

    def fake_urlopen(request: Request, timeout: float) -> _Response:
        requests.append(request)
        return _Response(body.encode())

    monkeypatch.setattr(supervisor, "urlopen", fake_urlopen)

    assert get_own_options("geheim") == {"daily_kcal_limit": 1900}
    assert requests[0].full_url == "http://supervisor/addons/self/info"
    assert requests[0].get_method() == "GET"
    assert requests[0].data is None


@pytest.mark.parametrize("body", [b"", b"kein json", b'{"data": {}}', b'{"data": []}'])
def test_get_own_options_without_options_is_an_error(
    monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    monkeypatch.setattr(supervisor, "urlopen", lambda request, timeout: _Response(body))

    with pytest.raises(SupervisorError):
        get_own_options("geheim")


def test_error_result_in_successful_response_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"result": "error", "message": "Optionen ungültig"}).encode()
    monkeypatch.setattr(supervisor, "urlopen", lambda request, timeout: _Response(body))

    with pytest.raises(SupervisorError, match="Optionen ungültig"):
        set_own_options({}, "geheim")


def test_get_core_state_reads_entity(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[Request] = []
    body = json.dumps({"entity_id": "todo.furth", "attributes": {"supported_features": 71}})

    def fake_urlopen(request: Request, timeout: float) -> _Response:
        requests.append(request)
        return _Response(body.encode())

    monkeypatch.setattr(supervisor, "urlopen", fake_urlopen)

    state = supervisor.get_core_state("todo.furth", "geheim")

    assert state["attributes"]["supported_features"] == 71
    assert requests[0].full_url == "http://supervisor/core/api/states/todo.furth"
    assert requests[0].get_method() == "GET"


def test_call_service_with_response_returns_service_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[Request] = []
    answer = {"todo.furth": {"items": [{"summary": "Milch"}]}}
    body = json.dumps({"changed_states": [], "service_response": answer})

    def fake_urlopen(request: Request, timeout: float) -> _Response:
        requests.append(request)
        return _Response(body.encode())

    monkeypatch.setattr(supervisor, "urlopen", fake_urlopen)

    response = supervisor.call_service_with_response(
        "todo", "get_items", {"entity_id": "todo.furth"}, "geheim"
    )

    assert response == answer
    assert requests[0].full_url == (
        "http://supervisor/core/api/services/todo/get_items?return_response"
    )


def test_service_without_response_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(supervisor, "urlopen", lambda request, timeout: _Response(b"[]"))

    with pytest.raises(SupervisorError, match="keine Antwort"):
        supervisor.call_service_with_response("todo", "get_items", {}, "geheim")


def test_get_auth_users_reads_user_list(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[Request] = []
    body = json.dumps({"result": "ok", "data": {"users": [{"username": "fabi", "is_owner": True}]}})

    def fake_urlopen(request: Request, timeout: float) -> _Response:
        requests.append(request)
        return _Response(body.encode())

    monkeypatch.setattr(supervisor, "urlopen", fake_urlopen)

    assert supervisor.get_auth_users("geheim") == [{"username": "fabi", "is_owner": True}]
    assert requests[0].full_url == "http://supervisor/auth/list"


def test_get_auth_users_without_list_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(supervisor, "urlopen", lambda request, timeout: _Response(b'{"data": {}}'))

    with pytest.raises(SupervisorError, match="keine Benutzerliste"):
        supervisor.get_auth_users("geheim")
