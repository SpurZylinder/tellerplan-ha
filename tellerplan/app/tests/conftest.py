import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from db import create_db_engine, create_session_factory
from main import create_app
from migrate import upgrade_to_head
from settings import Settings, load_settings

TEST_OPTIONS = {
    "daily_kcal_limit": 2000,
    "protein_goal_g": 150,
    "fat_goal_g": 70,
    "carbs_goal_g": 200,
    "meal_names": ["Frühstück", "Mittag", "Abendessen", "Snacks"],
    "ranking_protein_weight": 0.7,
    "api_token": "test-token",
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


@pytest.fixture
def migrated(settings: Settings) -> Settings:
    """Einstellungen mit einer auf den neuesten Stand migrierten Datenbank."""
    upgrade_to_head(settings)
    return settings


@pytest.fixture
def session(migrated: Settings) -> Iterator[Session]:
    engine = create_db_engine(migrated)
    with create_session_factory(engine)() as db_session:
        yield db_session
    engine.dispose()


@pytest.fixture
def ingress_client(migrated: Settings) -> TestClient:
    return TestClient(create_app(migrated), base_url=f"http://testserver:{migrated.ingress_port}")


@pytest.fixture
def api_client(migrated: Settings) -> TestClient:
    return TestClient(create_app(migrated), base_url=f"http://testserver:{migrated.api_port}")
