import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from conftest import TEST_OPTIONS
from settings import OPTIONS_ENV_VAR, get_settings, load_settings, options_path


def test_load_settings_reads_all_options(options_file: Path) -> None:
    settings = load_settings(options_file)

    assert settings.daily_kcal_limit == 2000
    assert settings.meal_names == ["Frühstück", "Mittag", "Abendessen", "Snacks"]
    assert settings.api_token == "test-token"


def test_relative_database_path_is_resolved_next_to_options(options_file: Path) -> None:
    settings = load_settings(options_file)

    assert settings.database_path == options_file.parent.resolve() / "app.db"
    assert settings.database_url.startswith("sqlite:///")


def test_missing_option_is_rejected(tmp_path: Path) -> None:
    incomplete = {key: value for key, value in TEST_OPTIONS.items() if key != "daily_kcal_limit"}
    path = tmp_path / "options.json"
    path.write_text(json.dumps(incomplete), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_settings(path)


def test_options_path_comes_from_environment(
    monkeypatch: pytest.MonkeyPatch, options_file: Path
) -> None:
    monkeypatch.setenv(OPTIONS_ENV_VAR, str(options_file))
    get_settings.cache_clear()

    assert options_path() == options_file
    assert get_settings().api_token == "test-token"
    get_settings.cache_clear()
