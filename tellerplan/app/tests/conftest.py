import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import create_app
from settings import Settings, load_settings

TEST_OPTIONS = {
    "daily_kcal_limit": 2000,
    "protein_goal_g": 150,
    "fat_goal_g": 70,
    "carbs_goal_g": 200,
    "meal_names": ["Frühstück", "Mittag", "Abendessen", "Snacks"],
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
def ingress_client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings), base_url=f"http://testserver:{settings.ingress_port}")


@pytest.fixture
def api_client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings), base_url=f"http://testserver:{settings.api_port}")
