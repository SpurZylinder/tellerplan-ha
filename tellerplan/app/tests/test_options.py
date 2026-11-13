"""Einstellseite und Zurückschreiben der Optionen (lokal und über den Supervisor)."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import files as files_module
import settings as settings_module
from settings import OptionsFileError, option_range, save_options
from supervisor import TOKEN_ENV_VAR, SupervisorError

GOALS = {
    "daily_kcal_limit": "1800",
    "protein_goal_g": "160",
    "fat_goal_g": "60",
    "carbs_goal_g": "180",
    "pantry_keywords": "Salz\nmehl, zucker\nsalz",
    "bring_list_entity": "todo.furth",
}


def _options(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class FakeSupervisor:
    """Optionen, wie Home Assistant sie hält; können neuer sein als options.json."""

    def __init__(self, options: dict[str, Any]) -> None:
        self.options = dict(options)
        self.sent: list[dict[str, Any]] = []

    def get(self, token: str) -> dict[str, Any]:
        return dict(self.options)

    def set(self, options: dict[str, Any], token: str) -> None:
        self.sent.append(options)
        self.options = dict(options)


@pytest.fixture
def fake_supervisor(monkeypatch: pytest.MonkeyPatch, options_file: Path) -> FakeSupervisor:
    fake = FakeSupervisor(_options(options_file))
    monkeypatch.setenv(TOKEN_ENV_VAR, "supervisor-token")
    monkeypatch.setattr(settings_module, "get_own_options", fake.get)
    monkeypatch.setattr(settings_module, "set_own_options", fake.set)
    return fake


def test_save_options_changes_only_given_values(options_file: Path) -> None:
    updated = save_options(options_file, {"daily_kcal_limit": 1800})

    assert updated.daily_kcal_limit == 1800
    stored = _options(options_file)
    assert stored["daily_kcal_limit"] == 1800
    assert stored["database_path"] == "app.db"  # nicht aufgelöst zurückgeschrieben


def test_save_options_rejects_values_outside_schema(options_file: Path) -> None:
    with pytest.raises(ValidationError):
        save_options(options_file, {"daily_kcal_limit": 100})

    assert _options(options_file)["daily_kcal_limit"] == 2000


def test_save_options_sends_all_options_to_supervisor(
    fake_supervisor: FakeSupervisor, options_file: Path
) -> None:
    save_options(options_file, {"protein_goal_g": 170})

    options = fake_supervisor.sent[0]
    assert options["protein_goal_g"] == 170
    assert options["api_token"] == "test-token"


def test_change_in_home_assistant_is_kept(
    fake_supervisor: FakeSupervisor, options_file: Path
) -> None:
    # In HA geändert, ohne Neustart: options.json kennt den neuen Wert noch nicht (K8)
    fake_supervisor.options["daily_kcal_limit"] = 1900

    updated = save_options(options_file, {"protein_goal_g": 170})

    assert fake_supervisor.sent[0]["daily_kcal_limit"] == 1900
    assert _options(options_file)["daily_kcal_limit"] == 1900
    assert updated.daily_kcal_limit == 1900
    assert updated.protein_goal_g == 170


def test_failed_file_write_is_reported_and_keeps_the_file(
    monkeypatch: pytest.MonkeyPatch, fake_supervisor: FakeSupervisor, options_file: Path
) -> None:
    def broken_replace(source: object, target: object) -> None:
        raise OSError("Datenträger voll")

    monkeypatch.setattr(files_module.os, "replace", broken_replace)

    with pytest.raises(OptionsFileError, match="nach einem Neustart"):
        save_options(options_file, {"protein_goal_g": 170})

    assert _options(options_file)["protein_goal_g"] == 150
    assert not options_file.with_name("options.json.tmp").exists()


def test_supervisor_rejection_leaves_file_unchanged(
    monkeypatch: pytest.MonkeyPatch, fake_supervisor: FakeSupervisor, options_file: Path
) -> None:
    def reject(options: dict[str, Any], token: str) -> None:
        raise SupervisorError("ungültig")

    monkeypatch.setattr(settings_module, "set_own_options", reject)

    with pytest.raises(SupervisorError):
        save_options(options_file, {"protein_goal_g": 170})

    assert _options(options_file)["protein_goal_g"] == 150


def test_option_range_matches_schema() -> None:
    assert option_range("daily_kcal_limit") == (500, 10000)
    assert option_range("carbs_goal_g") == (0, 1000)


def test_today_links_to_settings(ingress_client: TestClient) -> None:
    assert 'aria-label="Einstellungen"' in ingress_client.get("/").text


def test_settings_page_shows_current_goals(ingress_client: TestClient) -> None:
    text = ingress_client.get("/settings").text

    assert 'name="daily_kcal_limit" value="2000"' in text
    assert 'name="protein_goal_g" value="150"' in text


def test_saved_goals_apply_without_restart(ingress_client: TestClient, options_file: Path) -> None:
    response = ingress_client.post("/settings", data=GOALS, follow_redirects=False)

    assert response.status_code == 303
    assert "Gespeichert." in ingress_client.get(response.headers["location"]).text
    assert "Limit <b>1.800</b>" in ingress_client.get("/").text
    stored = _options(options_file)
    assert stored["protein_goal_g"] == 160
    assert stored["pantry_keywords"] == ["salz", "mehl", "zucker"]
    assert stored["bring_list_entity"] == "todo.furth"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("daily_kcal_limit", "100", "Tageslimit muss zwischen 500 und 10000 kcal liegen."),
        ("protein_goal_g", "12,5", "Eiweiß muss eine ganze Zahl sein."),
        ("fat_goal_g", "", "Fett fehlt."),
        ("bring_list_entity", "Einkauf", "Bring-Liste muss eine To-do-Entität sein"),
    ],
)
def test_invalid_goal_is_reported(
    ingress_client: TestClient, options_file: Path, field: str, value: str, message: str
) -> None:
    response = ingress_client.post("/settings", data={**GOALS, field: value})

    assert response.status_code == 200
    assert message in response.text
    assert _options(options_file)["daily_kcal_limit"] == 2000


def test_settings_page_saves_only_changed_fields(
    fake_supervisor: FakeSupervisor, ingress_client: TestClient, options_file: Path
) -> None:
    # Die Seite zeigt 2000 kcal; in HA steht inzwischen 1900, die Seite ändert nur Eiweiß
    fake_supervisor.options["daily_kcal_limit"] = 1900
    form = {**GOALS, "daily_kcal_limit": "2000", "protein_goal_g": "170"}

    ingress_client.post("/settings", data=form, follow_redirects=False)

    assert fake_supervisor.sent[0]["daily_kcal_limit"] == 1900
    assert fake_supervisor.sent[0]["protein_goal_g"] == 170
    assert _options(options_file)["daily_kcal_limit"] == 1900


def test_settings_page_reports_failed_file_write(
    monkeypatch: pytest.MonkeyPatch, fake_supervisor: FakeSupervisor, ingress_client: TestClient
) -> None:
    def broken_replace(source: object, target: object) -> None:
        raise OSError("Datenträger voll")

    monkeypatch.setattr(files_module.os, "replace", broken_replace)

    response = ingress_client.post("/settings", data=GOALS)

    assert response.status_code == 200
    assert "nach einem Neustart des Add-ons" in response.text


def test_supervisor_error_is_shown(
    monkeypatch: pytest.MonkeyPatch, fake_supervisor: FakeSupervisor, ingress_client: TestClient
) -> None:
    def reject(options: dict[str, Any], token: str) -> None:
        raise SupervisorError("Wert außerhalb des Schemas")

    monkeypatch.setattr(settings_module, "set_own_options", reject)

    response = ingress_client.post("/settings", data=GOALS)

    assert "Home Assistant hat die Werte nicht übernommen" in response.text
    assert "Limit <b>2.000</b>" in ingress_client.get("/").text


def test_supervisor_that_does_not_keep_the_values_is_an_error(
    monkeypatch: pytest.MonkeyPatch, fake_supervisor: FakeSupervisor, options_file: Path
) -> None:
    # Supervisor antwortet ohne Fehler, behält die Werte aber nicht
    monkeypatch.setattr(settings_module, "set_own_options", lambda options, token: None)

    with pytest.raises(SupervisorError, match="protein_goal_g nicht gespeichert"):
        save_options(options_file, {"protein_goal_g": 170})

    assert _options(options_file)["protein_goal_g"] == 150


def test_settings_page_reports_values_not_kept_by_home_assistant(
    monkeypatch: pytest.MonkeyPatch, fake_supervisor: FakeSupervisor, ingress_client: TestClient
) -> None:
    monkeypatch.setattr(settings_module, "set_own_options", lambda options, token: None)

    response = ingress_client.post("/settings", data=GOALS)

    assert "Home Assistant hat die Werte nicht übernommen" in response.text
    assert "Limit <b>2.000</b>" in ingress_client.get("/").text
