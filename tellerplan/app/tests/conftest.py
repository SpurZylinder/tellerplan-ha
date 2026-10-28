import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from db import create_db_engine, create_session_factory
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
    "api_token": "test-token",
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


@pytest.fixture
def ingress_client(migrated: Settings, options_file: Path) -> TestClient:
    """Wie der Ingress-Proxy von Home Assistant: Ingress-Port, Absender 172.30.32.2."""
    return TestClient(
        create_app(migrated, options_file),
        base_url=f"http://testserver:{migrated.ingress_port}",
        client=(INGRESS_PROXY_IP, 50000),
    )


@pytest.fixture
def api_client(migrated: Settings) -> TestClient:
    return TestClient(create_app(migrated), base_url=f"http://testserver:{migrated.api_port}")
