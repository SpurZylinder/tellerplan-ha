import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import cookidoo as cookidoo_module
import ha_auth as ha_auth_module
import ha_users as ha_users_module
import supervisor as supervisor_module
import web.access as web_access
from db import create_db_engine, create_session_factory
from ha_auth import HomeAssistantUnavailable
from ha_users import HaAccount
from main import create_app
from migrate import upgrade_to_head
from modules.nutrition.service import set_standard_units
from security import INGRESS_PROXY_IP
from settings import Settings, load_settings

TEST_OPTIONS = {
    "daily_kcal_limit": 2000,
    "protein_goal_g": 150,
    "fat_goal_g": 70,
    "carbs_goal_g": 200,
    "meal_names": ["Frühstück", "Mittag", "Abendessen", "Snacks"],
    "plan_default_meal": "Abendessen",
    "suggest_yesterday_meals": ["Mittag", "Snacks"],
    "frequency_window_days": 90,
    "recipe_categories": ["Frühstück", "Hauptgericht", "Beilage", "Snack", "Salat"],
    "meal_categories": [
        {"meal": "Mittag", "category": "Hauptgericht"},
        {"meal": "Mittag", "category": "Salat"},
        {"meal": "Snacks", "category": "Snack"},
    ],
    "standard_units": [{"unit": "EL", "grams": 15}, {"unit": "TL", "grams": 5}],
    "ranking_protein_weight": 0.7,
    "pantry_keywords": ["salz", "mehl", "zucker", "öl"],
    "bring_list_entity": "todo.einkauf",
    "cookidoo_locale": "de-DE",
    "api_token": "test-token",
    "allowed_users": [],
    "homeassistant_url": "",
    "database_path": "app.db",
}


@pytest.fixture
def options_file(tmp_path: Path) -> Path:
    path = tmp_path / "options.json"
    path.write_text(json.dumps(TEST_OPTIONS), encoding="utf-8")
    return path


@pytest.fixture
def settings(options_file: Path) -> Settings:
    return load_settings(options_file)


@pytest.fixture(autouse=True)
def standard_units(settings: Settings) -> None:
    """Wie beim Start der App: Standard-Einheiten aus den Einstellungen setzen."""
    set_standard_units(settings.standard_unit_grams)


@pytest.fixture(scope="session")
def template_database(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Einmal pro Testlauf migrierte Datenbank ohne BLS-Daten, als Kopiervorlage."""
    directory = tmp_path_factory.mktemp("template")
    options = directory / "options.json"
    options.write_text(json.dumps(TEST_OPTIONS), encoding="utf-8")
    template = load_settings(options)
    upgrade_to_head(template, skip_data_migrations=True)
    return template.database_path


@pytest.fixture
def migrated(settings: Settings, template_database: Path) -> Settings:
    """Einstellungen mit migrierter, leerer Datenbank (ohne BLS-Lebensmittel)."""
    shutil.copy(template_database, settings.database_path)
    return settings


@pytest.fixture
def session(migrated: Settings) -> Iterator[Session]:
    engine = create_db_engine(migrated)
    with create_session_factory(engine)() as db_session:
        yield db_session
    engine.dispose()


def _closing(client: TestClient) -> Iterator[TestClient]:
    """Gibt den Client heraus und schließt danach die Datenbank-Engine der App.

    Im Betrieb lebt eine Engine so lange wie der Prozess; in den Tests entsteht je Test
    eine App, deren Verbindungen sonst offen blieben (ResourceWarning).
    """
    yield client
    client.app.state.engine.dispose()


class NetworkInTest(RuntimeError):
    """Ein Test hat versucht, echtes Netzwerk zu nutzen."""


def _no_network(*args: object, **kwargs: object) -> object:
    raise NetworkInTest(
        "Tests dürfen kein echtes Netzwerk nutzen (Home Assistant, Supervisor, Cookidoo); "
        "bitte die Aufrufe im Test durch eine Attrappe ersetzen."
    )


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sperrt alle Netzwerkzugänge der App; Tests, die sie brauchen, ersetzen sie selbst.

    Anlass (2026-11-13): Tests der Vollbild-App erreichten über `homeassistant.local` das
    echte Home Assistant im Heimnetz, das sie als fehlgeschlagene Anmeldungen protokollierte.
    """
    monkeypatch.setattr(ha_auth_module, "urlopen", _no_network)
    monkeypatch.setattr(supervisor_module, "urlopen", _no_network)
    monkeypatch.setattr(ha_users_module, "_run_websocket", _no_network)
    monkeypatch.setattr(cookidoo_module, "Cookidoo", _no_network)


# Konten wie in Home Assistant; die Test-Clients sind über Ingress als ADMIN_ID angemeldet
ADMIN_ID = "admin-id"
MEMBER_ID = "member-id"
ACCOUNTS = {
    ADMIN_ID: HaAccount(ADMIN_ID, "spurzylinder", "SpurZylinder", True, True, False),
    MEMBER_ID: HaAccount(MEMBER_ID, "fabian", "Fabian", False, True, False),
    # Angemeldete in den Tests der Vollbild-App (test_login.py)
    "a1": HaAccount("a1", "spurzylinder", "SpurZylinder", True, True, False),
    "b2": HaAccount("b2", "fabian", "Fabian", False, True, False),
    "sys": HaAccount("sys", "", "Supervisor", True, True, True),
    "gone": HaAccount("gone", "alt", "Alt", False, False, False),
}
INGRESS_HEADERS = {"x-remote-user-id": ADMIN_ID, "x-remote-user-name": "spurzylinder"}


class FakeDirectory:
    """Benutzerliste von Home Assistant ohne Netzwerk."""

    def __init__(self) -> None:
        self.accounts = dict(ACCOUNTS)
        self.unavailable = False

    def find(self, token: str, user_id: str) -> HaAccount | None:
        if self.unavailable:
            raise HomeAssistantUnavailable("weg")
        return self.accounts.get(user_id)


@pytest.fixture(autouse=True)
def accounts(monkeypatch: pytest.MonkeyPatch) -> FakeDirectory:
    fake = FakeDirectory()
    monkeypatch.setattr(web_access, "directory", fake)
    return fake


@pytest.fixture
def ingress_client(migrated: Settings, options_file: Path) -> Iterator[TestClient]:
    """Wie der Ingress-Proxy von Home Assistant: Ingress-Port, Absender 172.30.32.2, Admin."""
    yield from _closing(
        TestClient(
            create_app(migrated, options_file),
            base_url=f"http://testserver:{migrated.ingress_port}",
            client=(INGRESS_PROXY_IP, 50000),
            headers=INGRESS_HEADERS,
        )
    )


@pytest.fixture
def api_client(migrated: Settings) -> Iterator[TestClient]:
    yield from _closing(
        TestClient(create_app(migrated), base_url=f"http://testserver:{migrated.api_port}")
    )
