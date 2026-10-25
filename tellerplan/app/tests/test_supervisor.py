"""Aufrufe an die Supervisor-API, ohne echten Supervisor."""

import io
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

import supervisor
from supervisor import SupervisorError, set_own_options, supervisor_token


class _Response:
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None


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
